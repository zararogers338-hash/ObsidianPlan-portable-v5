"""File and directory hashing primitives + the data-manifest generator.

Every hash here is CALCULATED from real file content (never guessed, never
cached). The data manifest walks a project tree, tags each file with its data
layer, and reports:
  - sha256 per file,
  - a deterministic directory fingerprint (git fallback identity),
  - layer statistics and violations (e.g. unexpected writes under data/raw),
  - whether data/raw contains registered-immutable files that differ from a
    previous manifest (tamper evidence).

Pure stdlib, offline, deterministic.
"""

from __future__ import annotations

import os
from typing import Any

from _common import (ToolError, dir_fingerprint, emit_progress, normalize_rel,
                     safe_join, sha256_file, walk_files)

DATA_LAYERS = [
    "data/raw",
    "data/interim",
    "data/processed",
    "data/external",
    "artifacts",
    "models",
    "experiments",
    "evidence",
    "failures",
    "reports",
    "provenance",
]


def classify_layer(rel: str) -> str:
    """Best-effort layer classification: first matching top-level segment wins."""
    segs = normalize_rel(rel).split("/")
    if len(segs) >= 2 and "/".join(segs[:2]) == "data/raw":
        return "data/raw"
    if len(segs) >= 2 and "/".join(segs[:2]) in ("data/interim", "data/processed", "data/external"):
        return "/".join(segs[:2])
    if segs and segs[0] in DATA_LAYERS:
        return segs[0]
    return "unmanaged"


def _is_managed_by_skill(rel: str) -> bool:
    return classify_layer(rel) != "unmanaged" or rel.startswith("provenance/")


def manifest_main(p: dict) -> dict:
    """Generate a data manifest for root (or targets)."""
    from _common import resolve_root

    root = resolve_root(p)
    targets = p.get("targets") or []
    emit_progress(f"generating data manifest for {root}")

    if targets:
        relpaths: list[str] = []
        for t in targets:
            full = safe_join(root, t)
            if os.path.isdir(full):
                relpaths.extend(normalize_rel(os.path.relpath(f, root))
                                for f in walk_files(full))
            elif os.path.isfile(full):
                relpaths.append(normalize_rel(t))
            else:
                raise ToolError("MRV-E302", f"target does not exist: {t!r}",
                                details={"target": t})
        relpaths = sorted(set(relpaths))
    else:
        relpaths = walk_files(root)

    entries: list[dict[str, Any]] = []
    layer_counts: dict[str, int] = {}
    layer_bytes: dict[str, int] = {}
    raw_files: list[str] = []
    for rel in relpaths:
        full = os.path.join(root, rel)
        try:
            digest = sha256_file(full)
        except OSError as exc:
            raise ToolError("MRV-E302", f"cannot hash {rel!r}: {exc}",
                            details={"path": rel}) from exc
        size = os.path.getsize(full)
        layer = classify_layer(rel)
        layer_counts[layer] = layer_counts.get(layer, 0) + 1
        layer_bytes[layer] = layer_bytes.get(layer, 0) + size
        if layer == "data/raw":
            raw_files.append(rel)
        entries.append({
            "path": rel,
            "layer": layer,
            "size": size,
            "sha256": digest,
        })

    entries.sort(key=lambda e: e["path"])
    digest = dir_fingerprint(root, relpaths)
    previous = p.get("previous_manifest")
    raw_violations: list[dict] = []
    if previous:
        prev_path = os.path.join(root, previous) if previous.startswith(("data/", "provenance/", "reports/", "lockfiles/")) else previous
        if os.path.isfile(prev_path):
            try:
                import json
                prev = json.load(open(prev_path, encoding="utf-8"))
                prev_hashes = {e["path"]: e.get("sha256") for e in prev.get("entries", [])}
                for rel in raw_files:
                    cur = next((e for e in entries if e["path"] == rel), None)
                    old = prev_hashes.get(rel)
                    if cur and old and cur["sha256"] != old:
                        raw_violations.append({
                            "path": rel,
                            "registered_hash": old,
                            "current_hash": cur["sha256"],
                            "severity": "error",
                        })
            except Exception as exc:  # noqa: BLE001 - previous manifest is advisory
                raise ToolError("MRV-E203", f"previous manifest unreadable: {exc}",
                                details={"path": previous}) from exc

    return {
        "manifest_id": f"data-manifest-{digest[:12]}",
        "schema_version": "1.0.0",
        "root": root,
        "entry_count": len(entries),
        "fingerprint": digest,
        "layer_counts": layer_counts,
        "layer_bytes": layer_bytes,
        "raw_file_count": len(raw_files),
        "raw_write_protection_ok": _raw_write_protection_ok(root),
        "raw_violations": raw_violations,
        "entries": entries,
    }


def _raw_write_protection_ok(root: str) -> bool:
    """Heuristic write-protection check: data/raw must exist and be read-only
    at the directory level, OR every file under it must be flagged read-only.

    On Windows, the read-only attribute is authoritative; on POSIX we check the
    mode bits. A missing data/raw is *not* a violation (no raw data to protect),
    but an existing data/raw with writable files is.
    """
    raw_dir = os.path.join(root, "data", "raw")
    if not os.path.isdir(raw_dir):
        return True
    protected = True
    details: list[str] = []
    for dirpath, _dirnames, filenames in os.walk(raw_dir):
        for f in filenames:
            full = os.path.join(dirpath, f)
            if os.access(full, os.W_OK):
                protected = False
                details.append(normalize_rel(os.path.relpath(full, root)))
    return protected


def check_raw_main(p: dict) -> dict:
    """Raw-data write-protection checker: the MRV-E501 gate."""
    from _common import resolve_root

    root = resolve_root(p)
    emit_progress("checking raw-data write protection")
    raw_dir = os.path.join(root, "data", "raw")
    exists = os.path.isdir(raw_dir)
    ok = _raw_write_protection_ok(root)
    violations = _raw_write_violations(root) if exists else []
    return {
        "data_raw_present": exists,
        "protected": ok,
        "violations": violations,
        "verdict": "protected" if (ok or not exists) else "write_protection_breach",
        "note": ("data/raw files must be read-only; manual edits must create new "
                 "derived files and leave an audit trail."),
    }


def _raw_write_violations(root: str) -> list[dict]:
    raw_dir = os.path.join(root, "data", "raw")
    out: list[dict] = []
    if not os.path.isdir(raw_dir):
        return out
    for dirpath, _dirnames, filenames in os.walk(raw_dir):
        for f in filenames:
            full = os.path.join(dirpath, f)
            if os.access(full, os.W_OK):
                out.append({"path": normalize_rel(os.path.relpath(full, root))})
    return out


def _is_managed(rel: str) -> bool:
    return _is_managed_by_skill(rel)
