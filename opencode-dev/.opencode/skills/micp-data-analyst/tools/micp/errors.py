"""Error-code taxonomy for micp-data-analyst.

Every failure the skill can produce carries one of these codes so the Obsidian
controller can route programmatically while humans get a readable message.
Codes are stable: never renumber, only append.

Layout: MDA-E<category><ordinal>
  1xx input contract        5xx approvals / permissions
  2xx evidence / units      6xx downstream capabilities
  3xx context / file        7xx self-check / output contract
  4xx tooling / environment 8xx compatibility / migration
"""

from __future__ import annotations

import enum

from _common import ToolError


class MdaErrorCode(enum.Enum):
    # 1xx — input contract
    INPUT_SCHEMA_VIOLATION = ("MDA-E101", "Input does not conform to schemas/input.schema.json.")
    MISSING_REQUIRED_FIELD = ("MDA-E102", "A key field required for the analysis is absent (BLOCKED).")
    INVALID_ANALYSIS_MODE = ("MDA-E103", "Unknown analysis mode dispatched to the service.")
    SAMPLES_UNDERSPECIFIED = ("MDA-E104", "samples present but data_columns missing/empty; cannot interpret rows.")
    RANGE_OUT_OF_BOUNDS = ("MDA-E105", "A numeric value is outside the validated range for this variable.")

    # 2xx — evidence / units
    EVIDENCE_UNVERIFIABLE = ("MDA-E201", "Evidence or data reference cannot be resolved or integrity-checked.")
    UNIT_INCONSISTENT = ("MDA-E202", "Quantities carry incompatible or missing units.")
    UNIT_PARSE_ERROR = ("MDA-E203", "A unit string could not be parsed.")
    MISSING_UNIT = ("MDA-E204", "A numeric variable is declared without a unit (required for reporting).")

    # 3xx — context / file integrity
    CONTEXT_CORRUPT = ("MDA-E301", "A context or working file is damaged, truncated, or non-finite (NaN/Inf) where a real number is required.")
    INPUT_FILE_UNREADABLE = ("MDA-E302", "An input file referenced by the caller cannot be read.")

    # 4xx — tooling / environment
    TOOL_UNAVAILABLE = ("MDA-E401", "A required tool or library is not available in this environment.")
    NUMERICAL_FAILURE = ("MDA-E402", "The numerical solver failed to converge.")

    # 5xx — approvals / permissions
    PERMISSION_DENIED = ("MDA-E501", "The acting role is not permitted to perform this action.")
    APPROVAL_REQUIRED = ("MDA-E502", "Action is gated on human approval that has not been granted (field deployment, live experiment, dangerous chemical handling, long-term knowledge write).")

    # 6xx — downstream capabilities
    DOWNSTREAM_CAPABILITY_MISSING = ("MDA-E601", "Progress requires another skill that is not available (e.g. micp-geotechnical-performance, modeling-optimizer, red-team).")
    DOWNSTREAM_CONTRACT_MISMATCH = ("MDA-E602", "An upstream artifact does not match its declared contract.")

    # 7xx — self-check / output contract
    OUTPUT_SCHEMA_VIOLATION = ("MDA-E701", "Skill output failed validation against schemas/output.schema.json.")
    SELF_CHECK_FAILED = ("MDA-E702", "Post-analysis self-check failed (non-finite result, empty statistics, or gate violation).")
    EPISTEMIC_MISLABEL = ("MDA-E703", "A claim is labeled with an epistemic level stronger than its support.")

    # 8xx — compatibility / migration
    VERSION_MISMATCH = ("MDA-E801", "Payload declares a contract version this build cannot consume.")
    MIGRATION_REQUIRED = ("MDA-E802", "Outputs written under an older major contract require explicit migration before use.")

    # 9xx — schema engine internal
    SCHEMA_ENGINE = ("MDA-E900", "Schema-engine internal error.")

    def __init__(self, code: str, default_message: str) -> None:
        self._code = code
        self._default_message = default_message

    @property
    def code(self) -> str:
        return self._code

    @property
    def default_message(self) -> str:
        return self._default_message


class MdaError(ToolError):
    """Structured exception carrying an MdaErrorCode plus machine-readable detail.

    Extends ToolError so every tool shares the envelope + exit-code machinery
    in _common.run_tool. `code` (the machine string), `message`, `details`,
    `retryable`, and `exit_code` are all inherited from ToolError.
    """

    def __init__(
        self,
        code: MdaErrorCode,
        message: str | None = None,
        *,
        detail: dict | None = None,
        retryable: bool = False,
        exit_code: int = 2,
    ) -> None:
        self.ecode = code
        super().__init__(
            code.code,
            message or code.default_message,
            retryable=retryable,
            details=detail or {},
            exit_code=exit_code,
        )

    def to_dict(self) -> dict:
        return {
            "code": self.code,
            "message": self.message,
            "detail": self.details,
            "retryable": self.retryable,
        }
