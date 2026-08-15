"""Urease activity normalization and unit conversion.

Strictly separates the quantities the skill must never conflate (spec §四.1):
  - OD600            biomass proxy (turbidity), dimensionless
  - CFU/mL           viable cell count per volume
  - cell dry weight  g/L (CDW)
  - viable fraction  0..1
  - urease activity  amount of urea hydrolyzed per time per volume (total)
  - specific activity activity normalized to a biomass proxy

Conversions that have NO default mapping are rejected (e.g. OD600 -> CFU/mL
without a calibrated curve, because the ratio is strain/phase/media dependent).
"""

from __future__ import annotations

import re
from typing import Any

from ._common import ensure_finite, require_activity_unit
from .errors import MbrError, MbrErrorCode

# ---- unit grammar ---------------------------------------------------------

# token : U | mM urea | µmol urea/min ... we only support a curated set and
# reject anything unknown loudly rather than guessing.
_ACTIVITY_PER_VOLUME = {
    "u/ml": 1.0,             # U/mL == µmol urea/min/mL
    "umol/ml/min": 1.0,      # same dimension
    "mumol/ml/min": 1.0,
    "mmol/l/h": None,        # needs conversion factor via molar volume below
    "mm urea/min": None,     # mM urea/min == mmol/L/min
}

# Factor to convert "mmol/L/min" (a.k.a. mM urea/min) into U/mL.
# 1 U/mL = 1 µmol urea/min/mL. 1 mmol/L/min = 1 µmol/mL/min = 1 U/mL.
_MM_UREA_PER_MIN_TO_U_PER_ML = 1.0

# 1 mmol/L/h = 1/60 µmol/mL/min
_MM_PER_H_TO_U_PER_ML = 1.0 / 60.0

# Specific-activity denominators.
_BIOMASS_UNITS = {
    "od": None,        # dimensionless; ratio to OD requires no numeric conversion
    "od600": None,
    "ml": None,        # per mL of suspension -> total activity, not specific
    "g": None,         # per gram
    "g cdw": None,
    "gdcw": None,
    "mg": None,
    "cell": None,
    "cfu": None,
}


def _normalize_unit_text(unit: str) -> str:
    return re.sub(r"\s+", " ", unit.strip().lower()).replace("·", " ")


def _is_specific(unit: str) -> bool:
    """True when the unit divides by a biomass proxy (per OD / per CFU / per CDW)."""
    u = _normalize_unit_text(unit)
    return any(mark in u for mark in ("/od", "/cfu", "/cell", "/g", "/mg", " per od", " per cfu"))


def activity_to_u_per_ml(activity: float, unit: str) -> dict[str, Any]:
    """Convert any supported total-activity unit to U/mL (µmol urea/min/mL).

    Returns {"u_per_ml": float, "interpretation": str, "converted": bool}.
    Raises MbrError on unsupported or specific-activity units (which cannot be
    converted without a biomass denominator value).
    """
    require_activity_unit(unit)  # MBR-E203 when unit missing/OD-proxy
    u = _normalize_unit_text(unit)
    a = ensure_finite(activity, "urease_activity")
    if _is_specific(u):
        raise MbrError(
            MbrErrorCode.UNIT_INCONSISTENT,
            f"'{unit}' is a *specific* activity unit (per biomass). Convert it "
            "only together with its biomass denominator; a bare numeric value "
            "cannot be converted to U/mL.",
            detail={"unit": unit, "kind": "specific"},
        )
    if u in ("u/ml", "umol/ml/min", "mumol/ml/min"):
        return {"u_per_ml": a, "interpretation": "total activity", "converted": False}
    if u == "mm urea/min":
        return {
            "u_per_ml": a * _MM_UREA_PER_MIN_TO_U_PER_ML,
            "interpretation": "total activity (1 mM urea/min == 1 U/mL)",
            "converted": True,
        }
    if u == "mmol/l/min":
        return {
            "u_per_ml": a * _MM_UREA_PER_MIN_TO_U_PER_ML,
            "interpretation": "total activity (1 mmol/L/min == 1 U/mL)",
            "converted": True,
        }
    if u == "mmol/l/h":
        return {
            "u_per_ml": a * _MM_PER_H_TO_U_PER_ML,
            "interpretation": "total activity (1 mmol/L/h == 1/60 U/mL)",
            "converted": True,
        }
    raise MbrError(
        MbrErrorCode.UNIT_INCONSISTENT,
        f"Unsupported urease activity unit '{unit}'. Supported total units: "
        "U/mL, µmol/mL/min, mM urea/min, mmol/L/min, mmol/L/h.",
        detail={"unit": unit},
    )


