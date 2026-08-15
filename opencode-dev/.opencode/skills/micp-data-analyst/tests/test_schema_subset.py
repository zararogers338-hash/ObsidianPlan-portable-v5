"""Schema-subset guard: our schemas must only use keywords the local validator
(_jsonschema.py) actually supports.

If a schema silently relies on an unsupported keyword, validation would be
wrong. This test walks every schema file and asserts each keyword is in _KNOWN.
"""

from __future__ import annotations

import json
import os
import sys

TOOLS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                         "tools", "micp")
sys.path.insert(0, TOOLS_DIR)

from _jsonschema import _KNOWN  # noqa: E402

SCHEMAS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                           "schemas")


def _walk(node, path: str, errors: list[str]) -> None:
    if isinstance(node, bool):
        return
    if not isinstance(node, dict):
        return
    for key, value in node.items():
        if key.startswith("x-"):
            continue
        if key not in _KNOWN:
            errors.append(f"{path}: unsupported keyword {key!r}")
            continue
        # Only descend through keyword positions that hold (sub-)schemas.
        if key in ("properties", "patternProperties", "$defs"):
            for name, sub in value.items():
                _walk(sub, f"{path}/{key}/{name}", errors)
        elif key in ("additionalProperties", "items", "contains", "not", "propertyNames"):
            _walk(value, f"{path}/{key}", errors)
        elif key in ("prefixItems", "anyOf", "oneOf", "allOf"):
            for i, item in enumerate(value):
                _walk(item, f"{path}/{key}[{i}]", errors)


def test_all_schemas_stay_in_supported_subset() -> None:
    schema_files = sorted(f for f in os.listdir(SCHEMAS_DIR) if f.endswith(".schema.json"))
    assert schema_files, "no schemas found"
    for fname in schema_files:
        with open(os.path.join(SCHEMAS_DIR, fname), encoding="utf-8") as fh:
            schema = json.load(fh)
        errors: list[str] = []
        _walk(schema, fname, errors)
        assert not errors, f"{fname}: {errors}"


def test_schemas_are_valid_json_objects() -> None:
    for fname in os.listdir(SCHEMAS_DIR):
        if fname.endswith(".schema.json"):
            with open(os.path.join(SCHEMAS_DIR, fname), encoding="utf-8") as fh:
                data = json.load(fh)
            assert isinstance(data, dict)
            assert "type" in data
