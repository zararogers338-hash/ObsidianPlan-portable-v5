"""Minimal JSON Schema (draft 2020-12 subset) validator + envelope self-check.

This mirrors the design of the OSR skill's `jsonschema.ts`: a deliberately
small, dependency-free validator supporting exactly the keywords this
repository's schemas use, so the whole skill is offline-testable and never
requires the `jsonschema` package on the critical path.

Supported keywords:
  type, required, properties, additionalProperties, items, enum, const,
  pattern, minLength, maxLength, minimum, maximum, exclusiveMinimum,
  minItems, maxItems, anyOf, oneOf, allOf, $ref (local "#/$defs/..." only),
  format (annotation only, never rejects).
Unknown keywords are ignored (annotation behavior). `format` is accepted but
not enforced, matching OSR.
"""

from __future__ import annotations

import os
import re
from typing import Any

# JSON Schema types -> python callables
_TYPE_CHECKERS: dict[str, Any] = {
    "string": lambda v: isinstance(v, str),
    "number": lambda v: isinstance(v, (int, float)) and not isinstance(v, bool),
    "integer": lambda v: isinstance(v, int) and not isinstance(v, bool),
    "boolean": lambda v: isinstance(v, bool),
    "object": lambda v: isinstance(v, dict),
    "array": lambda v: isinstance(v, list),
    "null": lambda v: v is None,
}


def _is_object(v: Any) -> bool:
    return isinstance(v, dict)


def _resolve_ref(root: dict[str, Any], ref: str) -> dict[str, Any] | None:
    if not ref.startswith("#/"):
        return None  # remote refs unsupported by design
    parts = ref[2:].split("/")
    node: Any = root
    for part in parts:
        if not _is_object(node):
            return None
        node = node.get(_unescape(part))
    return node if _is_object(node) else None


def _unescape(token: str) -> str:
    return token.replace("~1", "/").replace("~0", "~")


def _type_matches(value: Any, expected: str | list[str]) -> bool:
    names = expected if isinstance(expected, list) else [expected]
    return any(_TYPE_CHECKERS.get(t, lambda _v: False)(value) for t in names)


class ValidationIssue:
    __slots__ = ("path", "message")

    def __init__(self, path: str, message: str) -> None:
        self.path = path
        self.message = message

    def to_dict(self) -> dict[str, str]:
        return {"path": self.path, "message": self.message}


