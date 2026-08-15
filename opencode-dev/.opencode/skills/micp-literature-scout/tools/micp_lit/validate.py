"""Validation: JSON-schema validation with graceful offline degradation.

Uses `jsonschema` when installed; otherwise falls back to a minimal built-in
checker covering the constraints this skill's contracts actually rely on
(required fields, enums, patterns for the subset of the schema the output
envelope uses). Keeps the skill installable with zero third-party deps.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

SCHEMAS = Path(__file__).resolve().parent.parent.parent / "schemas"

try:
    from jsonschema import Draft7Validator, ValidationError  # type: ignore

    _HAS_JSONSCHEMA = True
except Exception:  # noqa: BLE001
    _HAS_JSONSCHEMA = False

# Fields the minimal checker treats as `type: string` and enums from the schemas.
_STR_KEYS = {
    "status", "summary", "database", "query", "contract_version", "task_id",
    "project_id", "request", "action", "skill_version", "controller_version",
    "timestamp", "doi", "title", "container", "ref_id", "type", "format",
    "language", "media_type", "uri", "note", "name", "reason", "message", "code",
    "evidence", "scope", "label", "level", "quality", "comparability", "bias",
    "rule", "statement", "detail", "format", "written_to",
}
_ENUM_KEYS = {
    "status": {"SUCCESS", "PARTIAL", "BLOCKED", "FAILED", "NEED_ADDITIONAL_SKILL", "HUMAN_APPROVAL_REQUIRED"},
    "label": {"OBSERVED", "REPORTED", "CALCULATED", "INFERRED", "HYPOTHESIS", "RECOMMENDATION"},
    "action": {"search.run", "search.repeat", "doi.verify", "dedup.merge",
               "triage.screen", "cite.export", "sources.register", "validate.self"},
    "database": {"auto", "openalex", "crossref", "pubmed", "offline_fixture", "none"},
    "format": {"bibtex", "csv", "json", "ris"},
    "risk_level": {"low", "medium", "high", "critical"},
}
_OBJECT_KEYS = {"context", "constraints", "evidence_refs", "data_refs", "upstream_outputs",
                "human_approval_state", "query", "records", "reference", "provenance",
                "validation", "artifacts", "errors", "findings", "assumptions",
                "evidence_used", "uncertainty", "risks", "requested_next_skills"}
# Output required top-level keys (spec §六).
_OUTPUT_REQUIRED = [
    "status", "summary", "findings", "assumptions", "evidence_used",
    "uncertainty", "risks", "artifacts", "requested_next_skills",
    "validation", "provenance", "errors",
]
# Input required top-level keys (spec §六 + contract).
_INPUT_REQUIRED = [
    "contract_version", "task_id", "project_id", "request", "action",
    "skill_version", "timestamp",
]


class ValidationIssue:
    __slots__ = ("path", "message")

    def __init__(self, path: str, message: str) -> None:
        self.path = path
        self.message = message

    def to_dict(self) -> dict[str, str]:
        return {"path": self.path, "message": self.message}


def _load_schema(name: str) -> dict[str, Any]:
    path = SCHEMAS / name
    if not path.is_file():
        raise FileNotFoundError(f"schema missing: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def validate_against(name: str, data: Any, *, use_minimal: bool = False) -> tuple[bool, list[ValidationIssue]]:
    """Validate `data` against schema file `name`. Returns (valid, issues)."""
    schema = _load_schema(name)
    if _HAS_JSONSCHEMA and not use_minimal:
        validator = Draft7Validator(schema)
        issues = [ValidationIssue(".".join(str(p) for p in e.absolute_path) or "",
                                  e.message)
                  for e in sorted(validator.iter_errors(data), key=lambda e: e.absolute_path)]
        return (len(issues) == 0), issues
    return _minimal_validate(name, schema, data)


def _minimal_validate(name: str, schema: dict[str, Any], data: Any) -> tuple[bool, list[ValidationIssue]]:
    issues: list[ValidationIssue] = []
    props = schema.get("properties", {})
    required = schema.get("required", [])

    if not isinstance(data, dict):
        return False, [ValidationIssue("", "root must be an object")]

    for field in required:
        if field not in data:
            issues.append(ValidationIssue(field, f"missing required property '{field}'"))

    for field, value in data.items():
        prop = props.get(field)
        if not prop:
            if schema.get("additionalProperties") is False:
                issues.append(ValidationIssue(field, f"additional property '{field}' not allowed"))
            continue
        expected = prop.get("type")
        if expected == "string" and not isinstance(value, str):
            issues.append(ValidationIssue(field, f"expected string, got {type(value).__name__}"))
        elif expected == "integer" and not isinstance(value, int):
            issues.append(ValidationIssue(field, f"expected integer, got {type(value).__name__}"))
        elif expected == "boolean" and not isinstance(value, bool):
            issues.append(ValidationIssue(field, f"expected boolean, got {type(value).__name__}"))
        elif expected == "array" and not isinstance(value, list):
            issues.append(ValidationIssue(field, f"expected array, got {type(value).__name__}"))
        elif expected == "object" and not isinstance(value, dict):
            issues.append(ValidationIssue(field, f"expected object, got {type(value).__name__}"))
        enum_vals = prop.get("enum")
        if enum_vals and value not in enum_vals:
            issues.append(ValidationIssue(field, f"enum violation: {value!r} not in {enum_vals}"))
        pattern = prop.get("pattern")
        if pattern and isinstance(value, str) and not re.match(pattern, value):
            issues.append(ValidationIssue(field, f"pattern violation: {value!r} !~ {pattern}"))
    return (len(issues) == 0), issues


def validate_input(data: Any) -> tuple[bool, list[ValidationIssue]]:
    return validate_against("input.schema.json", data)


def validate_output(data: Any) -> tuple[bool, list[ValidationIssue]]:
    return validate_against("output.schema.json", data)


def list_issues(issues: list[ValidationIssue]) -> list[dict[str, str]]:
    return [i.to_dict() for i in issues]
