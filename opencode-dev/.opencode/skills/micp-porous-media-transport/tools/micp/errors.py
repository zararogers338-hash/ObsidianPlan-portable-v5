"""Error-code taxonomy for micp-porous-media-transport.

Every failure the skill can produce carries one of these codes so the Obsidian
controller can route programmatically while humans get a readable message.
Codes are stable: never renumber, only append.

Layout: OPM-E<category><ordinal>
  1xx input contract        5xx approvals / permissions
  2xx evidence / units      6xx downstream capabilities
  3xx context / file        7xx self-check / output contract
  4xx tooling / environment 8xx compatibility / migration
"""

from __future__ import annotations

import enum


class OpErrorCode(enum.Enum):
    # 1xx — input contract
    INPUT_SCHEMA_VIOLATION = ("OPM-E101", "Input does not conform to schemas/input.schema.json.")
    MISSING_REQUIRED_FIELD = ("OPM-E102", "A key field required to build the model is absent "
                                          "(MODEL_BLOCKED).")
    INVALID_ACTION = ("OPM-E103", "Unknown action dispatched to the service.")
    INVALID_SCENARIO = ("OPM-E104", "Scenario definition is structurally invalid.")

    # 2xx — evidence / units
    EVIDENCE_UNVERIFIABLE = ("OPM-E201", "Evidence or data reference cannot be resolved or "
                                          "integrity-checked.")
    UNIT_INCONSISTENT = ("OPM-E202", "Quantities carry incompatible or missing units.")
    UNIT_PARSE_ERROR = ("OPM-E203", "A unit string could not be parsed.")
    RANGE_OUT_OF_BOUNDS = ("OPM-E204", "A physical parameter is outside the validated range for "
                                       "this model scale.")

    # 3xx — context / file integrity
    CONTEXT_CORRUPT = ("OPM-E301", "A context or working file is damaged, truncated, or "
                                    "non-finite (NaN/Inf) where a real number is required.")
    INPUT_FILE_UNREADABLE = ("OPM-E302", "An input file referenced by the caller cannot be read.")

    # 4xx — tooling / environment
    TOOL_UNAVAILABLE = ("OPM-E401", "A required tool or library is not available in this "
                                     "environment.")
    TOOL_TIMEOUT = ("OPM-E402", "A tool call exceeded its time budget.")
    NUMERICAL_FAILURE = ("OPM-E403", "The numerical solver failed to converge.")

    # 5xx — approvals / permissions
    PERMISSION_DENIED = ("OPM-E501", "The acting role is not permitted to perform this action.")
    APPROVAL_REQUIRED = ("OPM-E502", "Action is gated on human approval that has not been "
                                     "granted (field deployment, live experiment, dangerous "
                                     "chemical handling, long-term knowledge write).")

    # 6xx — downstream capabilities
    DOWNSTREAM_CAPABILITY_MISSING = ("OPM-E601", "Progress requires another skill that is not "
                                                  "available (e.g. mineral-phase-interpreter, "
                                                  "experiment-designer, modeling-optimizer).")
    DOWNSTREAM_CONTRACT_MISMATCH = ("OPM-E602", "An upstream artifact does not match its declared "
                                                 "contract.")

    # 7xx — self-check / output contract
    OUTPUT_SCHEMA_VIOLATION = ("OPM-E701", "Skill output failed validation against "
                                           "schemas/output.schema.json.")
    SELF_CHECK_FAILED = ("OPM-E702", "Post-analysis self-check failed (conservation error, "
                                     "non-finite result, or grid-sensitivity mismatch).")
    EPISTEMIC_MISLABEL = ("OPM-E703", "A claim is labeled with an epistemic level stronger than "
                                       "its support.")

    # 8xx — compatibility / migration
    UNSUPPORTED_SCHEMA_VERSION = ("OPM-E801", "Payload declares a contract version this build "
                                               "cannot consume.")
    MIGRATION_REQUIRED = ("OPM-E802", "Outputs written under an older major contract require "
                                       "explicit migration before use.")

    def __init__(self, code: str, default_message: str) -> None:
        self._code = code
        self._default_message = default_message

    @property
    def code(self) -> str:
        return self._code

    @property
    def default_message(self) -> str:
        return self._default_message


class OpError(Exception):
    """Structured exception carrying an OpErrorCode plus machine-readable detail."""

    def __init__(
        self,
        code: OpErrorCode,
        message: str | None = None,
        *,
        detail: dict | None = None,
        retryable: bool = False,
    ) -> None:
        self.code = code
        self.detail = detail or {}
        self.retryable = retryable
        super().__init__(message or code.default_message)

    @property
    def message(self) -> str:
        return str(self.args[0])

    def to_dict(self) -> dict:
        return {
            "code": self.code.code,
            "message": self.message,
            "detail": self.detail,
            "retryable": self.retryable,
        }