def validate_into(
    value: Any,
    schema: Any,
    root: dict[str, Any],
    path: str,
    issues: list[ValidationIssue],
    seen: set[str],
) -> None:
    if schema is True:
        return
    if schema is False:
        issues.append(ValidationIssue(path, "value rejected by `false` schema"))
        return
    if not _is_object(schema):
        return

    # $ref (cycle guard)
    ref = schema.get("$ref")
    if isinstance(ref, str):
        if ref in seen:
            return
        target = _resolve_ref(root, ref)
        if target is None:
            issues.append(ValidationIssue(path, f"unresolvable $ref: {ref}"))
            return
        validate_into(value, target, root, path, issues, seen | {ref})

    # enum / const
    enum = schema.get("enum")
    if isinstance(enum, list) and not any(_json_eq(e, value) for e in enum):
        issues.append(ValidationIssue(path, f"value not in enum: {enum}"))
    if "const" in schema and not _json_eq(schema["const"], value):
        issues.append(ValidationIssue(path, f"value does not equal const {schema['const']}"))

    # type
    typ = schema.get("type")
    if typ is not None:
        if not isinstance(typ, (str, list)):
            issues.append(ValidationIssue(path, "invalid `type` keyword in schema"))
        elif not _type_matches(value, typ):
            issues.append(ValidationIssue(
                path,
                f"expected type {typ}, got {_type_name(value)}",
            ))
            return  # deeper checks meaningless on type mismatch

    # strings
    if isinstance(value, str):
        min_len = schema.get("minLength")
        max_len = schema.get("maxLength")
        if isinstance(min_len, int) and len(value) < min_len:
            issues.append(ValidationIssue(path, f"string shorter than minLength {min_len}"))
        if isinstance(max_len, int) and len(value) > max_len:
            issues.append(ValidationIssue(path, f"string longer than maxLength {max_len}"))
        pattern = schema.get("pattern")
        if isinstance(pattern, str):
            try:
                if re.search(pattern, value) is None:
                    issues.append(ValidationIssue(path, f"string does not match pattern {pattern}"))
            except re.error:
                issues.append(ValidationIssue(path, f"invalid pattern in schema: {pattern}"))

    # numbers
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        minimum = schema.get("minimum")
        maximum = schema.get("maximum")
        if isinstance(minimum, (int, float)) and value < minimum:
            issues.append(ValidationIssue(path, f"number below minimum {minimum}"))
        if isinstance(maximum, (int, float)) and value > maximum:
            issues.append(ValidationIssue(path, f"number above maximum {maximum}"))
        ex_min = schema.get("exclusiveMinimum")
        ex_max = schema.get("exclusiveMaximum")
        if isinstance(ex_min, (int, float)) and value <= ex_min:
            issues.append(ValidationIssue(path, f"number not above exclusiveMinimum {ex_min}"))
        if isinstance(ex_max, (int, float)) and value >= ex_max:
            issues.append(ValidationIssue(path, f"number not below exclusiveMaximum {ex_max}"))

    # arrays
    if isinstance(value, list):
        min_items = schema.get("minItems")
        max_items = schema.get("maxItems")
        if isinstance(min_items, int) and len(value) < min_items:
            issues.append(ValidationIssue(path, f"array shorter than minItems {min_items}"))
        if isinstance(max_items, int) and len(value) > max_items:
            issues.append(ValidationIssue(path, f"array longer than maxItems {max_items}"))
        items = schema.get("items")
        if _is_object(items):
            for idx, item in enumerate(value):
                validate_into(item, items, root, f"{path}/{idx}", issues, seen)

    # objects
    if _is_object(value):
        required = schema.get("required")
        if isinstance(required, list):
            for key in required:
                if key not in value:
                    issues.append(ValidationIssue(path, f'missing required property "{key}"'))
        props = schema.get("properties", {})
        if _is_object(props):
            for key, prop_schema in props.items():
                if key in value:
                    validate_into(value[key], prop_schema, root, f"{path}/{key}", issues, seen)
        addl = schema.get("additionalProperties")
        if addl is False:
            for key in value:
                if key not in props:
                    issues.append(ValidationIssue(path, f'additional property "{key}" not allowed'))
        elif _is_object(addl):
            for key in value:
                if key not in props:
                    validate_into(value[key], addl, root, f"{path}/{key}", issues, seen)

    # combinators
    if isinstance(schema.get("allOf"), list):
        for sub in schema["allOf"]:
            validate_into(value, sub, root, path, issues, set(seen))
    if isinstance(schema.get("anyOf"), list):
        if not any(validate(value, sub, root) == [] for sub in schema["anyOf"]):
            issues.append(ValidationIssue(path, "value matches none of the anyOf branches"))
    if isinstance(schema.get("oneOf"), list):
        matches = [sub for sub in schema["oneOf"] if validate(value, sub, root) == []]
        if len(matches) != 1:
            issues.append(ValidationIssue(
                path,
                f"value matches {len(matches)} oneOf branches (expected exactly 1)",
            ))
    if _is_object(schema.get("not")):
        if validate(value, schema["not"], root) == []:
            issues.append(ValidationIssue(path, "value matches the `not` schema"))


def validate(value: Any, schema: Any, root: dict[str, Any] | None = None) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    root_schema = root if root is not None else schema
    if not _is_object(root_schema):
        return issues
    validate_into(value, schema, root_schema, "", issues, set())
    return issues


def _json_eq(a: Any, b: Any) -> bool:
    try:
        import json
        return json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)
    except (TypeError, ValueError):
        return a == b


def _type_name(value: Any) -> str:
    if isinstance(value, list):
        return "array"
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    return type(value).__name__


# ---------------------------------------------------------------------------
# schema loading (cached)
# ---------------------------------------------------------------------------

_SCHEMA_CACHE: dict[str, dict[str, Any]] = {}

# <skill root> = <module dir>/../..  (tools/mmpi/validate.py -> skill root)
_SKILL_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def load_schema(kind: str, schema_dir: str | None = None) -> dict[str, Any]:
    """Load schemas/input.schema.json or schemas/output.schema.json (cached).

    Resolves relative to the skill root unless schema_dir is given (tests may
    pass a temp dir). Falls back gracefully when the file is missing so the
    tool can still self-report a contract error rather than crashing.
    """
    import json

    if kind in _SCHEMA_CACHE:
        return _SCHEMA_CACHE[kind]

    if schema_dir is None:
        schema_dir = os.path.join(_SKILL_ROOT, "schemas")
    path = os.path.join(schema_dir, f"{kind}.schema.json")
    if not os.path.isfile(path):
        raise FileNotFoundError(f"schema file not found: {path}")
    with open(path, "r", encoding="utf-8") as fh:
        schema: dict[str, Any] = json.load(fh)
    _SCHEMA_CACHE[kind] = schema
    return schema


def validate_input(payload: Any, schema_dir: str | None = None) -> list[ValidationIssue]:
    schema = load_schema("input", schema_dir)
    return validate(payload, schema)


def validate_output(payload: Any, schema_dir: str | None = None) -> list[ValidationIssue]:
    schema = load_schema("output", schema_dir)
    return validate(payload, schema)
