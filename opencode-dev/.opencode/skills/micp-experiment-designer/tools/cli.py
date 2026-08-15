#!/usr/bin/env python3
"""CLI entry point for micp-experiment-designer tools.

Reads one JSON envelope from stdin. The envelope selects a tool via
`tool` (or the subcommand-style first positional) and passes its `payload`.
Tools share the `_common` envelope protocol:

  input:  {"tool": "<name>", "payload": {...}}
  output: {"ok": true,  "tool": ..., "version": ..., "result": {...}}
          {"ok": false, "tool": ..., "version": ..., "error": {...}}

Exit codes: 0 ok; 2 input/validation; 3 contract/scientific problem;
4 internal error. Every tool is offline and deterministic.

Usage:
  echo '{"tool":"doe_power","payload":{...}}' | python -m tools.cli
  echo '{"tool":"doe_power","payload":{...}}' | python tools/cli.py
"""

from __future__ import annotations

import json
import sys

from ._common import ToolError, read_json_stdin, reject_non_finite, envelope_ok, envelope_err

TOOLS = {
    "doe_power": "doe_power",
    "randomizer": "randomizer",
    "quantity_calc": "quantity_calc",
    "sop_check": "sop_check",
    "preregister": "preregister",
    "validate": "validate",
}


def main() -> None:
    payload = read_json_stdin()
    reject_non_finite(payload)

    tool_name = payload.get("tool")
    if not isinstance(tool_name, str) or tool_name not in TOOLS:
        err = ToolError("E_TOOL_UNKNOWN", f"unknown tool '{tool_name}'",
                        details={"known": sorted(TOOLS)})
        sys.stdout.write(envelope_err("cli", err) + "\n")
        sys.exit(2)

    import importlib
    try:
        mod = importlib.import_module(f".{TOOLS[tool_name]}", __package__)
    except Exception as exc:  # pragma: no cover - import failure
        err = ToolError("E_DEPENDENCY", f"cannot load tool '{tool_name}': {exc}",
                        retryable=True, exit_code=4)
        sys.stdout.write(envelope_err(tool_name, err) + "\n")
        sys.exit(4)

    fn = getattr(mod, "main", None)
    if fn is None:  # pragma: no cover - module contract enforced by tests
        err = ToolError("E_INTERNAL", f"tool '{tool_name}' has no main()",
                        retryable=True, exit_code=4)
        sys.stdout.write(envelope_err(tool_name, err) + "\n")
        sys.exit(4)

    result = fn(payload.get("payload") or {})
    sys.stdout.write(envelope_ok(tool_name, result) + "\n")
    sys.exit(0)


if __name__ == "__main__":
    try:
        main()
    except ToolError as err:
        sys.stdout.write(envelope_err("cli", err) + "\n")
        sys.exit(err.exit_code)
    except BrokenPipeError:
        sys.exit(0)
    except Exception as exc:  # noqa: BLE001
        err = ToolError("E_INTERNAL", f"unexpected internal error: {type(exc).__name__}: {exc}",
                        retryable=True, exit_code=4)
        sys.stdout.write(envelope_err("cli", err) + "\n")
        sys.exit(4)
