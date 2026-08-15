"""Error-code taxonomy for obsidian-red-team.

Every failure the skill can produce carries one of these codes so the Obsidian
controller can route programmatically while humans get a readable message.
Codes are stable: never renumber, only append.

Layout: ORT-E<category><ordinal>
  1xx input contract        5xx approvals / permissions
  2xx evidence / units      6xx downstream capabilities
  3xx context / file        7xx self-check / output contract
  4xx tooling / environment 8xx compatibility / migration
"""

from __future__ import annotations

import enum

from common import ToolError


class OrtErrorCode(enum.Enum):
    # 1xx — input contract
    INPUT_SCHEMA_VIOLATION = ("ORT-E101", "Input does not conform to schemas/input.schema.json.")
    MISSING_TARGETS = ("ORT-E102", "No auditable target provided; a review needs at least one target to attack.")
    INVALID_MODE = ("ORT-E103", "Unknown review mode/subcommand dispatched to the service.")
    INVALID_VALUE = ("ORT-E104", "A constraint value (severity / state gate / dimension) is invalid.")

    # 2xx — evidence / units
    CITATION_UNVERIFIABLE = ("ORT-E201", "A reference cannot be verified offline (missing DOI/locator or malformed).")
    EVIDENCE_CHAIN_BROKEN = ("ORT-E202", "An evidence chain does not reach the claim: a link is unresolvable or inconsistent.")
    UNIT_INCONSISTENT = ("ORT-E203", "Quantities carry incompatible or missing units/dimensions.")
    ORDER_OF_MAGNITUDE = ("ORT-E204", "A numeric claim is off by orders of magnitude.")
    BALANCE_VIOLATION = ("ORT-E205", "A material/element/molar balance fails to close within the engineering tolerance.")
    PSEUDOREPLICATION = ("ORT-E206", "Non-independent samples are treated as independent (pseudo-replication).")
    MODEL_BOUNDARY = ("ORT-E207", "Model is applied outside its verified domain (missing BC, unidentifiable params, same-data cal/val, scale overflow).")
    STAT_STRUCTURE = ("ORT-E208", "Statistical reporting violates structure rules (p-only, selective reporting, effect-size omission, model assumptions).")
    REGULATION_UNVERIFIED = ("ORT-E209", "A deployment with regulatory exposure lacks any applicable-limit verification.")

    # 3xx — context / file integrity
    CONTEXT_CORRUPT = ("ORT-E301", "A context or working file is damaged, truncated, or non-finite.")
    INPUT_FILE_UNREADABLE = ("ORT-E302", "An input file referenced by the caller cannot be read.")

    # 4xx — tooling / environment
    TOOL_UNAVAILABLE = ("ORT-E401", "A required tool or library is not available in this environment.")
    NUMERICAL_FAILURE = ("ORT-E402", "A numerical computation failed to converge.")

    # 5xx — approvals / permissions
    PERMISSION_DENIED = ("ORT-E501", "The acting role is not permitted to perform this action.")
    APPROVAL_REQUIRED = ("ORT-E502", "Action is gated on human approval that has not been granted (field deployment, live experiment, long-term knowledge write).")
    WRITE_BOUNDARY = ("ORT-E503", "An action crosses the write boundary of this skill (mutating audited conclusions/data or long-term knowledge).")

    # 6xx — downstream capabilities
    DOWNSTREAM_CAPABILITY_MISSING = ("ORT-E601", "Progress requires another skill that is not available (e.g. decision-gate, biosafety-auditor).")
    DOWNSTREAM_CONTRACT_MISMATCH = ("ORT-E602", "An upstream artifact does not match its declared contract.")

    # 7xx — self-check / output contract
    OUTPUT_SCHEMA_VIOLATION = ("ORT-E701", "Skill output failed validation against schemas/output.schema.json.")
    SELF_CHECK_FAILED = ("ORT-E702", "Post-review self-check failed (blocking findings without REVIEW_FAIL/HOLD, or status inconsistency).")
    EPISTEMIC_MISLABEL = ("ORT-E703", "A claim is labeled with an epistemic level stronger than its support.")

    # 8xx — compatibility / migration
    VERSION_MISMATCH = ("ORT-E801", "Payload declares a contract version this build cannot consume.")
    MIGRATION_REQUIRED = ("ORT-E802", "Outputs written under an older major contract require explicit migration before use.")

    # 9xx — schema engine internal
    SCHEMA_ENGINE = ("ORT-E900", "Schema-engine internal error.")

    def __init__(self, code: str, default_message: str) -> None:
        self._code = code
        self._default_message = default_message

    @property
    def code(self) -> str:
        return self._code

    @property
    def default_message(self) -> str:
        return self._default_message


class OrtError(ToolError):
    """Structured exception carrying an OrtErrorCode plus machine-readable detail."""

    def __init__(
        self,
        code: OrtErrorCode,
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
