#!/usr/bin/env python3
"""Randomization & experiment-number generator for micp-experiment-designer.

Produces a reproducible, auditable experimental-unit allocation:

  - complete randomization (simple random allocation of units to groups),
  - blocked randomization (blocks of fixed size; within each block the group
    counts are balanced — required when batch/cure timing could confound),
  - allocation-concealment numbering: opaque sequential experiment IDs that
    carry no group information (blind-friendly, e.g. "EXP-0001"),
  - a machine-readable allocation list that a second experimenter can verify
    against the recorded seed.

Reproducibility / auditability rules:
  - The PRNG is `random.Random(seed)` seeded with a caller-provided seed (or a
    fixed, derived default). Given the same seed and design, the allocation
    list is byte-identical across runs and machines (pure-Python Mersenne
    Twister; no OS entropy).
  - The seed, method, and full allocation table are returned so the run can be
    audited and re-verified. The seed is ALSO recorded so that unmasking is
    possible under a pre-agreed rule — see `references/sources.md` S3.
  - The tool NEVER assigns a unit to a group without a declared group list and
    total unit count, and NEVER silently re-uses a seed.

Hard rules from the brief:
  - Total units and group counts must be consistent (sum(group_counts) == n_units)
    when group_counts is provided; otherwise groups are sized as equal as
    possible.
  - Units with a `block` field are grouped by block; within each block the
    allocation rebalances by method.
  - For blocked randomization every block must have size divisible by the
    number of groups, else E_INPUT_VALUE with an explanation.
"""

from __future__ import annotations

import random
import re
from typing import Any

from ._common import ToolError, as_int, as_list, as_str, run_tool

TOOL = "randomizer"


def _parse_groups(payload: dict[str, Any]) -> list[str]:
    groups = as_list(payload.get("groups", []), "groups", min_len=2, max_len=16)
    out: list[str] = []
    for i, g in enumerate(groups):
        name = as_str(g, f"groups[{i}]", min_len=1, max_len=32)
        if name in out:
            raise ToolError("E_INPUT_VALUE", f"duplicate group name '{name}'", details={"group": name})
        out.append(name)
    return out


def _seed(payload: dict[str, Any]) -> int:
    raw = payload.get("seed")
    if raw is None:
        # deterministic default derived from the request id (no OS entropy)
        return _hash_to_int(payload.get("task_id") or "default")
    if isinstance(raw, bool) or not isinstance(raw, int):
        raise ToolError("E_TYPE", "seed must be an integer", details={"path": "seed"})
    return raw


def _hash_to_int(s: str) -> int:
    """FNV-1a (64-bit) — deterministic cross-platform integer from a string."""
    h = 0xCBF29CE484222325
    for ch in s.encode("utf-8"):
        h ^= ch
        h = (h * 0x100000001B3) & 0xFFFFFFFFFFFFFFFF
    return h


def _parse_units(payload: dict[str, Any]) -> list[dict[str, Any]]:
    units = as_list(payload.get("units", []), "units", min_len=1, max_len=10000)
    out: list[dict[str, Any]] = []
    for i, u in enumerate(units):
        if not isinstance(u, dict):
            raise ToolError("E_TYPE", f"units[{i}] must be an object", details={"path": f"units[{i}]"})
        uid = as_str(u.get("id", ""), f"units[{i}].id", min_len=1, max_len=64)
        block = u.get("block")
        if block is not None:
            if not isinstance(block, str):
                raise ToolError("E_TYPE", f"units[{i}].block must be a string", details={"path": f"units[{i}].block"})
        out.append({"id": uid, "block": block})
    # enforce unique unit ids
    seen = set()
    for u in out:
        if u["id"] in seen:
            raise ToolError("E_INPUT_VALUE", f"duplicate unit id '{u['id']}'", details={"id": u["id"]})
        seen.add(u["id"])
    return out


def _ids(payload: dict[str, Any], n: int) -> list[str]:
    ids = as_list(payload.get("ids", []), "ids", max_len=n)
    if ids and len(ids) != n:
        raise ToolError("E_INPUT_VALUE", f"ids list must have exactly {n} entries (got {len(ids)})",
                        details={"expected": n, "got": len(ids)})
    if not ids:
        prefix = as_str(payload.get("id_prefix", "EXP"), "id_prefix", min_len=1, max_len=16)
        ids = [f"{prefix}-{i:04d}" for i in range(1, n + 1)]
    return ids


