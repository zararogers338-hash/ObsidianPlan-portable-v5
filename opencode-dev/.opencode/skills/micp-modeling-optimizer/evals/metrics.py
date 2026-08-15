"""Metric computation for the micp-modeling-optimizer eval suite (M1-M7)."""

from __future__ import annotations

# Thresholds (from SKILL.md §八)
THRESHOLDS = {
    "M1": 0.95,   # structured-output pass rate
    "M2": 1.0,    # tool real-call rate (invariant by construction)
    "M3": 0.9,    # citation/data traceability rate
    "M4": 1.0,    # missing-input recognition rate
    "M5": 1.0,    # adversarial interception rate
    "M6": 1.0,    # repeated-run consistency (deterministic tools)
    "M7": 2000.0,  # mean failure-recovery time (ms)
}


def measure(suite_report: dict) -> dict:
    m1 = suite_report.get("output_schema_passes", 0) / max(suite_report.get("outputs", 1), 1)
    m2 = suite_report.get("tool_real_calls", 0) / max(suite_report.get("outputs", 1), 1)
    m3 = suite_report.get("traceable_outputs", 0) / max(suite_report.get("successful_outputs", 1), 1)
    m4 = suite_report.get("missing_input_blocked", 0) / max(suite_report.get("missing_input_total", 1), 1)
    m5 = suite_report.get("adversarial_blocked", 0) / max(suite_report.get("adversarial_total", 1), 1)
    m6 = 1.0 if suite_report.get("repeat_consistent", False) else 0.0
    m7 = suite_report.get("recovery_mean_ms", float("nan"))
    return compute({"M1": m1, "M2": m2, "M3": m3, "M4": m4, "M5": m5, "M6": m6, "M7": m7})


def compute(results: dict) -> dict:
    methods = {
        "M1": "every CLI output validated against schemas/output.schema.json; pass_rate = passes / total",
        "M2": "the eval runner only ever invokes tools/modeling.py; invariant by construction",
        "M3": "evidence_refs/data_refs supplied in input appear in output evidence_used",
        "M4": "for each missing required scenario field, BLOCKED with MMO-E101/E102 and the field named",
        "M5": "adversarial cases (same-data fit, unknown action, bad version, unknown model) all blocked",
        "M6": "identical input run twice -> identical output (deterministic; timestamps stripped)",
        "M7": "mean wall-clock ms for a malformed-payload recovery",
    }
    out = {}
    all_pass = True
    for mid, measured in results.items():
        threshold = THRESHOLDS[mid]
        if mid == "M7":
            passed = measured <= threshold
        else:
            passed = measured >= threshold - 1e-9
        if not passed:
            all_pass = False
        out[mid] = {
            "measured": round(measured, 4),
            "threshold": threshold,
            "pass": passed,
            "method": methods[mid],
        }
    out["all_pass"] = all_pass
    return out
