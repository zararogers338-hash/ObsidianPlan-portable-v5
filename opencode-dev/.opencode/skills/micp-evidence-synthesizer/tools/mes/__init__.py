"""micp-evidence-synthesizer tool package (MES).

Offline-capable, dependency-light numerical + validation toolkit backing the
MES skill. Each module maps to one declared capability in skill.yaml.

Modules:
    errors       — OES error-code registry (single source of truth)
    models       — output envelope helpers, epistemic labels, layers
    jsonschema   — minimal builtin draft-07 validator (fallback when the
                   `jsonschema` package is absent)
    evidence_validate  — Evidence Card validation + traceability
    unit_map     — unit normalization (preserve raw values)
    effect_compute     — Cohen's d / Hedges' g / mean difference from arms
    meta_analyze       — fixed-effect + DerSimonian-Laird random-effects
    heterogeneity_compute — I2 / tau2 / Q / prediction interval + 4-type class
    evidence_map       — evidence matrix + conflict matrix
    sensitivity_run    — leave-one-out sensitivity analysis
    grade_assess       — GRADE-style certainty (5 domains)
    result_check_overgeneralization — scope / counterexample / label self-check
    service      — orchestration + unified envelope
"""

from .errors import MesError, MesErrorCode
from .models import OutputStatus, SKILL_NAME, SKILL_VERSION

__all__ = ["MesError", "MesErrorCode", "OutputStatus", "SKILL_NAME", "SKILL_VERSION"]
__version__ = "1.0.0"
