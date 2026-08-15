"""Schema-validation adapter.

Uses the `jsonschema` package when available; falls back to a small built-in
validator covering the JSON-Schema subset our contract files use. The fallback
keeps the skill fully functional offline on a bare Python install — the
failure mode is weaker diagnostics, never skipped validation.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from .errors import OdgError, OdgErrorCode

try:  # pragma: no cover - exercised in integration env
    import jsonschema as _js

    _HAVE_JS = True
except Exception:  # pragma: no cover
    _js = None
    _HAVE_JS = False

_SCHEMA_DIR = Path(__file__).resolve().parent.parent.parent / "schemas"

_SCHEMA_NAMES = {
    "input": "input.schema.json",
    "output": "output.schema.json",
    "decision-memo": "decision-memo.schema.json",
    "gate-rule": "gate-rule.schema.json",
}


def _load_schema(name: str) -> dict[str, Any]:
    path = _SCHEMA_DIR / name
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise OdgError(
            OdgErrorCode.TOOL_UNAVAILABLE,
            f"Contract schema {name} unreadable: {exc}",
            detail={"path": str(path)},
        ) from exc


_TYPE_MAP = {
    "object": dict, "array": list, "string": str,
    "integer": int, "number": (int, float), "boolean": bool, "null": type(None),
}


def _fallback_validate(instance: Any, schema: dict[str, Any], path: str = "$") -> list[str]:
    errs: list[str] = []
    if not isinstance(schema, dict):
        return errs

    if "enum" in schema and instance not in schema["enum"]:
        errs.append(f"{path}: {instance!r} not in enum {schema['enum']}")
        return errs
    if "const" in schema and instance != schema["const"]:
        errs.append(f"{path}: expected const {schema['const']!r}, got {instance!r}")

    stype = schema.get("type")
    if stype:
        types = stype if isinstance(stype, list) else [stype]
        if not any(
            isinstance(instance, _TYPE_MAP[t]) and not (
                t in ("integer", "number") and isinstance(instance, bool))
            for t in types
        ):
            errs.append(f"{path}: expected type {stype}, got {type(instance).__name__}")
            return errs

    if isinstance(instance, dict):
        for req in schema.get("required", []):
            if req not in instance:
                errs.append(f"{path}: missing required property '{req}'")
        props = schema.get("properties", {})
        for k, v in instance.items():
            if k in props:
                errs.extend(_fallback_validate(v, props[k], f"{path}.{k}"))
            elif schema.get("additionalProperties") is False:
                errs.append(f"{path}: unexpected property '{k}'")
        # $ref resolution (limited): only internal #/$defs/... refs
        for k, v in instance.items():
            sub = props.get(k)
            if isinstance(sub, dict) and "$ref" in sub and k in instance:
                target = sub["$ref"]
                if target.startswith("#/$defs/"):
                    defn = schema.get("$defs", {}).get(target[len("#/$defs/"):])
                    if isinstance(defn, dict):
                        errs.extend(_fallback_validate(instance[k], defn, f"{path}.{k}"))
    elif isinstance(instance, list):
        if "minItems" in schema and len(instance) < schema["minItems"]:
            errs.append(f"{path}: fewer than {schema['minItems']} items")
        item_schema = schema.get("items")
        if isinstance(item_schema, dict):
            if "$ref" in item_schema and item_schema["$ref"].startswith("#/$defs/"):
                defn = schema.get("$defs", {}).get(item_schema["$ref"][len("#/$defs/"):])
                if isinstance(defn, dict):
                    for i, item in enumerate(instance):
                        errs.extend(_fallback_validate(item, defn, f"{path}[{i}]"))
            else:
                for i, item in enumerate(instance):
                    errs.extend(_fallback_validate(item, item_schema, f"{path}[{i}]"))

    if isinstance(instance, str):
        if "pattern" in schema and not re.fullmatch(schema["pattern"], instance):
            errs.append(f"{path}: {instance!r} does not match pattern {schema['pattern']}")

    if isinstance(instance, (int, float)) and not isinstance(instance, bool):
        if "minimum" in schema and instance < schema["minimum"]:
            errs.append(f"{path}: {instance} < minimum {schema['minimum']}")
        if "maximum" in schema and instance > schema["maximum"]:
            errs.append(f"{path}: {instance} > maximum {schema['maximum']}")

    if isinstance(instance, dict) and "$ref" in schema:
        pass  # handled by parent resolution above

    return errs


def validate(instance: Any, schema_key: str, *, error_code: OdgErrorCode) -> None:
    """Validate or raise OdgError(error_code) with full violation detail."""
    schema_name = _SCHEMA_NAMES[schema_key]
    schema = _load_schema(schema_name)
    if _HAVE_JS:
        # Strip the $schema URI so jsonschema uses its bundled meta-schema
        # instead of fetching the remote draft-2020-12 schema (offline-safe).
        schema = {k: v for k, v in schema.items() if k != "$schema"}
        try:
            validator = _js.validators.validator_for(schema)
            validator.check_schema(schema)
        except Exception as exc:  # pragma: no cover
            raise OdgError(
                error_code,
                f"Schema {schema_name} itself is invalid: {exc}",
            ) from exc
        violations = sorted(
            validator(schema).iter_errors(instance),
            key=lambda e: list(e.absolute_path),
        )
        if violations:
            raise OdgError(
                error_code,
                "; ".join(
                    f"{'/'.join(map(str, v.absolute_path)) or '<root>'}: {v.message}"
                    for v in violations[:10]
                ),
                detail={
                    "schema": schema_name,
                    "violation_count": len(violations),
                    "violations": [
                        {"path": "/".join(map(str, v.absolute_path)) or "<root>",
                         "message": v.message}
                        for v in violations[:25]
                    ],
                },
            )
        return

    errs = _fallback_validate(instance, schema)
    if errs:
        raise OdgError(
            error_code,
            "; ".join(errs[:10]),
            detail={"schema": schema_name, "violations": errs[:25], "validator": "builtin-fallback"},
        )


def validate_input(payload: Any) -> None:
    validate(payload, "input", error_code=OdgErrorCode.INPUT_SCHEMA_VIOLATION)


def validate_output(payload: Any) -> None:
    validate(payload, "output", error_code=OdgErrorCode.OUTPUT_SCHEMA_VIOLATION)


def validate_memo(payload: Any) -> None:
    validate(payload, "decision-memo", error_code=OdgErrorCode.OUTPUT_SCHEMA_VIOLATION)


def validate_gate_rules(payload: Any) -> None:
    validate(payload, "gate-rule", error_code=OdgErrorCode.RULE_TABLE_UNAVAILABLE)
