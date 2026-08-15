"""Error-code taxonomy for micp-modeling-optimizer.

Every failure the skill can produce carries one of these codes so the Obsidian
controller can route programmatically while humans get a readable message.
Codes are stable: never renumber, only append.

Layout: MMO-E<category><ordinal>
  1xx input contract          5xx approvals / permissions
  2xx evidence / units        6xx downstream capabilities
  3xx context / file          7xx self-check / output contract
  4xx tooling / environment   8xx compatibility / migration
"""

from __future__ import annotations

import enum

from _common import ToolError


class MmoErrorCode(enum.Enum):
    # 1xx — input contract
    INPUT_SCHEMA_VIOLATION = (
        "MMO-E101",
        "Input does not conform to schemas/input.schema.json.",
    )
    MISSING_REQUIRED_FIELD = (
        "MMO-E102",
        "A key field required to build the model is absent (MODEL_BLOCKED).",
    )
    INVALID_ACTION = ("MMO-E103", "Unknown action dispatched to the service.")
    INVALID_MODEL_SPEC = (
        "MMO-E104",
        "The model specification is structurally invalid or self-inconsistent.",
    )
    INVALID_OBJECTIVE = (
        "MMO-E105",
        "The objective/constraint specification is invalid.",
    )
    INVALID_PARAM_DEF = (
        "MMO-E106",
        "A parameter definition (bounds, source, role) is invalid.",
    )

    # 2xx — evidence / units
    EVIDENCE_UNVERIFIABLE = (
        "MMO-E201",
        "Evidence or data reference cannot be resolved or integrity-checked.",
    )
    UNIT_INCONSISTENT = (
        "MMO-E202",
        "Quantities carry incompatible or missing units.",
    )
    UNIT_PARSE_ERROR = ("MMO-E203", "A unit string could not be parsed.")
    RANGE_OUT_OF_BOUNDS = (
        "MMO-E204",
        "A physical parameter is outside the validated range for this model scale.",
    )

    # 3xx — context / file integrity
    CONTEXT_CORRUPT = (
        "MMO-E301",
        "A context or working file is damaged, truncated, or non-finite "
        "(NaN/Inf) where a real number is required.",
    )
    INPUT_FILE_UNREADABLE = (
        "MMO-E302",
        "An input file referenced by the caller cannot be read.",
    )

    # 4xx — tooling / environment
    TOOL_UNAVAILABLE = (
        "MMO-E401",
        "A required tool or library is not available in this environment.",
    )
    NUMERICAL_FAILURE = (
        "MMO-E402",
        "A numerical solver, optimizer, or sampler failed to converge.",
    )
    CONSERVATION_VIOLATION = (
        "MMO-E403",
        "The model violates mass conservation (self-check failed).",
    )
    NUMERICAL_INSTABILITY = (
        "MMO-E404",
        "The model is numerically unstable under the requested scheme/grid.",
    )
    IDENTIFIABILITY_FAILURE = (
        "MMO-E405",
        "Parameter identifiability analysis failed or produced no usable "
        "result (e.g. Fisher information singular).",
    )

    # 5xx — approvals / permissions
    PERMISSION_DENIED = ("MMO-E501", "The acting role is not permitted to perform this action.")
    APPROVAL_REQUIRED = (
        "MMO-E502",
        "Action is gated on human approval that has not been granted (field "
        "deployment, live experiment, dangerous chemical handling, long-term "
        "knowledge write).",
    )

    # 6xx — downstream capabilities
    DOWNSTREAM_CAPABILITY_MISSING = (
        "MMO-E601",
        "Progress requires another skill that is not available (e.g. "
        "micp-geotechnical-performance, experiment-designer, red-team).",
    )
    DOWNSTREAM_CONTRACT_MISMATCH = (
        "MMO-E602",
        "An upstream artifact does not match its declared contract.",
    )

    # 7xx — self-check / output contract
    OUTPUT_SCHEMA_VIOLATION = (
        "MMO-E701",
        "Skill output failed validation against schemas/output.schema.json.",
    )
    SELF_CHECK_FAILED = (
        "MMO-E702",
        "Post-analysis self-check failed (conservation error, non-finite "
        "result, or grid-sensitivity mismatch).",
    )
    EPISTEMIC_MISLABEL = (
        "MMO-E703",
        "A claim is labeled with an epistemic level stronger than its support.",
    )

    # 8xx — compatibility / migration
    UNSUPPORTED_SCHEMA_VERSION = (
        "MMO-E801",
        "Payload declares a contract version this build cannot consume.",
    )
    MIGRATION_REQUIRED = (
        "MMO-E802",
        "Outputs written under an older major contract require explicit "
        "migration before use.",
    )

    def __init__(self, code: str, default_message: str) -> None:
        self._code = code
        self._default_message = default_message

    @property
    def code(self) -> str:
        return self._code

    @property
    def default_message(self) -> str:
        return self._default_message


class MmoError(ToolError):
    """Structured exception carrying an MmoErrorCode plus machine-readable detail."""

    def __init__(
        self,
        code: MmoErrorCode,
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
            details=detail or {},
            retryable=retryable,
            exit_code=exit_code,
        )

    def to_dict(self) -> dict:
        return {
            "code": self.code,
            "message": self.message,
            "detail": self.details,
            "retryable": self.retryable,
        }
