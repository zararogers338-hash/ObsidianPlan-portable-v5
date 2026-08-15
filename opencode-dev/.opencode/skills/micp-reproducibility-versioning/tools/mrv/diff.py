"""Result diff comparator.

Compares two JSON documents (manifest/artifact/provenance snapshots) and two
filesets of hashes. Every comparison is structural (recursive, key-sorted) so
output is deterministic. Difference kinds: added / removed / modified /
content_change / hash_mismatch / identical.

Used by `reproduce` to report a rerun-vs-first-run diff and by `diff` for any
two artifacts.
"""

from __future__ import annotations

import json
import os
from typing import Any

from _common import (ToolError, canonical_json, emit_progress, normalize_rel,
                     resolve_root, safe_join, sha256_file)

DIFF_KINDS = ("added", "removed", "modified", "content_change", "hash_mismatch", "identical")


def deep_diff(a: Any, b: Any, path: str = "", out: list[dict] | None = None) -> list[dict]:
    """Structural recursive diff between two JSON values."""
    out = out if out is not None else []
    if type(a) is not type(b):
        out.append({"kind": "modified", "path": path or "$",
                    "old": _short(a), "new": _short(b)})
        return out
    if isinstance(a, dict):
        for k in sorted(set(a) | set(b)):
            if k not in b:
                out.append({"kind": "removed", "path": f"{path}.{k}", "old": _short(a[k])})
            elif k not in a:
                out.append({"kind": "added", "path": f"{path}.{k}", "new": _short(b[k])})
            else:
                deep_diff(a[k], b[k], f"{path}.{k}", out)
        return out
    if isinstance(a, list):
        if len(a) != len(b):
            out.append({"kind": "modified", "path": path or "$",
                        "old": f"array[{len(a)}]", "new": f"array[{len(b)}]"})
        for i, (x, y) in enumerate(zip(a, b)):
            deep_diff(x, y, f"{path}[{i}]", out)
        return out
    if a != b:
        out.append({"kind": "modified", "path": path or "$",
                    "old": _short(a), "new": _short(b)})
    return out


def _short(v: Any, limit: int = 400) -> str:
    s = v if isinstance(v, str) else json.dumps(v, ensure_ascii=False, sort_keys=True)
    return s if len(s) <= limit else s[:limit] + "…"


def _load_doc(root: str, ref: str) -> dict:
    """Load a JSON document by path (relative to root)."""
    full = ref
    if not os.path.isabs(full):
        full = safe_join(root, ref)
    if not os.path.isfile(full):
        raise ToolError("MRV-E302", f"document not found: {ref!r}", details={"path": ref})
    try:
        with open(full, encoding="utf-8") as fh:
            doc = json.load(fh)
    except json.JSONDecodeError as exc:
        raise ToolError("MRV-E301", f"document is not valid JSON: {ref!r}: {exc}",
                        details={"path": ref}) from exc
    if not isinstance(doc, dict):
        raise ToolError("MRV-E301", f"document must be a JSON object: {ref!r}",
                        details={"path": ref})
    return doc


def diff_docs(a: dict, b: dict, label_a: str, label_b: str) -> list[dict]:
    """Compare two loaded documents; differences carry labels."""
    diffs = deep_diff(a, b)
    if not diffs:
        return [{"kind": "identical", "path": "$",
                 "old": label_a, "new": label_b}]
    return diffs


def diff_hashes(a: dict[str, str], b: dict[str, str]) -> list[dict]:
    """Compare two path->sha256 maps (filesets)."""
    diffs: list[dict] = []
    for path in sorted(set(a) | set(b)):
        if path not in b:
            diffs.append({"kind": "removed", "path": path, "old": a[path]})
        elif path not in a:
            diffs.append({"kind": "added", "path": path, "new": b[path]})
        elif a[path] != b[path]:
            diffs.append({"kind": "hash_mismatch", "path": path,
                          "old": a[path], "new": b[path]})
    return diffs


def diff_main(p: dict) -> dict:
    """Diff tool entry.

    Semantics:
      - previous_manifest (baseline) is compared against the *current*
        `provenance/reproduction-manifest.json` (the latest run) when present,
        otherwise against the live filesystem entries the baseline records.
      - previous_provenance (baseline) is compared against the current
        `provenance/provenance.log` (both parsed as JSONL event lists).
    """
    root = resolve_root(p)
    emit_progress("computing result diff")
    prev = p.get("previous_manifest")
    prev_prov = p.get("previous_provenance")

    if not prev and not prev_prov:
        raise ToolError("MRV-E102", "diff requires previous_manifest (or previous_provenance)",
                        details={"field": "previous_manifest"})

    diffs: list[dict] = []
    if prev:
        prev_doc = _load_doc(root, prev)
        cur_manifest = os.path.join(root, "provenance", "reproduction-manifest.json")
        if os.path.isfile(cur_manifest):
            cur_doc = _load_doc(root, "provenance/reproduction-manifest.json")
            diffs.extend(diff_docs(prev_doc, cur_doc, prev,
                                   "provenance/reproduction-manifest.json"))
        else:
            diffs.extend(_diff_manifest_vs_tree(root, prev_doc))
    if prev_prov:
        prev_events = _load_log(root, prev_prov)
        cur_events = _load_log(root, "provenance/provenance.log")
        diffs.extend(diff_docs({"events": prev_events}, {"events": cur_events},
                               prev_prov, "provenance/provenance.log"))
    identical = bool(diffs) and all(d["kind"] == "identical" for d in diffs)
    return {
        "differences": diffs,
        "identical": identical,
        "difference_count": len([d for d in diffs if d["kind"] != "identical"]),
        "schema_version": "1.0.0",
    }


def _load_log(root: str, ref: str) -> list[dict]:
    full = safe_join(root, ref)
    if not os.path.isfile(full):
        return []
    events: list[dict] = []
    with open(full, encoding="utf-8") as fh:
        for lineno, raw in enumerate(fh, 1):
            raw = raw.strip()
            if not raw:
                continue
            try:
                events.append(json.loads(raw))
            except json.JSONDecodeError as exc:
                raise ToolError("MRV-E301",
                                f"corrupt log line {lineno} in {ref!r}: {exc}",
                                details={"path": ref, "line": lineno}) from exc
    return events


def _diff_manifest_vs_tree(root: str, manifest: dict) -> list[dict]:
    """Compare a manifest's recorded hashes against the live filesystem."""
    diffs: list[dict] = []
    entries = manifest.get("entries") or manifest.get("inputs") or []
    if not entries:
        return [{"kind": "modified", "path": "$",
                 "old": "manifest has no entries/inputs", "new": "no baseline"}]
    for e in entries:
        rel = e.get("path")
        if not rel:
            continue
        recorded = e.get("sha256") or e.get("hash")
        full = safe_join(root, rel)
        if not os.path.isfile(full):
            diffs.append({"kind": "removed", "path": rel, "old": recorded})
            continue
        try:
            cur = sha256_file(full)
        except OSError:
            continue
        if cur != recorded:
            diffs.append({"kind": "hash_mismatch", "path": rel,
                          "old": recorded, "new": cur})
    return diffs
