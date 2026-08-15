"""Integration tests: the tool pipeline as a whole on a valid MICP DAG.

Proves the tools compose (validate -> dag_check -> granularity -> budget ->
critical_path -> self_audit) and that a well-formed plan passes all gates.
"""

from __future__ import annotations

import json
import os

from conftest import MICP_DAG, VALID_MICP_NODES, run_tool

SKILL_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _load_skill_schema(name: str) -> dict:
    with open(os.path.join(SKILL_ROOT, "schemas", name), encoding="utf-8") as fh:
        return json.load(fh)


def test_validate_input_schema_is_strict() -> None:
    """The input contract itself must parse (it is loaded by validate.py)."""
    schema = _load_skill_schema("input.schema.json")
    assert schema["$id"].endswith("input.schema.json")
    assert "task_id" in schema["required"]
    assert "request" in schema["required"]


def test_output_schema_requires_all_load_bearing_fields() -> None:
    schema = _load_skill_schema("output.schema.json")
    required = {"status", "summary", "findings", "assumptions", "evidence_used",
                "uncertainty", "risks", "artifacts", "requested_next_skills",
                "validation", "provenance", "errors"}
    assert required <= set(schema["required"])


def test_task_node_schema_requires_dod() -> None:
    schema = _load_skill_schema("task-node.schema.json")
    assert "definition_of_done" in schema["required"]
    assert "primary_skill" in schema["required"]


def test_pipeline_passes_all_gates() -> None:
    # 1. validate each node against the task-node schema (document must be an object)
    for node in VALID_MICP_NODES:
        doc_payload = {"schema": "schemas/task-node.schema.json", "document": node}
        result = run_tool("validate", doc_payload)
        assert result["result"]["valid"] is True, result["result"]["errors"]

    # 2. dag_check: valid DAG
    dag = run_tool("dag_check", {"nodes": VALID_MICP_NODES})
    assert dag["result"]["is_dag"] is True
    assert dag["result"]["cycles"] == []
    assert dag["result"]["unknown_dependencies"] == []

    # 3. granularity: every node OK
    gran = run_tool("granularity_scorer", {"nodes": VALID_MICP_NODES})
    assert all(n["verdict"] == "OK" for n in gran["result"]["nodes"]), gran["result"]["nodes"]

    # 4. budget: estimates computed for every kind
    tasks = [{"id": n["id"], "kind": n["kind"], "risk_level": n["risk_level"],
              "data_sensitivity": n["data_sensitivity"], "est_context_tokens": n["est_context_tokens"]}
             for n in VALID_MICP_NODES]
    budget = run_tool("budget_estimator", {"tasks": tasks})
    assert set(budget["result"]["estimates"]) == {n["id"] for n in VALID_MICP_NODES}
    assert budget["result"]["totals"]["hours"] > 0

    # 5. critical_path: DAG metrics present
    cp = run_tool("critical_path", {"nodes": VALID_MICP_NODES})
    assert cp["result"]["critical_path"][0] == "lit_review"
    assert cp["result"]["critical_path"][-1] == "ureolysis_chem"
    assert cp["result"]["critical_path_hours"] > 0

    # 6. self_audit: all gates pass
    audit = run_tool("self_audit", {"output": MICP_DAG})
    assert audit["result"]["pass"] is True, audit["result"]["gates"]
