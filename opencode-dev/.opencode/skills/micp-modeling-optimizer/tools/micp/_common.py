"""Shared constants, epistemic labels, status enums, and CLI plumbing for the
micp-modeling-optimizer skill.

Dependency-free (stdlib only) so the whole tool suite runs offline and can be
imported from tests without installing anything. scipy/numpy are optional
numerical backends used by the heavier analysis modules; every module degrades
to documented stdlib math when they are absent.
"""

from __future__ import annotations

import enum
import json
import math
import random
import sys
import time
from typing import Any, Callable

SKILL_NAME = "micp-modeling-optimizer"
SKILL_VERSION = "1.0.0"
CONTRACT_VERSION = "1.0"

# Allowed output statuses — mirrors the unified envelope of the sibling skills.
STATUSES = (
    "SUCCESS",
    "PARTIAL",
    "BLOCKED",
    "FAILED",
    "NEED_ADDITIONAL_SKILL",
    "HUMAN_APPROVAL_REQUIRED",
)

# Epistemic labels. INFERRED / HYPOTHESIS / RECOMMENDATION may never be
# reported as OBSERVED.
EPISTEMIC_LABELS = (
    "OBSERVED",
    "REPORTED",
    "CALCULATED",
    "INFERRED",
    "HYPOTHESIS",
    "RECOMMENDATION",
)


class OutputStatus(str, enum.Enum):
    SUCCESS = "SUCCESS"
    PARTIAL = "PARTIAL"
    BLOCKED = "BLOCKED"
    FAILED = "FAILED"
    NEED_ADDITIONAL_SKILL = "NEED_ADDITIONAL_SKILL"
    HUMAN_APPROVAL_REQUIRED = "HUMAN_APPROVAL_REQUIRED"


class EpistemicLabel(str, enum.Enum):
    OBSERVED = "OBSERVED"
    REPORTED = "REPORTED"
    CALCULATED = "CALCULATED"
    INFERRED = "INFERRED"
    HYPOTHESIS = "HYPOTHESIS"
    RECOMMENDATION = "RECOMMENDATION"


# ---- Stoichiometry & physical constants (sources in references/sources.md) ----
# Urea hydrolysis: 1 urea -> 2 NH4+ + 1 HCO3- (carbonate species). This is the
# canonical MICP stoichiometry used across the Ebigbo (2012) / Hommel (2015)
# reactive-transport lineage.
UREA_TO_AMMONIUM = 2.0
UREA_TO_CARBONATE = 1.0
UREA_MOLAR_MASS = 60.06        # g/mol
CACO3_MOLAR_MASS = 100.0869    # g/mol
CA_MOLAR_MASS = 40.078         # g/mol
N_MOLAR_MASS = 14.0067         # g/mol
CACO3_DENSITY = 2711.0         # kg/m3 (calcite)

# Optional scientific backends
try:  # pragma: no cover - environment dependent
    import numpy as np  # type: ignore

    HAS_NUMPY = True
except Exception:  # pragma: no cover
    HAS_NUMPY = False

try:  # pragma: no cover - environment dependent
    import scipy  # type: ignore

    HAS_SCIPY = True
except Exception:  # pragma: no cover
    HAS_SCIPY = False

try:  # pragma: no cover - environment dependent
    import jsonschema  # type: ignore

    HAS_JSONSCHEMA = True
except Exception:  # pragma: no cover
    HAS_JSONSCHEMA = False


class ToolError(Exception):
    """Structured error carrying code / message / details / retryable / exit_code.

    exit_code semantics (documented in tools/README.md):
      0  envelope produced (status field carries the outcome)
      2  malformed or unusable payload / hard contract violation
      3  tooling unavailable (missing dependency)
      4  internal engine failure
    """

    def __init__(
        self,
        code: str,
        message: str,
        *,
        details: dict | None = None,
        retryable: bool = False,
        exit_code: int = 2,
    ) -> None:
        self.code = code
        self.message = message
        self.details = details or {}
        self.retryable = retryable
        self.exit_code = exit_code
        super().__init__(message)


# ---------------------------------------------------------------------------
# CLI plumbing
# ---------------------------------------------------------------------------

