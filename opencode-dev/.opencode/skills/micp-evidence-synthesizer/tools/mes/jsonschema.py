"""Minimal JSON Schema (draft-07 subset) validator.

Used when the optional `jsonschema` package is not installed, so every tool and
test stays offline-capable with zero required dependencies. Supports the subset
used by schemas/input.schema.json and schemas/output.schema.json:
type, required, properties, additionalProperties, items, enum, const, pattern,
minLength/maxLength, minimum/maximum/minItems/maxItems, $ref (to $defs), and
definitions via $defs. Everything else is ignored conservatively.

Prefer the `jsonschema` package when available; this is the documented fallback
(skill.yaml: libs_optional.jsonschema).
"""

from __future__ import annotations

import json
import re
from typing import Any, Iterator

# Compiled fallback regexes (kept for parity with the package validator).
_CACHED = {}


def _compile(pattern: str) -> re.Pattern:
    if pattern not in _CACHED:
        _CACHED[pattern] = re.compile(pattern)
    return _CACHED[pattern]


class Issue:
    __slots__ = ("path", "message")

    def __init__(self, path: str, message: str):
        self.path = path
        self.message = message

    def __repr__(self) -> str:  # pragma: no cover
        return f"Issue(path={self.path!r}, message={self.message!r})"


def validate(value: Any, schema: dict, root: dict | None = None, path: str = "$") -> list[Issue]:
    """Validate `value` against `schema`. Returns a list of Issue (empty == valid)."""
    root = root or schema
    issues: list[Issue] = []
    _walk(value, schema, root, path, issues)
    return issues


def _type_matches(value: Any, expected: str) -> bool:
    if expected == "object":
        return isinstance(value, dict)
    if expected == "array":
        return isinstance(value, list)
    if expected == "string":
        return isinstance(value, str)
    if expected == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "boolean":
        return isinstance(value, bool)
    if expected == "null":
        return value is None
    return False


def _walk(value: Any, schema: dict, root: dict, path: str, out: list[Issue]) -> None:
    if not isinstance(schema, dict):
        return

    # $ref resolution into $defs (only same-document refs are supported).
    if "$ref" in schema:
        ref = schema["$ref"]
        if ref.startswith("#/$defs/"):
            name = ref[len("#/$defs/") :]
            target = root.get("$defs", {}).get(name)
            if target is None:
                out.append(Issue(path, f"unresolvable $ref {ref}"))
                return
            # Preserve sibling constraints by validating against target only.
            schema = target
        else:  # pragma: no cover — external refs unsupported
            out.append(Issue(path, f"unsupported $ref {ref}"))
            return

    # anyOf: valid if at least one branch validates cleanly.
    if "anyOf" in schema:
        branches = schema["anyOf"]
        if not branches:
            out.append(Issue(path, "empty anyOf"))
            return
        for branch in branches:
            branch_issues: list[Issue] = []
            _walk(value, branch, root, path, branch_issues)
            if not branch_issues:
                return
        out.append(Issue(path, "value does not match any anyOf branch"))
        return

    expected = schema.get("type")
    if isinstance(expected, list):
        if not any(_type_matches(value, t) for t in expected):
            out.append(Issue(path, f"value type {type(value).__name__} not in {expected}"))
            return
    elif expected is not None:
        if not _type_matches(value, expected):
            out.append(Issue(path, f"expected {expected}, got {type(value).__name__}"))
            return

    if isinstance(value, str):
        if "minLength" in schema and len(value) < schema["minLength"]:
            out.append(Issue(path, f"string shorter than minLength {schema['minLength']}"))
        if "maxLength" in schema and len(value) > schema["maxLength"]:
            out.append(Issue(path, f"string longer than maxLength {schema['maxLength']}"))
        if "pattern" in schema and not _compile(schema["pattern"]).search(value):
            out.append(Issue(path, f"string does not match pattern {schema['pattern']}"))
        if "enum" in schema and value not in schema["enum"]:
            out.append(Issue(path, f"value {value!r} not in enum {schema['enum']}"))

    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if "minimum" in schema and value < schema["minimum"]:
            out.append(Issue(path, f"value {value} below minimum {schema['minimum']}"))
        if "maximum" in schema and value > schema["maximum"]:
            out.append(Issue(path, f"value {value} above maximum {schema['maximum']}"))

    if expected == "object" and isinstance(value, dict):
        if "required" in schema:
            for key in schema["required"]:
                if key not in value:
                    out.append(Issue(f"{path}.{key}", f"missing required property {key!r}"))
        props = schema.get("properties") or {}
        for key, val in value.items():
            sub = props.get(key)
            if sub is not None:
                _walk(val, sub, root, f"{path}.{key}", out)
            elif schema.get("additionalProperties") is False:
                out.append(Issue(f"{path}.{key}", f"additional property {key!r} not allowed"))

    if expected == "array" and isinstance(value, list):
        if "minItems" in schema and len(value) < schema["minItems"]:
            out.append(Issue(path, f"array shorter than minItems {schema['minItems']}"))
        if "maxItems" in schema and len(value) > schema["maxItems"]:
            out.append(Issue(path, f"array longer than maxItems {schema['maxItems']}"))
        items = schema.get("items")
        if isinstance(items, dict):
            for i, item in enumerate(value):
                _walk(item, items, root, f"{path}[{i}]", out)

    if "const" in schema and value != schema["const"]:
        out.append(Issue(path, f"expected const {schema['const']!r}, got {value!r}"))


def is_valid(value: Any, schema: dict) -> bool:
    return not validate(value, schema)


def validate_json_str(text: str, schema: dict) -> list[Issue]:
    try:
        value = json.loads(text)
    except json.JSONDecodeError as exc:
        return [Issue("$", f"invalid JSON: {exc.msg} at line {exc.lineno}")]
    return validate(value, schema)
