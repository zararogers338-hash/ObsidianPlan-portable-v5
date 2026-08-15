"""Shared constants and identifiers for micp-scaleup-injection-engineer."""

from __future__ import annotations

import enum

SKILL_NAME = "micp-scaleup-injection-engineer"
SKILL_VERSION = "1.0.1"
CONTRACT_VERSION = "1.0"


class OutputStatus(enum.Enum):
    SUCCESS = "SUCCESS"
    PARTIAL = "PARTIAL"
    BLOCKED = "BLOCKED"
    FAILED = "FAILED"
    NEED_ADDITIONAL_SKILL = "NEED_ADDITIONAL_SKILL"
    HUMAN_APPROVAL_REQUIRED = "HUMAN_APPROVAL_REQUIRED"


class EpistemicLabel(enum.Enum):
    OBSERVED = "OBSERVED"
    REPORTED = "REPORTED"
    CALCULATED = "CALCULATED"
    INFERRED = "INFERRED"
    HYPOTHESIS = "HYPOTHESIS"
    RECOMMENDATION = "RECOMMENDATION"


# --- Physical / chemical constants (SI, REPORTED from literature; see
# references/sources.md for the evidence codes). ---

# Molar masses [kg/mol]
M_Urea = 60.06e-3
M_CaCl2 = 110.98e-3
M_CaCO3 = 100.09e-3
M_NH4 = 18.04e-3          # NH4+ as ion
M_N = 14.007e-3           # nitrogen atom

# Molar volume of water [m3/mol] (for concentration conversions)
V_WATER = 1.8e-5

# Precipitation stoichiometry (ureolysis path):
#   1 urea  -> 2 NH4+ + CO3^2-
#   Ca2+ + CO3^2- -> CaCO3(s)
# So per mol CaCO3: 1 mol urea, 1 mol Ca, 2 mol NH4+ (which equals 2 mol NH4-N).
MOL_NH4_PER_CACO3 = 2.0
MOL_UREA_PER_CACO3 = 1.0
MOL_CA_PER_CACO3 = 1.0

# Target CaCO3 content anchor for meaningful reinforcement [kg/m3 of soil]
# van Paassen (2010): >= 60 kg/m3 (~2 mol CaCO3 per litre of pore space).
TARGET_CACO3_CONTENT_ANCHOR_KG_M3 = 60.0
# Practical typical range for uniform cemented sand (van Paassen 2010).
CACO3_CONTENT_RANGE_KG_M3 = (30.0, 600.0)

# Concentration design window (Al Qabany & Soga 2013):
#   0.5 M urea/CaCl2 optimum; 1 M reduces UCS ~50% and causes localized
#   clogging. Below ~0.1 M needs many pore volumes (uneconomic).
CONC_OPTIMUM_MOL_M3 = 500.0            # 0.5 M
CONC_UPPER_SAFE_MOL_M3 = 750.0         # hard ceiling before strong clogging risk
CONC_ECONOMIC_LOW_MOL_M3 = 100.0       # below ~0.1 M is uneconomic (many PV)

# Pressure: modern grouting caps injection pressure at ~80% of the measured
# fracture pressure (OEGG 2017); fracture initiation ~ 2x overburden.
FRAC_PRESSURE_OVERBURDEN_FACTOR = 2.0
SAFE_INJECTION_FRACTION_OF_FRAC = 0.8
# Practical field flow rate range [m3/s] ~ 5-15 L/min (OEGG 2017).
FLOW_RATE_LOW_M3_S = 5.0 / 60.0e3
FLOW_RATE_HIGH_M3_S = 15.0 / 60.0e3

# Hydraulic gradient anchors: van Paassen 2010 used gradient < 1 in the 5 m
# column; keeping gradient low limits clogging-driven pressure build-up.
MAX_HYDRAULIC_GRADIENT_PILOT = 1.0

# Clogging pressure-warning threshold: when predicted injection pressure
# approaches the allowable limit, flag clogging risk.
CLOG_PRESSURE_WARNING_FRACTION = 0.7

# Ammonium-N production per CaCO3 [mol NH4-N / mol CaCO3] = 2.0
AMMONIUM_MOL_PER_CACO3 = 2.0

# Scale levels and their stage-gate ordering.
SCALE_LEVELS = ("pilot_column", "metre", "site", "field")

# Layer / geology
# Typical fine-sand permeability range (REPORTED/INFERRED — must be replaced
# by site data at site/field scale; this is only a sanity-check range).
PERM_FINE_SAND_RANGE_M2 = (1e-13, 1e-11)

# Shear-wave velocity / CPT detection anchors (Gomez et al. 2017/2018):
#   Vs detects ~1.0% calcite; CPT ~3.0%; qc/Vs gain ~500-700% at >5%.
VS_DETECT_CALCITE_FRACTION = 0.01
CPT_DETECT_CALCITE_FRACTION = 0.03

# Default tolerances
BALANCE_REL_TOL = 1e-6
