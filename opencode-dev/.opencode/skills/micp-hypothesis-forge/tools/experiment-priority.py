"""Discriminating-experiment priority tool.

Input (one JSON on stdin):
  {
    "experiments": [
      {"id": "E1", "name": "...", "information_gain_bits": 0.4,
       "cost_rank": 1, "cost_units": "usd", "risk_rank": 2, "risk_level": "low",
       "time_scale_days": 3, "feasibility": 0.9},
      ...
    ],
    "max_budget_rank": null,    # optional hard cap on cost_rank (1 = cheapest)
    "weights": {"gain": 0.5, "cost": 0.3, "risk": 0.2}   # optional; sums to 1
  }

Ranking score = w_gain*norm_gain - w_cost*norm_cost - w_risk*norm_risk + small
feasibility bonus. All normalization is deterministic; ties broken by id.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import ToolError, as_dict, emit_ok, run_tool, check_finite

TOOL = "experiment-priority"

RISK_LEVELS = ("low", "medium", "high")
RISK_RANK = {"low": 1, "medium": 2, "high": 3}


def _norm(values: list[float]) -> list[float]:
    if not values:
        return []
    lo, hi = min(values), max(values)
    if hi == lo:
        return [0.5] * len(values)
    return [(v - lo) / (hi - lo) for v in values]


def main(payload: Any) -> dict:
    payload = as_dict(payload)
    experiments = payload.get("experiments")
    if experiments is None:
        raise ToolError("MHX-E102", "missing required field `experiments`.", exit_code=2)
    if not isinstance(experiments, list) or not experiments:
        raise ToolError("MHX-E102", "experiments must be a non-empty array.", exit_code=2)

    weights = payload.get("weights") or {"gain": 0.5, "cost": 0.3, "risk": 0.2}
    w_gain = check_finite(weights.get("gain", 0.5), what="weights.gain")
    w_cost = check_finite(weights.get("cost", 0.3), what="weights.cost")
    w_risk = check_finite(weights.get("risk", 0.2), what="weights.risk")
    total = w_gain + w_cost + w_risk
    if total <= 0:
        raise ToolError("MHX-E301", "weights must sum to a positive value.", exit_code=2)

    rows = []
    for e in experiments:
        if not isinstance(e, dict):
            raise ToolError("MHX-E105", "each experiment must be an object.", exit_code=2)
        if not isinstance(e.get("id"), str) or not e["id"].strip():
            raise ToolError("MHX-E102", "experiment missing non-empty `id`.", exit_code=2)
        gain = check_finite(e.get("information_gain_bits", 0.0), what=f"{e['id']}.information_gain_bits")
        cost_rank = check_finite(e.get("cost_rank", 1.0), what=f"{e['id']}.cost_rank")
        risk = e.get("risk_level", "medium")
        if risk not in RISK_LEVELS:
            raise ToolError("MHX-E105",
                            f"{e['id']}.risk_level must be one of {RISK_LEVELS}, got {risk!r}.",
                            exit_code=2)
        risk_rank = float(RISK_RANK[risk])
        if e.get("risk_rank") is not None:
            risk_rank = check_finite(e["risk_rank"], what=f"{e['id']}.risk_rank")
        time_days = check_finite(e.get("time_scale_days", 1.0), what=f"{e['id']}.time_scale_days")
        feasibility = check_finite(e.get("feasibility", 0.5), what=f"{e['id']}.feasibility")
        rows.append({
            "id": e["id"], "name": e.get("name", e["id"]),
            "information_gain_bits": gain, "cost_rank": cost_rank,
            "risk_level": risk, "risk_rank": risk_rank,
            "time_scale_days": time_days, "feasibility": feasibility,
        })

    # Hard budget cap on cost_rank
    max_cost = payload.get("max_budget_rank")
    if max_cost is not None:
        max_cost = check_finite(max_cost, what="max_budget_rank")
        infeasible = [r for r in rows if r["cost_rank"] > max_cost]
        rows = [r for r in rows if r["cost_rank"] <= max_cost]
    else:
        infeasible = []

    gains = _norm([r["information_gain_bits"] for r in rows])
    costs = _norm([r["cost_rank"] for r in rows])
    risks = _norm([r["risk_rank"] for r in rows])

    scored = []
    for i, r in enumerate(rows):
        score = (w_gain * gains[i] - w_cost * costs[i] - w_risk * risks[i]
                 + 0.05 * r["feasibility"])
        scored.append({**r, "score": round(score, 4)})

    scored.sort(key=lambda r: (-r["score"], r["id"]))
    for i, r in enumerate(scored, start=1):
        r["rank"] = i

    return {
        "ranked_experiments": scored,
        "ranked_ids": [r["id"] for r in scored],
        "budget_infeasible": [r["id"] for r in infeasible],
        "weights_used": {"gain": w_gain, "cost": w_cost, "risk": w_risk},
        "notes": [
            "score = w_gain*norm(gain) - w_cost*norm(cost_rank) - w_risk*norm(risk_rank)"
            " + 0.05*feasibility; ranks are 0..1 normalizations within this batch.",
            "prefer experiments with high information gain, low cost rank, and low risk;"
            " the matrix tool computes information_gain_bits from hypothesis pairs.",
        ],
    }


if __name__ == "__main__":
    run_tool(TOOL, main)
