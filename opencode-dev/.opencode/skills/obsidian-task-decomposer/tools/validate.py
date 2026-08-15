#!/usr/bin/env python3
"""validate.py — validate a JSON document against a JSON Schema (2020-12 subset).

stdin:
  {"schema": <path to schema file, relative to this tool's directory or absolute>,
   "document": <any JSON value>}

stdout (ok):  {"ok": true, "result": {"valid": true, "errors": []}}
stdout (bad): {"ok": true, "result": {"valid": false, "errors": [{path, message}, ...]}}

Schema-load failures and unreadable files return structured ToolError envelopes.
Offline: schema is read from disk only; no network, no clock, no randomness.
"""

from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from _common import ToolError, as_dict, as_str, run_tool
from _jsonschema import validate

SKILL_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _load_schema(name: str):
    # Resolve relative to the skill root so callers pass "schemas/input.schema.json".
    candidate = name if os.path.isabs(name) else os.path.join(SKILL_ROOT, name)
    real = os.path.realpath(candidate)
    if not (real.startswith(os.path.realpath(SKILL_ROOT)) or os.path.isabs(name)):
        raise ToolError("E_PATH_ESCAPE", f"schema path escapes skill directory: {name}")
    if not os.path.isfile(real):
        raise ToolError("E_FILE_MISSING", f"schema file not found: {name}",
                        details={"resolved": real})
    try:
        with open(real, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except json.JSONDecodeError as exc:
        raise ToolError("E_FILE_CORRUPT", f"schema file {name} is not valid JSON: {exc}",
                        details={"resolved": real})
    except OSError as exc:
        raise ToolError("E_FILE_UNREADABLE", f"cannot read schema file {name}: {exc}",
                        retryable=True)


def main(payload):
    doc = as_dict(payload, "$")
    schema_name = as_str(doc.get("schema"), "$.schema", min_len=1)
    if "document" not in doc:
        raise ToolError("E_INPUT_MISSING_FIELD", "missing required field 'document'",
                        details={"field": "document"})
    schema = _load_schema(schema_name)
    errors = validate(doc["document"], schema)
    return {"valid": not errors, "errors": errors, "schema": schema_name}


if __name__ == "__main__":
    run_tool("validate", main)
