#!/usr/bin/env python3
"""micp-reproducibility-versioning unified CLI.

Reads a JSON envelope on stdin and dispatches to a sub-tool:

  python tools/mrv/cli.py service        < input.json   (full skill pipeline)
  python tools/mrv/cli.py reproduce      < input.json   (one-shot reproduction loop)
  python tools/mrv/cli.py manifest       < input.json   (data manifest)
  python tools/mrv/cli.py env            < input.json   (environment collector)
  python tools/mrv/cli.py lock           < input.json   (dependency export & lock)
  python tools/mrv/cli.py seed           < input.json   (random-seed manager)
  python tools/mrv/cli.py record         < input.json   (provenance recorder)
  python tools/mrv/cli.py diff           < input.json   (result diff comparator)
  python tools/mrv/cli.py compat         < input.json   (version compatibility checker)
  python tools/mrv/cli.py migrate        < input.json   (schema migrator)
  python tools/mrv/cli.py check-raw      < input.json   (raw write-protection checker)
  python tools/mrv/cli.py check-pollution < input.json  (artifact pollution detector)
  python tools/mrv/cli.py validate       < input.json   (input schema validation only)

Exit codes: 0 success; 2 input/validation; 3 graph/contract; 4 internal.
Progress goes to stderr; stdout carries only the JSON envelope.
"""

from __future__ import annotations

import json
import sys

from _common import ToolError, reject_non_finite


def _dispatch(name: str, payload: dict) -> dict:
    if name == "service":
        from service import main as service_main
        return service_main(payload)
    if name == "reproduce":
        from reproduce import reproduce_main
        return reproduce_main(payload)
    if name == "manifest":
        from hashing import manifest_main
        return manifest_main(payload)
    if name == "env":
        from envinfo import env_main
        return env_main(payload)
    if name == "lock":
        from envinfo import lock_main
        return lock_main(payload)
    if name == "seed":
        from seed import seed_main
        return seed_main(payload)
    if name == "record":
        from provenance import record_main
        return record_main(payload)
    if name == "diff":
        from diff import diff_main
        return diff_main(payload)
    if name == "compat":
        from envinfo import compat_main
        return compat_main(payload)
    if name == "migrate":
        from envinfo import migrate_main
        return migrate_main(payload)
    if name == "check-raw":
        from hashing import check_raw_main
        return check_raw_main(payload)
    if name == "check-pollution":
        from checkers import pollution_main
        return pollution_main(payload)
    if name == "validate":
        from service import main as service_main
        clean = dict(payload)
        clean.pop("op", None)  # never leak the dispatch field into the contract
        return service_main({"op": "validate_input", **clean})
    raise ToolError("MRV-E103", f"unknown subcommand {name!r}",
                    details={"allowed": _SUBCOMMANDS})


_SUBCOMMANDS = ("service", "reproduce", "manifest", "env", "lock", "seed",
                "record", "diff", "compat", "migrate", "check-raw",
                "check-pollution", "validate")


def main() -> None:
    """Deprecated alias; real entry is `_cli_entry`. Kept for API compatibility."""
    _cli_entry()


def _cli_entry() -> None:
    """Entry wrapper matching the micp-data-analyst convention:
    build the envelope here; errors are raised as ToolError and handled by
    _common.run_tool's envelope machinery.
    """
    try:
        payload = run_tool_read_stdin()
        reject_non_finite(payload)
        name = sys.argv[1] if len(sys.argv) > 1 else "service"
        result = _dispatch(name, payload)
        sys.stdout.write(json.dumps(
            {"ok": True, "tool": name, "version": "1.0.0", "result": result},
            ensure_ascii=False, indent=2, sort_keys=True) + "\n")
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


def run_tool_read_stdin() -> dict:
    """Local stdin reader (ToolError on empty/malformed input)."""
    raw = sys.stdin.read()
    if not raw.strip():
        raise ToolError("E_INPUT_EMPTY", "stdin was empty; expected a JSON document")
    try:
        payload = json.loads(raw, parse_constant=_reject_constant)
    except json.JSONDecodeError as exc:
        raise ToolError("E_INPUT_INVALID_JSON",
                        f"stdin is not valid JSON: {exc.msg} at line {exc.lineno} "
                        f"column {exc.colno}",
                        details={"line": exc.lineno, "column": exc.colno}) from exc
    if not isinstance(payload, dict):
        raise ToolError("E_INPUT_INVALID_JSON", "envelope must be a JSON object")
    return payload


def _reject_constant(value: str):
    """Reject bare NaN / Infinity / -Infinity constants in the input JSON."""
    raise ToolError("E_NUMERIC_NON_FINITE", f"non-finite constant {value!r} is not allowed",
                    details={"constant": value})


if __name__ == "__main__":
    _cli_entry()
