"""Regression tests: contract stability across runs.

The skill guarantees repeat-run consistency (deterministic output on identical
input) and contract-level stability. These tests would catch an accidental
breaking change to the tool envelope or the documented error taxonomy.
"""

from __future__ import annotations

import json

from conftest import VALID_MICP_NODES, run_tool


def test_dag_check_is_deterministic() -> None:
    payload = {"nodes": VALID_MICP_NODES}
    first = json.dumps(run_tool("dag_check", payload), sort_keys=True)
    second = json.dumps(run_tool("dag_check", payload), sort_keys=True)
    assert first == second


def test_critical_path_is_deterministic() -> None:
    payload = {"nodes": VALID_MICP_NODES}
    first = json.dumps(run_tool("critical_path", payload), sort_keys=True)
    second = json.dumps(run_tool("critical_path", payload), sort_keys=True)
    assert first == second


def test_budget_is_deterministic() -> None:
    payload = {"tasks": [{"id": "a", "kind": "simulation", "risk_level": "medium",
                          "data_sensitivity": "internal"}]}
    first = json.dumps(run_tool("budget_estimator", payload), sort_keys=True)
    second = json.dumps(run_tool("budget_estimator", payload), sort_keys=True)
    assert first == second


def test_envelope_has_tool_and_version_fields() -> None:
    env = run_tool("dag_check", {"nodes": VALID_MICP_NODES})
    assert env["tool"] == "dag_check"
    assert env["version"] == "1.0.0"
    assert "result" in env


def test_error_envelope_has_code_message_retryable_details() -> None:
    env = run_tool("critical_path", {"nodes": [{"id": "x", "depends_on": ["ghost"]}]},
                   expect_exit=3)
    assert env["ok"] is False
    error = env["error"]
    for key in ("code", "message", "retryable", "details"):
        assert key in error, f"error envelope missing {key}"
