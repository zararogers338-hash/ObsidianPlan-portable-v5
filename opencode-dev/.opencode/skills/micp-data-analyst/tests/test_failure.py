"""Failure-path tests: malformed, conflicting, and adversarial input.

Every failure must come back as a machine-parseable envelope with a clean exit
code and a non-empty error, never a traceback.
"""

from __future__ import annotations

import json

from conftest import PSEUDO_INPUT, run_tool


def test_empty_stdin_is_clean_error() -> None:
    import subprocess
    import sys
    import os

    script = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                          "tools", "micp", "cli.py")
    proc = subprocess.run([sys.executable, script, "stats"], input="",
                          capture_output=True, text=True, timeout=60)
    assert proc.returncode == 2
    env = json.loads(proc.stdout)
    assert env["ok"] is False
    assert env["error"]["code"] in ("E_INPUT_EMPTY", "MDA-E301")


def test_malformed_json_is_clean_error() -> None:
    import subprocess
    import sys
    import os

    script = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                          "tools", "micp", "cli.py")
    proc = subprocess.run([sys.executable, script, "stats"], input="{not json",
                          capture_output=True, text=True, timeout=60)
    assert proc.returncode == 2
    env = json.loads(proc.stdout)
    assert env["error"]["code"] in ("E_INPUT_INVALID_JSON", "MDA-E301")


def test_non_finite_number_rejected() -> None:
    env = run_tool("stats", {"op": "descriptive", "values": [1, 2, float("nan")]},
                   expect_exit=2)
    assert env["ok"] is False
    assert env["error"]["code"] == "E_NUMERIC_NON_FINITE"


def test_unknown_stats_op() -> None:
    env = run_tool("stats", {"op": "quantum_art"}, expect_exit=2)
    assert env["ok"] is False
    assert env["error"]["code"] == "E_INPUT_RANGE"


def test_service_blocks_on_missing_samples() -> None:
    payload = {
        "task_id": "f1", "project_id": "p", "skill_version": "1.0.0",
        "controller_version": "obsidian-ctl-0.1.0", "timestamp": "2026-08-06T12:00:00Z",
        "request": "Run statistical inference on the MICP strength data.",
        "risk_level": "medium", "human_approval_state": "not_required",
        "requested_output_format": "json",
    }
    env = run_tool("service", payload)
    body = env["result"]
    assert body["status"] == "BLOCKED"
    fields = {m["field"] for m in body["missing_inputs"]}
    assert "samples (or data_refs)" in fields or "samples" in fields


def test_service_blocks_on_short_request() -> None:
    payload = {
        "task_id": "f2", "project_id": "p", "skill_version": "1.0.0",
        "controller_version": "obsidian-ctl-0.1.0", "timestamp": "2026-08-06T12:00:00Z",
        "request": "?", "risk_level": "low",
        "human_approval_state": "not_required", "requested_output_format": "json",
    }
    env = run_tool("service", payload)
    body = env["result"]
    assert body["status"] == "BLOCKED"
    assert any("request" in m["field"] for m in body["missing_inputs"])


def test_service_blocks_when_samples_without_columns() -> None:
    payload = dict(PSEUDO_INPUT)
    payload["data_columns"] = []
    env = run_tool("service", payload)
    body = env["result"]
    assert body["status"] == "BLOCKED"
    assert any("data_columns" in m["field"] for m in body["missing_inputs"])


def test_service_version_gate() -> None:
    payload = dict(PSEUDO_INPUT)
    payload["skill_version"] = "2.0.0"
    env = run_tool("service", payload)
    body = env["result"]
    assert body["status"] == "BLOCKED"
    assert any(e["code"] == "MDA-E801" for e in body["errors"])


def test_service_routes_mixed_effects_downstream() -> None:
    payload = dict(PSEUDO_INPUT)
    payload["constraints"] = {"analysis_modes": ["mixed_effects"]}
    env = run_tool("service", payload)
    body = env["result"]
    assert body["status"] == "NEED_ADDITIONAL_SKILL"
    assert any(r["skill"] == "obsidian-modeling-optimizer"
               for r in body["requested_next_skills"])


def test_service_requires_approval_for_field_deployment() -> None:
    payload = dict(PSEUDO_INPUT)
    payload["request"] = "Field deployment: analyze the in-situ strength data."
    payload["risk_level"] = "high"
    payload["human_approval_state"] = "pending"
    env = run_tool("service", payload)
    body = env["result"]
    assert body["status"] == "HUMAN_APPROVAL_REQUIRED"


def test_validate_accepts_well_formed_envelope() -> None:
    payload = dict(PSEUDO_INPUT)
    env = run_tool("validate", payload)
    assert env["result"]["valid"] is True
