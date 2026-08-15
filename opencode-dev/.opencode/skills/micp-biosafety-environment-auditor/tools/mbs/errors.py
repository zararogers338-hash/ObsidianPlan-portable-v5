"""Error-code taxonomy for micp-biosafety-environment-auditor.

Every failure the skill can produce carries one of these codes so the
Obsidian controller can route programmatically while humans get a readable
message. Codes are stable: never renumber, only append.

Layout: MBS-E<category><ordinal>
  1xx input contract        5xx approvals / permissions
  2xx evidence / regulatory  6xx downstream capabilities
  3xx data / conservation    7xx self-check / output contract
  4xx tooling / environment  8xx deprecated-compatibility
"""

from __future__ import annotations

import enum
from typing import Any


class MbsErrorCode(enum.Enum):
    # 1xx — input contract
    INPUT_SCHEMA_VIOLATION = ("MBS-E101", "Input does not conform to schemas/input.schema.json.")
    MISSING_REQUIRED_FIELD = ("MBS-E102", "A required input field is absent.")

    # 2xx — evidence / regulatory / strain
    REGULATION_UNVERIFIABLE = ("MBS-E201", "Applicable regulation or limit value cannot be verified. Mark REGULATORY_VERIFICATION_REQUIRED; do not fabricate.")
    REGULATION_STALE = ("MBS-E202", "Regulatory record is stale or past its verification horizon; re-verify before use.")
    STRAIN_IDENTITY_UNKNOWN = ("MBS-E203", "Strain identity is unknown or unverifiable; biosafety classification cannot be trusted.")
    EVIDENCE_UNRESOLVABLE = ("MBS-E204", "An evidence/data reference cannot be resolved.")
    BYPASS_REQUESTED = ("MBS-E205", "A request to bypass permit, biosafety or waste-management process was refused.")

    # 3xx — data / conservation / context
    MASS_BALANCE_CLOSED = ("MBS-E301", "Nitrogen mass balance does not close within tolerance; environmental conclusions are blocked.")
    NUMERIC_INVALID = ("MBS-E302", "A numeric value is NaN/Inf or out of a physically valid range.")
    CONTEXT_CORRUPT = ("MBS-E303", "Context or input data file is damaged or truncated.")

    # 4xx — tooling / environment
    TOOL_UNAVAILABLE = ("MBS-E401", "A required tool or dependency is not available.")
    TOOL_TIMEOUT = ("MBS-E402", "A tool call exceeded its time budget.")

    # 5xx — approvals / permissions
    PERMISSION_DENIED = ("MBS-E501", "The acting role is not permitted to perform this action.")
    APPROVAL_REQUIRED = ("MBS-E502", "Action is gated on human approval that has not been granted.")

    # 6xx — downstream capabilities
    DOWNSTREAM_CAPABILITY_MISSING = ("MBS-E601", "Progress requires another skill that is not available.")
    UPSTREAM_CONTRACT_MISMATCH = ("MBS-E602", "An upstream artifact does not match its declared contract.")

    # 7xx — self-check / output contract
    OUTPUT_SCHEMA_VIOLATION = ("MBS-E701", "Skill output failed validation against schemas/output.schema.json.")
    SELF_CHECK_FAILED = ("MBS-E702", "Post-action self-check failed (result does not reproduce / labels inconsistent).")

    # 8xx — compatibility
    UNSUPPORTED_SCHEMA_VERSION = ("MBS-E801", "Payload declares a contract version this build cannot consume.")
    MIGRATION_REQUIRED = ("MBS-E802", "Artifact predates the current contract and needs explicit migration.")

    def __init__(self, code: str, default_message: str) -> None:
        self._code = code
        self._default_message = default_message

    @property
    def code(self) -> str:
        return self._code

    @property
    def default_message(self) -> str:
        return self._default_message


class MbsError(Exception):
    """Structured exception carrying an MbsErrorCode plus machine-readable detail."""

    def __init__(
        self,
        code: MbsErrorCode,
        message: str | None = None,
        *,
        detail: dict[str, Any] | None = None,
        retryable: bool = False,
    ) -> None:
        self.code = code
        self.detail = detail or {}
        self.retryable = retryable
        super().__init__(message or code.default_message)

    @property
    def message(self) -> str:
        return str(self.args[0])

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code.code,
            "message": self.message,
            "detail": self.detail,
            "retryable": self.retryable,
        }
