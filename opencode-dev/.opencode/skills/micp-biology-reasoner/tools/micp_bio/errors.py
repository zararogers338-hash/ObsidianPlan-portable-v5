"""Error-code taxonomy for micp-biology-reasoner.

Every failure the skill can produce carries one of these codes so the
Obsidian controller can route programmatically while humans get a readable
message. Codes are stable: never renumber, only append.

Layout: MBR-E<category><ordinal>
  1xx input contract        5xx approvals / permissions
  2xx evidence / units      6xx downstream capabilities
  3xx data / context        7xx self-check / output contract
  4xx tooling / environment 8xx deprecated-compatibility
"""

from __future__ import annotations

import enum
from typing import Any


class MbrErrorCode(enum.Enum):
    # 1xx — input contract
    INPUT_SCHEMA_VIOLATION = ("MBR-E101", "Input does not conform to schemas/input.schema.json.")
    MISSING_REQUIRED_FIELD = ("MBR-E102", "A required input field is absent.")

    # 2xx — evidence / units / biology
    EVIDENCE_UNRESOLVABLE = ("MBR-E201", "An evidence/data reference cannot be resolved.")
    EVIDENCE_UNVERIFIABLE = ("MBR-E202", "Evidence or data is not independently verifiable (no sha256, no resolvable source).")
    UNIT_INCONSISTENT = ("MBR-E203", "Quantities carry incompatible or missing units (e.g. activity without a unit).")
    OD_NOT_ACTIVITY = ("MBR-E204", "OD600 (a biomass proxy) is being used as if it were urease activity.")
    NON_UREOLYTIC_MODEL_MISAPPLIED = ("MBR-E205", "A urea-hydrolysis model was applied to a non-ureolytic pathway.")
    STRAIN_NAME_INFERRED = ("MBR-E206", "Field performance was inferred from a strain name without measurement data.")

    # 3xx — data / context integrity
    CONTEXT_CORRUPT = ("MBR-E301", "Context or input data file is damaged or truncated.")
    NUMERIC_INVALID = ("MBR-E302", "A numeric value is NaN/Inf or out of a physically valid range.")

    # 4xx — tooling / environment
    TOOL_UNAVAILABLE = ("MBR-E401", "A required tool or dependency is not available.")
    TOOL_TIMEOUT = ("MBR-E402", "A tool call exceeded its time budget.")

    # 5xx — approvals / permissions
    PERMISSION_DENIED = ("MBR-E501", "The acting role is not permitted to perform this action.")
    APPROVAL_REQUIRED = ("MBR-E502", "Action is gated on human approval that has not been granted.")

    # 6xx — downstream capabilities
    DOWNSTREAM_CAPABILITY_MISSING = ("MBR-E601", "Progress requires another skill that is not available.")
    UPSTREAM_CONTRACT_MISMATCH = ("MBR-E602", "An upstream artifact does not match its declared contract.")

    # 7xx — self-check / output contract
    OUTPUT_SCHEMA_VIOLATION = ("MBR-E701", "Skill output failed validation against schemas/output.schema.json.")
    SELF_CHECK_FAILED = ("MBR-E702", "Post-action self-check failed (result does not reproduce / labels inconsistent).")

    # 8xx — compatibility
    UNSUPPORTED_SCHEMA_VERSION = ("MBR-E801", "Payload declares a contract version this build cannot consume.")
    MIGRATION_REQUIRED = ("MBR-E802", "Artifact predates the current contract and needs explicit migration.")

    def __init__(self, code: str, default_message: str) -> None:
        self._code = code
        self._default_message = default_message

    @property
    def code(self) -> str:
        return self._code

    @property
    def default_message(self) -> str:
        return self._default_message


class MbrError(Exception):
    """Structured exception carrying an MbrErrorCode plus machine-readable detail."""

    def __init__(
        self,
        code: MbrErrorCode,
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
