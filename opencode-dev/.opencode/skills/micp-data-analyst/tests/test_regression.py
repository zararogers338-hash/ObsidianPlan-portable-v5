"""Regression tests: contract stability and determinism.

The skill guarantees repeat-run consistency (byte-identical output on identical
input) and stable envelopes. These tests catch accidental breaking changes to
the tool envelope or the documented error taxonomy.
"""

from __future__ import annotations

import json

from conftest import PSEUDO_INPUT, run_tool


def test_service_is_deterministic() -> None:
    first = json.dumps(run_tool("service", PSEUDO_INPUT), sort_keys=True)
    second = json.dumps(run_tool("service", PSEUDO_INPUT), sort_keys=True)
    assert first == second


def test_stats_is_deterministic() -> None:
    payload = {"op": "descriptive", "values": [1, 2, 3, 4, 5], "seed": 7,
               "bootstrap": True}
    first = json.dumps(run_tool("stats", payload), sort_keys=True)
    second = json.dumps(run_tool("stats", payload), sort_keys=True)
    assert first == second


def test_envelope_has_tool_and_version() -> None:
    env = run_tool("stats", {"op": "descriptive", "values": [1, 2, 3]})
    assert env["tool"] == "stats"
    assert env["version"] == "1.0.0"
    assert "result" in env


def test_error_envelope_has_code_message_retryable_details() -> None:
    env = run_tool("stats", {"op": "descriptive", "values": [1, "x"]}, expect_exit=2)
    error = env["error"]
    for key in ("code", "message", "retryable", "details"):
        assert key in error, f"error envelope missing {key}"


def test_pseudo_replication_detected_with_unit_aggregation() -> None:
    env = run_tool("service", PSEUDO_INPUT)
    body = env["result"]
    assert body["status"] == "SUCCESS"
    pr = body["pseudo_replication"]
    assert pr["detected"] is True
    assert pr["findings"][0]["effective_n"] == 4
    gc = body["statistics"]["group_comparison"]
    assert gc["unit_aggregated"] is True
    assert gc["sampling_unit"] == "specimen"
    # effect size on aggregated independent units (n=2 per group)
    assert gc["effect_size"]["n1"] == 2
    assert gc["effect_size"]["n2"] == 2


def test_statistics_are_finite() -> None:
    env = run_tool("service", PSEUDO_INPUT)
    body = env["result"]
    ci = body["statistics"]["variables"]["ucs"]["ci"]
    assert ci["ci_lower"] < ci["ci_upper"]
    assert abs(ci["ci_lower"]) < 1e6  # sanity: no astronomically wrong CI


def test_every_finding_has_epistemic_tag() -> None:
    env = run_tool("service", PSEUDO_INPUT)
    body = env["result"]
    valid = {"OBSERVED", "REPORTED", "CALCULATED", "INFERRED",
             "HYPOTHESIS", "RECOMMENDATION"}
    for f in body["findings"]:
        assert f["epistemic_tag"] in valid, f
        if f["epistemic_tag"] in ("OBSERVED", "REPORTED"):
            assert f.get("source"), f"OBSERVED/REPORTED finding needs a source: {f}"
