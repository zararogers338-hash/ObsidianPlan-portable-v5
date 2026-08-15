"""Image integrity / hash-chain auditing for SEM image provenance (spec §八.4, §九 test #8).

The spec requires: 原始图像不可覆盖;任何图像增强、去噪、分割和人工修改必须保留参数和审计日志.
This module provides the hash bookkeeping that makes that checkable:

  * SHA-256 digest of a raw image file (bytes), plus a JSON sidecar path.
  * ``verify`` mode: recompute a hash and compare against a stored/claimed
    hash — mismatch raises OMM-E501 (state corrupted) with the old/new digests.
  * ``chain`` mode: append to an append-only hash chain (JSONL), where every
    entry carries the previous entry's hash — so processing history cannot be
    silently rewritten (tamper-evident audit trail).
  * A blind-test helper ``describe_processing_diff`` so an auditor can compare
    a "before" and "after" hash claim without trusting either.

Everything is offline and pure stdlib (hashlib/json). No image is ever
modified: hashing reads bytes only.
"""

from __future__ import annotations

import hashlib
import json
import os
from typing import Any

from .errors import OmError, make_error

HASH_ALGO = "sha256"


def sha256_file(path: str, chunk_size: int = 1 << 20) -> str:
    """Return the lowercase hex SHA-256 of a file's bytes (streaming read)."""
    if not os.path.isfile(path):
        raise make_error("OMM-E206", "图像文件不可读或损坏", {"path": path})
    h = hashlib.sha256()
    try:
        with open(path, "rb") as fh:
            while True:
                chunk = fh.read(chunk_size)
                if not chunk:
                    break
                h.update(chunk)
    except OSError as exc:  # pragma: no cover - OS-level read failure
        raise make_error("OMM-E206", f"图像文件读取失败: {exc}", {"path": path}) from exc
    return h.hexdigest()


def sha256_bytes(data: bytes) -> str:
    """Return the lowercase hex SHA-256 of raw bytes (e.g. a PNG in memory)."""
    return hashlib.sha256(data).hexdigest()


def verify_file_hash(path: str, expected_hash: str | None = None, *, claimed: str | None = None) -> dict[str, Any]:
    """Verify a file's SHA-256 against an expected/claimed hash.

    ``expected_hash`` is the reference the caller believes is correct;
    ``claimed`` is an alias for the same concept (either may be used).
    Returns a report; a mismatch raises OMM-E501 (do not proceed on a
    corrupted/untrusted original — the skill must not analyse an image whose
    integrity cannot be established).
    """
    expected = expected_hash if expected_hash is not None else claimed
    actual = sha256_file(path)
    ok = expected is None or actual == expected
    report = {
        "algo": HASH_ALGO,
        "path": path,
        "sha256": actual,
        "expected_sha256": expected,
        "match": ok,
    }
    if not ok:
        raise make_error(
            "OMM-E501",
            "图像哈希不匹配:原始文件可能被修改或损坏",
            {"path": path, "expected_sha256": expected, "actual_sha256": actual},
        )
    return report


def _load_chain(chain_path: str) -> list[dict[str, Any]]:
    if not os.path.isfile(chain_path):
        return []
    entries: list[dict[str, Any]] = []
    with open(chain_path, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                entries.append(json.loads(line))
    return entries


def _chain_tail_hash(entries: list[dict[str, Any]]) -> str | None:
    if not entries:
        return None
    last = entries[-1]
    payload = last.get("payload") or last
    return last.get("entry_hash") or sha256_bytes(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8"))


def append_chain(
    chain_path: str,
    entry: dict[str, Any],
    *,
    dry_run: bool = True,
    approval_granted: bool = False,
) -> dict[str, Any]:
    """Append a tamper-evident entry to an append-only JSONL hash chain.

    Each entry stores ``prev_hash`` (the digest of the previous entry) and its
    own ``entry_hash`` = sha256(payload + prev_hash). ``dry_run=True`` (default)
    only returns what *would* be written; writing requires
    ``approval_granted=True`` (spec §七 write-gate).
    """
    prev = _chain_tail_hash(_load_chain(chain_path))
    payload = {
        "action": "image_hash.append_chain",
        "path": entry.get("path"),
        "sha256": entry.get("sha256"),
        "label": entry.get("label", "raw"),
        "note": entry.get("note"),
        "prev_hash": prev,
    }
    entry_hash = sha256_bytes(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8"))
    result = {
        "dry_run": dry_run,
        "chain_path": chain_path,
        "prev_hash": prev,
        "entry_hash": entry_hash,
        "would_write": {"payload": payload, "entry_hash": entry_hash},
    }
    if dry_run:
        return result
    if not approval_granted:
        raise make_error("OMM-E303", "审计日志写入被审批门拦截,需 human_approval_state.granted=true", {"chain_path": chain_path})
    with open(chain_path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps({"payload": payload, "entry_hash": entry_hash}, ensure_ascii=False) + "\n")
    result["written"] = True
    return result


def verify_chain(chain_path: str) -> dict[str, Any]:
    """Recompute every entry's hash against the chain's own prev_hash links.

    Detects any tampered/missing/reordered entry (hash chain broken). Pure
    read; never writes.
    """
    entries = _load_chain(chain_path)
    report: dict[str, Any] = {"ok": True, "entries": len(entries), "issues": []}
    prev: str | None = None
    for i, ent in enumerate(entries):
        payload = ent.get("payload") or ent
        declared = ent.get("entry_hash")
        recomputed = sha256_bytes(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8"))
        if declared is not None and declared != recomputed:
            report["ok"] = False
            report["issues"].append({"index": i, "kind": "entry_hash_mismatch"})
        if payload.get("prev_hash") != prev:
            report["ok"] = False
            report["issues"].append({"index": i, "kind": "prev_hash_link_broken"})
        prev = recomputed
    return report


def describe_processing_diff(before_hash: str, after_hash: str, *, params: dict[str, Any] | None = None) -> dict[str, Any]:
    """Blind-test helper: declare whether a before/after hash pair differ and
    record the processing parameters, without trusting either side (spec §八.4).
    """
    same = before_hash == after_hash
    return {
        "before_sha256": before_hash,
        "after_sha256": after_hash,
        "changed": not same,
        "note": "哈希不同说明像素级发生过修改(含任何去噪/分割/增强);哈希相同不代表未处理(处理可无损往返)",
        "processing_params_recorded": params or {},
        "audit_recommendation": (
            "哈希已改变:必须保留处理参数与审计日志,且原始图像不可覆盖"
            if not same
            else "哈希一致:若仍声称处理过,应提供处理参数以证明无损处理"
        ),
    }
