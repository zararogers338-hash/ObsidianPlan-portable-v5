"""Shared utilities for micp-experiment-designer tools.

All tools are pure standard-library Python (>=3.10), offline, and deterministic
(run-to-run byte-identical on identical input). They communicate over
stdin/stdout with JSON envelopes:

  success: {"ok": true,  "tool": <name>, "version": <semver>, "result": {...}}
  failure: {"ok": false, "tool": <name>, "version": <semver>,
            "error": {"code": <machine code>, "message": <human readable>,
                      "retryable": <bool>, "details": {...}}}

Exit codes: 0 success; 2 input/validation problem; 3 contract/scientific
problem; 4 internal error. Numbers are rejected when non-finite; unknown JSON
fields are rejected to keep contracts strict.

The optional scientific backend (scipy.stats / numpy) is imported lazily so the
skill still works on a bare interpreter: tools that do not need it never import
it, and tools that do degrade to a documented fallback (see the individual
tool README entries and the skill README "Limitations").
"""

from __future__ import annotations

import json
import math
import os
import sys
from datetime import datetime, timezone
from typing import Any

TOOLSET_VERSION = "1.0.0"

# Minimal, auditable JSON Schema draft 2020-12 subset (mirrors the
# task-decomposer convention). Supported keywords:
#   $schema $id $comment title description type enum const required properties
#   additionalProperties patternProperties items minItems maxItems uniqueItems
#   minLength maxLength pattern minimum maximum exclusiveMinimum exclusiveMaximum
#   multipleOf anyOf oneOf allOf not $ref($defs-only) default(ignored)
SCHEMA_DIALECT = "https://json-schema.org/draft/2020-12/schema"


class ToolError(Exception):
    """An expected, classifiable failure carrying a machine-readable code."""

    def __init__(self, code: str, message: str, *, retryable: bool = False,
                 details: dict[str, Any] | None = None, exit_code: int = 2):
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = retryable
        self.details = details or {}
        self.exit_code = exit_code


# ---------------------------------------------------------------------------
# JSON helpers
# ---------------------------------------------------------------------------

def read_json_stdin() -> Any:
    raw = sys.stdin.read()
    if not raw.strip():
        raise ToolError("E_INPUT_EMPTY", "stdin was empty; expected a JSON document")
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ToolError(
            "E_INPUT_INVALID_JSON",
            f"stdin is not valid JSON: {exc.msg} at line {exc.lineno} column {exc.colno}",
            details={"line": exc.lineno, "column": exc.colno},
        )


def _reject_non_finite(node: Any, path: str = "$") -> None:
    if isinstance(node, float) and not math.isfinite(node):
        raise ToolError("E_NUMERIC_NON_FINITE", f"non-finite number at {path}",
                        details={"path": path})
    if isinstance(node, dict):
        for k, v in node.items():
            _reject_non_finite(v, f"{path}.{k}")
    elif isinstance(node, list):
        for i, v in enumerate(node):
            _reject_non_finite(v, f"{path}[{i}]")


def reject_non_finite(doc: Any) -> Any:
    _reject_non_finite(doc)
    return doc


def envelope_ok(tool: str, result: dict[str, Any]) -> str:
    return json.dumps({"ok": True, "tool": tool, "version": TOOLSET_VERSION,
                       "result": result}, ensure_ascii=False, indent=2, sort_keys=True)


def envelope_err(tool: str, err: ToolError) -> str:
    return json.dumps({"ok": False, "tool": tool, "version": TOOLSET_VERSION,
                       "error": {"code": err.code, "message": err.message,
                                 "retryable": err.retryable,
                                 "details": err.details}},
                      ensure_ascii=False, indent=2, sort_keys=True)


def run_tool(tool: str, fn) -> None:
    """Entry-point wrapper: fn(stdin_json) -> result dict. Handles envelopes."""
    try:
        payload = read_json_stdin()
        reject_non_finite(payload)
        result = fn(payload)
        sys.stdout.write(envelope_ok(tool, result) + "\n")
        sys.exit(0)
    except ToolError as err:
        sys.stdout.write(envelope_err(tool, err) + "\n")
        sys.exit(err.exit_code)
    except BrokenPipeError:
        sys.exit(0)
    except Exception as exc:  # noqa: BLE001 - last-resort guard
        err = ToolError("E_INTERNAL", f"unexpected internal error: {type(exc).__name__}: {exc}",
                        retryable=True, exit_code=4)
        sys.stdout.write(envelope_err(tool, err) + "\n")
        sys.exit(4)


def emit_progress(message: str) -> None:
    """Progress lines go to stderr so stdout stays machine-parseable."""
    sys.stderr.write(f"[micp-experiment-designer] {message}\n")
    sys.stderr.flush()


# ---------------------------------------------------------------------------
# Type coercion guards (all numeric tools must check null / non-finite / range)
# ---------------------------------------------------------------------------

def require(cond: bool, code: str, message: str, **details: Any) -> None:
    if not cond:
        raise ToolError(code, message, details=details or None)


def as_str(value: Any, path: str, *, min_len: int = 0, max_len: int | None = None) -> str:
    require(isinstance(value, str), "E_TYPE", f"{path} must be a string", path=path, got=type(value).__name__)
    require(len(value) >= min_len, "E_RANGE", f"{path} must be at least {min_len} chars", path=path)
    if max_len is not None:
        require(len(value) <= max_len, "E_RANGE", f"{path} must be at most {max_len} chars", path=path)
    return value


def as_number(value: Any, path: str, *, min_v: float | None = None,
              max_v: float | None = None) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ToolError("E_TYPE", f"{path} must be a number", details={"path": path})
    f = float(value)
    if not math.isfinite(f):
        raise ToolError("E_NUMERIC_NON_FINITE", f"{path} must be finite", details={"path": path})
    if min_v is not None and f < min_v:
        raise ToolError("E_RANGE", f"{path} must be >= {min_v}", details={"path": path, "value": f})
    if max_v is not None and f > max_v:
        raise ToolError("E_RANGE", f"{path} must be <= {max_v}", details={"path": path, "value": f})
    return f


def as_int(value: Any, path: str, *, min_v: int | None = None, max_v: int | None = None) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ToolError("E_TYPE", f"{path} must be an integer", details={"path": path})
    if min_v is not None and value < min_v:
        raise ToolError("E_RANGE", f"{path} must be >= {min_v}", details={"path": path})
    if max_v is not None and value > max_v:
        raise ToolError("E_RANGE", f"{path} must be <= {max_v}", details={"path": path})
    return value


def as_list(value: Any, path: str, *, min_len: int = 0, max_len: int | None = None) -> list:
    if not isinstance(value, list):
        raise ToolError("E_TYPE", f"{path} must be an array", details={"path": path})
    if len(value) < min_len:
        raise ToolError("E_RANGE", f"{path} must have at least {min_len} items", details={"path": path})
    if max_len is not None and len(value) > max_len:
        raise ToolError("E_RANGE", f"{path} must have at most {max_len} items", details={"path": path})
    return value


def as_dict(value: Any, path: str) -> dict:
    if not isinstance(value, dict):
        raise ToolError("E_TYPE", f"{path} must be an object", details={"path": path})
    return value


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def env_flag(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}
