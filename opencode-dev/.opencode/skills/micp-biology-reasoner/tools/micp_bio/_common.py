"""Shared numeric validation for micp-biology-reasoner tools.

Every numeric tool must reject NaN/Inf and out-of-range values before
computing (spec §五). These helpers centralize that check so tools can't
drift apart.
"""

from __future__ import annotations

import math

from .errors import MbrError, MbrErrorCode


def ensure_finite(value: float, name: str) -> float:
    """Reject NaN/Inf; returns the float unchanged."""
    if value is None:
        raise MbrError(
            MbrErrorCode.NUMERIC_INVALID,
            f"{name} is missing (None); a finite number is required.",
            detail={"field": name, "value": None},
        )
    try:
        v = float(value)
    except (TypeError, ValueError) as exc:
        raise MbrError(
            MbrErrorCode.NUMERIC_INVALID,
            f"{name} is not numeric.",
            detail={"field": name, "value": repr(value)},
        ) from exc
    if not math.isfinite(v):
        raise MbrError(
            MbrErrorCode.NUMERIC_INVALID,
            f"{name} is non-finite (NaN/Inf); refusing to compute with it.",
            detail={"field": name, "value": v},
        )
    return v


def ensure_in_range(value: float, name: str, low: float, high: float, *, inclusive: bool = True) -> float:
    """Reject values outside [low, high] (or (low, high) when inclusive=False)."""
    v = ensure_finite(value, name)
    ok = (low <= v <= high) if inclusive else (low < v < high)
    if not ok:
        raise MbrError(
            MbrErrorCode.NUMERIC_INVALID,
            f"{name} must be within [{low}, {high}] (inclusive={inclusive}); got {v}.",
            detail={"field": name, "value": v, "low": low, "high": high},
        )
    return v


def ensure_fraction(value: float, name: str) -> float:
    """A probability/fraction in [0, 1]."""
    return ensure_in_range(value, name, 0.0, 1.0)


def require_activity_unit(unit: str | None) -> str:
    """Urease activity without a unit is a hard block (MBR-E203).

    OD600 is a biomass proxy and is *never* an activity unit.
    """
    if unit is None or str(unit).strip() == "":
        raise MbrError(
            MbrErrorCode.UNIT_INCONSISTENT,
            "urease_activity is provided without urease_activity_unit. "
            "Activity cannot be interpreted or compared without a unit "
            "(specific vs total; U/mL vs U/g CDW). Obtain the unit from the "
            "assay method/experimental record and retry.",
            detail={"field": "urease_activity_unit"},
        )
    u = str(unit).strip()
    if u.lower().startswith("od"):
        raise MbrError(
            MbrErrorCode.OD_NOT_ACTIVITY,
            f"'{u}' is an OD600 (biomass proxy) unit, not a urease activity unit. "
            "OD600 cannot stand in for urease activity; provide a true activity "
            "measurement (e.g. U/mL, mM urea/min, U/g CDW).",
            detail={"field": "urease_activity_unit", "unit": u},
        )
    return u
