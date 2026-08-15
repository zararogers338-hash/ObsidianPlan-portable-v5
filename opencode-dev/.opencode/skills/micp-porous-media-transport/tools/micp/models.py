"""Shared constants, epistemic labels, and status enums for the MICP skill.

Kept dependency-free (stdlib only) so the whole tool suite runs offline and
can be imported from tests without installing anything.
"""

from __future__ import annotations

import enum

SKILL_NAME = "micp-porous-media-transport"
SKILL_VERSION = "1.0.0"
CONTRACT_VERSION = "1.0"

# Allowed output statuses (spec §六) — mirrors the unified envelope.
STATUSES = ("SUCCESS", "PARTIAL", "BLOCKED", "FAILED",
            "NEED_ADDITIONAL_SKILL", "HUMAN_APPROVAL_REQUIRED")

# Epistemic labels (spec §六). INFERRED/HYPOTHESIS/RECOMMENDATION may never be
# reported as OBSERVED.
EPISTEMIC_LABELS = ("OBSERVED", "REPORTED", "CALCULATED", "INFERRED",
                    "HYPOTHESIS", "RECOMMENDATION")


class OutputStatus(str, enum.Enum):
    SUCCESS = "SUCCESS"
    PARTIAL = "PARTIAL"
    BLOCKED = "BLOCKED"
    FAILED = "FAILED"
    NEED_ADDITIONAL_SKILL = "NEED_ADDITIONAL_SKILL"
    HUMAN_APPROVAL_REQUIRED = "HUMAN_APPROVAL_REQUIRED"


class EpistemicLabel(str, enum.Enum):
    OBSERVED = "OBSERVED"
    REPORTED = "REPORTED"
    CALCULATED = "CALCULATED"
    INFERRED = "INFERRED"
    HYPOTHESIS = "HYPOTHESIS"
    RECOMMENDATION = "RECOMMENDATION"


# Stoichiometry (mass-conservation defaults; spec §七: urea hydrolysis and
# ammonium-nitrogen mass balance).
UREA_TO_AMMONIUM = 2.0        # 1 mol urea -> 2 mol NH4+ (+ 1 mol HCO3-/CO3^2-)
UREA_TO_CARBONATE = 1.0       # 1 mol urea -> 1 mol carbonate species
UREA_MOLAR_MASS = 60.06       # g/mol
CACO3_MOLAR_MASS = 100.0869   # g/mol
CA_MOLAR_MASS = 40.078        # g/mol
N_MOLAR_MASS = 14.0067        # g/mol
CACO3_DENSITY = 2711.0        # kg/m3 (calcite)
