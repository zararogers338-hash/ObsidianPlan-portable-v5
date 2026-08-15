"""Shared envelope, error, and progress machinery for the obsidian-red-team tools.

Pure stdlib. Every tool writes ONE JSON document to stdout:
  {"ok": true,  "tool": <name>, "version": "1.0.0", "result": {...}}
  {"ok": false, "tool": <name>, "version": "1.0.0", "error": {...}}
Exit codes: 0 success; 2 validation/input; 3 contract/graph; 4 internal.
Progress and diagnostics go to stderr; stdout carries ONLY the envelope.
"""

from __future__ import annotations

import json
import sys
import time
from typing import Any

TOOLSET_VERSION = "1.0.0"


def emit_progress(message: str) -> None:
    print(f"[ort] {message}", file=sys.stderr, flush=True)


class ToolError(Exception):
    """Structured error shared by all ORT tools.

    `exit_code` maps to the process exit code; `retryable` signals whether the
    caller may retry as-is; `details` carries machine-readable context.
    """

    def __init__(
        self,
        code: str,
        message: str,
        *,
        retryable: bool = False,
        details: dict | None = None,
        exit_code: int = 2,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = retryable
        self.details = details or {}
        self.exit_code = exit_code

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "detail": self.details,
            "retryable": self.retryable,
        }


def run_tool(tool: str, fn: Any) -> None:
    """Call fn() and emit the standard envelope to stdout.

    fn must return a plain dict (the `result` payload) or raise ToolError.
    """
    started = time.monotonic()
    try:
        result = fn()
        envelope = {"ok": True, "tool": tool, "version": TOOLSET_VERSION, "result": result}
        json.dump(envelope, sys.stdout, ensure_ascii=False, indent=2, sort_keys=True)
        sys.stdout.write("\n")
        sys.exit(0)
    except ToolError as err:
        envelope = {
            "ok": False,
            "tool": tool,
            "version": TOOLSET_VERSION,
            "error": err.to_dict(),
        }
        json.dump(envelope, sys.stdout, ensure_ascii=False, indent=2, sort_keys=True)
        sys.stdout.write("\n")
        sys.exit(err.exit_code)
    except BrokenPipeError:
        sys.exit(0)
    except Exception as exc:  # noqa: BLE001
        elapsed = time.monotonic() - started
        envelope = {
            "ok": False,
            "tool": tool,
            "version": TOOLSET_VERSION,
            "error": {
                "code": "E_INTERNAL",
                "message": f"unexpected internal error: {type(exc).__name__}: {exc}",
                "retryable": True,
                "detail": {"elapsed_sec": round(elapsed, 4)},
            },
        }
        json.dump(envelope, sys.stdout, ensure_ascii=False, indent=2, sort_keys=True)
        sys.stdout.write("\n")
        sys.exit(4)


def read_stdin_envelope() -> dict[str, Any]:
    raw = sys.stdin.read()
    if not raw.strip():
        raise ToolError("ORT-E301", "stdin was empty; expected a JSON document",
                        exit_code=2)
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ToolError("ORT-E301",
                        f"stdin is not valid JSON: {exc.msg} at line {exc.lineno}",
                        details={"line": exc.lineno, "col": exc.colno}, exit_code=2)
    if not isinstance(payload, dict):
        raise ToolError("ORT-E301", "envelope must be a JSON object", exit_code=2)
    return payload


def validate_required(payload: dict[str, Any], required: list[str]) -> dict[str, Any]:
    """Collect missing required fields with field-level guidance.

    Never a generic '信息不足': each missing field reports why it is critical and
    how to obtain it, matching the skill's missing-input discipline.
    """
    missing = []
    guidance = {
        "task_id": ("audit anchor and reproducibility", "assigned by the Task Decomposer"),
        "project_id": ("selects the review context", "registered at project setup"),
        "request": ("the audit request signal", "from the Mission Lock contract"),
        "skill_version": ("version compatibility gate", "declared in this skill's frontmatter"),
        "controller_version": ("permission model version gate", "injected by the Controller"),
        "timestamp": ("audit and reproducibility", "injected by the Controller at call time"),
        "targets": ("the artifacts under attack", "produce the conclusion/code/evidence to audit"),
        "target": ("one auditable artifact", "produce the claim/artifact to audit"),
        "citations": ("the references to verify", "attach the cited references"),
        "findings": ("the findings to score/block", "run the review pipeline first"),
        "claim": ("the claim to attack", "state the claim to be counter-exampled"),
        "evidence_chain": ("the evidence chain to check", "attach the reference chain"),
        "measurements": ("the numeric quantities to check", "attach the data table with units"),
        "reactions": ("the reaction scheme to balance", "attach the chemical equation(s)"),
        "model": ("the model specification", "attach the model equations and parameters"),
        "state_transition": ("the claimed state upgrade", "declare source -> target states"),
        "write_actions": ("the actions to check for scope", "list the write/permission claims"),
    }
    for field in required:
        value = payload.get(field)
        if value is None or value == "" or value == [] or value == {}:
            why, how = guidance.get(field, ("required for this operation", "provide it in the request"))
            missing.append({
                "field": field,
                "why_critical": why,
                "how_to_obtain": how,
            })
    return {"missing": missing}


def now_iso() -> str:
    import datetime
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def ensure_finite(value: Any) -> bool:
    import math
    if isinstance(value, bool):
        return True
    if isinstance(value, (int, float)):
        return math.isfinite(value)
    return True
