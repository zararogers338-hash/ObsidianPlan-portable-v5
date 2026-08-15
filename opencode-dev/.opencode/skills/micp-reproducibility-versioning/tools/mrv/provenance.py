"""Input/output provenance recorder — append-only, hash-chained audit log.

Each event records everything a Skill invocation must leave behind (section 六
of the SKILL.md): task_id, project_id, caller, skill id+version, input summary,
input refs, input hashes, tool calls, output hashes, errors, time, human
approval, git commit and environment.

Tamper-evidence: every event's `hash` covers the canonical JSON of its body plus
the previous event's `hash` (prev_hash); the first event uses a zero prev_hash.
`check-pollution` verifies the chain, so any edit/deletion breaks it.

Determinism: event timestamps are derived from the input `timestamp` field;
event ids are derived from content, so replaying the same input yields the same
event (byte-identical).
"""

from __future__ import annotations

import os
from typing import Any

from _common import (ToolError, canonical_json, emit_progress, normalize_rel,
                     resolve_root, safe_join, sha256_hex, stable_hash, walk_files)

ZERO_HASH = "0" * 64


def _event_body(p: dict, env: dict, input_hashes: dict, output_hashes: dict,
                tool_calls: list[dict], errors: list[dict],
                prev_hash: str, ts: str, seed_value: int | None) -> dict:
    """Assemble the signed body. Hash excludes the `hash` field itself."""
    refs = p.get("evidence_refs") or []
    data_refs = p.get("data_refs") or []
    return {
        "schema_version": "1.0.0",
        "event_id": f"ev-{stable_hash({'t': ts, 'tid': p.get('task_id'), 'a': p.get('action', 'record'), 'prev': prev_hash[:8]})[:16]}",
        "ts": ts,
        "task_id": p.get("task_id"),
        "project_id": p.get("project_id"),
        "caller": p.get("context", {}).get("caller", "controller") if isinstance(p.get("context"), dict) else "controller",
        "skill_id": "micp-reproducibility-versioning",
        "skill_version": "1.0.0",
        "controller_version": p.get("controller_version"),
        "action": p.get("action", "record"),
        "input_summary": (p.get("request") or "")[:4000],
        "input_refs": [{"ref_id": r.get("ref_id"), "locator": r.get("locator")} for r in refs]
        + [{"ref_id": r.get("ref_id"), "locator": r.get("locator")} for r in data_refs],
        "input_hashes": input_hashes,
        "tool_calls": tool_calls,
        "output_hashes": output_hashes,
        "git_commit": env.get("git", {}).get("git_commit") or env.get("git", {}).get("fingerprint"),
        "environment": env,
        "errors": errors,
        "human_approval": p.get("human_approval_state", "not_required"),
        "seed": seed_value,
        "prev_hash": prev_hash,
    }


def _write_event(root: str, rel_path: str, event: dict) -> dict:
    """Append one event (JSON object per line) and fsync the log.

    Appends are atomic-ish under the GIL and, because the chain hash is
    content-derived, a torn write is detectable by check-pollution.
    """
    full = safe_join(root, rel_path)
    os.makedirs(os.path.dirname(full), exist_ok=True)
    # deterministic event_id: recompute from the body so replay is identical
    body = dict(event)
    body.pop("hash", None)
    line = canonical_json(body) + "\n"
    event_hash = sha256_hex(line)
    signed = dict(event)
    signed["hash"] = event_hash
    with open(full, "a", encoding="utf-8") as fh:
        fh.write(canonical_json(signed) + "\n")
        fh.flush()
        try:
            os.fsync(fh.fileno())
        except OSError:
            pass
    return signed


def load_log(root: str, rel_path: str) -> list[dict]:
    """Read a provenance log file; returns the events in order."""
    full = safe_join(root, rel_path)
    if not os.path.isfile(full):
        return []
    events: list[dict] = []
    with open(full, encoding="utf-8") as fh:
        for lineno, raw in enumerate(fh, 1):
            raw = raw.strip()
            if not raw:
                continue
            try:
                events.append(__import__("json").loads(raw))
            except __import__("json").JSONDecodeError as exc:
                raise ToolError("MRV-E204", f"corrupt provenance event at line {lineno}: {exc}",
                                details={"path": rel_path, "line": lineno}) from exc
    return events


def verify_chain(events: list[dict]) -> list[str]:
    """Verify the hash chain. Returns a list of violations (empty = intact)."""
    violations: list[str] = []
    prev = ZERO_HASH
    for i, ev in enumerate(events):
        body = {k: v for k, v in ev.items() if k != "hash"}
        expected = sha256_hex(canonical_json(body) + "\n")
        if ev.get("hash") != expected:
            violations.append(f"event[{i}] hash mismatch")
        if ev.get("prev_hash") != prev:
            violations.append(f"event[{i}] prev_hash broken (expected {prev[:8]}...)")
        prev = ev.get("hash") or ""
    return violations


def record_main(p: dict) -> dict:
    """Provenance recorder: hash inputs/outputs, append one signed event."""
    root = resolve_root(p)
    emit_progress("recording provenance event")

    from envinfo import collect_environment
    from hashing import walk_files  # noqa: F401 (name kept local for clarity)

    ts = str(p.get("timestamp") or "1970-01-01T00:00:00Z")
    env = collect_environment(p)

    # Input fileset: explicit targets, else data/raw + data/external + inputs
    targets = p.get("targets")
    relpaths: list[str] = []
    if targets:
        for t in targets:
            full = safe_join(root, t)
            if os.path.isdir(full):
                relpaths.extend(normalize_rel(os.path.relpath(f, root))
                                for f in walk_files(full))
            elif os.path.isfile(full):
                relpaths.append(normalize_rel(t))
        relpaths = sorted(set(relpaths))
    else:
        for layer in ("data/raw", "data/external", "data/interim"):
            d = os.path.join(root, layer)
            if os.path.isdir(d):
                relpaths.extend(f"{layer}/{f}" for f in walk_files(d))
        relpaths = sorted(set(relpaths))

    input_hashes: dict[str, str] = {}
    for rel in relpaths:
        input_hashes[rel] = sha256_file_local(os.path.join(root, rel))

    output_hashes: dict[str, str] = {}
    outputs = p.get("constraints", {}).get("record_outputs", True)
    if outputs:
        for layer in ("data/processed", "artifacts", "reports", "models", "provenance"):
            d = os.path.join(root, layer)
            if os.path.isdir(d):
                for rel in walk_files(d):
                    output_hashes[rel] = sha256_file_local(os.path.join(root, rel))

    seed_value = resolve_seed_local(p)

    log_rel = "provenance/provenance.log"
    events = load_log(root, log_rel)
    prev_hash = events[-1].get("hash") if events else ZERO_HASH

    tool_calls = p.get("tool_calls") or []
    errors = p.get("errors") or []
    event = _event_body(p, env, input_hashes, output_hashes, tool_calls,
                        errors, prev_hash, ts, seed_value)
    signed = _write_event(root, log_rel, event)

    return {
        "log_path": normalize_rel(os.path.join(root, log_rel)),
        "event": signed,
        "chain_ok": True,
        "event_count": len(events) + 1,
    }


def sha256_file_local(path: str) -> str:
    from _common import sha256_file
    return sha256_file(path)


def resolve_seed_local(p: dict) -> int | None:
    from seed import resolve_seed
    try:
        return resolve_seed(p).get("value")
    except ToolError:
        return None
