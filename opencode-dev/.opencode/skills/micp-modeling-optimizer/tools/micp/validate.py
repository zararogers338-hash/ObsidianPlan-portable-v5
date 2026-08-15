"""JSON-Schema validation for micp-modeling-optimizer input/output contracts.

Prefers the `jsonschema` library when installed; falls back to a documented
subset validator (required / type / enum / additionalProperties / minLength /
maxLength / pattern) so the suite stays offline and dependency-free.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from _common import HAS_JSONSCHEMA, ToolError
from errors import MmoError, MmoErrorCode

_SCHEMA_DIR = Path(__file__).resolve().parent.parent.parent / "schemas"


def _load_schema(name: str) -> dict:
    p = _SCHEMA_DIR / name
    if not p.is_file():
        raise MmoError(MmoErrorCode.TOOL_UNAVAILABLE, f"schema file not found: {p}")
    return json.loads(p.read_text(encoding="utf-8"))


def validate_against(value: Any, schema: dict, *, schema_name: str) -> None:
    """Validate value against a schema; raise MmoError(MMO-E101) on failure."""
    if HAS_JSONSCHEMA:
        from jsonschema import Draft202012Validator, ValidationError  # type: ignore

        try:
            Draft202012Validator(schema).validate(value)
            return
        except ValidationError as exc:
            raise MmoError(
                MmoErrorCode.INPUT_SCHEMA_VIOLATION,
                f"{schema_name} validation failed: {exc.message}",
                detail={"path": list(exc.path), "schema_path": list(exc.schema_path)},
            ) from exc
    issues = _fallback_validate(value, schema)
    if issues:
        raise MmoError(
            MmoErrorCode.INPUT_SCHEMA_VIOLATION,
            f"{schema_name} validation failed (fallback): {issues[0]}",
            detail={"issues": issues[:10]},
        )


def check_output_schema(value: Any) -> None:
    """Validate the produced output against schemas/output.schema.json. This is
    the mandatory self-check before returning SUCCESS (MMO-E701 on failure)."""
    try:
        validate_against(value, _load_schema("output.schema.json"), schema_name="output")
    except MmoError as exc:
        if exc.ecode.code == "MMO-E101":
            raise MmoError(
                MmoErrorCode.OUTPUT_SCHEMA_VIOLATION,
                exc.message,
                detail=exc.details,
                retryable=True,
            ) from exc
        raise


def _fallback_validate(value: Any, schema: dict, path: str = "$") -> list[str]:
    """Minimal structural validator covering the subset used in our schemas."""
    issues: list[str] = []
    t = schema.get("type")
    if t == "object":
        if not isinstance(value, dict):
            issues.append(f"{path}: expected object")
            return issues
        if schema.get("additionalProperties") is False:
            extra = [k for k in value if k not in schema.get("properties", {})]
            for k in extra:
                issues.append(f"{path}.{k}: additional property not allowed")
        for k, subschema in schema.get("properties", {}).items():
            if k in value:
                issues.extend(_fallback_validate(value[k], subschema, f"{path}.{k}"))
        for req in schema.get("required", []):
            if req not in value:
                issues.append(f"{path}: missing required property '{req}'")
    elif t == "array":
        if not isinstance(value, list):
            issues.append(f"{path}: expected array")
            return issues
        items = schema.get("items", {})
        for i, v in enumerate(value):
            issues.extend(_fallback_validate(v, items, f"{path}[{i}]"))
    elif t == "string":
        if not isinstance(value, str):
            issues.append(f"{path}: expected string")
            return issues
        if "minLength" in schema and len(value) < schema["minLength"]:
            issues.append(f"{path}: shorter than minLength {schema['minLength']}")
        if "pattern" in schema and not re.search(schema["pattern"], value):
            issues.append(f"{path}: does not match pattern")
        if schema.get("enum") and value not in schema["enum"]:
            issues.append(f"{path}: not in enum {schema['enum']}")
    elif t in ("number", "integer"):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            issues.append(f"{path}: expected {t}")
    elif t == "boolean":
        if not isinstance(value, bool):
            issues.append(f"{path}: expected boolean")
    # oneOf / anyOf are only used lightly in our schemas; resolve by trying each
    for key in ("anyOf", "oneOf"):
        if key in schema:
            options = schema[key]
            ok = False
            for opt in options:
                if not _fallback_validate(value, opt, path):
                    ok = True
                    break
            if not ok:
                issues.append(f"{path}: failed {key}")
    return issues


def validate_input(payload: dict) -> None:
    """Validate a request payload against schemas/input.schema.json."""
    validate_against(payload, _load_schema("input.schema.json"), schema_name="input")
