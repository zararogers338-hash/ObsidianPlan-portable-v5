"""Schema-subset conformance tests for the MRV schemas.

Each contract schema must validate with the project's own minimal validator
(no third-party dependency) — the same subset micp-data-analyst relies on.
Also asserts the schemas themselves only use supported keywords.
"""

from __future__ import annotations

import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                "tools", "mrv"))

from _jsonschema import SchemaError, validate  # noqa: E402

SCHEMAS = [
    "input.schema.json",
    "output.schema.json",
    "reproduction-manifest.schema.json",
    "provenance-event.schema.json",
]


@pytest.fixture(scope="module")
def schemas():
    base = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "schemas")
    return {name: json.load(open(os.path.join(base, name), encoding="utf-8"))
            for name in SCHEMAS}


@pytest.mark.parametrize("name", SCHEMAS)
def test_schema_uses_supported_subset_only(schemas, name) -> None:
    validate({}, schemas[name])  # raises SchemaError if keywords are unsupported


def test_input_schema_valid_envelope(schemas) -> None:
    good = {
        "task_id": "t1", "project_id": "p1", "request": "复现并锁定环境",
        "action": "reproduce", "root": ".",
        "skill_version": "1.0.0", "controller_version": "obsidian-ctl-0.1.0",
        "timestamp": "2026-08-07T08:00:00Z", "risk_level": "low",
        "seed_policy": "reuse", "random_seed": 7,
        "commands": [{"id": "a", "cmd": "true", "cwd": ".", "expected_outputs": ["x"]}],
    }
    assert validate(good, schemas["input.schema.json"]) == []


def test_input_schema_rejects_unknown_action(schemas) -> None:
    bad = {
        "task_id": "t1", "project_id": "p1", "request": "x",
        "action": "nonsense",
        "skill_version": "1.0.0", "controller_version": "c",
        "timestamp": "2026-08-07T08:00:00Z",
    }
    assert validate(bad, schemas["input.schema.json"]) != []


def test_input_schema_rejects_extra_field(schemas) -> None:
    good = {
        "task_id": "t1", "project_id": "p1", "request": "复现",
        "skill_version": "1.0.0", "controller_version": "c",
        "timestamp": "2026-08-07T08:00:00Z",
    }
    assert validate(good, schemas["input.schema.json"]) == []
    bad = dict(good)
    bad["surprise_field"] = 1
    assert validate(bad, schemas["input.schema.json"]) != []


def test_manifest_schema_roundtrip(schemas) -> None:
    manifest = {
        "schema_version": "1.0.0",
        "manifest_id": "rm-test",
        "created_at": "2026-08-07T08:00:00Z",
        "project_id": "p1",
        "task_id": "t1",
        "versions": {"skill_version": "1.0.0", "git_commit": "fp_abcd"},
        "environment": {"os": {"system": "Windows"}, "runtime": {"python": "3.13"}},
        "inputs": [{"path": "data/raw/x.csv", "hash": "a" * 64}],
        "outputs": [{"path": "data/processed/y.csv", "hash": "b" * 64}],
        "parameters": {"temp": 25},
        "seed": {"value": 7, "policy": "reuse"},
        "commands": [{"id": "a", "cmd": "true"}],
        "checks": [{"check": "c", "passed": True}],
    }
    assert validate(manifest, schemas["reproduction-manifest.schema.json"]) == []
    bad = dict(manifest)
    bad["inputs"] = [{"path": "x.csv", "hash": "short"}]
    assert validate(bad, schemas["reproduction-manifest.schema.json"]) != []


def test_provenance_event_schema_roundtrip(schemas) -> None:
    event = {
        "schema_version": "1.0.0",
        "event_id": "ev-x",
        "ts": "2026-08-07T08:00:00Z",
        "task_id": "t1",
        "project_id": "p1",
        "caller": "controller",
        "skill_id": "micp-reproducibility-versioning",
        "skill_version": "1.0.0",
        "controller_version": "c",
        "action": "record",
        "input_summary": "s",
        "input_refs": [],
        "input_hashes": {},
        "tool_calls": [{"tool": "env", "ok": True}],
        "output_hashes": {},
        "git_commit": "fp_abc",
        "environment": {},
        "errors": [],
        "human_approval": "not_required",
        "prev_hash": "0" * 64,
        "hash": "f" * 64,
    }
    assert validate(event, schemas["provenance-event.schema.json"]) == []
    bad = dict(event)
    bad["skill_id"] = "not-the-right-skill"
    assert validate(bad, schemas["provenance-event.schema.json"]) != []
