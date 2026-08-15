#!/usr/bin/env python3
"""Contract/schema validation tool for micp-experiment-designer.

Validates an arbitrary JSON document against one of the skill's schemas
(input envelope, output envelope, or a custom schema passed inline). Used by
the skill itself (self-check: does my output pass the output schema?) and by
the Router (pre-flight input validation).

Supports:
  - `target: "input"` / `"output"` — validate against the bundled schemas.
  - `target: "inline"` + `schema: {...}` — validate against a caller-supplied
    JSON Schema (the skill's minimal draft-2020-12 subset validator).

This tool is deterministic and offline.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ._common import ToolError, as_str, run_tool
from .jsonschema_subset import validate_document

SCHEMA_DIR = Path(__file__).resolve().parent.parent / "schemas"


def _load_schema(name: str) -> dict[str, Any]:
    path = SCHEMA_DIR / name
    if not path.exists():
        raise ToolError("E_DEPENDENCY", f"schema file '{name}' not found", details={"path": str(path)})
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ToolError("E_SCHEMA", f"schema file '{name}' is not valid JSON: {exc}",
                        details={"path": str(path)})


def main(payload: dict[str, Any]) -> dict[str, Any]:
    target = as_str(payload.get("target", "input"), "target", min_len=1)
    if target not in ("input", "output", "inline"):
        raise ToolError("E_INPUT_VALUE", f"unknown target '{target}'",
                        details={"supported": ["input", "output", "inline"]})

    if target == "inline":
        schema = payload.get("schema")
        if not isinstance(schema, dict):
            raise ToolError("E_TYPE", "schema must be an object when target=inline", details={"path": "schema"})
    else:
        schema = _load_schema(f"{target}.schema.json")

    document = payload.get("document")
    report = validate_document(document, schema)
    if not report["valid"]:
        raise ToolError("E_SCHEMA_FAIL", "document failed schema validation",
                        details={"errors": report["errors"]})
    return {"target": target, "valid": True, "error_count": 0}


if __name__ == "__main__":
    run_tool(TOOL := "validate", main)
