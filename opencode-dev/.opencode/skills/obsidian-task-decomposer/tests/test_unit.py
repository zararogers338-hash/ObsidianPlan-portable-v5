"""Unit tests for individual tools.

These test tool behavior directly (scoring math, CPM math, budget math,
replan semantics) — not just that the pipeline composes.
"""

from __future__ import annotations

from conftest import VALID_MICP_NODES, run_tool


def test_granularity_marks_too_fine_node() -> None:
    nodes = [{
        "id": "micro",
        "definition_of_done": {"artifact": "x.json",
                                "acceptance_criteria": [{"metric": "n", "comparator": ">=", "threshold": 1}]},
        "primary_skill": "micp-data-analyst",
        "failure_modes": ["f"],
        "retry_policy": {"max_attempts": 1, "on_exhaustion": "fail_task"},
        "est_effort_hours": 0.05,
        "est_context_tokens": 1000,
    }]
    env = run_tool("granularity_scorer", {"nodes": nodes})
    assert env["result"]["nodes"][0]["verdict"] == "TOO_FINE"


def test_granularity_marks_under_specified() -> None:
    nodes = [{
        "id": "vague",
        "est_effort_hours": 4.0,
    }]
    env = run_tool("granularity_scorer", {"nodes": nodes})
    assert env["result"]["nodes"][0]["verdict"] == "UNDER_SPECIFIED"
    assert env["result"]["nodes"][0]["score"] < 70.0


def test_granularity_ok_for_good_node() -> None:
    env = run_tool("granularity_scorer", {"nodes": VALID_MICP_NODES})
    assert env["result"]["summary"]["ok_ratio"] == 1.0


def test_budget_scales_with_risk_and_sensitivity() -> None:
    low = run_tool("budget_estimator", {"tasks": [
        {"id": "a", "kind": "simulation", "risk_level": "low", "data_sensitivity": "public"}]})
    high = run_tool("budget_estimator", {"tasks": [
        {"id": "b", "kind": "simulation", "risk_level": "high", "data_sensitivity": "restricted"}]})
    hours_low = low["result"]["estimates"]["a"]["est_effort_hours"]
    hours_high = high["result"]["estimates"]["b"]["est_effort_hours"]
    assert hours_high > hours_low


def test_budget_unknown_kind_falls_back_with_warning() -> None:
    env = run_tool("budget_estimator", {"tasks": [
        {"id": "c", "kind": "quantum_art", "risk_level": "low", "data_sensitivity": "public"}]})
    assert env["result"]["warnings"], "expected a warning for unknown kind"
    assert env["result"]["estimates"]["c"]["kind"] == "synthesis"


def test_critical_path_slack_and_parallelism() -> None:
    nodes = [
        {"id": "root", "depends_on": [], "est_effort_hours": 1.0},
        {"id": "a", "depends_on": ["root"], "est_effort_hours": 2.0},
        {"id": "b", "depends_on": ["root"], "est_effort_hours": 2.0},
        {"id": "join", "depends_on": ["a", "b"], "est_effort_hours": 1.0},
    ]
    env = run_tool("critical_path", {"nodes": nodes})
    r = env["result"]
    assert r["critical_path_hours"] == 4.0          # 1 + 2 + 1
    assert set(r["critical_path"]) == {"root", "join"} or len(r["critical_path"]) >= 2
    assert r["parallelism"]["max_width"] == 2
    assert r["node_metrics"]["a"]["slack_hours"] == 0.0
    assert r["node_metrics"]["b"]["slack_hours"] == 0.0


def test_critical_path_uses_estimates_not_defaults_when_present() -> None:
    nodes = [{"id": "x", "depends_on": [], "est_effort_hours": 7.5}]
    env = run_tool("critical_path", {"nodes": nodes, "config": {"default_duration_hours": 4.0}})
    assert env["result"]["node_metrics"]["x"]["duration_hours"] == 7.5
    assert env["result"]["assumed_durations"] == []


