"""Minimal JSON Schema (draft 2020-12) validator for the ORT contracts.

Pure stdlib. Supports the subset actually used by the ORT schemas:
  type / properties / additionalProperties(false) / required / enum / const /
  pattern / minLength / maxLength / minItems / maxItems / items / allOf /
  anyOf / $defs / $ref / default (ignored).

Enough to enforce input/output/finding contracts offline, deterministically.
"""

from __future__ import annotations

import re
from typing import Any


class SchemaError(Exception):
    pass


def _resolve(ref: str, root: dict) -> dict:
    if not ref.startswith("#/"):
        raise SchemaError(f"unsupported $ref {ref!r}")
    node: Any = root
    for part in ref[2:].split("/"):
        part = part.replace("~1", "/").replace("~0", "~")
        if not isinstance(node, dict) or part not in node:
            raise SchemaError(f"cannot resolve $ref {ref!r}")
        node = node[part]
    if not isinstance(node, dict):
        raise SchemaError(f"$ref {ref!r} did not resolve to an object")
    return node


def validate(value: Any, schema: dict, root: dict | None = None) -> list[str]:
    root = root or schema
    issues: list[str] = []

    if "$ref" in schema:
        target = _resolve(schema["$ref"], root)
        return validate(value, target, root)

    if "allOf" in schema:
        for sub in schema["allOf"]:
            issues.extend(validate(value, sub, root))
        return issues

    if "anyOf" in schema:
        sub_results = [validate(value, sub, root) for sub in schema["anyOf"]]
        if not any(not r for r in sub_results):
            issues.append("value does not satisfy any branch of anyOf")
        return issues

    expected = schema.get("type")
    if expected == "string":
        if not isinstance(value, str):
            issues.append("expected string")
        else:
            if "minLength" in schema and len(value) < schema["minLength"]:
                issues.append(f"string shorter than minLength {schema['minLength']}")
            if "maxLength" in schema and len(value) > schema["maxLength"]:
                issues.append(f"string longer than maxLength {schema['maxLength']}")
            if "pattern" in schema and not re.search(schema["pattern"], value):
                issues.append(f"string does not match pattern {schema['pattern']!r}")
    elif expected == "integer":
        if isinstance(value, bool) or not isinstance(value, int):
            issues.append("expected integer")
    elif expected == "number":
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            issues.append("expected number")
    elif expected == "boolean":
        if not isinstance(value, bool):
            issues.append("expected boolean")
    elif expected == "array":
        if not isinstance(value, list):
            issues.append("expected array")
        else:
            if "minItems" in schema and len(value) < schema["minItems"]:
                issues.append(f"array shorter than minItems {schema['minItems']}")
            if "maxItems" in schema and len(value) > schema["maxItems"]:
                issues.append(f"array longer than maxItems {schema['maxItems']}")
            if "items" in schema:
                for i, item in enumerate(value):
                    issues.extend(f"items[{i}]: {e}" for e in validate(item, schema["items"], root))
    elif expected == "object" or "properties" in schema or "additionalProperties" in schema:
        if not isinstance(value, dict):
            issues.append("expected object")
            return issues
        props = schema.get("properties", {})
        for key in schema.get("required", []):
            if key not in value:
                issues.append(f"missing required property {key!r}")
        for key, val in value.items():
            if key in props:
                issues.extend(f"{key}: {e}" for e in validate(val, props[key], root))
            elif schema.get("additionalProperties") is False:
                issues.append(f"additional property {key!r} not allowed")
    elif expected is None:
        # no type constraint
        pass
    else:
        # unknown type keyword — be permissive on structure, strict on strings
        if isinstance(value, str) and "enum" in schema:
            pass

    if "enum" in schema and value not in schema["enum"]:
        issues.append(f"value not in enum {schema['enum']}")
    if "const" in schema and value != schema["const"]:
        issues.append(f"value != const {schema['const']!r}")

    return issues


def validate_with_schema(value: Any, schema: dict) -> list[str]:
    return validate(value, schema, schema)
