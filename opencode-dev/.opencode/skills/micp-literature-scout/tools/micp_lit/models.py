"""Domain models: epistemic labels, output statuses, evidence scopes, source kinds.

Enums serialize as plain strings so outputs stay JSON-validatable without custom
encoders. Epistemic strength ordering mirrors the state-manager convention but
is local to this skill (see SKILL.md §3, §10).
"""

from __future__ import annotations

import enum


class EpistemicLabel(str, enum.Enum):
    """Required claim labels (spec §六). A claim may never be labeled stronger
    than its provenance supports."""

    OBSERVED = "OBSERVED"              # directly instrumented/witnessed here
    REPORTED = "REPORTED"              # from a cited external source
    CALCULATED = "CALCULATED"          # derived by a verified tool from inputs
    INFERRED = "INFERRED"              # model reasoning over observed/reported
    HYPOTHESIS = "HYPOTHESIS"          # conjecture awaiting test
    RECOMMENDATION = "RECOMMENDATION"  # prescriptive, not descriptive


# Strength ranking: OBSERVED > CALCULATED > REPORTED > INFERRED > HYPOTHESIS.
# RECOMMENDATION is orthogonal and may never be presented as fact.
EPISTEMIC_STRENGTH: dict[str, int] = {
    EpistemicLabel.HYPOTHESIS.value: 1,
    EpistemicLabel.INFERRED.value: 2,
    EpistemicLabel.REPORTED.value: 3,
    EpistemicLabel.CALCULATED.value: 4,
    EpistemicLabel.OBSERVED.value: 5,
}


class OutputStatus(str, enum.Enum):
    """Unified output status (spec §六)."""

    SUCCESS = "SUCCESS"
    PARTIAL = "PARTIAL"
    BLOCKED = "BLOCKED"
    FAILED = "FAILED"
    NEED_ADDITIONAL_SKILL = "NEED_ADDITIONAL_SKILL"
    HUMAN_APPROVAL_REQUIRED = "HUMAN_APPROVAL_REQUIRED"


class EvidenceScope(str, enum.Enum):
    """Evidence scale the skill must keep distinct (SKILL.md §3, §13)."""

    LAB_COLUMN = "lab_column"
    METER_SCALE = "meter_scale"
    FIELD = "field"
    SIMULATION = "simulation"
    REVIEW = "review"
    META_ANALYSIS = "meta-analysis"
    STANDARD = "standard"
    PATENT = "patent"
    DATASET = "dataset"


class SourceKind(str, enum.Enum):
    """Classification of a record's source (used by triage and cite)."""

    RESEARCH = "research"
    REVIEW = "review"
    MODEL = "model"
    METHOD = "method"
    STANDARD = "standard"
    PATENT = "patent"
    DATASET = "dataset"
    BOOK = "book"
    OTHER = "other"


class TriageLevel(str, enum.Enum):
    """Evidence strength tiers produced by triage.screen.

    TIER1 primary empirical (field/meter-scale, high confidence)
    TIER2 primary empirical (lab) or modelling/methods, medium confidence
    TIER3 reviews / tertiary navigation
    REJECT out-of-scope or non-verifiable
    """

    TIER1 = "TIER1"
    TIER2 = "TIER2"
    TIER3 = "TIER3"
    REJECT = "REJECT"


class DoiStatus(str, enum.Enum):
    """DOI verification outcome."""

    VERIFIED = "verified"
    NOT_FOUND = "not_found"
    SUSPECTED_FORGED = "suspected_forged"
    CHECK_FAILED = "check_failed"
    OFFLINE_UNVERIFIED = "offline_unverified"


# Evidence-scope synonym map: normalize free-form scope strings into
# EvidenceScope values. Used by triage and validate.
SCOPE_SYNONYMS: dict[str, str] = {
    "lab": EvidenceScope.LAB_COLUMN.value,
    "lab_column": EvidenceScope.LAB_COLUMN.value,
    "column": EvidenceScope.LAB_COLUMN.value,
    "laboratory": EvidenceScope.LAB_COLUMN.value,
    "meter": EvidenceScope.METER_SCALE.value,
    "meter_scale": EvidenceScope.METER_SCALE.value,
    "meter-scale": EvidenceScope.METER_SCALE.value,
    "pilot": EvidenceScope.METER_SCALE.value,
    "field": EvidenceScope.FIELD.value,
    "field_trial": EvidenceScope.FIELD.value,
    "in_situ": EvidenceScope.FIELD.value,
    "in-situ": EvidenceScope.FIELD.value,
    "simulation": EvidenceScope.SIMULATION.value,
    "numerical": EvidenceScope.SIMULATION.value,
    "model": EvidenceScope.SIMULATION.value,
    "review": EvidenceScope.REVIEW.value,
    "meta_analysis": EvidenceScope.META_ANALYSIS.value,
    "meta-analysis": EvidenceScope.META_ANALYSIS.value,
    "standard": EvidenceScope.STANDARD.value,
    "patent": EvidenceScope.PATENT.value,
    "dataset": EvidenceScope.DATASET.value,
}