def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def envelope_ok(tool: str, version: str, result: Any) -> dict:
    return {"ok": True, "tool": tool, "version": version, "result": result}


def envelope_err(tool: str, version: str, err: Exception) -> dict:
    if isinstance(err, ToolError):
        return {
            "ok": False,
            "tool": tool,
            "version": version,
            "error": {
                "code": err.code,
                "message": err.message,
                "details": err.details,
                "retryable": err.retryable,
            },
        }
    return {
        "ok": False,
        "tool": tool,
        "version": version,
        "error": {"code": "E_INTERNAL", "message": str(err), "details": {}, "retryable": False},
    }


def run_tool(tool: str, handler: Callable[[dict], Any]) -> int:
    """Read one JSON object from stdin, dispatch, write one JSON object to
    stdout. Exit codes per tools/README.md."""
    raw = sys.stdin.read()
    try:
        payload = json.loads(raw)
        if not isinstance(payload, dict):
            raise ToolError("E_INPUT_VALUE", "payload must be a JSON object")
    except (json.JSONDecodeError, ToolError) as exc:
        print(json.dumps(envelope_err(tool, SKILL_VERSION, exc), ensure_ascii=False))
        code = exc.exit_code if isinstance(exc, ToolError) else 2
        return code
    try:
        result = handler(payload)
        print(json.dumps(envelope_ok(tool, SKILL_VERSION, result), ensure_ascii=False))
        return 0
    except ToolError as exc:
        print(json.dumps(envelope_err(tool, SKILL_VERSION, exc), ensure_ascii=False))
        return exc.exit_code
    except Exception as exc:  # pragma: no cover - defensive
        print(json.dumps(envelope_err(tool, SKILL_VERSION, exc), ensure_ascii=False))
        return 4


# ---------------------------------------------------------------------------
# Safe type extraction helpers
# ---------------------------------------------------------------------------

def as_dict(value: Any, name: str) -> dict:
    if not isinstance(value, dict):
        raise ToolError("E_TYPE", f"{name} must be an object", details={"field": name})
    return value


def as_str(value: Any, name: str, min_len: int = 0, max_len: int | None = None) -> str:
    if not isinstance(value, str):
        raise ToolError("E_TYPE", f"{name} must be a string", details={"field": name})
    if len(value) < min_len:
        raise ToolError("E_INPUT_VALUE", f"{name} must be at least {min_len} chars", details={"field": name})
    if max_len is not None and len(value) > max_len:
        raise ToolError("E_INPUT_VALUE", f"{name} must be at most {max_len} chars", details={"field": name})
    return value


def as_int(value: Any, name: str, min_v: int | None = None, max_v: int | None = None) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ToolError("E_TYPE", f"{name} must be an integer", details={"field": name})
    if min_v is not None and value < min_v:
        raise ToolError("E_INPUT_VALUE", f"{name} must be >= {min_v}", details={"field": name, "value": value})
    if max_v is not None and value > max_v:
        raise ToolError("E_INPUT_VALUE", f"{name} must be <= {max_v}", details={"field": name, "value": value})
    return value


def as_number(value: Any, name: str, min_v: float | None = None, max_v: float | None = None) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ToolError("E_TYPE", f"{name} must be a number", details={"field": name})
    out = float(value)
    if not math.isfinite(out):
        raise ToolError("E_INPUT_VALUE", f"{name} must be finite", details={"field": name})
    if min_v is not None and out < min_v:
        raise ToolError("E_INPUT_VALUE", f"{name} must be >= {min_v}", details={"field": name, "value": out})
    if max_v is not None and out > max_v:
        raise ToolError("E_INPUT_VALUE", f"{name} must be <= {max_v}", details={"field": name, "value": out})
    return out


def as_bool(value: Any, name: str) -> bool:
    if not isinstance(value, bool):
        raise ToolError("E_TYPE", f"{name} must be a boolean", details={"field": name})
    return value


def emit_progress(msg: str) -> None:
    """Progress notes go to stderr; stdout stays machine-pure."""
    print(f"[micp-modeling-optimizer] {msg}", file=sys.stderr)


def seeded_rng(seed: int) -> random.Random:
    """Deterministic, offline RNG. `random_seed` must be fixed for reproducibility."""
    return random.Random(seed)
