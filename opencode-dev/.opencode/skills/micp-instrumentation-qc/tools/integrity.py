"""micp-instrumentation-qc: raw/derived SHA-256 hashing, append-only hash-chained audit log, tamper detection.

Pure Python standard library. Deterministic. Enforces the skill's core invariant:
RAW DATA IS NEVER MODIFIED. Any derived record must reference its raw source by
SHA-256; the audit log is an append-only JSONL hash chain where each entry's
'prev_hash' is the SHA-256 of the previous entry's canonical JSON.

Security model: this is an audit trail for research integrity, not a cryptographic
oracle. It detects accidental modification and tampering within the trusted chain;
it cannot stop an adversary who rewrites the whole log. Timestamps used in the log
are the caller-supplied input timestamp when available (deterministic), else the
wall clock.
"""

from __future__ import annotations

import hashlib
import json
import os
from typing import Any

from _common import error, emit, read_input


def sha256_of(obj: Any, *, exclude: str | None = None) -> str:
    """Deterministic SHA-256 of an arbitrary JSON-serializable object.

    If `exclude` is given, that key is dropped from a dict before hashing (used so
    the self-referential entry_hash field is not part of its own hash).
    """
    if isinstance(obj, dict) and exclude and exclude in obj:
        obj = {k: v for k, v in obj.items() if k != exclude}
    canonical = json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _stable_json(entry: dict[str, Any]) -> str:
    return json.dumps(entry, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def sha256_file(path: str) -> str:
    """SHA-256 of a file's bytes (streamed)."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(65536), b""):
            h.update(block)
    return h.hexdigest()


def verify_raw(raw: list[Any]) -> dict[str, Any]:
    """Hash raw data references. Each element may be a path string or inline content."""
    results: list[dict[str, Any]] = []
    ok = True
    for i, r in enumerate(raw):
        if isinstance(r, str) and os.path.isfile(r):
            digest = sha256_file(r)
            source = r
            kind = "file"
        else:
            digest = sha256_of(r)
            source = "<inline>"
            kind = "inline"
        results.append({"index": i, "source": source, "kind": kind, "sha256": digest})
    return {"status": "ok" if ok else "failed", "results": results}


def append_log(entry: dict[str, Any], log_path: str, prev_hash: str | None = None) -> dict[str, Any]:
    """Append a single entry to the hash-chained JSONL audit log.

    The chain is built from the *existing* tail of the log (read at call time), so
    appends are safe even if the file already has entries. Returns the new entry
    with its hash and the chain's new tail hash.
    """
    if not log_path:
        raise ValueError("MICQ-E1004: audit log path required")
    # Load tail
    tail = None
    entries: list[dict[str, Any]] = []
    if os.path.isfile(log_path):
        with open(log_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    e = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise ValueError(f"MICQ-E1009: audit log corrupt at line: {exc}") from exc
                entries.append(e)
                tail = e

    if prev_hash is None:
        prev_hash = tail.get("entry_hash") if tail else None

    # Check the provided prev_hash agrees with the actual tail (chain integrity).
    if prev_hash != (tail.get("entry_hash") if tail else None):
        raise ValueError("MICQ-E1009: audit log chain broken (prev_hash does not match tail)")

    entry.setdefault("timestamp", os.environ.get("MICP_QC_NOW", None) or _now_iso())
    entry["prev_hash"] = prev_hash
    entry["entry_index"] = len(entries)
    body_hash = sha256_of(entry, exclude="entry_hash")
    entry["entry_hash"] = body_hash

    with open(log_path, "a", encoding="utf-8") as f:
        f.write(_stable_json(entry) + "\n")

    return {"appended": entry, "tail_hash": body_hash}


def _now_iso() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()


def verify_log(log_path: str) -> dict[str, Any]:
    """Verify the full hash chain of an audit log. Returns chain_ok + first broken index."""
    if not log_path or not os.path.isfile(log_path):
        raise ValueError("MICQ-E1004: audit log not found")
    prev = None
    index = 0
    broken_at: int | None = None
    with open(log_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            e = json.loads(line)
            if prev is not None and e.get("prev_hash") != prev:
                broken_at = index
                break
            if sha256_of(e, exclude="entry_hash") != e.get("entry_hash"):
                broken_at = index
                break
            prev = e.get("entry_hash")
            index += 1
    return {"chain_ok": broken_at is None, "entries": index, "broken_at": broken_at}


def run(data: dict[str, Any]) -> dict[str, Any]:
    """CLI entry: integrity [raw] | [log-append] | [log-verify].

    The canonical payload location is qc_input.raw / qc_input.derived (matching
    input.schema.json); top-level raw/derived are also accepted for compatibility.
    """
    action = data.get("action", "raw")
    qc_input = data.get("qc_input") or {}
    raw: Any = qc_input.get("raw") if qc_input.get("raw") is not None else data.get("raw")
    if action == "raw":
        return verify_raw(raw or [])
    if action == "log-append":
        return append_log(data.get("entry") or {}, data.get("log_path") or "")
    if action == "log-verify":
        return verify_log(data.get("log_path") or "")
    raise ValueError(f"MICQ-E1003: unknown integrity action '{action}'")
