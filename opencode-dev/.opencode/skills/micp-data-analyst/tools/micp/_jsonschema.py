"""Minimal, auditable JSON Schema (draft 2020-12 subset) validator.

Supported keywords (anything else in a schema is rejected up front):

  $schema $id $comment title description
  type enum const
  required properties additionalProperties patternProperties propertyNames
  items prefixItems minItems maxItems uniqueItems contains
  minLength maxLength pattern
  minimum maximum exclusiveMinimum exclusiveMaximum multipleOf
  anyOf oneOf allOf not
  $ref  (only local refs of the form #/$defs/<name>; recursion allowed)
  $defs

`default`, `format`, `examples`, `readOnly` are accepted but ignored
(annotation-only), matching JSON Schema semantics.
"""

from __future__ import annotations

import re
from typing import Any

from _common import ToolError

_META = {"$schema", "$id", "$comment", "title", "description", "default",
         "format", "examples", "readOnly", "writeOnly", "deprecated"}
_KNOWN = _META | {
    "type", "enum", "const",
    "required", "properties", "additionalProperties", "patternProperties", "propertyNames",
    "items", "prefixItems", "minItems", "maxItems", "uniqueItems", "contains",
    "minLength", "maxLength", "pattern",
    "minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum", "multipleOf",
    "anyOf", "oneOf", "allOf", "not",
    "$ref", "$defs",
}

_TYPES = {"null", "boolean", "object", "array", "number", "integer", "string"}


class SchemaError(ToolError):
    def __init__(self, message: str, *, details: dict | None = None):
        super().__init__("MDA-E900", message, details=details, exit_code=4)


def _check_schema_supported(schema: Any, path: str = "#") -> None:
    if isinstance(schema, bool):
        return
    if not isinstance(schema, dict):
        raise SchemaError(f"schema at {path} must be an object or boolean")
    unknown = set(schema) - _KNOWN
    if unknown:
        raise SchemaError(f"schema at {path} uses unsupported keyword(s): {sorted(unknown)}",
                          details={"path": path, "keywords": sorted(unknown)})
    if "type" in schema:
        t = schema["type"]
        types = t if isinstance(t, list) else [t]
        for one in types:
            if one not in _TYPES:
                raise SchemaError(f"schema at {path} has unknown type {one!r}")
    for key in ("properties", "patternProperties", "$defs"):
        if isinstance(schema.get(key), dict):
            for k, sub in schema[key].items():
                _check_schema_supported(sub, f"{path}/{key}/{k}")
    for key in ("additionalProperties", "items", "contains", "not", "propertyNames"):
        if key in schema:
            _check_schema_supported(schema[key], f"{path}/{key}")
    for key in ("prefixItems",):
        if isinstance(schema.get(key), list):
            for i, sub in enumerate(schema[key]):
                _check_schema_supported(sub, f"{path}/{key}/{i}")
    for key in ("anyOf", "oneOf", "allOf"):
        if isinstance(schema.get(key), list):
            for i, sub in enumerate(schema[key]):
                _check_schema_supported(sub, f"{path}/{key}/{i}")


def _resolve_ref(ref: str, root: dict) -> Any:
    if not ref.startswith("#/$defs/"):
        raise SchemaError(f"only local $defs refs are supported, got {ref!r}")
    node: Any = root
    for part in ref[2:].split("/"):
        if not isinstance(node, dict) or part not in node:
            raise SchemaError(f"unresolvable $ref {ref!r}")
        node = node[part]
    return node


def _type_of(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, (int, float)):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    return "object"


def _type_matches(value: Any, expected: str) -> bool:
    actual = _type_of(value)
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "number":
        return actual == "number"
    return actual == expected


