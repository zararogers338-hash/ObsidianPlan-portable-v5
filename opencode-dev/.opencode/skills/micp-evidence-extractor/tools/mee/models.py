"""Domain constants and shared helpers for micp-evidence-extractor (MEE).

The extraction contract's key invariant: every quantity carries an acquisition
mode (how the value entered the record) AND an epistemic tag (what the value
claims about the world). The two are never conflated:

  - REPORTED_TEXT / REPORTED_TABLE / DIGITIZED_FROM_FIGURE / CALCULATED_FROM_REPORTED_DATA
    describe provenance of a reported value.
  - INFERRED is used only for explicit derived conclusions.
  - NOT_REPORTED / AMBIGUOUS placeholders carry value=null and must never be
    used in arithmetic (guarded in quantity.py).

MICP discipline: OD600 (turbidity), cell concentration, CFU (viable count),
and urease activity are distinct quantities and are never inter-converted
without an explicit reported conversion factor.
"""

from __future__ import annotations

import hashlib
import json
from enum import Enum

SKILL_NAME = "micp-evidence-extractor"
SKILL_VERSION = "1.0.0"
CONTRACT_VERSION = "1.0.0"

STATUSES = (
    "SUCCESS",
    "PARTIAL",
    "BLOCKED",
    "FAILED",
    "NEED_ADDITIONAL_SKILL",
    "HUMAN_APPROVAL_REQUIRED",
)

EPISTEMIC_TAGS = ("OBSERVED", "REPORTED", "CALCULATED", "INFERRED", "HYPOTHESIS", "RECOMMENDATION")

ACQUISITION_MODES = (
    "REPORTED_TEXT",
    "REPORTED_TABLE",
    "DIGITIZED_FROM_FIGURE",
    "CALCULATED_FROM_REPORTED_DATA",
    "INFERRED",
    "NOT_REPORTED",
    "AMBIGUOUS",
)

# Modes whose value is a placeholder and must never enter arithmetic.
PLACEHOLDER_MODES = frozenset({"NOT_REPORTED", "AMBIGUOUS"})

# Acquisition modes whose values count as "reported by the authors" (for
# conflict checking and summary counting).
AUTHOR_REPORTED_MODES = frozenset({"REPORTED_TEXT", "REPORTED_TABLE"})

# Generic scope / media enums (mirrored by evidence-card.schema.json).
SCALES = ("lab_vial", "lab_batch", "lab_column", "meter_scale", "field", "simulation", "unknown")
SYSTEM_KINDS = ("pure_culture", "mixed_community", "in_situ_stimulation", "simulation_model",
                "review_secondary", "unknown")
MEDIA_KINDS = ("soil", "sand", "biocemented_soil", "biocemented_sand", "mortar", "concrete",
               "solution_only", "other", "unknown")
DOC_TYPES = ("original_research", "review", "simulation", "laboratory_trial", "meter_scale_trial",
             "field_case", "method_paper", "unknown")

# MICP quantities that are physically distinct and must never be conflated.
DISTINCT_QUANTITIES = ("od600", "cell_concentration", "cfu", "viable_cell_ratio", "urease_activity")


class Status(str, Enum):
    SUCCESS = "SUCCESS"
    PARTIAL = "PARTIAL"
    BLOCKED = "BLOCKED"
    FAILED = "FAILED"
    NEED_ADDITIONAL_SKILL = "NEED_ADDITIONAL_SKILL"
    HUMAN_APPROVAL_REQUIRED = "HUMAN_APPROVAL_REQUIRED"


class AcquisitionMode(str, Enum):
    REPORTED_TEXT = "REPORTED_TEXT"
    REPORTED_TABLE = "REPORTED_TABLE"
    DIGITIZED_FROM_FIGURE = "DIGITIZED_FROM_FIGURE"
    CALCULATED_FROM_REPORTED_DATA = "CALCULATED_FROM_REPORTED_DATA"
    INFERRED = "INFERRED"
    NOT_REPORTED = "NOT_REPORTED"
    AMBIGUOUS = "AMBIGUOUS"

    @property
    def is_placeholder(self) -> bool:
        return self.value in PLACEHOLDER_MODES

    @property
    def is_author_reported(self) -> bool:
        return self.value in AUTHOR_REPORTED_MODES


class EpistemicTag(str, Enum):
    OBSERVED = "OBSERVED"
    REPORTED = "REPORTED"
    CALCULATED = "CALCULATED"
    INFERRED = "INFERRED"
    HYPOTHESIS = "HYPOTHESIS"
    RECOMMENDATION = "RECOMMENDATION"


def stable_digest(*objects: Any) -> str:
    """Deterministic sha256 over JSON-canonicalized inputs (audit anchor)."""
    h = hashlib.sha256()
    for obj in objects:
        raw = json.dumps(obj, sort_keys=True, ensure_ascii=False, default=str)
        h.update(raw.encode("utf-8"))
    return h.hexdigest()


def digest_text(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()
