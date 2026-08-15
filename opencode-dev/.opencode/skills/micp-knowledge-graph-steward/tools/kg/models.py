"""Domain models for micp-knowledge-graph-steward.

Entity types, relationship types, evidence tiers, epistemic labels, claim
kinds, confidence levels, event vocabulary, and error-code taxonomy.

All enums serialize as plain strings so the JSONL event log stays
human-readable and schema-validatable without custom encoders (same
convention as the sibling obsidian-state-manager skill).
"""

from __future__ import annotations

import enum


class EntityType(str, enum.Enum):
    """MICP knowledge-graph entity classes (spec §四.2)."""

    STRAIN = "STRAIN"                    # microbial strain, e.g. Sporosarcina pasteurii DSM 33
    ENZYME = "ENZYME"                    # urease, carbonic anhydrase, ...
    SUBSTRATE = "SUBSTRATE"              # urea, calcium source, nutrient broth
    REACTANT = "REACTANT"                # species consumed in a reaction
    PRODUCT = "PRODUCT"                  # species produced (incl. NH4+)
    ION = "ION"                          # Ca2+, NH4+, CO3(2-) ...
    MINERAL_PHASE = "MINERAL_PHASE"      # calcite, vaterite, aragonite
    POROUS_MEDIUM = "POROUS_MEDIUM"      # sand column, soil specimen, filter bed
    PROCESS = "PROCESS"                  # ureolysis, denitrification, biosparging
    INSTRUMENT = "INSTRUMENT"            # XRD, SEM, ICP-OES, ...
    EXPERIMENT = "EXPERIMENT"            # an experiment / assay run
    PROPERTY = "PROPERTY"                # uniaxial compressive strength, permeability
    METRIC = "METRIC"                    # measured quantity with a unit
    ENV_INDICATOR = "ENV_INDICATOR"      # ammonia emission, pH, EC
    METHOD = "METHOD"                    # measurement/normalization procedure
    ARTIFACT = "ARTIFACT"                # dataset, publication, report


class RelationType(str, enum.Enum):
    """Relationship predicates between entities."""

    HAS_TYPE = "HAS_TYPE"
    SYNONYM_OF = "SYNONYM_OF"
    RELATED_TO = "RELATED_TO"
    CATALYZES = "CATALYZES"              # enzyme -> reaction/substrate
    CONSUMES = "CONSUMES"                # process -> reactant
    PRODUCES = "PRODUCES"                # process -> product
    MEASURED_BY = "MEASURED_BY"          # property/metric -> instrument/method
    OBSERVED_IN = "OBSERVED_IN"          # finding -> experiment
    SAME_AS = "SAME_AS"                  # identity statement (with confidence)
    IS_PHASE_OF = "IS_PHASE_OF"          # mineral phase belongs to a solid/system
    APPLIES_TO = "APPLIES_TO"            # rule/claim -> entity
    EVIDENCE_FOR = "EVIDENCE_FOR"
    EVIDENCE_AGAINST = "EVIDENCE_AGAINST"
    PARTOF = "PARTOF"
    DEPENDS_ON = "DEPENDS_ON"
    SUPPORTS = "SUPPORTS"                # experiment supports a hypothesis/claim
    REFUTES = "REFUTES"


class EvidenceTier(str, enum.Enum):
    """Source tier for knowledge items (spec §四.3)."""

    EXTERNAL_REPORTED = "EXTERNAL_REPORTED"  # cited from literature/external source
    INTERNAL_OBSERVED = "INTERNAL_OBSERVED"  # observed/measured in this project
    CALCULATED = "CALCULATED"                # derived by a verified tool
    INFERRED = "INFERRED"                    # model reasoning over observed/reported
    HYPOTHESIS = "HYPOTHESIS"                # conjecture awaiting test
    VALIDATED = "VALIDATED"                  # promoted after review + human approval


# Strength ordering used by the epistemic label self-check and by conflict
# arbitration. OBSERVED is the strongest descriptive tier.
TIER_STRENGTH: dict[EvidenceTier, int] = {
    EvidenceTier.HYPOTHESIS: 1,
    EvidenceTier.INFERRED: 2,
    EvidenceTier.EXTERNAL_REPORTED: 3,
    EvidenceTier.CALCULATED: 4,
    EvidenceTier.INTERNAL_OBSERVED: 5,
    EvidenceTier.VALIDATED: 6,
}


class EpistemicLabel(str, enum.Enum):
    """Required claim labels (spec §六)."""

    OBSERVED = "OBSERVED"
    REPORTED = "REPORTED"
    CALCULATED = "CALCULATED"
    INFERRED = "INFERRED"
    HYPOTHESIS = "HYPOTHESIS"
    RECOMMENDATION = "RECOMMENDATION"


EPISTEMIC_STRENGTH: dict[EpistemicLabel, int] = {
    EpistemicLabel.HYPOTHESIS: 1,
    EpistemicLabel.INFERRED: 2,
    EpistemicLabel.REPORTED: 3,
    EpistemicLabel.CALCULATED: 4,
    EpistemicLabel.OBSERVED: 5,
}


class ClaimKind(str, enum.Enum):
    """The kind of knowledge a Claim node carries.

    Distinguishes structural claims (identity / synonymy / type membership)
    from substantive scientific claims (mineral phase, property value, causal
    relation). Conflict detection only fires for COMPARABLE claims; a
    structural SAME_AS claim never conflicts with a property VALUE claim.
    """

    IDENTITY = "IDENTITY"          # entity resolution: this name == that entity
    TYPE = "TYPE"                  # classification: strain is Sporosarcina pasteurii
    SYNONYM = "SYNONYM"            # lexical alias of a canonical name
    VALUE = "VALUE"                # a property/quantity claim (unit-aware)
    OBSERVATION = "OBSERVATION"    # observed event/state
    CAUSAL = "CAUSAL"              # X influences/causes Y
    NORMATIVE = "NORMATIVE"        # standard/regulatory/design rule


