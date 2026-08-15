"""Minimal JSON Schema (draft 2020-12) subset validator for
micp-experiment-designer.

Mirrors the task-decomposer convention: a small, auditable validator that runs
on a bare Python interpreter, with `$ref` limited to `$defs` inside the same
document. Every schema the skill ships is written against this subset; the
subset itself is exercised by tests.

Supported keywords:
  $schema $id $comment title description type enum const required properties
  additionalProperties patternProperties items minItems maxItems uniqueItems
  minLength maxLength pattern minimum maximum exclusiveMinimum exclusiveMaximum
  multipleOf anyOf oneOf allOf not $ref($defs-only) default(ignored)

Anything outside this subset is a skill bug (caught by tests).
"""

from __future__ import annotations

import json
import math
import re
from typing import Any

from ._common import ToolError


class ValidationIssue:
    __slots__ = ("path", "message")

    def __init__(self, path: str, message: str):
        self.path = path
        self.message = message

    def as_dict(self) -> dict[str, str]:
        return {"path": self.path, "message": self.message}


def _as_list(v: Any) -> list[Any]:
    return v if isinstance(v, list) else [v]


class _Validator:
    def __init__(self, schema: dict[str, Any]):
        self.schema = schema
        self.defs = schema.get("$defs", {}) if isinstance(schema, dict) else {}

    def validate(self, instance: Any, schema: dict[str, Any], path: str) -> list[ValidationIssue]:
        issues: list[ValidationIssue] = []
        schema = schema or {}

        if "$ref" in schema:
            ref = schema["$ref"]
            if not ref.startswith("#/$defs/"):
                raise ToolError("E_SCHEMA_REF", f"unsupported $ref '{ref}': only #/$defs/ allowed",
                                details={"ref": ref})
            name = ref.split("/")[-1]
            if name not in self.defs:
                raise ToolError("E_SCHEMA_REF", f"$ref target '{name}' not found in $defs",
                                details={"ref": ref})
            issues.extend(self.validate(instance, self.defs[name], path))

        if "type" in schema:
            t = schema["type"]
            ok = {"object": isinstance(instance, dict),
                  "array": isinstance(instance, list),
                  "string": isinstance(instance, str),
                  "number": isinstance(instance, (int, float)) and not isinstance(instance, bool),
                  "integer": isinstance(instance, int) and not isinstance(instance, bool),
                  "boolean": isinstance(instance, bool),
                  "null": instance is None}[t]
            if not ok:
                issues.append(ValidationIssue(path, f"expected type {t}, got {type(instance).__name__}"))

        if "enum" in schema and not any(instance == e for e in schema["enum"]):
            issues.append(ValidationIssue(path, f"value not in enum {schema['enum']}"))
        if "const" in schema and instance != schema["const"]:
            issues.append(ValidationIssue(path, f"expected const {schema['const']}"))

        if "format" in schema and schema["format"] == "date-time":
            if not isinstance(instance, str) or not _is_datetime(instance):
                issues.append(ValidationIssue(path, f"not a valid date-time: {instance!r}"))

        if "oneOf" in schema:
            matched = sum(1 for s in schema["oneOf"] if not self.validate(instance, s, path))
            if matched != 1:
                issues.append(ValidationIssue(path, f"must match exactly one of oneOf (matched {matched})"))

        if "anyOf" in schema:
            if not any(not self.validate(instance, s, path) for s in schema["anyOf"]):
                issues.append(ValidationIssue(path, "must match at least one of anyOf"))

        if "allOf" in schema:
            for s in schema["allOf"]:
                issues.extend(self.validate(instance, s, path))

        if "not" in schema and not self.validate(instance, schema["not"], path):
            issues.append(ValidationIssue(path, "must not match 'not' schema"))

        if isinstance(instance, dict):
            self._validate_object(instance, schema, path, issues)
        elif isinstance(instance, list):
            self._validate_array(instance, schema, path, issues)
        elif isinstance(instance, str):
            self._validate_string(instance, schema, path, issues)
        elif isinstance(instance, (int, float)) and not isinstance(instance, bool):
            self._validate_number(instance, schema, path, issues)

        return issues

    def _validate_object(self, instance: dict, schema: dict[str, Any], path: str,
                         issues: list[ValidationIssue]) -> None:
        props = schema.get("properties", {})
        required = schema.get("required", [])
        for name in required:
            if name not in instance:
                issues.append(ValidationIssue(path, f"missing required property '{name}'"))
        for name, subschema in props.items():
            if name in instance:
                issues.extend(self.validate(instance[name], subschema, f"{path}.{name}"))
        if schema.get("additionalProperties") is False:
            allowed = set(props)
            for name in instance:
                if name not in allowed:
                    issues.append(ValidationIssue(path, f"additional property '{name}' not allowed"))
        for pattern, subschema in schema.get("patternProperties", {}).items():
            for name, value in instance.items():
                if re.search(pattern, name):
                    issues.extend(self.validate(value, subschema, f"{path}.{name}"))

    def _validate_array(self, instance: list, schema: dict[str, Any], path: str,
                        issues: list[ValidationIssue]) -> None:
        if "minItems" in schema and len(instance) < schema["minItems"]:
            issues.append(ValidationIssue(path, f"array shorter than minItems {schema['minItems']}"))
        if "maxItems" in schema and len(instance) > schema["maxItems"]:
            issues.append(ValidationIssue(path, f"array longer than maxItems {schema['maxItems']}"))
        if schema.get("uniqueItems"):
            seen = set()
            for i, item in enumerate(instance):
                key = json.dumps(item, sort_keys=True, default=str)
                if key in seen:
                    issues.append(ValidationIssue(f"{path}[{i}]", "duplicate item"))
                seen.add(key)
        items = schema.get("items")
        if isinstance(items, dict):
            for i, item in enumerate(instance):
                issues.extend(self.validate(item, items, f"{path}[{i}]"))
        elif isinstance(items, list):
            for i, item in enumerate(instance[: len(items)]):
                issues.extend(self.validate(item, items[i], f"{path}[{i}]"))

    def _validate_string(self, instance: str, schema: dict[str, Any], path: str,
                         issues: list[ValidationIssue]) -> None:
        if "minLength" in schema and len(instance) < schema["minLength"]:
            issues.append(ValidationIssue(path, f"string shorter than minLength {schema['minLength']}"))
        if "maxLength" in schema and len(instance) > schema["maxLength"]:
            issues.append(ValidationIssue(path, f"string longer than maxLength {schema['maxLength']}"))
        if "pattern" in schema and not re.search(schema["pattern"], instance):
            issues.append(ValidationIssue(path, f"does not match pattern {schema['pattern']}"))

    def _validate_number(self, instance: float, schema: dict[str, Any], path: str,
                         issues: list[ValidationIssue]) -> None:
        if not math.isfinite(instance):
            issues.append(ValidationIssue(path, "number must be finite"))
        if "minimum" in schema and instance < schema["minimum"]:
            issues.append(ValidationIssue(path, f"number < minimum {schema['minimum']}"))
        if "maximum" in schema and instance > schema["maximum"]:
            issues.append(ValidationIssue(path, f"number > maximum {schema['maximum']}"))
        if "exclusiveMinimum" in schema and instance <= schema["exclusiveMinimum"]:
            issues.append(ValidationIssue(path, f"number <= exclusiveMinimum {schema['exclusiveMinimum']}"))
        if "exclusiveMaximum" in schema and instance >= schema["exclusiveMaximum"]:
            issues.append(ValidationIssue(path, f"number >= exclusiveMaximum {schema['exclusiveMaximum']}"))
        if "multipleOf" in schema:
            m = schema["multipleOf"]
            if m and abs(instance / m - round(instance / m)) > 1e-9:
                issues.append(ValidationIssue(path, f"number is not a multiple of {m}"))


def _is_datetime(s: str) -> bool:
    # Loose ISO-8601: YYYY-MM-DD[T ]HH:MM:SS[.fff](Z|±HH:MM)
    return bool(re.match(
        r"^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:?\d{2})?$", s))


def validate(instance: Any, schema: dict[str, Any]) -> list[ValidationIssue]:
    """Validate `instance` against `schema`; returns a list of issues (empty = valid)."""
    if not isinstance(schema, dict):
        raise ToolError("E_SCHEMA", "schema must be an object")
    v = _Validator(schema)
    issues = v.validate(instance, schema, "$")
    # top-level required
    if isinstance(schema, dict):
        required = schema.get("required", [])
        if isinstance(instance, dict):
            for name in required:
                if name not in instance:
                    issues.append(ValidationIssue("$", f"missing required property '{name}'"))
    return issues


def validate_document(instance: Any, schema: dict[str, Any]) -> dict[str, Any]:
    """Wrapper returning a machine-readable report (used by the validate tool)."""
    issues = validate(instance, schema)
    return {
        "valid": len(issues) == 0,
        "errors": [i.as_dict() for i in issues],
    }
