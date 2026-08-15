"""Input/output schema validation for micp-biosafety-environment-auditor.

Uses jsonschema when available (project convention), with a minimal builtin
fallback validator so the skill stays runnable offline with zero third-party
deps for the envelope shape (spec §五: reuse mature deps; degrade gracefully).
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from .errors import MbsError, MbsErrorCode

SCHEMAS_DIR = Path(__file__).resolve().parent.parent.parent / "schemas"


def _load_schema(name: str) -> dict[str, Any]:
    path = SCHEMAS_DIR / name
    if not path.is_file():
        raise MbsError(
            MbsErrorCode.CONTEXT_CORRUPT,
            f"Schema file missing: {path}",
            detail={"path": str(path)},
        )
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise MbsError(
            MbsErrorCode.CONTEXT_CORRUPT,
            f"Schema file unreadable/invalid JSON: {path}",
            detail={"path": str(path), "error": str(exc)},
        ) from exc


def _validate_fallback(obj: Any, schema: dict[str, Any], path: str = "$") -> list[str]:
    """Minimal draft-07 subset validator: types, required, enums, patterns,
    numeric min/max, const, additionalProperties. Used only when jsonschema
    is unavailable."""
    errors: list[str] = []

    def add(msg: str) -> None:
        errors.append(f"{path}: {msg}")

    if schema.get("type") == "object" and isinstance(obj, dict):
        required = schema.get("required", [])
        for f in required:
            if f not in obj:
                add(f"missing required field '{f}'")
        props = schema.get("properties", {})
        if schema.get("additionalProperties") is False:
            for k in obj:
                if k not in props:
                    add(f"additional property '{k}' not allowed")
        for k, sub in props.items():
            if k in obj:
                _validate_fallback(obj[k], sub, f"{path}.{k}")
    elif schema.get("type") == "string" and isinstance(obj, str):
        if "pattern" in schema:
            if re.search(schema["pattern"], obj) is None:
                add(f"string '{obj[:40]}' does not match pattern {schema['pattern']}")
        if "const" in schema and obj != schema["const"]:
            add(f"string not equal const {schema['const']}")
    elif schema.get("type") == "number" and isinstance(obj, (int, float)) and not isinstance(obj, bool):
        if "minimum" in schema and obj < schema["minimum"]:
            add(f"value {obj} < minimum {schema['minimum']}")
        if "maximum" in schema and obj > schema["maximum"]:
            add(f"value {obj} > maximum {schema['maximum']}")
        if "enum" in schema and obj not in schema["enum"]:
            add(f"value {obj} not in enum")
    elif schema.get("type") == "integer" and isinstance(obj, int) and not isinstance(obj, bool):
        if "minimum" in schema and obj < schema["minimum"]:
            add(f"value {obj} < minimum {schema['minimum']}")
    elif schema.get("type") == "boolean" and isinstance(obj, bool):
        pass
    elif schema.get("type") == "array" and isinstance(obj, list):
        items = schema.get("items", {})
        for i, v in enumerate(obj):
            _validate_fallback(v, items, f"{path}[{i}]")
    elif schema.get("type") == "null" and obj is None:
        pass
    elif "enum" in schema and isinstance(obj, (str, int, float)):
        if obj not in schema["enum"]:
            add(f"value {obj!r} not in enum {schema['enum']}")
    elif "const" in schema:
        if obj != schema["const"]:
            add(f"value not equal const {schema['const']}")
    elif "required" in schema and isinstance(obj, dict):
        for f in schema["required"]:
            if f not in obj:
                add(f"missing required field '{f}'")
        props = schema.get("properties", {})
        for k, sub in props.items():
            if k in obj:
                _validate_fallback(obj[k], sub, f"{path}.{k}")
    elif isinstance(obj, (int, float)) and not isinstance(obj, bool) and "minimum" in schema:
        if obj < schema["minimum"]:
            add(f"value {obj} < minimum {schema['minimum']}")
    else:
        pass
    return errors


def _has_jsonschema() -> bool:
    try:
        import jsonschema  # noqa: F401

        return True
    except Exception:
        return False


def validate_input(payload: dict[str, Any]) -> list[str]:
    """Return list of input-schema violations (empty = valid)."""
    schema = _load_schema("input.schema.json")
    if _has_jsonschema():
        from jsonschema import Draft7Validator

        validator = Draft7Validator(schema)
        errors = sorted(validator.iter_errors(payload), key=lambda e: list(e.path))
        return [f"{'/'.join(str(p) for p in e.path) or '$'}: {e.message}" for e in errors]
    return _validate_fallback(payload, schema)


def validate_output(output: dict[str, Any]) -> list[str]:
    """Return list of output-schema violations (empty = valid)."""
    schema = _load_schema("output.schema.json")
    if _has_jsonschema():
        from jsonschema import Draft7Validator

        validator = Draft7Validator(schema)
        errors = sorted(validator.iter_errors(output), key=lambda e: list(e.path))
        return [f"{'/'.join(str(p) for p in e.path) or '$'}: {e.message}" for e in errors]
    return _validate_fallback(output, schema)


def check_output_schema(output: dict[str, Any]) -> None:
    """Raise MBS-E701 if the output envelope violates the output schema."""
    violations = validate_output(output)
    if violations:
        raise MbsError(
            MbsErrorCode.OUTPUT_SCHEMA_VIOLATION,
            "Output envelope failed validation against schemas/output.schema.json.",
            detail={"violations": violations},
        )
