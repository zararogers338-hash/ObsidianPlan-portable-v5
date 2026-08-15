"""Domain models: lifecycle states, events, memory tiers, epistemic labels.

All enums serialize as plain strings so the JSONL event log stays
human-readable and schema-validatable without custom encoders.
"""

from __future__ import annotations

import enum


class ResearchState(str, enum.Enum):
    """Obsidian Plan research-lifecycle states.

    Terminal states: REJECTED, DEPLOYABLE. VALIDATED is not terminal —
    conclusions can be superseded by later evidence (downgrade path).
    """

    OPEN = "OPEN"
    SCOPED = "SCOPED"
    EVIDENCE_GATHERING = "EVIDENCE_GATHERING"
    HYPOTHESIS_BUILDING = "HYPOTHESIS_BUILDING"
    DESIGNING = "DESIGNING"
    AWAITING_DATA = "AWAITING_DATA"
    ANALYZING = "ANALYZING"
    UNDER_REVIEW = "UNDER_REVIEW"
    VALIDATED = "VALIDATED"
    REJECTED = "REJECTED"
    DEPLOYABLE = "DEPLOYABLE"


TERMINAL_STATES: frozenset[ResearchState] = frozenset(
    {ResearchState.REJECTED, ResearchState.DEPLOYABLE}
)


class EventType(str, enum.Enum):
    """Append-only event vocabulary. New types may be appended in minor
    versions; existing semantics never change (event-sourcing rule)."""

    PROJECT_INITIALIZED = "PROJECT_INITIALIZED"
    STATE_TRANSITION_REQUESTED = "STATE_TRANSITION_REQUESTED"
    STATE_TRANSITIONED = "STATE_TRANSITIONED"
    STATE_TRANSITION_REJECTED = "STATE_TRANSITION_REJECTED"
    EVIDENCE_ATTACHED = "EVIDENCE_ATTACHED"
    EVIDENCE_RETRACTED = "EVIDENCE_RETRACTED"
    HYPOTHESIS_RECORDED = "HYPOTHESIS_RECORDED"
    HYPOTHESIS_STATUS_CHANGED = "HYPOTHESIS_STATUS_CHANGED"
    DECISION_RECORDED = "DECISION_RECORDED"
    TASK_CHECKPOINT = "TASK_CHECKPOINT"
    MEMORY_PROMOTED = "MEMORY_PROMOTED"
    REVIEW_REQUESTED = "REVIEW_REQUESTED"
    REVIEW_COMPLETED = "REVIEW_COMPLETED"
    APPROVAL_GRANTED = "APPROVAL_GRANTED"
    SNAPSHOT_WRITTEN = "SNAPSHOT_WRITTEN"
    RECOVERY_PERFORMED = "RECOVERY_PERFORMED"
    STALENESS_FLAGGED = "STALENESS_FLAGGED"
    DOWNGRADE_TRIGGERED = "DOWNGRADE_TRIGGERED"


class MemoryTier(str, enum.Enum):
    """The four memory classes the skill must keep distinct (spec §四.4)."""

    PROJECT = "project_memory"          # durable, versioned, survives sessions
    CONTEXT = "ephemeral_context"       # working set; may be truncated safely
    VERIFIED = "verified_knowledge"     # promoted only with human approval
    DRAFT = "unreviewed_draft"          # everything else by default


class EpistemicLabel(str, enum.Enum):
    """Required claim labels (spec §六). Strength order matters for the
    EPISTEMIC_MISLABEL self-check: a claim may never be labeled stronger
    than its provenance supports."""

    OBSERVED = "OBSERVED"              # directly instrumented/witnessed here
    REPORTED = "REPORTED"              # from a cited external source
    CALCULATED = "CALCULATED"          # derived by a verified tool from inputs
    INFERRED = "INFERRED"              # model reasoning over observed/reported
    HYPOTHESIS = "HYPOTHESIS"          # conjecture awaiting test
    RECOMMENDATION = "RECOMMENDATION"  # prescriptive, not descriptive


# Strength ranking: a claim's label may not exceed the strongest label
# justified by its evidence. OBSERVED > CALCULATED > REPORTED > INFERRED
# > HYPOTHESIS; RECOMMENDATION is orthogonal (never mislabeled as fact).
EPISTEMIC_STRENGTH: dict[EpistemicLabel, int] = {
    EpistemicLabel.HYPOTHESIS: 1,
    EpistemicLabel.INFERRED: 2,
    EpistemicLabel.REPORTED: 3,
    EpistemicLabel.CALCULATED: 4,
    EpistemicLabel.OBSERVED: 5,
}


class ActorRole(str, enum.Enum):
    """Roles allowed to drive transitions (spec §四.2: 允许角色)."""

    CONTROLLER = "controller"      # Obsidian Controller / Router
    SKILL = "skill"                # a specialist skill acting on its own work
    HUMAN = "human"                # human operator
    AUDITOR = "auditor"            # read/review-only actor


class OutputStatus(str, enum.Enum):
    """Unified output status (spec §六)."""

    SUCCESS = "SUCCESS"
    PARTIAL = "PARTIAL"
    BLOCKED = "BLOCKED"
    FAILED = "FAILED"
    NEED_ADDITIONAL_SKILL = "NEED_ADDITIONAL_SKILL"
    HUMAN_APPROVAL_REQUIRED = "HUMAN_APPROVAL_REQUIRED"


class HypothesisStatus(str, enum.Enum):
    PROPOSED = "PROPOSED"
    SUPPORTED = "SUPPORTED"
    CONTESTED = "CONTESTED"    # contradictory evidence attached
    REFUTED = "REFUTED"
    SUPERSEDED = "SUPERSEDED"
