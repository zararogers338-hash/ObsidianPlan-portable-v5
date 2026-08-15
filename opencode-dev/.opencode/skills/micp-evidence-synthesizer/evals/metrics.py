"""Metric computation shared by the eval runner (SKILL.md §十).

Kept importable as `metrics` so the results file records the exact formulas
and thresholds used — audit-able without re-running.
"""

from __future__ import annotations

THRESHOLDS = {
    "structured_output_pass_rate": 0.95,
    "tool_real_call_rate": 1.0,
    "traceability_rate": 0.9,
    "missing_input_identification_rate": 1.0,
    "adversarial_interception_rate": 1.0,
    "repeat_run_consistency": 1.0,
    "mean_failure_recovery_rounds": 1.0,  # ≤1 轮
}

FORMULAS = {
    "structured_output_pass_rate": "passes / n (all eval outputs validate against output.schema.json)",
    "tool_real_call_rate": "real tool invocations / n (no mocks exist in this skill)",
    "traceability_rate": "envelopes whose evidence_used ⊆ card ref_ids / n",
    "missing_input_identification_rate": "BLOCKED cases that name missing fields / BLOCKED cases",
    "adversarial_interception_rate": "adversarial cases without illegal SUCCESS / adversarial cases",
    "repeat_run_consistency": "deterministic outputs (ignoring provenance) / double runs",
    "mean_failure_recovery_rounds": "reported failure rounds (tracked in CHANGELOG)",
}


def check_metrics(metrics: dict) -> tuple[bool, dict]:
    """Return (all_met, {metric: (value, threshold, ok)})."""
    out = {}
    all_met = True
    for name, lo in THRESHOLDS.items():
        val = metrics.get(name, 0.0)
        ok = val >= lo
        if not ok:
            all_met = False
        out[name] = (val, lo, ok)
    return all_met, out
