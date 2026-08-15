#!/usr/bin/env python3
"""micp-data-analyst unified CLI.

Reads a JSON envelope on stdin and dispatches to a sub-tool:

  python tools/micp/cli.py service      < input.json   (full skill pipeline)
  python tools/micp/cli.py qc           < input.json   (data-quality + units + pseudo-replication)
  python tools/micp/cli.py stats        < input.json   (single statistics op; see stats.py ops)
  python tools/micp/cli.py validate     < input.json   (input schema validation only)

Exit codes: 0 success; 2 input/validation; 3 graph/contract; 4 internal.
Progress goes to stderr; stdout carries only the JSON envelope.
"""

from __future__ import annotations

import json
import sys

from _common import ToolError
from errors import MdaError, MdaErrorCode

_SUBCOMMANDS = ("service", "qc", "stats", "validate")


def _dispatch(name: str, payload: dict) -> dict:
    if name == "service":
        from service import main as service_main
        return service_main(payload)
    if name == "qc":
        from qc import main as qc_main
        return qc_main(payload)
    if name == "stats":
        from stats import main as stats_main
        return stats_main(payload)
    if name == "validate":
        from service import main as service_main
        clean = dict(payload)
        clean.pop("op", None)  # never leak the dispatch field into the contract
        return service_main({"op": "validate_input", **clean})
    raise MdaError(MdaErrorCode.INVALID_ANALYSIS_MODE,
                   f"unknown subcommand {name!r}",
                   detail={"allowed": list(_SUBCOMMANDS)})


def _read_stdin() -> dict:
    raw = sys.stdin.read()
    if not raw.strip():
        raise MdaError(MdaErrorCode.CONTEXT_CORRUPT,
                       "stdin was empty; expected a JSON document")
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise MdaError(MdaErrorCode.CONTEXT_CORRUPT,
                       f"stdin is not valid JSON: {exc.msg} at line {exc.lineno}")
    if not isinstance(payload, dict):
        raise MdaError(MdaErrorCode.CONTEXT_CORRUPT, "envelope must be a JSON object")
    return payload


def main() -> None:
    name = sys.argv[1] if len(sys.argv) > 1 else "service"
    payload = _read_stdin()
    result = _dispatch(name, payload)
    sys.stdout.write(json.dumps(
        {"ok": True, "tool": name, "version": "1.0.0", "result": result},
        ensure_ascii=False, indent=2, sort_keys=True) + "\n")


if __name__ == "__main__":
    # Note: dispatch functions return a plain dict; the envelope is built here,
    # so run_tool is not used (errors are raised as MdaError and handled below).
    try:
        main()
        sys.exit(0)
    except ToolError as err:
        sys.stdout.write(json.dumps(
            {"ok": False, "tool": "cli", "version": "1.0.0",
             "error": {"code": err.code, "message": err.message,
                       "retryable": err.retryable, "details": err.details}},
            ensure_ascii=False, indent=2, sort_keys=True) + "\n")
        sys.exit(err.exit_code)
    except BrokenPipeError:
        sys.exit(0)
    except Exception as exc:  # noqa: BLE001
        sys.stdout.write(json.dumps(
            {"ok": False, "tool": "cli", "version": "1.0.0",
             "error": {"code": "E_INTERNAL",
                       "message": f"unexpected internal error: {type(exc).__name__}: {exc}",
                       "retryable": True, "details": {}}},
            ensure_ascii=False, indent=2, sort_keys=True) + "\n")
        sys.exit(4)
