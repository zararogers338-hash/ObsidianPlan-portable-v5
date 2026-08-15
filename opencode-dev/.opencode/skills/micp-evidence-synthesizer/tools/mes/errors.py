"""OES error-code registry — single source of truth.

Error codes are machine-parseable by the controller (`code`) and human-readable
(`message`). `retryable` flags whether the caller may retry unchanged.
See SKILL.md §错误码体系 for the full table and message format.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass(frozen=True)
class ErrorSpec:
    code: str
    klass: str  # input | capability | dependency | policy | numeric | internal | state | version | budget
    default_message: str
    retryable: bool = False


# ---- registry ---------------------------------------------------------------

ERRORS: dict[str, ErrorSpec] = {
    "OES-E101": ErrorSpec("OES-E101", "input", "Input failed input.schema.json validation."),
    "OES-E102": ErrorSpec("OES-E102", "input", "Evidence refs missing, unverifiable, duplicate or corrupted."),
    "OES-E103": ErrorSpec("OES-E103", "input", "Unit or dimension mismatch across studies."),
    "OES-E104": ErrorSpec("OES-E104", "dependency", "Required dependent tool is unavailable.", retryable=True),
    "OES-E105": ErrorSpec("OES-E105", "policy", "Insufficient permission or permission denied."),
    "OES-E106": ErrorSpec("OES-E106", "capability", "Downstream capability is missing (NEED_ADDITIONAL_SKILL)."),
    "OES-E107": ErrorSpec("OES-E107", "policy", "Human approval not completed."),
    "OES-E108": ErrorSpec("OES-E108", "internal", "Output did not pass the output self-check."),
    "OES-E109": ErrorSpec("OES-E109", "state", "Context, evidence cards or files corrupted / unreadable."),
    "OES-E110": ErrorSpec("OES-E110", "budget", "Budget (tokens/cost/time/cards) exceeded."),
    "OES-E111": ErrorSpec("OES-E111", "numeric", "Non-finite, out-of-range or dimensionally invalid numeric value."),
    "OES-E112": ErrorSpec("OES-E112", "input", "Studies are not comparable for pooling; data must stay isolated."),
    "OES-E113": ErrorSpec("OES-E113", "input", "PICO/PECO core fields (population/intervention/outcome) missing."),
    "OES-E114": ErrorSpec("OES-E114", "input", "Insufficient evidence for quantitative pooling."),
    "OES-E115": ErrorSpec("OES-E115", "input", "Action is not supported by this skill."),
    "OES-E801": ErrorSpec("OES-E801", "version", "Contract/controller version is unsupported."),
    "OES-E802": ErrorSpec("OES-E802", "version", "skill_version unsupported by caller."),
}


@dataclass
class MesError(Exception):
    """Raised for tool-level failures that must surface as a typed error."""

    code: str
    message: str
    detail: Optional[dict] = None
    retryable: bool = False

    def __post_init__(self) -> None:
        spec = ERRORS.get(self.code)
        if spec is not None:
            self.retryable = spec.retryable

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "detail": self.detail or {},
            "retryable": self.retryable,
        }

    def __str__(self) -> str:  # pragma: no cover — debug aid
        return f"{self.code}: {self.message}"


class MesErrorCode:
    """Namespace of canonical code constants for call sites."""

    INPUT_SCHEMA = "OES-E101"
    EVIDENCE_UNVERIFIABLE = "OES-E102"
    UNIT_MISMATCH = "OES-E103"
    TOOL_UNAVAILABLE = "OES-E104"
    PERMISSION_DENIED = "OES-E105"
    CAPABILITY_MISSING = "OES-E106"
    APPROVAL_PENDING = "OES-E107"
    SELF_CHECK_FAILED = "OES-E108"
    CORRUPTION = "OES-E109"
    BUDGET_EXCEEDED = "OES-E110"
    NUMERIC_INVALID = "OES-E111"
    NOT_COMPARABLE = "OES-E112"
    PICO_MISSING = "OES-E113"
    INSUFFICIENT_POOLING = "OES-E114"
    ACTION_UNSUPPORTED = "OES-E115"
    VERSION_UNSUPPORTED = "OES-E801"
    SKILL_VERSION_UNSUPPORTED = "OES-E802"
