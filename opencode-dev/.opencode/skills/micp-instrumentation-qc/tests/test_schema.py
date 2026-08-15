"""Schema tests: input/output envelopes validate against schemas/*.json.

These are integration tests for the contract: they prove the machine-readable
contracts are internally consistent (a valid input envelope passes, an invalid
one fails, and a produced output envelope passes the output schema).
"""

import json
import os
import sys

import pytest

SKILL = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, os.path.join(SKILL, "tools"))

jsonschema = pytest.importorskip("jsonschema")

SCHEMAS = os.path.join(SKILL, "schemas")


def load(name):
    with open(os.path.join(SCHEMAS, name), encoding="utf-8") as f:
        return json.load(f)


def test_schemas_are_valid_json():
    for name in ("input.schema.json", "output.schema.json"):
        s = load(name)
        jsonschema.Draft7Validator.check_schema(s)


def _valid_input():
    return {
        "task_id": "task-1",
        "project_id": "proj-1",
        "request": "建立 pH 标定 QC 计划",
        "skill_version": "1.0.0",
        "controller_version": "1.0.0",
        "timestamp": "2026-08-06T12:00:00+00:00",
        "requested_output_format": "qc_report",
        "qc_input": {
            "instruments": [{
                "instrument_id": "pH-1", "kind": "pH", "model": "Mettler S220",
                "measurement_range": [0, 14], "saturation_threshold": 14.0,
            }],
            "measurements": [{
                "measurement_id": "m0", "instrument_id": "pH-1", "sample_id": "s1",
                "value": 7.02, "unit": "pH", "timestamp": "2026-08-01T10:00:00",
            }],
            "samples": [{"sample_id": "s1", "collection_time": "2026-08-01T09:00:00"}],
        },
    }


def test_valid_input_passes():
    v = jsonschema.Draft7Validator(load("input.schema.json"))
    errs = list(v.iter_errors(_valid_input()))
    assert not errs, errs


def test_missing_required_field_fails():
    v = jsonschema.Draft7Validator(load("input.schema.json"))
    data = _valid_input()
    del data["skill_version"]
    errs = list(v.iter_errors(data))
    assert any("skill_version" in e.message for e in errs)


def test_unknown_enum_fails():
    v = jsonschema.Draft7Validator(load("input.schema.json"))
    data = _valid_input()
    data["requested_output_format"] = "banana"
    errs = list(v.iter_errors(data))
    assert errs


def test_additional_properties_rejected():
    v = jsonschema.Draft7Validator(load("input.schema.json"))
    data = _valid_input()
    data["surprise_field"] = True
    errs = list(v.iter_errors(data))
    assert errs


def test_measurement_missing_required_field_fails():
    v = jsonschema.Draft7Validator(load("input.schema.json"))
    data = _valid_input()
    del data["qc_input"]["measurements"][0]["value"]
    errs = list(v.iter_errors(data))
    assert errs


def _valid_output():
    return {
        "status": "SUCCESS",
        "summary": "QC passed",
        "findings": [{
            "id": "f1", "type": "measurement", "severity": "info",
            "message": "all pass", "statement": {"text": "ok", "label": "OBSERVED", "source": "instr-1"},
        }],
        "assumptions": [],
        "evidence_used": ["data_refs/0"],
        "uncertainty": {"level": "low", "notes": "no calibration needed"},
        "risks": [],
        "artifacts": [],
        "requested_next_skills": [],
        "qc_report": {"report_type": "qc_report", "overall_passed": True, "pass_rate": 1.0,
                      "instrument_status": [], "sample_flags": [], "analysis_restrictions": [],
                      "retest_items": []},
        "validation": {"schema_passed": True, "self_check_passed": True, "tool_calls": [{"tool": "qc", "ok": True}]},
        "provenance": {"skill": "micp-instrumentation-qc", "skill_version": "1.0.0",
                       "contract_version": "1.0.0", "timestamp": "2026-08-06T12:00:00+00:00",
                       "tools_used": ["qc_pipeline"]},
        "errors": [],
    }


def test_valid_output_passes():
    v = jsonschema.Draft7Validator(load("output.schema.json"))
    errs = list(v.iter_errors(_valid_output()))
    assert not errs, errs


def test_output_missing_required_fails():
    v = jsonschema.Draft7Validator(load("output.schema.json"))
    data = _valid_output()
    del data["provenance"]
    errs = list(v.iter_errors(data))
    assert errs


def test_output_status_enum_fails():
    v = jsonschema.Draft7Validator(load("output.schema.json"))
    data = _valid_output()
    data["status"] = "MAYBE"
    errs = list(v.iter_errors(data))
    assert errs


def test_output_error_code_pattern():
    v = jsonschema.Draft7Validator(load("output.schema.json"))
    data = _valid_output()
    data["errors"] = [{"code": "MICQ-E1001", "message": "input invalid"}]
    errs = list(v.iter_errors(data))
    assert not errs
    data["errors"] = [{"code": "NOPE-9999", "message": "bad"}]
    errs = list(v.iter_errors(data))
    assert errs
