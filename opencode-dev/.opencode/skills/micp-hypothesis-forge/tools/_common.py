"""Shared envelope, numeric-guard, and IO helpers for micp-hypothesis-forge tools.

Every tool follows the Obsidian Plan / Panshi stdio contract:
  stdin   exactly one JSON document
  stdout  exactly one JSON document  -- never log here; progress -> stderr
  exit    0 success | 2 input/validation | 3 graph/contract | 4 internal

Envelope:
  success: {"ok": true,  "version": "1.0.0", "tool": "<name>", "result": {...}}
  failure: {"ok": false, "tool": "<name>",   "version": "1.0.0",
            "error": {"code", "message", "retryable", "details"}}

Offline, deterministic, Python 3.10+ standard library only.
"""

from __future__ import annotations

import json
import math
import sys
from typing import Any, Callable

TOOL_VERSION = "1.0.0"

# Exit codes (project convention, tools/README.md)
EXIT_OK = 0
EXIT_INPUT = 2
EXIT_CONTRACT = 3
EXIT_INTERNAL = 4


class ToolError(Exception):
    """Structured tool failure carrying an MHX error code + machine detail."""

    def __init__(self, code: str, message: str, *, retryable: bool = False,
                 details: dict | None = None, exit_code: int = EXIT_INPUT) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = retryable
        self.details = details or {}
        self.exit_code = exit_code


def read_payload() -> Any:
    """Read exactly one JSON document from stdin. Raises ToolError(E_INPUT_INVALID_JSON)."""
    raw = sys.stdin.read()
    if not raw or not raw.strip():
        raise ToolError(
            "MHX-E104", "stdin was empty; expected exactly one JSON document.",
            retryable=False, exit_code=EXIT_INPUT,
        )
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ToolError(
            "MHX-E104", f"stdin is not valid JSON: {exc.msg} at line {exc.lineno}.",
            retryable=False, exit_code=EXIT_INPUT,
            details={"line": exc.lineno, "col": exc.colno},
        ) from exc


def as_dict(payload: Any, *, what: str = "payload") -> dict:
    if not isinstance(payload, dict):
        raise ToolError(
            "MHX-E105", f"{what} must be a JSON object, got {type(payload).__name__}.",
            retryable=False, exit_code=EXIT_INPUT,
        )
    return payload


def as_list(payload: Any, *, what: str = "value") -> list:
    if not isinstance(payload, list):
        raise ToolError(
            "MHX-E105", f"{what} must be a JSON array, got {type(payload).__name__}.",
            retryable=False, exit_code=EXIT_INPUT,
        )
    return payload


def as_str(payload: Any, *, what: str = "value") -> str:
    if not isinstance(payload, str) or payload == "":
        raise ToolError(
            "MHX-E105", f"{what} must be a non-empty string.",
            retryable=False, exit_code=EXIT_INPUT,
        )
    return payload


def check_finite(value: Any, *, what: str = "value") -> float:
    """Reject non-numeric / non-finite / empty values (spec: numeric discipline)."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ToolError(
            "MHX-E301", f"{what} must be a finite number, got {value!r}.",
            retryable=False, exit_code=EXIT_INPUT, details={"field": what},
        )
    v = float(value)
    if not math.isfinite(v):
        raise ToolError(
            "MHX-E301", f"{what} is not finite (NaN/Inf): {value!r}.",
            retryable=False, exit_code=EXIT_INPUT, details={"field": what},
        )
    return v


def clamp_unit(value: float, lo: float, hi: float, *, what: str = "value") -> float:
    """Clamp to [0,1] after finite check (used for scores)."""
    v = check_finite(value, what=what)
    return max(lo, min(hi, v))


def emit_ok(tool: str, result: dict) -> None:
    print(json.dumps({"ok": True, "version": TOOL_VERSION, "tool": tool,
                      "result": result}, ensure_ascii=False, sort_keys=True))


def emit_error(tool: str, err: ToolError) -> None:
    print(json.dumps({
        "ok": False, "tool": tool, "version": TOOL_VERSION,
        "error": {"code": err.code, "message": err.message,
                  "retryable": err.retryable, "details": err.details},
    }, ensure_ascii=False, sort_keys=True))


def run_tool(tool: str, main: Callable[[Any], dict]) -> None:
    """Entry wrapper: read stdin -> run -> emit envelope -> map exit code.

    The tool name is the file's own name (e.g. "dag") used in envelope + exit.
    """
    try:
        payload = read_payload()
        result = main(payload)
        emit_ok(tool, result)
        sys.exit(EXIT_OK)
    except ToolError as err:
        emit_error(tool, err)
        sys.exit(err.exit_code)
    except json.JSONDecodeError as err:  # defensive; read_payload already guards
        emit_error(tool, ToolError(
            "MHX-E104", f"invalid JSON: {err.msg}", exit_code=EXIT_INPUT))
        sys.exit(EXIT_INPUT)
    except RecursionError as err:
        emit_error(tool, ToolError(
            "MHX-E403", f"recursion limit exceeded: {err}", retryable=True,
            exit_code=EXIT_INTERNAL))
        sys.exit(EXIT_INTERNAL)
    except Exception as err:  # last-resort internal error (never swallow silently)
        emit_error(tool, ToolError(
            "MHX-E404", f"unexpected internal error: {err!r}", retryable=True,
            exit_code=EXIT_INTERNAL))
        sys.exit(EXIT_INTERNAL)
