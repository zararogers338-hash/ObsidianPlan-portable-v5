#!/usr/bin/env python3
"""budget_estimator.py — reference-class budget estimation per task kind.

Implements an outside-view estimator (planning-fallacy mitigation, see
references/sources.md S5): each task kind has a reference-class base effort,
and the estimate = base × multipliers × buffer. Reference classes are
PROJECT-CUSTOM DEFAULTS calibrated for Panshi MICP research workflows, not
literature values; the method (reference-class forecasting) is what S5 justifies.

Deterministic and offline. All estimates are tagged CALCULATED.

stdin:
  {"tasks": [{"id": "...", "kind": "<task kind>", "risk_level": "low|medium|high"?,
              "data_sensitivity": "public|internal|sensitive|restricted"?,
              "est_context_tokens": int?}...],
   "config": {"buffer": 1.3, "currency": "USD", "cost_per_hour": 0.0}?}

stdout result:
  {"estimates": {id: {kind, base_hours, multipliers: {...}, buffer,
                       est_effort_hours, est_cost, basis: "CALCULATED"}},
   "totals": {"hours": float, "cost": float},
   "warnings": [...]}
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from _common import ToolError, as_dict, as_list, as_number, as_str, run_tool

# Reference classes (project-custom; hours of focused expert/agent work).
# Chosen so that a single node stays verifiable (<= 40 h default upper bound).
REFERENCE_CLASSES: dict[str, dict] = {
    "evidence_retrieval":  {"base_hours": 2.0,  "note": "search + screen + shortlist sources"},
    "mechanism_reasoning": {"base_hours": 4.0,  "note": "chain-of-mechanism analysis from evidence"},
    "experiment_design":   {"base_hours": 6.0,  "note": "protocol + controls + analysis plan"},
    "data_processing":     {"base_hours": 3.0,  "note": "clean/transform/QC a dataset"},
    "simulation":          {"base_hours": 8.0,  "note": "model setup, runs, sanity checks"},
    "measurement":         {"base_hours": 4.0,  "note": "instrument/data acquisition incl. QC"},
    "audit":               {"base_hours": 3.0,  "note": "independent check against criteria"},
    "decision":            {"base_hours": 1.5,  "note": "weigh evidence, record decision + rationale"},
    "synthesis":           {"base_hours": 4.0,  "note": "merge multiple evidence streams"},
    "red_team_review":     {"base_hours": 3.0,  "note": "adversarial review of a claim or artifact"},
    "human_wait":          {"base_hours": 0.25, "note": "wall-clock wait on human; effort ~0"},
}

VALID_KINDS = sorted(REFERENCE_CLASSES)

RISK_MULTIPLIER = {"low": 1.0, "medium": 1.2, "high": 1.5}
SENSITIVITY_MULTIPLIER = {"public": 1.0, "internal": 1.05, "sensitive": 1.2, "restricted": 1.4}
CONTEXT_MULTIPLIER_THRESHOLD = 80_000  # tokens; above this, comprehension overhead kicks in
CONTEXT_MULTIPLIER = 1.15


def main(payload):
    doc = as_dict(payload, "$")
    tasks = as_list(doc.get("tasks"), "$.tasks", min_len=1, max_len=500)
    cfg = as_dict(doc.get("config", {}), "$.config")
    buffer = as_number(cfg.get("buffer", 1.3), "$.config.buffer", min_v=1.0, max_v=3.0)
    cost_per_hour = as_number(cfg.get("cost_per_hour", 0.0), "$.config.cost_per_hour",
                              min_v=0.0, max_v=100_000.0)
    currency = cfg.get("currency", "USD")
    if not isinstance(currency, str) or len(currency) > 8:
        raise ToolError("E_CONFIG", "currency must be a short string code")

    estimates: dict[str, dict] = {}
    warnings: list[str] = []
    seen: set[str] = set()

    for i, raw in enumerate(tasks):
        t = as_dict(raw, f"$.tasks[{i}]")
        tid = as_str(t.get("id"), f"$.tasks[{i}].id", min_len=1)
        if tid in seen:
            raise ToolError("E_INPUT_DUPLICATE", f"duplicate task id {tid!r}",
                            details={"id": tid})
        seen.add(tid)
        kind = as_str(t.get("kind"), f"$.tasks[{i}].kind", min_len=1)
        if kind not in REFERENCE_CLASSES:
            warnings.append(f"{tid}: unknown kind {kind!r}; fell back to 'synthesis' reference class")
            ref = REFERENCE_CLASSES["synthesis"]
            kind_used = "synthesis"
        else:
            ref = REFERENCE_CLASSES[kind]
            kind_used = kind

        multipliers: dict[str, float] = {}
        risk = t.get("risk_level", "medium")
        if risk not in RISK_MULTIPLIER:
            raise ToolError("E_INPUT_RANGE", f"{tid}: risk_level must be one of "
                            f"{sorted(RISK_MULTIPLIER)}", details={"id": tid, "got": risk})
        multipliers["risk_level"] = RISK_MULTIPLIER[risk]

        sens = t.get("data_sensitivity", "internal")
        if sens not in SENSITIVITY_MULTIPLIER:
            raise ToolError("E_INPUT_RANGE", f"{tid}: data_sensitivity must be one of "
                            f"{sorted(SENSITIVITY_MULTIPLIER)}", details={"id": tid, "got": sens})
        multipliers["data_sensitivity"] = SENSITIVITY_MULTIPLIER[sens]

        ctx = t.get("est_context_tokens")
        if ctx is not None:
            c = as_number(ctx, f"$.tasks[{i}].est_context_tokens", min_v=0, max_v=10_000_000)
            if c > CONTEXT_MULTIPLIER_THRESHOLD:
                multipliers["large_context"] = CONTEXT_MULTIPLIER

        mult_total = 1.0
        for m in multipliers.values():
            mult_total *= m
        hours = ref["base_hours"] * mult_total * buffer
        estimates[tid] = {
            "kind": kind_used,
            "base_hours": ref["base_hours"],
            "multipliers": multipliers,
            "buffer": buffer,
            "est_effort_hours": round(hours, 2),
            "est_cost": round(hours * cost_per_hour, 2),
            "currency": currency,
            "reference_note": ref["note"],
            "basis": "CALCULATED",
        }

    total_hours = round(sum(e["est_effort_hours"] for e in estimates.values()), 2)
    total_cost = round(sum(e["est_cost"] for e in estimates.values()), 2)
    return {
        "estimates": estimates,
        "totals": {"hours": total_hours, "cost": total_cost, "currency": currency},
        "warnings": warnings,
        "method": ("reference-class forecasting: base_hours x risk x sensitivity x context x buffer; "
                   "reference classes are project-custom defaults (see sources.md S5 for method)"),
    }


if __name__ == "__main__":
    run_tool("budget_estimator", main)
