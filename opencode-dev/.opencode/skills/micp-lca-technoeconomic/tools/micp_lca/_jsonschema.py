"""A small draft-07 JSON-Schema subset validator (offline, stdlib-only).

Supports the keywords used by the skill contracts: type, properties,
required, additionalProperties, enum, const, pattern, minLength, maxLength,
minimum, maximum, minItems, items, $ref (local), anyOf, oneOf, allOf, format.
Unknown keywords are ignored (per spec). Used by `cli.py validate` and by the
service self-check, and as a fallback when the `jsonschema` package is absent
(the repo tools must never hard-depend on it).
"""

from __future__ import annotations

import re
from typing import Any


class _RefResolver:
    def __init__(self, root: dict):
        self.root = root

    def resolve(self, ref: str) -> Any:
        if not ref.startswith("#"):
            return None  # external refs unsupported
        parts = [p for p in ref[1:].split("/") if p]
        node: Any = self.root
        for part in parts:
            if isinstance(node, dict):
                node = node.get(part.replace("~1", "/").replace("~0", "~"))
            else:
                return None
            if node is None:
                return None
        return node


def _type_ok(value: Any, t: str) -> bool:
    if t == "object":
        return isinstance(value, dict)
    if t == "array":
        return isinstance(value, list)
    if t == "string":
        return isinstance(value, str)
    if t == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if t == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if t == "boolean":
        return isinstance(value, bool)
    if t == "null":
        return value is None
    return True


def validate(value: Any, schema: Any, resolver: _RefResolver, path: str = "$",
             issues: list[dict] | None = None) -> list[dict]:
    issues = issues if issues is not None else []

    if isinstance(schema, bool):
        if not schema:
            issues.append({"path": path, "message": "schema is false"})
        return issues

    if not isinstance(schema, dict):
        return issues

    # $ref first
    ref = schema.get("$ref")
    if ref:
        target = resolver.resolve(ref)
        if target is not None:
            validate(value, target, resolver, path, issues)
            return issues
        issues.append({"path": path, "message": f"unresolved $ref {ref}"})
        return issues

    for kw in ("allOf", "anyOf", "oneOf"):
        if kw in schema:
            subs = schema[kw]
            if kw == "allOf":
                for s in subs:
                    validate(value, s, resolver, path, issues)
            elif kw == "anyOf":
                matched = any(not validate(value, s, resolver, path, []) for s in subs)
                if not matched:
                    issues.append({"path": path, "message": "matches no anyOf branch"})
            elif kw == "oneOf":
                matched = sum(1 for s in subs if not validate(value, s, resolver, path, []))
                if matched != 1:
                    issues.append({"path": path, "message": f"oneOf matched {matched} branches"})

    if "type" in schema:
        types = schema["type"] if isinstance(schema["type"], list) else [schema["type"]]
        if not any(_type_ok(value, t) for t in types):
            issues.append({"path": path, "message": f"expected type {schema['type']}, got {type(value).__name__}"})

    if "const" in schema and value != schema["const"]:
        issues.append({"path": path, "message": f"const mismatch: {value!r} != {schema['const']!r}"})

    if "enum" in schema and value not in schema["enum"]:
        issues.append({"path": path, "message": f"{value!r} not in enum"})

    if isinstance(value, str):
        if "minLength" in schema and len(value) < schema["minLength"]:
            issues.append({"path": path, "message": f"string shorter than {schema['minLength']}"})
        if "maxLength" in schema and len(value) > schema["maxLength"]:
            issues.append({"path": path, "message": f"string longer than {schema['maxLength']}"})
        if "pattern" in schema and not re.search(schema["pattern"], value):
            issues.append({"path": path, "message": f"string does not match pattern {schema['pattern']}"})

    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if "minimum" in schema and value < schema["minimum"]:
            issues.append({"path": path, "message": f"{value} < minimum {schema['minimum']}"})
        if "maximum" in schema and value > schema["maximum"]:
            issues.append({"path": path, "message": f"{value} > maximum {schema['maximum']}"})

    if isinstance(value, list):
        if "minItems" in schema and len(value) < schema["minItems"]:
            issues.append({"path": path, "message": f"fewer than {schema['minItems']} items"})
        if "items" in schema:
            item_schema = schema["items"]
            if isinstance(item_schema, list):
                for i, v in enumerate(value):
                    if i < len(item_schema):
                        validate(v, item_schema[i], resolver, f"{path}[{i}]", issues)
            else:
                for i, v in enumerate(value):
                    validate(v, item_schema, resolver, f"{path}[{i}]", issues)

    if isinstance(value, dict):
        props = schema.get("properties", {})
        for key, subschema in props.items():
            if key in value:
                validate(value[key], subschema, resolver, f"{path}.{key}", issues)
        required = schema.get("required", [])
        for key in required:
            if key not in value:
                issues.append({"path": path, "message": f"missing required property {key!r}"})
        if schema.get("additionalProperties") is False:
            allowed = set(props) | set(schema.get("patternProperties", {}).keys())
            for key in value:
                if key not in allowed:
                    issues.append({"path": path, "message": f"additional property {key!r} not allowed"})

    return issues


def validate_json(value: Any, schema: dict) -> list[dict]:
    return validate(value, schema, _RefResolver(schema))
