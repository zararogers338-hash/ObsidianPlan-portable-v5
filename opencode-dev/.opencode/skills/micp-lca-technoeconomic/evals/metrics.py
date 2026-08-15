"""Metrics harness (spec §八: minimum performance indicators).

Each metric is measured with a concrete method and a minimum threshold, then
reported as JSON. `evals/run_evals.py` runs the full eval suite and calls into
`measure` for the metric report.

Metrics:
  M1 structured-output pass rate     — output.schema.json validation passes
  M2 tool real-call rate             — successful actions that produced computed artifacts
  M3 reference/data traceability     — provenance.factors covers used factors
  M4 missing-input recognition rate  — BLOCKED for each fabricated missing field
  M5 adversarial interception rate   — adversarial cases blocked or flagged
  M6 repeated-run consistency        — identical input => identical output envelope (fixed clock)
  M7 mean failure-recovery time      — ms to produce a valid envelope on malformed input
"""

from __future__ import annotations

from pathlib import Path

SCHEMA_JSON_OUT = Path(__file__).resolve().parent.parent / "schemas" / "output.schema.json"


def compute(results: dict[str, float]) -> dict:
    return {
        "report": {
            "M1_structured_output_pass_rate": {
                "measured": results.get("M1", 0.0),
                "threshold": 0.95,
                "method": "validate every CLI output against schemas/output.schema.json; "
                          "pass_rate = passes / total outputs",
                "pass": results.get("M1", 0.0) >= 0.95,
            },
            "M2_tool_real_call_rate": {
                "measured": results.get("M2", 0.0),
                "threshold": 1.0,
                "method": "for N compute actions, require real artifacts in the output "
                          "(environmental_results / cost_results / uncertainty); "
                          "rate = actions_with_artifacts / success_actions",
                "pass": results.get("M2", 0.0) >= 1.0,
            },
            "M3_traceability_rate": {
                "measured": results.get("M3", 0.0),
                "threshold": 0.9,
                "method": "successful outputs whose provenance.factors lists factor "
                          "ids that were actually used, over all successful outputs",
                "pass": results.get("M3", 0.0) >= 0.9,
            },
            "M4_missing_input_recognition_rate": {
                "measured": results.get("M4", 0.0),
                "threshold": 1.0,
                "method": "for each of K fabricated missing fields (functional_unit, "
                          "baseline, scope), require BLOCKED naming the field",
                "pass": results.get("M4", 0.0) >= 1.0,
            },
            "M5_adversarial_interception_rate": {
                "measured": results.get("M5", 0.0),
                "threshold": 1.0,
                "method": "adversarial cases (lab-price-as-field, asymmetric boundary, "
                          "expired factor, dimension conflict) that were blocked or flagged",
                "pass": results.get("M5", 0.0) >= 1.0,
            },
            "M6_repeated_run_consistency": {
                "measured": results.get("M6", 0.0),
                "threshold": 1.0,
                "method": "run the same comparison payload twice with fixed seed+clock; "
                          "output envelopes must be byte-identical",
                "pass": results.get("M6", 0.0) >= 1.0,
            },
            "M7_mean_failure_recovery_ms": {
                "measured": results.get("M7", 0.0),
                "threshold": 2000.0,
                "method": "feed a structurally broken payload 5 times; mean wall-clock "
                          "to a valid output envelope",
                "pass": results.get("M7", 0.0) <= 2000.0,
            },
        }
    }


def measure(suite_report: dict) -> dict:
    m1 = suite_report.get("output_schema_passes", 0) / max(suite_report.get("outputs", 1), 1)
    m2 = suite_report.get("tool_real_calls", 0) / max(suite_report.get("successful_outputs", 1), 1)
    m3 = suite_report.get("traceable_outputs", 0) / max(suite_report.get("successful_outputs", 1), 1)
    m4 = suite_report.get("missing_input_blocked", 0) / max(suite_report.get("missing_input_total", 1), 1)
    m5 = suite_report.get("adversarial_blocked", 0) / max(suite_report.get("adversarial_total", 1), 1)
    m6 = 1.0 if suite_report.get("repeat_consistent", False) else 0.0
    m7 = suite_report.get("recovery_mean_ms", float("nan"))
    return compute({
        "M1": m1, "M2": m2, "M3": m3, "M4": m4, "M5": m5, "M6": m6, "M7": m7,
    })
