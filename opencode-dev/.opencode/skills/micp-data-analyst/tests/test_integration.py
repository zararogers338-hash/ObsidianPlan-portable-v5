"""Integration tests: the full skill pipeline end to end.

Proves the service composes (validate -> version -> preconditions -> qc ->
stats -> self-check) and that a well-formed request produces a self-consistent,
schema-valid output document.
"""

from __future__ import annotations

import json
import os

from conftest import PSEUDO_INPUT, run_tool

SKILL_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _load_skill_schema(name: str) -> dict:
    with open(os.path.join(SKILL_ROOT, "schemas", name), encoding="utf-8") as fh:
        return json.load(fh)


def test_input_schema_is_strict() -> None:
    schema = _load_skill_schema("input.schema.json")
    assert schema["$id"].endswith("micp-data-analyst.input.json")
    for f in ("task_id", "project_id", "request", "skill_version",
              "controller_version", "timestamp"):
        assert f in schema["required"]


def test_output_schema_requires_all_load_bearing_fields() -> None:
    schema = _load_skill_schema("output.schema.json")
    required = {"status", "summary", "findings", "assumptions", "evidence_used",
                "uncertainty", "risks", "artifacts", "requested_next_skills",
                "validation", "provenance", "errors"}
    assert required <= set(schema["required"])


def test_full_pipeline_output_validates_against_output_schema() -> None:
    env = run_tool("service", PSEUDO_INPUT)
    body = env["result"]
    assert body["status"] == "SUCCESS"
    schema = _load_skill_schema("output.schema.json")
    sys_path = __import__("sys")
    sys_path.path.insert(0, os.path.join(SKILL_ROOT, "tools", "micp"))
    from _jsonschema import validate as js_validate  # noqa: PLC0415
    errs = js_validate(body, schema)
    assert not errs, errs[:3]


def test_output_has_data_quality_and_statistics() -> None:
    env = run_tool("service", PSEUDO_INPUT)
    body = env["result"]
    assert "data_quality" in body
    assert "statistics" in body
    assert "pseudo_replication" in body
    dq = body["data_quality"]
    assert dq["checks"]  # at least one check ran
    assert isinstance(dq["issues"], list)


def test_output_has_provenance_and_validation_gates() -> None:
    env = run_tool("service", PSEUDO_INPUT)
    body = env["result"]
    pv = body["provenance"]
    assert pv["skill"] == "micp-data-analyst"
    assert pv["skill_version"] == "1.0.0"
    assert pv["generator"]
    gates = body["validation"]["gates"]
    for gate in ("G1_input_schema", "G2_version_gate", "G3_preconditions",
                 "G4_self_check", "G5_epistemic_tags"):
        assert gate in gates
    assert body["validation"]["self_audit_pass"] is True


def test_tool_runs_recorded_in_validation() -> None:
    env = run_tool("service", PSEUDO_INPUT)
    body = env["result"]
    tools = {tr["tool"] for tr in body["validation"]["tool_runs"]}
    assert "qc" in tools
    assert "stats" in tools
