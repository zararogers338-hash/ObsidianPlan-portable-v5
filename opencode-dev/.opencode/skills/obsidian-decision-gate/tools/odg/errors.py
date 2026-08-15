"""Error-code taxonomy for obsidian-decision-gate.

Every failure the skill can produce carries one of these codes so the
Obsidian controller can route programmatically while humans get a readable
message. Codes are stable: never renumber, only append.

Layout: ODG-E<category><ordinal>
  1xx input contract         5xx approvals / permissions
  2xx evidence / metrics     6xx downstream capabilities
  3xx state machine / gates  7xx self-check / output contract
  4xx tooling / environment  8xx deprecated-compatibility
"""

from __future__ import annotations

import enum


class OdgErrorCode(enum.Enum):
    # 1xx — input contract
    INPUT_SCHEMA_VIOLATION = ("ODG-E101", "Input does not conform to schemas/input.schema.json.")
    MISSING_REQUIRED_FIELD = ("ODG-E102", "A required input field is absent.")
    INVALID_STATE_NAME = ("ODG-E103", "An unknown lifecycle state was referenced.")
    INVALID_ACTION = ("ODG-E104", "Unsupported action for the provided inputs.")

    # 2xx — evidence / metrics
    EVIDENCE_UNVERIFIABLE = ("ODG-E201", "Evidence reference cannot be resolved or integrity-checked.")
    EVIDENCE_IRRETRIEVABLE = ("ODG-E202", "Evidence declared irreproducible or not reproducible.")
    MISSING_CONTROL = ("ODG-E203", "Key control arm missing from experiments.")
    MASS_BALANCE_FAILURE = ("ODG-E205", "Mass balance failed closure check.")
    MODEL_UNVALIDATED = ("ODG-E206", "Model has no independent/hold-out validation.")
    SUCCESS_CRITERIA_NOT_MET = ("ODG-E207", "Mission success criteria not met.")
    FAILURE_THRESHOLD_TRIGGERED = ("ODG-E208", "Mission failure threshold triggered.")
    REGULATORY_UNVERIFIED = ("ODG-E209", "Regulatory status unverified or expired.")

    # 3xx — state machine / gates
    ILLEGAL_TRANSITION = ("ODG-E305", "Proposed state transition is not in the whitelist (illegal jump).")
    BLOCKER_PRESENT = ("ODG-E306", "One or more blocking items prevent the upgrade.")
    SCALE_LADDER_GAP = ("ODG-E307", "Scale ladder has a gap (e.g. lab directly to deploy).")
    NO_MONITORING_SHUTDOWN = ("ODG-E308", "Monitoring and shutdown conditions are required for pilot/deploy.")
    ENV_RISK_OPEN = ("ODG-E309", "Environmental risk findings not closed.")

    # 4xx — tooling / environment
    TOOL_UNAVAILABLE = ("ODG-E401", "A required tool or adapter is not available in this environment.")
    RULE_TABLE_UNAVAILABLE = ("ODG-E402", "gate-rules.json could not be loaded or is invalid.")
    CLOCK_UNAVAILABLE = ("ODG-E403", "Could not resolve the current time for expiry checks.")

    # 5xx — approvals / permissions
    PERMISSION_DENIED = ("ODG-E501", "The acting role is not permitted to perform this action.")
    APPROVAL_REQUIRED = ("ODG-E502", "Upgrade is gated on human approval that has not been granted.")
    APPROVAL_STALE = ("ODG-E503", "Human approval was granted for a different revision and must be renewed.")

    # 6xx — downstream capabilities
    DOWNSTREAM_CAPABILITY_MISSING = ("ODG-E601", "Progress requires another skill that is not available.")
    DOWNSTREAM_CONTRACT_MISMATCH = ("ODG-E602", "An upstream artifact does not match its declared contract.")

    # 7xx — self-check / output contract
    OUTPUT_SCHEMA_VIOLATION = ("ODG-E701", "Skill output failed validation against schemas/output.schema.json.")
    SELF_CHECK_FAILED = ("ODG-E702", "Post-action self-check failed (e.g., decision inconsistent with blockers).")
    EPISTEMIC_MISLABEL = ("ODG-E703", "A claim is labeled with an epistemic level stronger than its support.")

    # 8xx — compatibility
    UNSUPPORTED_SCHEMA_VERSION = ("ODG-E801", "Payload declares a contract version this build cannot consume.")
    MIGRATION_REQUIRED = ("ODG-E802", "Stored state predates the current contract and needs explicit migration.")

    def __init__(self, code: str, default_message: str) -> None:
        self._code = code
        self._default_message = default_message

    @property
    def code(self) -> str:
        return self._code

    @property
    def default_message(self) -> str:
        return self._default_message


class OdgError(Exception):
    """Structured exception carrying an OdgErrorCode plus machine-readable detail."""

    def __init__(
        self,
        code: OdgErrorCode,
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
