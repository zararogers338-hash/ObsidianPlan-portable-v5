"""Failure-path tests: malformed, conflicting, and adversarial input.

Every failure must come back as a machine-parseable envelope with the expected
exit code (2 = input/validation, 3 = graph/contract) and a non-empty error.
"""

from __future__ import annotations

import json

from conftest import CYCLE_NODES, VALID_MICP_NODES, run_tool


def test_empty_stdin_is_a_clean_error() -> None:
    import subprocess
    import sys
    import os

    script = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "tools", "dag_check.py")
    proc = subprocess.run([sys.executable, script], input="", capture_output=True, text=True)
    assert proc.returncode == 2
    env = json.loads(proc.stdout)
    assert env["ok"] is False
    assert env["error"]["code"] == "E_INPUT_EMPTY"


def test_malformed_json_is_a_clean_error() -> None:
    import subprocess
    import sys
    import os

    script = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "tools", "dag_check.py")
    proc = subprocess.run([sys.executable, script], input="{not json", capture_output=True, text=True)
    assert proc.returncode == 2
    env = json.loads(proc.stdout)
    assert env["error"]["code"] == "E_INPUT_INVALID_JSON"


def test_dag_check_detects_cycle() -> None:
    env = run_tool("dag_check", {"nodes": CYCLE_NODES})
    assert env["ok"] is True
    assert env["result"]["is_dag"] is False
    assert len(env["result"]["cycles"]) >= 1


def test_dag_check_reports_unknown_dependency() -> None:
    nodes = [
        {"id": "x", "depends_on": ["ghost"]},
    ]
    env = run_tool("dag_check", {"nodes": nodes})
    assert env["result"]["is_dag"] is False
    assert env["result"]["unknown_dependencies"] == ["ghost"]


def test_dag_check_reports_self_loop() -> None:
    nodes = [{"id": "s", "depends_on": ["s"]}]
    env = run_tool("dag_check", {"nodes": nodes})
    assert env["result"]["self_loops"] == ["s"]
    assert env["result"]["is_dag"] is False


def test_critical_path_rejects_cycle_with_exit_3() -> None:
    env = run_tool("critical_path", {"nodes": CYCLE_NODES}, expect_exit=3)
    assert env["ok"] is False
    assert env["error"]["code"] == "E_GRAPH_CYCLIC"
    assert env["error"]["details"]["cycles"]


def test_granularity_rejects_bad_weights() -> None:
    payload = {"nodes": VALID_MICP_NODES,
               "config": {"weights": {"definition_of_done": 1.0, "single_owner": 1.0}}}
    env = run_tool("granularity_scorer", payload, expect_exit=2)
    assert env["ok"] is False
    assert env["error"]["code"] == "E_CONFIG"


def test_granularity_flags_non_finite_effort() -> None:
    bad = json.loads(json.dumps(VALID_MICP_NODES))
    bad[0]["est_effort_hours"] = float("nan")
    env = run_tool("granularity_scorer", {"nodes": bad}, expect_exit=2)
    assert env["ok"] is False
    assert env["error"]["code"] == "E_NUMERIC_NON_FINITE"


def test_budget_rejects_unknown_risk_level() -> None:
    tasks = [{"id": "t1", "kind": "simulation", "risk_level": "extreme"}]
    env = run_tool("budget_estimator", {"tasks": tasks}, expect_exit=2)
    assert env["ok"] is False
    assert env["error"]["code"] == "E_INPUT_RANGE"


def test_replan_unknown_trigger_fails() -> None:
    plan = {"nodes": VALID_MICP_NODES}
    trigger = {"reason": "critical experiment failed", "failed_node_ids": ["no_such_node"]}
    env = run_tool("replan_diff", {"plan": plan, "trigger": trigger}, expect_exit=3)
    assert env["ok"] is False
    assert env["error"]["code"] == "E_GRAPH_UNKNOWN_NODE"


def test_replan_cyclic_plan_fails() -> None:
    plan = {"nodes": CYCLE_NODES}
    trigger = {"reason": "replan", "failed_node_ids": ["a"]}
    env = run_tool("replan_diff", {"plan": plan, "trigger": trigger}, expect_exit=3)
    assert env["error"]["code"] == "E_GRAPH_CYCLIC"


def test_self_audit_catches_implicit_dependency() -> None:
    import json as _json
    nodes = _json.loads(_json.dumps(VALID_MICP_NODES))
    # node 2 declares an input from a node that is NOT its ancestor
    nodes[1]["inputs"] = ["lit_review:evidence_shortlist", "context", "other:artifact"]
    out = {"dag": {"nodes": nodes},
           "execution_limits": {"max_call_depth": 8, "max_iterations": 50},
           "findings": []}
    env = run_tool("self_audit", {"output": out})
    assert env["result"]["pass"] is False
    assert env["result"]["gates"]["G1_no_implicit_dependencies"]["pass"] is False


def test_self_audit_catches_missing_human_gate_on_high_risk() -> None:
    import json as _json
    nodes = _json.loads(_json.dumps(VALID_MICP_NODES))
    nodes[1]["risk_level"] = "high"
    nodes[1]["human_approval_gate"] = False
    out = {"dag": {"nodes": nodes},
           "execution_limits": {"max_call_depth": 8, "max_iterations": 50},
           "findings": []}
    env = run_tool("self_audit", {"output": out})
    assert env["result"]["gates"]["G5_limits_and_human_gates"]["pass"] is False


def test_self_audit_rejects_bad_epistemic_tag() -> None:
    out = {
        "dag": {"nodes": VALID_MICP_NODES},
        "execution_limits": {"max_call_depth": 8, "max_iterations": 50},
        "findings": [{"statement": "X", "epistemic_tag": "MADE_UP"}],
    }
    env = run_tool("self_audit", {"output": out})
    assert env["result"]["gates"]["G6_epistemic_tags"]["pass"] is False


def test_validate_rejects_path_escape() -> None:
    env = run_tool("validate", {"schema": "../../etc/passwd", "document": {}}, expect_exit=2)
    assert env["ok"] is False
    assert env["error"]["code"] == "E_PATH_ESCAPE"