def specific_urease_activity(activity: float, activity_unit: str, denominator: float, denominator_kind: str) -> dict[str, Any]:
    """Compute specific urease activity = activity / biomass denominator.

    denominator_kind: 'od600' | 'cdw_g_per_l' | 'cfu_per_ml' | 'ml'
    """
    require_activity_unit(activity_unit)
    a = ensure_finite(activity, "urease_activity")
    d = ensure_finite(denominator, "denominator")
    if d == 0.0:
        raise MbrError(
            MbrErrorCode.NUMERIC_INVALID,
            "Cannot normalize by a zero biomass denominator.",
            detail={"denominator_kind": denominator_kind},
        )
    # Bring activity to a consistent numerator per the denominator kind.
    if denominator_kind == "od600":
        # total activity per mL divided by OD600 -> per OD600
        base = activity_to_u_per_ml(a, activity_unit)["u_per_ml"]
        return {"specific": base / d, "unit": "U/mL/OD600", "numerator_unit": "U/mL", "denominator": "OD600"}
    if denominator_kind == "cdw_g_per_l":
        base = activity_to_u_per_ml(a, activity_unit)["u_per_ml"]
        # A U/mL with CDW in g/L: 1 L = 1000 mL, so
        #   U/mL ÷ (g/L) = (U/mL) ÷ (g/1000 mL) = 1000·U/g CDW
        return {"specific": base * 1000.0 / d, "unit": "U/g CDW", "numerator_unit": "U/mL", "denominator": "g/L CDW"}
    if denominator_kind == "cfu_per_ml":
        base = activity_to_u_per_ml(a, activity_unit)["u_per_ml"]
        # U/mL ÷ (CFU/mL) = U/CFU
        return {"specific": base / d, "unit": "U/CFU", "numerator_unit": "U/mL", "denominator": "CFU/mL"}
    if denominator_kind == "ml":
        # already total activity per mL; return as-is with a clear label
        return {"specific": base_ml(a, activity_unit), "unit": "U/mL", "numerator_unit": "U/mL", "denominator": "mL"}
    raise MbrError(
        MbrErrorCode.UNIT_INCONSISTENT,
        f"Unknown denominator_kind '{denominator_kind}'.",
        detail={"denominator_kind": denominator_kind},
    )


def base_ml(activity: float, unit: str) -> float:
    return activity_to_u_per_ml(activity, unit)["u_per_ml"]


def cell_concentration_from_od(
    od600: float,
    *,
    calibration: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Convert OD600 -> CFU/mL ONLY via an explicit calibration.

    Without calibration this raises MBR-E203: the OD600:CFU ratio is strain,
    phase and media dependent and must never be guessed.
    """
    od = ensure_finite(od600, "od600")
    if od < 0:
        raise MbrError(MbrErrorCode.NUMERIC_INVALID, "OD600 cannot be negative.", detail={"od600": od})
    if not calibration or not isinstance(calibration, dict):
        raise MbrError(
            MbrErrorCode.UNIT_INCONSISTENT,
            "OD600 -> CFU/mL requires an explicit calibration (a fitted linear "
            "relation from THIS strain/medium/phase). None was provided; "
            "refusing to guess the ratio.",
            detail={"field": "calibration"},
        )
    slope = calibration.get("slope")
    intercept = calibration.get("intercept", 0.0)
    if slope is None:
        raise MbrError(
            MbrErrorCode.UNIT_INCONSISTENT,
            "Calibration must define slope (CFU/mL per OD600 unit).",
            detail={"field": "calibration.slope"},
        )
    slope = ensure_finite(float(slope), "calibration.slope")
    intercept = ensure_finite(float(intercept), "calibration.intercept")
    cfu = max(0.0, slope * od + intercept)
    return {
        "cfu_per_ml": cfu,
        "via": "calibration",
        "note": "Applies only within the calibrated OD600 range for this strain/medium/phase.",
    }
