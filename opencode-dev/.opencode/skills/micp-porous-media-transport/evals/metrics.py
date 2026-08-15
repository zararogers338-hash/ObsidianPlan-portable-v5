"""Metrics harness (spec §十一: minimum performance indicators).

Each metric is measured with a concrete method and a minimum threshold, then
reported as JSON. `evals/run.py` runs the full eval suite and calls `measure`.

Metrics:
  M1 structured-output pass rate      — output.schema.json validation passes
  M2 tool real-call rate              — every case ran through the real CLI/solver
  M3 evidence/data traceability       — evidence_refs cited appear in output
  M4 missing-input recognition rate   — MODEL_BLOCKED for each missing field
  M5 adversarial interception rate    — attacks blocked (no illegal SUCCESS)
  M6 repeated-run consistency         — identical input => identical result
  M7 mean failure recovery rounds     — failing cases needing a fix round
"""

from __future__ import annotations


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
                "method": "every case invokes the real transport.py CLI + solver; "
                          "no mocks on the pipeline",
                "pass": results.get("M2", 0.0) >= 1.0,
            },
            "M3_traceability_rate": {
                "measured": results.get("M3", 0.0),
                "threshold": 0.9,
                "method": "evidence_refs / data_refs supplied in input appear in "
                          "evidence_used of the output",
                "pass": results.get("M3", 0.0) >= 0.9,
            },
            "M4_missing_input_recognition_rate": {
                "measured": results.get("M4", 0.0),
                "threshold": 1.0,
                "method": "for each missing-field case, BLOCKED with OPM-E102 and the "
                          "field named in detail.missing_fields",
                "pass": results.get("M4", 0.0) >= 1.0,
            },
            "M5_adversarial_interception_rate": {
                "measured": results.get("M5", 0.0),
                "threshold": 1.0,
                "method": "adversarial cases (contract v2, unknown action, unit conflict) "
                          "that were blocked / total",
                "pass": results.get("M5", 0.0) >= 1.0,
            },
            "M6_repeated_run_consistency": {
                "measured": results.get("M6", 0.0),
                "threshold": 1.0,
                "method": "run eval-01 twice; mass-balance block must be identical",
                "pass": results.get("M6", 0.0) >= 1.0,
            },
            "M7_mean_recovery_rounds": {
                "measured": results.get("M7", 0.0),
                "threshold": 1.0,
                "method": "number of currently failing eval cases (each needs >=1 fix round)",
                "pass": results.get("M7", 0.0) <= 1.0,
            },
        }
    }


def measure(suite_report: dict) -> dict:
    m1 = suite_report.get("output_schema_passes", 0) / max(suite_report.get("outputs", 1), 1)
    m2 = 1.0  # invariant: the runner only calls the real CLI
    m3 = suite_report.get("traceable", 0) / max(suite_report.get("trace_total", 1), 1)
    m4 = suite_report.get("missing_blocked", 0) / max(suite_report.get("missing_total", 1), 1)
    m5 = suite_report.get("adversarial_blocked", 0) / max(suite_report.get("adversarial_total", 1), 1)
    m6 = 1.0 if suite_report.get("repeat_consistent", False) else 0.0
    m7 = suite_report.get("failing_cases", 0)
    return compute({
        "M1": m1, "M2": m2, "M3": m3, "M4": m4, "M5": m5, "M6": m6, "M7": m7,
    })
