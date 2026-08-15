"""Error-code taxonomy for micp-reproducibility-versioning.

Every failure the skill can produce carries one of these codes so the Obsidian
controller can route programmatically while humans get a readable message.
Codes are stable: never renumber, only append.

Layout: MRV-E<category><ordinal>
  1xx input contract          5xx approvals / permissions / integrity gates
  2xx integrity / evidence    6xx downstream capabilities
  3xx context / files / exec  7xx self-check / output contract
  4xx tooling / environment   8xx compatibility / migration
"""

from __future__ import annotations

import enum

from _common import ToolError


class MrvErrorCode(enum.Enum):
    # 1xx — input contract
    INPUT_SCHEMA_VIOLATION = ("MRV-E101", "Input does not conform to schemas/input.schema.json.")
    MISSING_REQUIRED_FIELD = ("MRV-E102", "A key field required for governance is absent (BLOCKED).")
    UNKNOWN_ACTION = ("MRV-E103", "Unknown governance action dispatched to the service.")
    ROOT_UNREADABLE = ("MRV-E104", "root is not a readable directory.")
    NO_REPRODUCTION_COMMANDS = ("MRV-E105", "reproduce requires a commands array of steps.")
    ACTION_AMBIGUOUS = ("MRV-E106", "No explicit action and the request text is ambiguous; provide action= explicitly.")

    # 2xx — integrity / evidence
    HASH_UNVERIFIABLE = ("MRV-E201", "A reference or hash cannot be verified.")
    FILE_HASH_MISMATCH = ("MRV-E202", "File content does not match the registered hash (tamper/pollution).")
    MANIFEST_INCONSISTENT = ("MRV-E203", "Data manifest is inconsistent with the registered fingerprints.")
    PROVENANCE_CHAIN_BROKEN = ("MRV-E204", "Provenance log hash chain is broken (tampering detected).")

    # 3xx — context / files / execution
    CONTEXT_CORRUPT = ("MRV-E301", "A context or working file is damaged, truncated, or non-finite.")
    PATH_OUT_OF_BOUNDS = ("MRV-E302", "A path escapes the governance root or is unreadable.")
    COMMAND_FAILED = ("MRV-E303", "A reproduction command failed or timed out.")

    # 4xx — tooling / environment
    TOOL_UNAVAILABLE = ("MRV-E401", "A required tool or runtime is not available in this environment.")
    DEPENDENCY_RESOLUTION_FAILED = ("MRV-E402", "Dependency export/resolution failed.")

    # 5xx — approvals / permissions / integrity gates
    PERMISSION_DENIED = ("MRV-E501", "The acting role is not permitted to perform this action.")
    APPROVAL_REQUIRED = ("MRV-E502", "Action is gated on human approval that has not been granted (field deployment, live experiment, dangerous chemical handling, long-term knowledge write).")
    SENSITIVE_DATA_UNCARED = ("MRV-E503", "Sensitive data lacks access control or masking.")

    # 6xx — downstream capabilities
    DOWNSTREAM_CAPABILITY_MISSING = ("MRV-E601", "Progress requires another skill that is not available.")
    DOWNSTREAM_CONTRACT_MISMATCH = ("MRV-E602", "An upstream artifact does not match its declared contract.")

    # 7xx — self-check / output contract
    OUTPUT_SCHEMA_VIOLATION = ("MRV-E701", "Skill output failed validation against schemas/output.schema.json.")
    SELF_CHECK_FAILED = ("MRV-E702", "Post-reproduction self-check failed.")
    EPISTEMIC_MISLABEL = ("MRV-E703", "A claim is labeled with an epistemic level stronger than its support.")

    # 8xx — compatibility / migration
    VERSION_MISMATCH = ("MRV-E801", "Payload declares a contract version this build cannot consume.")
    MIGRATION_REQUIRED = ("MRV-E802", "Artifacts written under an older major contract require explicit migration before use.")

    # 9xx — schema engine internal
    SCHEMA_ENGINE = ("MRV-E900", "Schema-engine internal error.")

    def __init__(self, code: str, default_message: str) -> None:
        self._code = code
        self._default_message = default_message

    @property
    def code(self) -> str:
        return self._code

    @property
    def default_message(self) -> str:
        return self._default_message


class MrvError(ToolError):
    """Structured exception carrying an MrvErrorCode plus machine-readable detail."""

    def __init__(
        self,
        code: MrvErrorCode,
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