def test_replan_preserves_unrelated_and_completed_nodes() -> None:
    plan_nodes = [
        {"id": "lit", "depends_on": [], "status": "completed"},
        {"id": "exp", "depends_on": ["lit"], "status": "failed"},
        {"id": "analysis", "depends_on": ["exp"], "status": "pending"},
        {"id": "writeup", "depends_on": ["analysis"], "status": "pending"},
        {"id": "unrelated_audit", "depends_on": [], "status": "pending"},
    ]
    plan = {"nodes": plan_nodes}
    trigger = {"reason": "experiment failed", "failed_node_ids": ["exp"]}
    env = run_tool("replan_diff", {"plan": plan, "trigger": trigger})
    r = env["result"]
    assert r["rework"] == ["exp"]
    assert r["invalidated"] == ["analysis", "writeup"]
    assert r["preserved"] == ["lit", "unrelated_audit"]
    assert r["stale_completed"] == []


def test_replan_flags_stale_completed_after_trigger() -> None:
    plan_nodes = [
        {"id": "lit", "depends_on": [], "status": "completed"},
        {"id": "exp", "depends_on": ["lit"], "status": "completed"},
        {"id": "analysis", "depends_on": ["exp"], "status": "pending"},
    ]
    plan = {"nodes": plan_nodes}
    trigger = {"reason": "evidence changed", "changed_node_ids": ["lit"]}
    env = run_tool("replan_diff", {"plan": plan, "trigger": trigger})
    r = env["result"]
    # completed nodes downstream of the changed node are preserved but flagged stale
    assert r["stale_completed"] == ["exp"]
    assert "exp" in r["preserved"]


def test_replan_accepts_replacements_and_stays_acyclic() -> None:
    plan_nodes = [
        {"id": "a", "depends_on": [], "status": "completed"},
        {"id": "b", "depends_on": ["a"], "status": "failed"},
        {"id": "c", "depends_on": ["b"], "status": "pending"},
    ]
    plan = {"nodes": plan_nodes}
    trigger = {"reason": "b approach invalid", "failed_node_ids": ["b"]}
    replacements = [
        {"id": "b2", "depends_on": ["a"], "outputs": ["b2_artifact"]},
        {"id": "c2", "depends_on": ["b2"], "outputs": ["c2_artifact"]},
    ]
    env = run_tool("replan_diff", {"plan": plan, "trigger": trigger,
                                   "replacement_nodes": replacements})
    r = env["result"]
    merged_ids = [n["id"] for n in r["merged_plan"]["nodes"]]
    assert "b2" in merged_ids and "c2" in merged_ids
    assert r["added"] == ["b2", "c2"]
    # a preserved + b rework (kept) + 2 replacements = 4 nodes; c was invalidated
    assert r["merged_graph"]["node_count"] == 4
    assert "c" not in merged_ids


def test_replan_rejects_replacement_id_clash() -> None:
    # Trigger 'a' invalidates downstream pending 'c'; 'b' (completed, downstream)
    # is preserved-but-stale. A replacement id 'b' collides with the preserved 'b'.
    plan_nodes = [
        {"id": "a", "depends_on": [], "status": "completed"},
        {"id": "b", "depends_on": ["a"], "status": "completed"},
        {"id": "c", "depends_on": ["b"], "status": "pending"},
    ]
    plan = {"nodes": plan_nodes}
    trigger = {"reason": "new evidence invalidates upstream", "changed_node_ids": ["a"]}
    env = run_tool("replan_diff", {"plan": plan, "trigger": trigger,
                                   "replacement_nodes": [{"id": "b", "depends_on": []}]},
                   expect_exit=3)
    assert env["error"]["code"] == "E_REPLAN_ID_CLASH"


def test_self_audit_reports_all_gates_even_on_failure() -> None:
    import json

    nodes = json.loads(json.dumps(VALID_MICP_NODES))
    nodes[0]["inputs"] = ["nope:thing"]  # implicit dependency
    out = {"dag": {"nodes": nodes},
           "execution_limits": {"max_call_depth": 8, "max_iterations": 50},
           "findings": []}
    env = run_tool("self_audit", {"output": out})
    r = env["result"]
    assert r["pass"] is False
    # all six gates present
    for gate in ("G1_no_implicit_dependencies", "G2_single_owner", "G3_verifiable_dod",
                 "G4_acyclic", "G5_limits_and_human_gates", "G6_epistemic_tags"):
        assert gate in r["gates"], f"{gate} missing from gates"
