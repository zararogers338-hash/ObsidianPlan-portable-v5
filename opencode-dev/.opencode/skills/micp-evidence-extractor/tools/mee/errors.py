"""Error-code taxonomy for micp-evidence-extractor.

Every failure the skill can produce carries one of these codes so the Obsidian
controller can route programmatically while humans get a readable message.
Codes are stable: never renumber, only append.

Layout: MEE-E<category><ordinal>
  1xx input contract         5xx approvals / permissions
  2xx units / provenance     6xx downstream capabilities
  3xx source / adapters      7xx self-check / isolation
  4xx tooling / environment  8xx compatibility / migration
"""

from __future__ import annotations

import enum

from _common import ToolError


class MeeErrorCode(enum.Enum):
    # 1xx — input contract
    INPUT_SCHEMA_VIOLATION = ("MEE-E101", "Input does not conform to schemas/input.schema.json.")
    MISSING_REQUIRED_FIELD = ("MEE-E102", "A key field required for extraction is absent (BLOCKED).")
    NO_DOCUMENT_SOURCE = ("MEE-E103", "No document source provided: document / document_text / source_path all absent.")
    DOCUMENT_UNPARSEABLE = ("MEE-E104", "The provided document structure is not parseable as a source document.")

    # 2xx — units / provenance
    UNIT_PARSE_ERROR = ("MEE-E201", "A unit string could not be parsed.")
    UNIT_DIMENSION_CONFLICT = ("MEE-E202", "Two quantities with the same physical role carry incompatible dimensions.")
    UNIT_AMBIGUOUS = ("MEE-E203", "A quantity's unit is absent or ambiguous; normalized_value cannot be derived.")
    PROVENANCE_MISSING = ("MEE-E204", "A quantity or finding lacks a source locator (page/table/figure).")
    DOI_FORGED = ("MEE-E205", "DOI failed structural verification or metadata consistency.")

    # 3xx — source / adapters
    SOURCE_UNREADABLE = ("MEE-E301", "An input file referenced by the caller cannot be read.")
    ADAPTER_UNSUPPORTED = ("MEE-E302", "The source media type is not supported by any adapter.")
    PDF_CORRUPT = ("MEE-E303", "The PDF file is corrupt, truncated, or password-protected; text cannot be recovered.")
    HTML_PARSE_FAILED = ("MEE-E304", "HTML parsing produced no usable content.")
    CSV_PARSE_FAILED = ("MEE-E305", "CSV parsing failed or produced no rows.")

    # 4xx — tooling / environment
    TOOL_UNAVAILABLE = ("MEE-E401", "A required tool or library is not available in this environment.")
    FIGURE_DIGITIZATION_UNAVAILABLE = ("MEE-E402", "No image library is available for figure digitization.")

    # 5xx — approvals / permissions
    PERMISSION_DENIED = ("MEE-E501", "The acting role is not permitted to perform this action.")
    APPROVAL_REQUIRED = ("MEE-E502", "Action is gated on human approval that has not been granted.")

    # 6xx — downstream capabilities
    DOWNSTREAM_CAPABILITY_MISSING = ("MEE-E601", "Progress requires another skill that is not available.")
    DOWNSTREAM_CONTRACT_MISMATCH = ("MEE-E602", "An upstream artifact does not match its declared contract.")

    # 7xx — self-check / isolation
    OUTPUT_SCHEMA_VIOLATION = ("MEE-E701", "Skill output failed validation against schemas/output.schema.json.")
    CARD_SCHEMA_VIOLATION = ("MEE-E702", "One or more evidence cards failed validation against schemas/evidence-card.schema.json.")
    ISOLATION_VIOLATION = ("MEE-E703", "Experimental-group or time-point isolation check failed.")
    EPISTEMIC_MISLABEL = ("MEE-E704", "A claim is labeled with an epistemic level stronger than its support.")
    AMBIGUITY_NOT_FLAGGED = ("MEE-E705", "A value that should be AMBIGUOUS/NOT_REPORTED was recorded as reported.")

    # 8xx — compatibility / migration
    VERSION_MISMATCH = ("MEE-E801", "Payload declares a contract version this build cannot consume.")
    MIGRATION_REQUIRED = ("MEE-E802", "Outputs written under an older major contract require explicit migration before use.")

    # 9xx — schema engine internal
    SCHEMA_ENGINE = ("MEE-E900", "Schema-engine internal error.")

    def __init__(self, code: str, default_message: str) -> None:
        self._code = code
        self._default_message = default_message

    @property
    def code(self) -> str:
        return self._code

    @property
    def default_message(self) -> str:
        return self._default_message


class MeeError(ToolError):
    """Structured exception carrying an MeeErrorCode plus machine-readable detail."""

    def __init__(
        self,
        code: MeeErrorCode,
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
