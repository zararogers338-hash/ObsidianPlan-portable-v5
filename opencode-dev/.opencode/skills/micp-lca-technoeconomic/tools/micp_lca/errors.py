"""Error-code taxonomy for micp-lca-technoeconomic.

Every failure the skill can produce carries one of these codes so the Obsidian
controller can route programmatically while humans get a readable message.
Codes are stable: never renumber, only append.

Layout: LCA-E<category><ordinal>
  1xx input contract        5xx approvals / permissions
  2xx evidence / factors    6xx downstream capabilities
  3xx context / file        7xx self-check / output contract
  4xx tooling / environment 8xx compatibility / migration
"""

from __future__ import annotations

import enum

from _common import ToolError


class LcaErrorCode(enum.Enum):
    # 1xx — input contract
    INPUT_SCHEMA_VIOLATION = ("LCA-E101", "Input does not conform to schemas/input.schema.json.")
    MISSING_REQUIRED_FIELD = ("LCA-E102", "A key field required for the analysis is absent (BLOCKED).")
    MISSING_FUNCTIONAL_UNIT = ("LCA-E103", "functional_unit (or a usable scope with reference flow and system boundary) is required before any formal calculation.")
    MISSING_BASELINE = ("LCA-E104", "baseline is required for any comparison (LCA/techno-economic); absent baseline blocks the request.")
    UNKNOWN_ACTION = ("LCA-E105", "Unknown action dispatched to the service.")
    INCOMPLETE_SCOPE = ("LCA-E106", "Scope is missing one or more mandatory boundary declarations (time, geography, energy mix, transport, TRL).")

    # 2xx — evidence / factors / units
    FACTOR_UNVERIFIABLE = ("LCA-E201", "A factor's provenance (source/region/year/version) is missing or unverifiable.")
    FACTOR_EXPIRED = ("LCA-E202", "A factor is too old for the declared analysis year (default >5 years stale).")
    FACTOR_REQUIRES_UNIT = ("LCA-E203", "A numeric factor is declared without an explicit unit.")
    LAB_PRICE_AS_FIELD_COST = ("LCA-E204", "A lab-reagent catalogue price is being used as a field-scale cost without a documented scaling adjustment.")
    UNIT_PARSE_ERROR = ("LCA-E205", "A unit string could not be parsed or converted.")
    UNIT_INCONSISTENT = ("LCA-E206", "Quantities carry incompatible or missing units.")
    FACTOR_UNKNOWN = ("LCA-E207", "The requested factor or cost item is not present in the factor database; a real value must be supplied before calculation.")
    DATA_YEAR_MISSING = ("LCA-E208", "A data point declares neither a data year nor falls back to the analysis year; provenance is incomplete.")

    # 3xx — context / file integrity
    CONTEXT_CORRUPT = ("LCA-E301", "A context or working file is damaged, truncated, or non-finite.")
    INPUT_FILE_UNREADABLE = ("LCA-E302", "An input file referenced by the caller cannot be read.")

    # 4xx — tooling / environment
    TOOL_UNAVAILABLE = ("LCA-E401", "A required tool or library is not available in this environment.")
    NUMERICAL_FAILURE = ("LCA-E402", "A numerical computation failed (e.g. Monte Carlo produced no finite samples).")
    NO_CONVERGENCE = ("LCA-E403", "A simulation did not converge to a stable estimate.")

    # 5xx — approvals / permissions
    PERMISSION_DENIED = ("LCA-E501", "The acting role is not permitted to perform this action.")
    APPROVAL_REQUIRED = ("LCA-E502", "Action is gated on human approval that has not been granted (field deployment, real cost commitment, release of an environmental claim).")

    # 6xx — downstream capabilities
    DOWNSTREAM_CAPABILITY_MISSING = ("LCA-E601", "Progress requires another skill that is not available (e.g. micp-geotechnical-performance for UCS targets, red-team for adversarial review).")
    DOWNSTREAM_CONTRACT_MISMATCH = ("LCA-E602", "An upstream artifact does not match its declared contract.")

    # 7xx — self-check / output contract
    OUTPUT_SCHEMA_VIOLATION = ("LCA-E701", "Skill output failed validation against schemas/output.schema.json.")
    SELF_CHECK_FAILED = ("LCA-E702", "Post-analysis self-check failed (non-finite result, empty sections, or gate violation).")
    EPISTEMIC_MISLABEL = ("LCA-E703", "A claim is labeled with an epistemic level stronger than its support.")
    BOUNDARY_ASYMMETRY = ("LCA-E704", "A comparative assessment uses inconsistent system boundaries between scenarios (e.g. waste treatment included in MICP but omitted in the baseline).")
    UNFAIR_FUNCTIONAL_UNIT = ("LCA-E705", "Scenarios compared under different functional units, performance targets, or lifetimes.")

    # 8xx — compatibility / migration
    VERSION_MISMATCH = ("LCA-E801", "Payload declares a contract version this build cannot consume.")
    MIGRATION_REQUIRED = ("LCA-E802", "Outputs written under an older major contract require explicit migration before use.")

    # 9xx — schema engine internal
    SCHEMA_ENGINE = ("LCA-E900", "Schema-engine internal error.")

    def __init__(self, code: str, default_message: str) -> None:
        self._code = code
        self._default_message = default_message

    @property
    def code(self) -> str:
        return self._code

    @property
    def default_message(self) -> str:
        return self._default_message


class LcaError(ToolError):
    """Structured exception carrying an LcaErrorCode plus machine-readable detail."""

    def __init__(
        self,
        code: LcaErrorCode,
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