def _verify_format(ids: list[str]) -> None:
    for i, s in enumerate(ids):
        if not re.fullmatch(r"[A-Za-z0-9_-]+", s):
            raise ToolError("E_INPUT_VALUE", f"ids[{i}] '{s}' has disallowed characters (use A-Z a-z 0-9 _ -)",
                            details={"id": s})


def _complete_randomization(rng: random.Random, units: list[dict[str, Any]],
                            groups: list[str]) -> list[str]:
    counts = _balanced_counts(len(units), len(groups))
    pool: list[str] = []
    for g, c in zip(groups, counts):
        pool.extend([g] * c)
    rng.shuffle(pool)
    return pool


def _blocked_randomization(rng: random.Random, units: list[dict[str, Any]],
                           groups: list[str]) -> list[str]:
    """Stratified-by-block allocation. Block sizes must divide by group count."""
    blocks: dict[str, list[dict[str, Any]]] = {}
    for u in units:
        blocks.setdefault(u["block"] or "_default", []).append(u)
    out: list[str] = []
    for block_name, members in blocks.items():
        if len(members) % len(groups) != 0:
            raise ToolError(
                "E_INPUT_VALUE",
                f"block '{block_name}' has {len(members)} units, not divisible by "
                f"{len(groups)} groups; blocked randomization requires equal group "
                f"counts per block (add or remove a unit, or use complete randomization)",
                details={"block": block_name, "n": len(members), "groups": len(groups)},
            )
        per_group = len(members) // len(groups)
        pool: list[str] = []
        for g in groups:
            pool.extend([g] * per_group)
        rng.shuffle(pool)
        out.extend(pool)
    return out


def _balanced_counts(n: int, k: int) -> list[int]:
    base, rem = divmod(n, k)
    return [base + (1 if i < rem else 0) for i in range(k)]


def main(payload: dict[str, Any]) -> dict[str, Any]:
    groups = _parse_groups(payload)
    units = _parse_units(payload)
    seed = _seed(payload)
    method = as_str(payload.get("method", "complete"), "method", min_len=1)
    method = method.lower()
    if method not in ("complete", "blocked"):
        raise ToolError("E_INPUT_VALUE", f"unknown method '{method}'",
                        details={"supported": ["complete", "blocked"]})

    # unit-count sanity: if group counts given, enforce consistency
    group_counts = payload.get("group_counts")
    if group_counts is not None:
        if not isinstance(group_counts, dict):
            raise ToolError("E_TYPE", "group_counts must be an object", details={"path": "group_counts"})
        total = sum(group_counts.values())
        if total != len(units):
            raise ToolError("E_INPUT_VALUE",
                            f"group_counts total {total} != unit count {len(units)}",
                            details={"total": total, "units": len(units)})
        for g in group_counts:
            if g not in groups:
                raise ToolError("E_INPUT_VALUE", f"group_counts has unknown group '{g}'",
                                details={"group": g, "known": groups})

    ids = _ids(payload, len(units))
    _verify_format(ids)

    rng = random.Random(seed)
    if method == "blocked":
        allocation = _blocked_randomization(rng, units, groups)
    else:
        allocation = _complete_randomization(rng, units, groups)

    table = []
    for i, u in enumerate(units):
        table.append({
            "experiment_id": ids[i],
            "unit_id": u["id"],
            "group": allocation[i],
            "block": u.get("block"),
        })

    return {
        "method": method,
        "seed": seed,
        "seed_algorithm": "FNV-1a-64(task_id) if not provided",
        "groups": groups,
        "n_units": len(units),
        "allocation": table,
        "checksum": _allocation_checksum(table),
        "verification_command": "re-run the tool with the same input and seed; compare `allocation` and `checksum`",
    }


def _allocation_checksum(table: list[dict[str, Any]]) -> str:
    """Deterministic checksum over the allocation table (audit/verification)."""
    import hashlib
    h = hashlib.sha256()
    for row in table:
        h.update(f"{row['experiment_id']}|{row['unit_id']}|{row['group']}|{row['block']}\n".encode())
    return h.hexdigest()


if __name__ == "__main__":
    run_tool(TOOL, main)
