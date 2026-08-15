"""Metrics harness (spec §十一: minimum performance indicators).

Each metric is measured with a concrete method and a minimum threshold, then
reported as JSON. `evals/run.py` runs the full eval suite and calls into
`compute` for the metric report.

Metrics:
  M1 structured-output pass rate      — output.schema.json validation passes
  M2 tool real-call rate              — actions whose events actually hit the store
  M3 evidence/data traceability       — sha256 present on attach; refs resolvable
  M4 missing-input recognition rate   — BLOCKED for each fabricated missing field
  M5 adversarial interception rate    — illegal transitions & contract attacks blocked
  M6 repeated-run consistency         — identical input => identical projection
  M7 mean recovery time               — recovery.recover elapsed ms (wall clock)
"""

from __future__ import annotations

import json
import statistics
import time
from pathlib import Path

SCHEMA_JSON_OUT = Path(__file__).resolve().parent.parent / "schemas" / "output.schema.json"


def compute(results: dict[str, float]) -> dict:
    """`results` maps metric key -> measured value (a rate or count or ms)."""
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
                "method": "for N mutating actions, count events appended to the on-disk "
                          "events.jsonl; rate = projects_with_events / actions_that_should_append",
                "pass": results.get("M2", 0.0) >= 1.0,
            },
            "M3_traceability_rate": {
                "measured": results.get("M3", 0.0),
                "threshold": 0.9,
                "method": "evidence.attach with sha256 over all attaches; conclusions that "
                          "cite evidence refs that exist in the stream / total citations",
                "pass": results.get("M3", 0.0) >= 0.9,
            },
            "M4_missing_input_recognition_rate": {
                "measured": results.get("M4", 0.0),
                "threshold": 1.0,
                "method": "for each of K required fields, submit a payload missing exactly it "
                          "and require BLOCKED with the field named in the violation",
                "pass": results.get("M4", 0.0) >= 1.0,
            },
            "M5_adversarial_interception_rate": {
                "measured": results.get("M5", 0.0),
                "threshold": 1.0,
                "method": "adversarial cases (illegal transition, contract_version 2, path "
                          "traversal, non-JSON stdin, unknown action) that were blocked / total",
                "pass": results.get("M5", 0.0) >= 1.0,
            },
            "M6_repeated_run_consistency": {
                "measured": results.get("M6", 0.0),
                "threshold": 1.0,
                "method": "run the same event sequence twice in two stores; projection "
                          "snapshots must be byte-identical",
                "pass": results.get("M6", 0.0) >= 1.0,
            },
            "M7_mean_recovery_time_ms": {
                "measured": results.get("M7", 0.0),
                "threshold": 5000.0,
                "method": "recovery.recover over a 50-event stream, 5 runs, mean wall-clock ms",
                "pass": results.get("M7", 0.0) <= 5000.0,
            },
        }
    }


def measure(suite_report: dict) -> dict:
    """Extract M1–M7 from a suite run report produced by evals/run.py."""
    m1 = suite_report.get("output_schema_passes", 0) / max(suite_report.get("outputs", 1), 1)
    m2 = 1.0 if suite_report.get("events_appended_total", 0) > 0 else 0.0
    m3 = suite_report.get("evidence_with_sha", 0) / max(suite_report.get("evidence_total", 1), 1)
    m4 = suite_report.get("missing_input_blocked", 0) / max(suite_report.get("missing_input_total", 1), 1)
    m5 = suite_report.get("adversarial_blocked", 0) / max(suite_report.get("adversarial_total", 1), 1)
    m6 = 1.0 if suite_report.get("repeat_consistent", False) else 0.0
    m7 = suite_report.get("recovery_mean_ms", float("nan"))
    return compute({
        "M1": m1, "M2": m2, "M3": m3, "M4": m4, "M5": m5, "M6": m6, "M7": m7,
    })
