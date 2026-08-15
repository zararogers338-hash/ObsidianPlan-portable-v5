"""Pseudo-replication detector (伪重复检测器).

Determines whether rows in a dataset are independent samples or multiple
measurements of the same sampling unit. Resolution order:

  1. explicit `sampling_unit` column
  2. `batch` column (rows sharing a batch are not independent if the batch is
     the experimental unit)
  3. `id`/specimen column (multiple rows per id = repeated measures)
  4. position/time columns (multiple rows per column/time = nested)

For each detected structure it reports the effective independent n versus the
row count. When the analysis claims a group difference that is significant
only because pseudo-replication inflated n, this is BLOCKING material
(BLOCK-5) — the detector reports the numbers; the blocking engine decides.

Offline, deterministic, pure stdlib.
"""

from __future__ import annotations

from typing import Any

from common import ToolError, emit_progress
from errors import OrtErrorCode, OrtError


def _resolve_unit(row: dict[str, Any], col: dict[str, Any]) -> tuple[str, str | None]:
    """Return (unit_key, strategy)."""
    su = col.get("sampling_unit")
    if su:
        return (f"{su}:{row.get(col['name'])}", "sampling_unit")
    if col.get("role") == "batch":
        return (f"batch:{row.get(col['name'])}", "batch")
    if col.get("role") == "id":
        return (f"id:{row.get(col['name'])}", "id")
    if col.get("role") == "position":
        return (f"pos:{row.get(col['name'])}", "position")
    if col.get("role") == "time":
        return (f"time:{row.get(col['name'])}", "time")
    return (f"row:{row.get(col['name'])}", None)


def _detect(payload: dict[str, Any]) -> dict[str, Any]:
    samples = payload.get("samples") or []
    columns = payload.get("data_columns") or []
    if not samples or not columns:
        raise OrtError(OrtErrorCode.INPUT_SCHEMA_VIOLATION,
                       "pseudo: samples and data_columns are required",
                       detail={"how_to_fix": "attach the data rows and the column dictionary"})

    col_by_name = {c.get("name"): c for c in columns}
    # pick the id-like column: sampling_unit > batch > id > position > time
    strategy_col = None
    strategy = None
    for cand, role_value in (("sampling_unit", "sampling_unit"),
                             ("batch", "batch"), ("id", "id"),
                             ("position", "position"), ("time", "time")):
        for c in columns:
            if cand == "sampling_unit" and c.get("sampling_unit"):
                strategy_col = c
                strategy = "sampling_unit"
                break
            if cand != "sampling_unit" and c.get("role") == role_value:
                strategy_col = c
                strategy = role_value
                break
        if strategy_col:
            break

    if strategy_col is None:
        # every row is its own unit → no pseudo-replication detectable
        return {
            "detected": False,
            "effective_n": len(samples),
            "rows": len(samples),
            "strategy": None,
            "findings": [],
        }

    units: dict[str, int] = {}
    for row in samples:
        key, _ = _resolve_unit(row, strategy_col)
        units[key] = units.get(key, 0) + 1
    effective_n = len(units)
    findings = []
    if effective_n < len(samples):
        repeated = [{"unit": u, "rows": c} for u, c in sorted(units.items()) if c > 1]
        findings.append({
            "unit": strategy,
            "reason": f"{len(samples)} rows collapse to {effective_n} independent {strategy} unit(s): "
                      "multiple measurements share a sampling unit and are not independent",
            "effective_n": effective_n,
            "rows": len(samples),
            "recommended_analysis": (
                "aggregate to the sampling unit before group inference, or use a "
                "mixed-effects model routed to obsidian-modeling-optimizer"
            ),
        })
        # whether the claim leans on inflated n
        claim_group_difference = bool(payload.get("claim_group_difference"))
        findings[0]["claim_relies_on_inflated_n"] = claim_group_difference and effective_n < 8
    return {
        "detected": effective_n < len(samples),
        "effective_n": effective_n,
        "rows": len(samples),
        "strategy": strategy,
        "strategy_column": strategy_col.get("name"),
        "findings": findings,
    }


def main(payload: dict[str, Any]) -> dict[str, Any]:
    emit_progress("pseudo: detecting pseudo-replication")
    return _detect(payload)


if __name__ == "__main__":
    from common import read_stdin_envelope, run_tool
    run_tool("pseudo", lambda: main(read_stdin_envelope()))