def validate(instance: Any, schema: Any, root: dict | None = None,
             path: str = "$", spath: str = "#", _ref_depth: int = 0) -> list[dict]:
    """Return a list of {path, message} errors; empty list means valid."""
    if root is None:
        if isinstance(schema, bool) or not isinstance(schema, dict):
            raise SchemaError("root schema must be an object")
        _check_schema_supported(schema)
        root = schema
    if _ref_depth > 64:
        raise SchemaError("$ref recursion too deep (possible cyclic schema)")

    errors: list[dict] = []

    if isinstance(schema, bool):
        if not schema:
            errors.append({"path": path, "message": "value not allowed (schema is false)"})
        return errors
    if not isinstance(schema, dict):
        raise SchemaError(f"schema at {spath} must be an object or boolean")

    if "$ref" in schema:
        target = _resolve_ref(schema["$ref"], root)
        return validate(instance, target, root, path, schema["$ref"], _ref_depth + 1)

    def err(msg: str) -> None:
        errors.append({"path": path, "message": msg})

    # --- type ---
    if "type" in schema:
        expected = schema["type"]
        types = expected if isinstance(expected, list) else [expected]
        if not any(_type_matches(instance, t) for t in types):
            err(f"expected type {'/'.join(types)}, got {_type_of(instance)}")
            return errors  # further keyword checks would be noise

    # --- enum / const ---
    if "const" in schema and instance != schema["const"]:
        err(f"must equal const {schema['const']!r}")
    if "enum" in schema:
        if not any(instance == option for option in schema["enum"]):
            err(f"must be one of {schema['enum']!r}")

    # --- string ---
    if isinstance(instance, str):
        if "minLength" in schema and len(instance) < schema["minLength"]:
            err(f"string shorter than minLength {schema['minLength']}")
        if "maxLength" in schema and len(instance) > schema["maxLength"]:
            err(f"string longer than maxLength {schema['maxLength']}")
        if "pattern" in schema:
            try:
                if re.search(schema["pattern"], instance) is None:
                    err(f"string does not match pattern {schema['pattern']!r}")
            except re.error as exc:
                raise SchemaError(f"bad regex at {spath}: {exc}")

    # --- number ---
    if isinstance(instance, (int, float)) and not isinstance(instance, bool):
        v = instance
        if "minimum" in schema and v < schema["minimum"]:
            err(f"must be >= {schema['minimum']}")
        if "maximum" in schema and v > schema["maximum"]:
            err(f"must be <= {schema['maximum']}")
        if "exclusiveMinimum" in schema and v <= schema["exclusiveMinimum"]:
            err(f"must be > {schema['exclusiveMinimum']}")
        if "exclusiveMaximum" in schema and v >= schema["exclusiveMaximum"]:
            err(f"must be < {schema['exclusiveMaximum']}")
        if "multipleOf" in schema:
            m = schema["multipleOf"]
            if m == 0:
                raise SchemaError(f"multipleOf 0 at {spath}")
            q = v / m
            if abs(q - round(q)) > 1e-9:
                err(f"must be a multiple of {m}")

    # --- array ---
    if isinstance(instance, list):
        if "minItems" in schema and len(instance) < schema["minItems"]:
            err(f"array shorter than minItems {schema['minItems']}")
        if "maxItems" in schema and len(instance) > schema["maxItems"]:
            err(f"array longer than maxItems {schema['maxItems']}")
        if schema.get("uniqueItems"):
            seen: list[Any] = []
            for i, item in enumerate(instance):
                if any(item == s for s in seen):
                    err(f"duplicate item at index {i} (uniqueItems)")
                    break
                seen.append(item)
        if "prefixItems" in schema:
            for i, sub in enumerate(schema["prefixItems"]):
                if i < len(instance):
                    errors.extend(validate(instance[i], sub, root, f"{path}[{i}]", f"{spath}/prefixItems/{i}"))
        if "items" in schema:
            start = len(schema.get("prefixItems", [])) if isinstance(schema.get("prefixItems"), list) else 0
            for i in range(start, len(instance)):
                errors.extend(validate(instance[i], schema["items"], root, f"{path}[{i}]", f"{spath}/items"))
        if "contains" in schema:
            if not any(not validate(item, schema["contains"], root, path, spath) for item in instance):
                err("array does not contain an item matching `contains`")

    # --- object ---
    if isinstance(instance, dict):
        required = schema.get("required", [])
        for key in required:
            if key not in instance:
                err(f"missing required property {key!r}")
        props = schema.get("properties", {})
        pats = schema.get("patternProperties", {})
        for key, value in instance.items():
            matched = False
            if key in props:
                matched = True
                errors.extend(validate(value, props[key], root, f"{path}.{key}", f"{spath}/properties/{key}"))
            for pat, sub in pats.items():
                try:
                    if re.search(pat, key):
                        matched = True
                        errors.extend(validate(value, sub, root, f"{path}.{key}", f"{spath}/patternProperties/{pat}"))
                except re.error as exc:
                    raise SchemaError(f"bad patternProperties regex {pat!r} at {spath}: {exc}")
            if not matched and "additionalProperties" in schema:
                ap = schema["additionalProperties"]
                if ap is False:
                    err(f"additional property {key!r} not allowed")
                elif isinstance(ap, dict):
                    errors.extend(validate(value, ap, root, f"{path}.{key}", f"{spath}/additionalProperties"))
        if "propertyNames" in schema:
            for key in instance:
                errors.extend(validate(key, schema["propertyNames"], root, f"{path}<{key}>",
                                       f"{spath}/propertyNames"))

    # --- combinators ---
    if "allOf" in schema:
        for i, sub in enumerate(schema["allOf"]):
            errors.extend(validate(instance, sub, root, path, f"{spath}/allOf/{i}"))
    if "anyOf" in schema:
        if not any(not validate(instance, sub, root, path, spath) for sub in schema["anyOf"]):
            err("does not match any anyOf branch")
    if "oneOf" in schema:
        matches = sum(1 for sub in schema["oneOf"] if not validate(instance, sub, root, path, spath))
        if matches != 1:
            err(f"matches {matches} oneOf branches, expected exactly 1")
    if "not" in schema:
        if not validate(instance, schema["not"], root, path, spath):
            err("matches the forbidden `not` schema")

    return errors


def assert_valid(instance: Any, schema: dict, *, what: str = "document") -> None:
    errs = validate(instance, schema)
    if errs:
        first = errs[:10]
        raise ToolError(
            "MDA-E101",
            f"{what} failed schema validation: {first[0]['path']}: {first[0]['message']}"
            + (f" (+{len(errs) - 1} more)" if len(errs) > 1 else ""),
            details={"errors": first, "error_count": len(errs)},
        )
