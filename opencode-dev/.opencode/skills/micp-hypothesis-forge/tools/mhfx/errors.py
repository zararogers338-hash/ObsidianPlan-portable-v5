"""Error-code taxonomy for micp-hypothesis-forge.

Single source of truth. Every failure the skill can produce carries one of
these codes so the Obsidian controller can route programmatically while humans
get a readable message. Codes are stable: never renumber, only append.

Layout: MHX-E<category><ordinal>
  1xx input contract         5xx approvals / permissions
  2xx evidence / units /     6xx downstream capabilities
      falsifiability         7xx self-check / output contract
  3xx context / file         8xx compatibility / migration
  4xx tooling / environment
"""

from __future__ import annotations

import enum


class MhfxErrorCode(enum.Enum):
    # 1xx — input contract
    INPUT_SCHEMA_VIOLATION = ("MHX-E101", "Input does not conform to schemas/input.schema.json.")
    MISSING_REQUIRED_FIELD = ("MHX-E102", "A key field required to forge hypotheses is absent.")
    INVALID_ACTION = ("MHX-E103", "Unknown action dispatched to the skill service.")
    INVALID_JSON = ("MHX-E104", "stdin is not a single valid JSON document.")
    INVALID_TYPE = ("MHX-E105", "A payload field has the wrong JSON type.")
    NON_FALSIFIABLE = ("MHX-E106", "A supplied statement is not falsifiable (no refutation condition).")
    UNKNOWN_REFERENCE = ("MHX-E107", "A node, evidence, or data reference cannot be resolved "
                                     "within the provided input.")

    # 2xx — evidence / units / epistemology
    EVIDENCE_UNVERIFIABLE = ("MHX-E201", "Evidence or data reference cannot be resolved or "
                                         "integrity-checked.")
    UNIT_INCONSISTENT = ("MHX-E202", "Observable variables or predictions carry incompatible "
                                     "or missing units.")
    UNIT_PARSE_ERROR = ("MHX-E203", "A unit string could not be parsed.")
    RANGE_OUT_OF_BOUNDS = ("MHX-E204", "A numeric value is outside the validated physical range.")
    EPISTEMIC_MISLABEL = ("MHX-E205", "A claim is labeled with an epistemic level stronger than "
                                      "its support.")

    # 3xx — context / file integrity
    CONTEXT_CORRUPT = ("MHX-E301", "A context or working file is damaged, truncated, or holds "
                                   "non-finite (NaN/Inf) numbers where real values are required.")
    INPUT_FILE_UNREADABLE = ("MHX-E302", "An input file referenced by the caller cannot be read.")

    # 4xx — tooling / environment
    TOOL_UNAVAILABLE = ("MHX-E401", "A required tool or library is not available in this "
                                    "environment.")
    TOOL_TIMEOUT = ("MHX-E402", "A tool call exceeded its time budget.")
    NUMERICAL_FAILURE = ("MHX-E403", "The numerical solver / scorer failed to converge.")
    INTERNAL = ("MHX-E404", "Unexpected internal failure.")

    # 5xx — approvals / permissions
    PERMISSION_DENIED = ("MHX-E501", "The acting role is not permitted to perform this action.")
    APPROVAL_REQUIRED = ("MHX-E502", "Action is gated on human approval that has not been "
                                     "granted (field deployment, live bio-experiment, hazardous "
                                     "chemical handling, long-term knowledge write).")

    # 6xx — downstream capabilities
    DOWNSTREAM_CAPABILITY_MISSING = ("MHX-E601", "Progress requires another skill that is not "
                                                 "available (e.g. experiment-designer, "
                                                 "evidence-synthesizer, modeling-optimizer).")
    DOWNSTREAM_CONTRACT_MISMATCH = ("MHX-E602", "An upstream artifact does not match its "
                                                "declared contract.")

    # 7xx — self-check / output contract
    OUTPUT_SCHEMA_VIOLATION = ("MHX-E701", "Skill output failed validation against "
                                          "schemas/output.schema.json.")
    SELF_CHECK_FAILED = ("MHX-E702", "Post-generation self-audit gate did not pass.")

    # 8xx — compatibility / migration
    UNSUPPORTED_SCHEMA_VERSION = ("MHX-E801", "Payload declares a contract version this build "
                                              "cannot consume.")
    MIGRATION_REQUIRED = ("MHX-E802", "Outputs written under an older major contract require "
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


class MhfxError(Exception):
    """Structured exception carrying an MhfxErrorCode plus machine-readable detail."""

    def __init__(
        self,
        code: MhfxErrorCode,
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
