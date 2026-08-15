"""Error-code taxonomy for obsidian-state-manager.

Every failure the skill can produce carries one of these codes so the
Obsidian controller can route programmatically while humans get a readable
message. Codes are stable: never renumber, only append.

Layout: OSM-E<category><ordinal>
  1xx input contract        5xx approvals / permissions
  2xx evidence / units      6xx downstream capabilities
  3xx store integrity       7xx self-check / output contract
  4xx tooling / environment 8xx deprecated-compatibility
"""

from __future__ import annotations

import enum


class OsmErrorCode(enum.Enum):
    # 1xx — input contract
    INPUT_SCHEMA_VIOLATION = ("OSM-E101", "Input does not conform to schemas/input.schema.json.")
    MISSING_REQUIRED_FIELD = ("OSM-E102", "A required input field is absent.")
    INVALID_STATE_NAME = ("OSM-E103", "An unknown lifecycle state was referenced.")
    INVALID_EVENT_SEQUENCE = ("OSM-E104", "Command references a stream revision that does not match.")

    # 2xx — evidence / units
    EVIDENCE_UNVERIFIABLE = ("OSM-E201", "Evidence reference cannot be resolved or integrity-checked.")
    EVIDENCE_INTEGRITY_MISMATCH = ("OSM-E202", "Evidence content hash does not match the recorded hash.")
    UNIT_INCONSISTENT = ("OSM-E203", "Quantities carry incompatible or missing units.")
    EVIDENCE_STALE = ("OSM-E204", "Evidence or conclusion has passed its review-by horizon.")

    # 3xx — store integrity
    EVENT_LOG_CORRUPT = ("OSM-E301", "Event log failed hash-chain verification.")
    SNAPSHOT_CORRUPT = ("OSM-E302", "Snapshot file is unreadable or fails integrity check.")
    CONTEXT_CORRUPT = ("OSM-E303", "A context/working file is damaged or truncated mid-record.")
    PROJECT_NOT_FOUND = ("OSM-E304", "No state stream exists for the requested project_id.")
    TRANSITION_REJECTED = ("OSM-E305", "Illegal lifecycle transition; hard-blocked by the state machine.")
    GUARD_UNSATISFIED = ("OSM-E306", "Transition is legal in principle but its guard conditions are unmet.")
    IRREVERSIBLE_TRANSITION = ("OSM-E307", "Target transition is marked irreversible and cannot be rolled back.")

    # 4xx — tooling / environment
    TOOL_UNAVAILABLE = ("OSM-E401", "A required tool or adapter is not available in this environment.")
    TOOL_TIMEOUT = ("OSM-E402", "A tool call exceeded its time budget.")
    STORE_IO_FAILURE = ("OSM-E403", "The state store could not be read or written.")

    # 5xx — approvals / permissions
    PERMISSION_DENIED = ("OSM-E501", "The acting role is not permitted to perform this action.")
    APPROVAL_REQUIRED = ("OSM-E502", "Action is gated on human approval that has not been granted.")
    APPROVAL_STALE = ("OSM-E503", "Human approval was granted for a different revision and must be renewed.")

    # 6xx — downstream capabilities
    DOWNSTREAM_CAPABILITY_MISSING = ("OSM-E601", "Progress requires another skill that is not available.")
    DOWNSTREAM_CONTRACT_MISMATCH = ("OSM-E602", "An upstream artifact does not match its declared contract.")

    # 7xx — self-check / output contract
    OUTPUT_SCHEMA_VIOLATION = ("OSM-E701", "Skill output failed validation against schemas/output.schema.json.")
    SELF_CHECK_FAILED = ("OSM-E702", "Post-action self-check failed (e.g., rebuild != snapshot).")
    EPISTEMIC_MISLABEL = ("OSM-E703", "A claim is labeled with an epistemic level stronger than its support.")

    # 8xx — compatibility
    UNSUPPORTED_SCHEMA_VERSION = ("OSM-E801", "Payload declares a contract version this build cannot consume.")
    MIGRATION_REQUIRED = ("OSM-E802", "Stored state predates the current contract and needs explicit migration.")

    def __init__(self, code: str, default_message: str) -> None:
        self._code = code
        self._default_message = default_message

    @property
    def code(self) -> str:
        return self._code

    @property
    def default_message(self) -> str:
        return self._default_message


class OsmError(Exception):
    """Structured exception carrying an OsmErrorCode plus machine-readable detail."""

    def __init__(
        self,
        code: OsmErrorCode,
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
