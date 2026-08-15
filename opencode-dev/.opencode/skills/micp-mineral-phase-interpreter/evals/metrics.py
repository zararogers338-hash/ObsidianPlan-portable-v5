"""Metrics harness (spec §十一: minimum performance indicators).

Each metric is measured with a concrete method and a minimum threshold, then
reported as JSON. `evals/run.py` executes the eval suite and calls `measure`.

Metrics:
  M1 structured-output pass rate       — output.schema.json validation passes
  M2 tool real-call rate               — actions whose computation actually ran
  M3 evidence/data traceability        — refs resolved or inline samples present
  M4 missing-input recognition rate    — BLOCKED naming each removed field
  M5 adversarial interception rate     — adversarial cases blocked/typed-failed
  M6 repeated-run consistency          — identical input => identical envelope
  M7 mean recovery time                — FAILED->successful rerun wall-clock (ms)
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
                "method": "for each case, the action handler must populate results/ "
                          "(a real computation), not just echo; rate = cases_with_results / cases",
                "pass": results.get("M2", 0.0) >= 1.0,
            },
            "M3_traceability_rate": {
                "measured": results.get("M3", 0.0),
                "threshold": 0.9,
                "method": "envelopes whose evidence_used or inline samples ground every "
                          "conclusion / total envelopes",
                "pass": results.get("M3", 0.0) >= 0.9,
            },
            "M4_missing_input_recognition_rate": {
                "measured": results.get("M4", 0.0),
                "threshold": 1.0,
                "method": "for each of K required fields, submit payload missing exactly it "
                          "and require BLOCKED with the field named in the violation",
                "pass": results.get("M4", 0.0) >= 1.0,
            },
            "M5_adversarial_interception_rate": {
                "measured": results.get("M5", 0.0),
                "threshold": 1.0,
                "method": "adversarial cases (non-object stdin, contract v2, NaN, path "
                          "traversal, unknown action, out-of-range TGA) that were blocked "
                          "or failed with a typed OMM error / total",
                "pass": results.get("M5", 0.0) >= 1.0,
            },
            "M6_repeated_run_consistency": {
                "measured": results.get("M6", 0.0),
                "threshold": 1.0,
                "method": "run the same payload twice; envelopes must be identical "
                          "after stripping timestamps",
                "pass": results.get("M6", 0.0) >= 1.0,
            },
            "M7_mean_recovery_time_ms": {
                "measured": results.get("M7", 0.0),
                "threshold": 5000.0,
                "method": "submit a known-bad payload (expect FAILED/BLOCKED), fix the "
                          "payload, rerun; mean wall-clock over 3 rounds",
                "pass": results.get("M7", 0.0) <= 5000.0,
            },
        }
    }


def measure(suite_report: dict) -> dict:
    m1 = suite_report.get("output_schema_passes", 0) / max(suite_report.get("outputs", 1), 1)
    actionable = max(suite_report.get("actionable_total", 1), 1)
    m2 = suite_report.get("tool_real_calls", 0) / actionable
    m3 = suite_report.get("traceable_outputs", 0) / max(suite_report.get("outputs", 1), 1)
    m4 = suite_report.get("missing_input_blocked", 0) / max(suite_report.get("missing_input_total", 1), 1)
    m5 = suite_report.get("adversarial_intercepted", 0) / max(suite_report.get("adversarial_total", 1), 1)
    m6 = 1.0 if suite_report.get("repeat_consistent", False) else 0.0
    m7 = suite_report.get("recovery_mean_ms", float("nan"))
    return compute({
        "M1": m1, "M2": m2, "M3": m3, "M4": m4, "M5": m5, "M6": m6, "M7": m7,
    })
