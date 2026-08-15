"""Metrics harness (spec §十一: minimum performance indicators).

Each metric is measured with a concrete method and a minimum threshold, then
reported as JSON. evals/run.py executes cases.yaml through the real CLI and
calls `measure` for the final metric report.

M1 structured-output pass rate   — every CLI output validates against output.schema.json
M2 tool real-call rate          — search.* actions that actually returned records /
                                  wrote a trace (offline fixture counts as a real tool call)
M3 citation/data traceability   — records whose DOI is verified or structurally valid /
                                  total records returned
M4 missing-input recognition    — BLOCKED + E102 naming the field for each dropped required field
M5 adversarial interception     — forged DOIs, unknown actions, contract conflicts all blocked
M6 repeated-run consistency     — same query twice → same repro_id & identical records
M7 mean failure-recovery time   — BLOCKED/FAILED envelope produced in < threshold ms
"""

from __future__ import annotations

import time


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
                "method": "search.* actions: rate = actions_that_returned_records / total; "
                          "offline fixture counts as a real tool call, dry_run does not",
                "pass": results.get("M2", 0.0) >= 1.0,
            },
            "M3_citation_traceability_rate": {
                "measured": results.get("M3", 0.0),
                "threshold": 0.9,
                "method": "records with doi_status verified|offline-unverified|structurally valid "
                          "/ total records returned",
                "pass": results.get("M3", 0.0) >= 0.9,
            },
            "M4_missing_input_recognition_rate": {
                "measured": results.get("M4", 0.0),
                "threshold": 1.0,
                "method": "for each of K required fields dropped, require BLOCKED + E102 "
                          "naming the field; rate = named_blocked / K",
                "pass": results.get("M4", 0.0) >= 1.0,
            },
            "M5_adversarial_interception_rate": {
                "measured": results.get("M5", 0.0),
                "threshold": 1.0,
                "method": "adversarial cases (forged DOI, unknown action, contract conflict) "
                          "that were BLOCKED/FAILED/PARTIAL-with-error / total",
                "pass": results.get("M5", 0.0) >= 1.0,
            },
            "M6_repeated_run_consistency": {
                "measured": results.get("M6", 0.0),
                "threshold": 1.0,
                "method": "same query twice in two service runs: repro_id equal and records "
                          "byte-identical",
                "pass": results.get("M6", 0.0) >= 1.0,
            },
            "M7_mean_failure_recovery_time_ms": {
                "measured": results.get("M7", 0.0),
                "threshold": 5000.0,
                "method": "wall-clock ms to produce a BLOCKED/FAILED envelope, 5 samples, mean",
                "pass": results.get("M7", 0.0) <= 5000.0,
            },
        }
    }


def measure(suite: dict) -> dict:
    """Extract M1–M7 from a suite report produced by evals/run.py."""
    outputs = max(suite.get("outputs", 1), 1)
    m1 = suite.get("output_schema_passes", 0) / outputs
    m2 = suite.get("tool_real_calls", 0) / max(suite.get("tool_real_attempts", 1), 1)
    m3 = suite.get("traceable_records", 0) / max(suite.get("total_records", 1), 1)
    m4 = suite.get("missing_input_named", 0) / max(suite.get("missing_input_total", 1), 1)
    m5 = suite.get("adversarial_blocked", 0) / max(suite.get("adversarial_total", 1), 1)
    m6 = 1.0 if suite.get("repeat_consistent", False) else 0.0
    m7 = suite.get("recovery_mean_ms", float("nan"))
    return compute({"M1": m1, "M2": m2, "M3": m3, "M4": m4, "M5": m5, "M6": m6, "M7": m7})