class ConfidenceLevel(str, enum.Enum):
    """Assigned confidence of a claim, always ≤ its evidence tier."""

    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class ConflictStatus(str, enum.Enum):
    """State of a detected claim conflict (spec §四.5)."""

    OPEN = "OPEN"                  # conflict exists, not adjudicated
    RESOLVED = "RESOLVED"          # adjudicated: one side preferred
    SUPERSEDED = "SUPERSEDED"      # one side withdrawn/updated
    UNRESOLVED = "UNRESOLVED"      # documented, intentionally kept open


class ClaimStatus(str, enum.Enum):
    """Lifecycle of a claim node."""

    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"
    RETRACTED = "RETRACTED"


class OutputStatus(str, enum.Enum):
    """Unified output status (spec §六)."""

    SUCCESS = "SUCCESS"
    PARTIAL = "PARTIAL"
    BLOCKED = "BLOCKED"
    FAILED = "FAILED"
    NEED_ADDITIONAL_SKILL = "NEED_ADDITIONAL_SKILL"
    HUMAN_APPROVAL_REQUIRED = "HUMAN_APPROVAL_REQUIRED"


class ActorRole(str, enum.Enum):
    CONTROLLER = "controller"
    SKILL = "skill"
    HUMAN = "human"
    AUDITOR = "auditor"


# ---------------------------------------------------------------------------
# Error codes (single source of truth; spec §十一.2)
#
# Layout: KGE-E<category><ordinal>
#   1xx input contract / schema         5xx approvals / permissions
#   2xx evidence / units                6xx downstream capabilities
#   3xx store / context integrity       7xx self-check / output contract
#   4xx tooling / environment           8xx migration / compatibility
# ---------------------------------------------------------------------------
class KgeErrorCode(enum.Enum):
    # 1xx — input contract
    INPUT_SCHEMA_VIOLATION = ("KGE-E101", "Input does not conform to schemas/input.schema.json.")
    MISSING_REQUIRED_FIELD = ("KGE-E102", "A required input field is absent.")
    UNKNOWN_ACTION = ("KGE-E103", "The requested action is not part of this skill.")
    ENTITY_NOT_FOUND = ("KGE-E104", "Referenced entity id does not exist in this knowledge base.")

    # 2xx — evidence / units
    EVIDENCE_UNVERIFIABLE = ("KGE-E201", "Evidence reference cannot be resolved or integrity-checked.")
    EVIDENCE_INTEGRITY_MISMATCH = ("KGE-E202", "Evidence content hash does not match the recorded hash.")
    UNIT_INCONSISTENT = ("KGE-E203", "Quantities carry incompatible or missing units.")
    EPISTEMIC_MISLABEL = ("KGE-E204", "A claim is labeled with an epistemic level stronger than its support.")

    # 3xx — store / context integrity
    STORE_CORRUPT = ("KGE-E301", "Knowledge store failed hash-chain verification.")
    CONTEXT_CORRUPT = ("KGE-E302", "A context/working file is damaged or truncated mid-record.")
    STORE_NOT_FOUND = ("KGE-E303", "No knowledge base exists for the requested project_id.")
    CONFLICT_UNDETECTED = ("KGE-E304", "A conflict state references a claim pair that cannot be found.")

    # 4xx — tooling / environment
    TOOL_UNAVAILABLE = ("KGE-E401", "A required tool or adapter is not available in this environment.")
    TOOL_TIMEOUT = ("KGE-E402", "A tool call exceeded its time budget.")
    STORE_IO_FAILURE = ("KGE-E403", "The knowledge store could not be read or written.")
    BACKUP_FAILED = ("KGE-E404", "Backup archive could not be created.")

    # 5xx — approvals / permissions
    PERMISSION_DENIED = ("KGE-E501", "The acting role is not permitted to perform this action.")
    APPROVAL_REQUIRED = ("KGE-E502", "Action is gated on human approval that has not been granted.")
    APPROVAL_STALE = ("KGE-E503", "Human approval was granted for a different revision and must be renewed.")

    # 6xx — downstream capabilities
    DOWNSTREAM_CAPABILITY_MISSING = ("KGE-E601", "Progress requires another skill that is not available.")
    DOWNSTREAM_CONTRACT_MISMATCH = ("KGE-E602", "An upstream artifact does not match its declared contract.")

    # 7xx — self-check / output contract
    OUTPUT_SCHEMA_VIOLATION = ("KGE-E701", "Skill output failed validation against schemas/output.schema.json.")
    SELF_CHECK_FAILED = ("KGE-E702", "Post-action self-check failed (e.g., rebuild != snapshot).")
    RESULT_REJECTED = ("KGE-E703", "Result was generated but failed its own quality gate.")

    # 8xx — migration / compatibility
    UNSUPPORTED_SCHEMA_VERSION = ("KGE-E801", "Payload declares a contract version this build cannot consume.")
    MIGRATION_REQUIRED = ("KGE-E802", "Stored state predates the current contract and needs explicit migration.")

    def __init__(self, code: str, default_message: str) -> None:
        self._code = code
        self._default_message = default_message

    @property
    def code(self) -> str:
        return self._code

    @property
    def default_message(self) -> str:
        return self._default_message


class KgeError(Exception):
    """Structured exception carrying a KgeErrorCode plus machine-readable detail."""

    def __init__(
        self,
        code: KgeErrorCode,
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
