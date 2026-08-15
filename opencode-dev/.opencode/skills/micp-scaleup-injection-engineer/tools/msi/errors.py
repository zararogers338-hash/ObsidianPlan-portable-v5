"""Error-code taxonomy for micp-scaleup-injection-engineer.

Every failure the skill can produce carries one of these codes so the Obsidian
controller can route programmatically while humans get a readable message.
Codes are stable: never renumber, only append.

Layout: MSI-E<category><ordinal>
  1xx input contract        5xx approvals / permissions
  2xx evidence / units      6xx downstream capabilities
  3xx context / file        7xx self-check / output contract
  4xx tooling / environment 8xx compatibility / migration
"""

from __future__ import annotations

import enum


class OpErrorCode(enum.Enum):
    # 1xx — input contract
    INPUT_SCHEMA_VIOLATION = ("MSI-E101", "Input does not conform to schemas/input.schema.json.")
    MISSING_REQUIRED_FIELD = ("MSI-E102", "A key field required to build the scale-up plan is "
                                          "absent (BLOCKED).")
    INVALID_ACTION = ("MSI-E103", "Unknown action dispatched to the service.")
    INVALID_SCENARIO = ("MSI-E104", "Scenario definition is structurally invalid.")

    # 2xx — evidence / units
    EVIDENCE_UNVERIFIABLE = ("MSI-E201", "Evidence or data reference cannot be resolved or "
                                         "integrity-checked.")
    UNIT_INCONSISTENT = ("MSI-E202", "Quantities carry incompatible or missing units.")
    UNIT_PARSE_ERROR = ("MSI-E203", "A unit string could not be parsed.")
    RANGE_OUT_OF_BOUNDS = ("MSI-E204", "A physical parameter is outside the validated range for "
                                       "this scale level.")

    # 3xx — context / file integrity
    CONTEXT_CORRUPT = ("MSI-E301", "A context or working file is damaged, truncated, or "
                                   "non-finite (NaN/Inf) where a real number is required.")
    INPUT_FILE_UNREADABLE = ("MSI-E302", "An input file referenced by the caller cannot be read.")

    # 4xx — tooling / environment
    TOOL_UNAVAILABLE = ("MSI-E401", "A required tool or library is not available in this "
                                    "environment.")
    TOOL_TIMEOUT = ("MSI-E402", "A tool call exceeded its time budget.")
    NUMERICAL_FAILURE = ("MSI-E403", "A numerical computation failed to converge.")

    # 5xx — approvals / permissions
    PERMISSION_DENIED = ("MSI-E501", "The acting role is not permitted to perform this action.")
    APPROVAL_REQUIRED = ("MSI-E502", "Action is gated on human approval that has not been "
                                     "granted (field deployment gate: geotechnical sign-off, "
                                     "biosafety review, regulatory verification, construction "
                                     "risk, waste/ammonia plan, emergency plan).")

    # 6xx — downstream capabilities
    DOWNSTREAM_CAPABILITY_MISSING = ("MSI-E601", "Progress requires another skill that is not "
                                                 "available (e.g. micp-porous-media-transport, "
                                                 "micp-geotechnical-performance).")
    DOWNSTREAM_CONTRACT_MISMATCH = ("MSI-E602", "An upstream artifact does not match its declared "
                                                "contract.")

    # 7xx — self-check / output contract
    OUTPUT_SCHEMA_VIOLATION = ("MSI-E701", "Skill output failed validation against "
                                           "schemas/output.schema.json.")
    SELF_CHECK_FAILED = ("MSI-E702", "Post-analysis self-check failed (mass balance, "
                                     "conservation, or threshold inconsistency).")
    EPISTEMIC_MISLABEL = ("MSI-E703", "A claim is labeled with an epistemic level stronger than "
                                      "its support.")

    # 8xx — compatibility / migration
    UNSUPPORTED_SCHEMA_VERSION = ("MSI-E801", "Payload declares a contract version this build "
                                              "cannot consume.")
    MIGRATION_REQUIRED = ("MSI-E802", "Outputs written under an older major contract require "
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
