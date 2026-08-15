"""Minimal JSON-Schema subset validator for micp-hypothesis-forge.

Implements the subset the skill's schemas actually use (draft-07 keywords):
  type, required, additionalProperties, properties, items, enum, const,
  minLength, maxLength, pattern, minimum, maximum, default, oneOf, $ref
  (same-schema-only), $schema/$id ignored.

Path-safe: `schema` may be a filename relative to the skill root OR an inline
schema object. Filename resolution is sandboxed to the skill directory
(E_PATH_ESCAPE on traversal). Offline, deterministic, stdlib-only.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

# Skill root = this file's parent's parent's parent
# (…/skills/micp-hypothesis-forge/tools/mhfx/jsonschema.py -> …/micp-hypothesis-forge)
SKILL_ROOT = Path(__file__).resolve().parent.parent.parent

SUPPORTED_KEYWORDS = (
    "type", "required", "additionalProperties", "properties", "items",
    "enum", "const", "minLength", "maxLength", "pattern", "minimum",
    "maximum", "default", "oneOf", "$ref",
)


class SchemaError(Exception):
    """Raised on schema loading/validation problems that are the caller's fault."""

    def __init__(self, code: str, message: str, details: dict | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}


def _load_schema(schema: Any) -> dict:
    if isinstance(schema, dict):
        return schema
    if isinstance(schema, str):
        raw_path = Path(schema)
        if raw_path.is_absolute() or ".." in raw_path.parts:
            raise SchemaError("E_PATH_ESCAPE",
                              f"schema path escapes the skill directory: {schema!r}")
        candidate = (SKILL_ROOT / schema).resolve()
        if not str(candidate).startswith(str(SKILL_ROOT.resolve())):
            raise SchemaError("E_PATH_ESCAPE",
                              f"schema path escapes the skill directory: {schema!r}")
        if not candidate.is_file():
            raise SchemaError("E_SCHEMA_NOT_FOUND",
                              f"schema file not found: {candidate}")
        try:
            return json.loads(candidate.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise SchemaError("E_SCHEMA_CORRUPT",
                              f"schema file is not valid JSON: {candidate}: {exc}") from exc
    raise SchemaError("E_SCHEMA_TYPE", "schema must be an object or a relative filename")


def _type_ok(value: Any, expected: str) -> bool:
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
    return True  # unknown type keyword: ignore


def validate_document(document: Any, schema: Any, _path: str = "$") -> list[dict]:
    """Return a list of {path, message} errors; empty list = valid."""
    try:
        root = _load_schema(schema)
    except SchemaError as exc:
        return [{"path": _path, "message": f"{exc.code}: {exc.message}"}]

    errors: list[dict] = []
    stack: list[tuple[Any, dict, str]] = [(document, root, _path)]

    while stack:
        value, node, path = stack.pop()

        # $ref (same-document only; we resolve top-level definitions)
        ref = node.get("$ref")
        if isinstance(ref, str):
            if ref.startswith("#/$defs/"):
                key = ref.split("/")[-1]
                target = root.get("$defs", {}).get(key)
            elif ref.startswith("#/definitions/"):
                key = ref.split("/")[-1]
                target = root.get("definitions", {}).get(key)
            elif ref == "#":
                target = root
            else:
                errors.append({"path": path, "message": f"unsupported $ref {ref!r}"})
                continue
            if not isinstance(target, dict):
                errors.append({"path": path, "message": f"unresolved $ref {ref!r}"})
                continue
            node = target

        # oneOf
        if "oneOf" in node:
            subschemas = node["oneOf"]
            if not isinstance(subschemas, list) or not subschemas:
                errors.append({"path": path, "message": "oneOf must be a non-empty array"})
                continue
            matches = 0
            for sub in subschemas:
                if not validate_document(value, sub, path):
                    matches += 1
            if matches != 1:
                errors.append({"path": path,
                               "message": f"must match exactly one of oneOf (got {matches})"})
                continue

        # type
        if "type" in node:
            expected = node["type"]
            types = expected if isinstance(expected, list) else [expected]
            if not any(_type_ok(value, t) for t in types):
                errors.append({"path": path,
                               "message": f"expected type {expected}, got {type(value).__name__}"})
                continue  # type failure: skip deeper structural checks on wrong type

        if isinstance(value, dict):
            # required
            for key in node.get("required", []):
                if key not in value:
                    errors.append({"path": f"{path}.{key}", "message": "is required"})
            # additionalProperties / properties
            props = node.get("properties", {})
            allowed = set(props) | set(node.get("required", []))
            if node.get("additionalProperties") is False:
                for key in value:
                    if key not in allowed and key not in props:
                        errors.append({"path": f"{path}.{key}",
                                       "message": "additional property not allowed"})
            for key, sub in props.items():
                if key in value:
                    stack.append((value[key], sub, f"{path}.{key}"))

        elif isinstance(value, list):
            items = node.get("items")
            if isinstance(items, dict):
                for i, item in enumerate(value):
                    stack.append((item, items, f"{path}[{i}]"))

        # scalar constraints
        if isinstance(value, str):
            if "minLength" in node and len(value) < node["minLength"]:
                errors.append({"path": path,
                               "message": f"length {len(value)} < minLength {node['minLength']}"})
            if "maxLength" in node and len(value) > node["maxLength"]:
                errors.append({"path": path,
                               "message": f"length {len(value)} > maxLength {node['maxLength']}"})
            if "pattern" in node and not re.match(node["pattern"], value):
                errors.append({"path": path, "message": f"does not match {node['pattern']!r}"})
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            if "minimum" in node and value < node["minimum"]:
                errors.append({"path": path, "message": f"{value} < minimum {node['minimum']}"})
            if "maximum" in node and value > node["maximum"]:
                errors.append({"path": path, "message": f"{value} > maximum {node['maximum']}"})

        # enum / const
        if "enum" in node and value not in node["enum"]:
            errors.append({"path": path,
                           "message": f"must be one of {node['enum']}, got {value!r}"})
        if "const" in node and value != node["const"]:
            errors.append({"path": path, "message": f"must equal {node['const']!r}"})

    return errors


def validate_schema(document: Any, schema: Any) -> dict:
    """Convenience wrapper returning {'valid': bool, 'errors': [...]}."""
    errors = validate_document(document, schema)
    return {"valid": not errors, "errors": errors}
