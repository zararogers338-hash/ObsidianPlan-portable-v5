"""Schema-validation adapter (mirrors sibling obsidian-state-manager).

Uses the `jsonschema` package when available (it is in the Obsidian build
environment); falls back to a small built-in validator covering exactly the
JSON-Schema subset our two contract files use (type/properties/required/
enum/pattern/additionalProperties/items/minItems). The fallback keeps the
skill fully functional offline on a bare Python install — the failure mode
is weaker diagnostics, never skipped validation.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from .errors import KgeError, KgeErrorCode

try:  # pragma: no cover - exercised in integration env
    import jsonschema as _js

    _HAVE_JS = True
except Exception:  # pragma: no cover
    _js = None
    _HAVE_JS = False

_SCHEMA_DIR = Path(__file__).resolve().parent.parent.parent / "schemas"


def _load_schema(name: str) -> dict[str, Any]:
    path = _SCHEMA_DIR / name
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise KgeError(KgeErrorCode.TOOL_UNAVAILABLE,
                       f"Contract schema {name} unreadable: {exc}") from exc


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

    stype = schema.get("type")
    if stype:
        types = stype if isinstance(stype, list) else [stype]
        if not any(isinstance(instance, _TYPE_MAP[t]) and not (t in ("integer", "number")
                   and isinstance(instance, bool)) for t in types):
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
    elif isinstance(instance, list):
        if "minItems" in schema and len(instance) < schema["minItems"]:
            errs.append(f"{path}: fewer than {schema['minItems']} items")
        item_schema = schema.get("items")
        if isinstance(item_schema, dict):
            for i, item in enumerate(instance):
                errs.extend(_fallback_validate(item, item_schema, f"{path}[{i}]"))

    if isinstance(instance, str) and "pattern" in schema:
        if not re.fullmatch(schema["pattern"], instance):
            errs.append(f"{path}: {instance!r} does not match pattern {schema['pattern']}")

    return errs


def validate(instance: Any, schema_name: str, *, error_code: KgeErrorCode) -> None:
    """Validate or raise KgeError(error_code) with full violation detail."""
    schema = _load_schema(schema_name)
    if _HAVE_JS:
        validator = _js.validators.validator_for(schema)
        validator.check_schema(schema)
        violations = sorted(validator(schema).iter_errors(instance),
                            key=lambda e: list(e.absolute_path))
        if violations:
            raise KgeError(
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
        raise KgeError(error_code,
                       "; ".join(errs[:10]),
                       detail={"schema": schema_name, "violations": errs[:25],
                               "validator": "builtin-fallback"})


def _coerce_defaults(instance: Any, schema_name: str) -> Any:
    """Apply schema-declared defaults to absent properties (draft-07 semantics
    via jsonschema's extend_with_default). Returns a new object; the caller's
    input is never mutated. No-op on the builtin fallback path (whose schema
    subset does not consult defaults anyway)."""
    if not _HAVE_JS:
        return instance
    schema = _load_schema(schema_name)

    def _extend(validator_cls):
        validate_prop = validator_cls.VALIDATORS["properties"]

        def set_defaults(validator, properties, instance_, schema_):
            if isinstance(instance_, dict):
                for prop, subschema in properties.items():
                    if isinstance(subschema, dict) and "default" in subschema \
                            and prop not in instance_:
                        instance_[prop] = subschema["default"]
            yield from validate_prop(validator, properties, instance_, schema_)

        return _js.validators.extend(validator_cls, {"properties": set_defaults})

    validator_cls = _extend(_js.validators.validator_for(schema))
    import copy
    clone = copy.deepcopy(instance)
    validator_cls(schema).validate(clone)  # raises on violation; caller re-validates for errors
    return clone


def validate_input(payload: Any) -> None:
    validate(payload, "input.schema.json", error_code=KgeErrorCode.INPUT_SCHEMA_VIOLATION)


def coerce_input_defaults(payload: Any) -> Any:
    return _coerce_defaults(payload, "input.schema.json")


def validate_output(payload: Any) -> None:
    validate(payload, "output.schema.json", error_code=KgeErrorCode.OUTPUT_SCHEMA_VIOLATION)
