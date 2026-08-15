"""Unit normalization and dimensional checking for micp-evidence-extractor.

Rules:
  - Every quantity must carry raw unit + canonical (normalized) unit.
  - Quantities that are physically distinct must NEVER be inter-converted:
    OD600 (turbidity), cell concentration, CFU (viable count), viable-cell
    ratio, and urease activity are separate dimensions. There is no
    conversion between them without an explicitly reported conversion factor,
    which this tool never fabricates.
  - A quantity whose raw unit is absent or ambiguous gets normalized_value=null,
    normalized_unit="", and acquisition_mode=AMBIGUOUS (MEE-E203).

Supported conversions (canonical target left of '='):
  strength:  kPa = 1 kPa; MPa = 1000 kPa
  permeability: m/s (SI); cm/s = 1e-2 m/s; m/d = 1e-5/0.864 m/s; D ≈ 9.869e-13 m2
  concentration (mass): g/L = 1 g/L; mg/L = 1e-3 g/L; kg/m3 = 1 g/L
  molar: mol/L = 1 mol/L; mM = 1e-3 mol/L; mol/m3 = 1e-3 mol/L; M = 1 mol/L
  temperature: degC; degF = (degF-32)/1.8 degC
  mass percent: pct = 1 percent; ppm = 1e-4 percent
  length: mm; cm = 10 mm; m = 1000 mm
  time: h; min = 1/60 h; s = 1/3600 h; d = 24 h
  density: g/cm3; kg/m3 = 1e-3 g/cm3
  conductivity: mS/cm; uS/cm = 1e-3 mS/cm
  volume: mL = 1e-6 m3; uL = 1e-9 m3; cm3 = 1e-6 m3
  flow (injection rate): mL/min = 1 mL/min; mL/h = 1/60 mL/min; L/min = 1000 mL/min
  pressure: kPa; MPa = 1000 kPa; psi ≈ 6.89476 kPa
  energy: kJ; MJ = 1000 kJ; kWh = 3600 kJ
"""

from __future__ import annotations

import re
from typing import Any

from _common import ToolError
from errors import MeeError, MeeErrorCode

# unit-token -> (dimension, canonical value factor, canonical unit)
# factor converts 1 raw-unit into canonical units; canonical unit = target of the row.
# NOTE: the bare token "m" is ambiguous (metre vs molar). The dictionary keeps
# the metre reading; the concentration reading is resolved contextually in
# canonicalize() when a role/label hints at a concentration quantity.
_UNITS: dict[str, tuple[str, float, str]] = {
    # strength
    "kpa": ("strength", 1.0, "kPa"),
    "mpa": ("strength", 1000.0, "kPa"),
    "kn/m2": ("strength", 1.0, "kPa"),
    "kpa.": ("strength", 1.0, "kPa"),
    # permeability
    "m/s": ("permeability", 1.0, "m/s"),
    "m s-1": ("permeability", 1.0, "m/s"),
    "ms-1": ("permeability", 1.0, "m/s"),
    "cm/s": ("permeability", 1e-2, "m/s"),
    "m/d": ("permeability", 1.0 / 86400.0, "m/s"),
    "md": ("permeability", 1.0 / 86400.0, "m/s"),
    "m/day": ("permeability", 1.0 / 86400.0, "m/s"),
    "darcy": ("permeability", 9.869233e-13, "m/s"),  # intrinsic-permeability proxy, flagged
    "d": ("permeability", 9.869233e-13, "m/s"),
    # concentration (mass)
    "g/l": ("conc_mass", 1.0, "g/L"),
    "mg/l": ("conc_mass", 1e-3, "g/L"),
    "kg/m3": ("conc_mass", 1.0, "g/L"),
    "g/l.": ("conc_mass", 1.0, "g/L"),
    "mg/ml": ("conc_mass", 1.0, "g/L"),
    "ug/l": ("conc_mass", 1e-6, "g/L"),
    # molar concentration (explicit spellings; the bare "m"/"M" token is
    # resolved contextually in _lookup — molar vs metre)
    "mol/l": ("conc_molar", 1.0, "mol/L"),
    "mol/m3": ("conc_molar", 1e-3, "mol/L"),
    "mm": ("conc_molar", 1e-3, "mol/L"),
    "um": ("conc_molar", 1e-6, "mol/L"),
    # urease activity (hydrolysis rate per OD/volume) — a distinct quantity
    # from OD600 or CFU. The canonical form preserves the reported value: there
    # is NO universal conversion between assay conventions (mM urea/min/OD vs
    # U/mL vs U/mg), so factor=1 keeps the number as reported and the unit
    # string becomes the comparable canonical token.
    "mm urea": ("urease_rate", 1.0, "mmol_urea/OD"),
    "mm urea/min": ("urease_rate", 1.0, "mmol_urea/min/OD"),
    "mm urea/min/od": ("urease_rate", 1.0, "mmol_urea/min/OD"),
    "mm urea min-1": ("urease_rate", 1.0, "mmol_urea/min/OD"),
    "mm urea min-1 od-1": ("urease_rate", 1.0, "mmol_urea/min/OD"),
    "mmol urea": ("urease_rate", 1.0, "mmol_urea/OD"),
    "mmol urea/min": ("urease_rate", 1.0, "mmol_urea/min/OD"),
    "m urea": ("urease_rate", 1.0, "mol_urea/OD"),
    "u/od": ("urease_rate", 1.0, "U/OD"),
    "u/ml": ("urease_rate", 1.0, "U/mL"),
    "u mg-1": ("urease_rate", 1.0, "U/mg"),
    # OD600 turbidity — never equated with CFU or cell concentration
    "od600": ("od600", 1.0, "OD600"),
    "od 600": ("od600", 1.0, "OD600"),
    "od": ("od600", 1.0, "OD600"),
    # temperature
    "degc": ("temperature", 1.0, "degC"),
    "c": ("temperature", 1.0, "degC"),
    "°c": ("temperature", 1.0, "degC"),
    # mass percent / fraction
    "pct": ("percent", 1.0, "percent"),
    "%": ("percent", 1.0, "percent"),
    "ppm": ("percent", 1e-4, "percent"),
    # length
    "mm": ("length", 1.0, "mm"),
    "cm": ("length", 10.0, "mm"),
    "m": ("length", 1000.0, "mm"),
    "um": ("length", 1e-3, "mm"),
    # time
    "h": ("time", 1.0, "h"),
    "hr": ("time", 1.0, "h"),
    "hour": ("time", 1.0, "h"),
    "d": ("time", 24.0, "h"),
    "day": ("time", 24.0, "h"),
    "min": ("time", 1.0 / 60.0, "h"),
    "minute": ("time", 1.0 / 60.0, "h"),
    "s": ("time", 1.0 / 3600.0, "h"),
    "sec": ("time", 1.0 / 3600.0, "h"),
    # density
    "g/cm3": ("density", 1.0, "g/cm3"),
    "kg/m3": ("density", 1e-3, "g/cm3"),
    # conductivity
    "ms/cm": ("conductivity", 1.0, "mS/cm"),
    "us/cm": ("conductivity", 1e-3, "mS/cm"),
    # volume
    "ml": ("volume", 1e-6, "m3"),
    "ul": ("volume", 1e-9, "m3"),
    "cm3": ("volume", 1e-6, "m3"),
    "l": ("volume", 1e-3, "m3"),
    # flow (injection rate)
    "ml/min": ("flow", 1.0, "mL/min"),
    "ml/h": ("flow", 1.0 / 60.0, "mL/min"),
    "l/min": ("flow", 1000.0, "mL/min"),
    "ml/hr": ("flow", 1.0 / 60.0, "mL/min"),
    # pressure
    "kpa": ("pressure", 1.0, "kPa"),
    "mpa": ("pressure", 1000.0, "kPa"),
    "psi": ("pressure", 6.894757, "kPa"),
    # energy
    "kj": ("energy", 1.0, "kJ"),
    "mj": ("energy", 1000.0, "kJ"),
    "kwh": ("energy", 3600.0, "kJ"),
    "wh": ("energy", 3.6, "kJ"),
}

# Labels/roles that strongly hint "m"/"M" means molar concentration, not metres.
_MOLAR_HINTS = ("urea", "cacl2", "cacl", "cacl2", "calcium", "nh4", "ammonium",
                "concentration", "concn", "mol", "molar", "urease substrate",
                "cementation", "reagent", "urea concentration", "urea conc")


def _fold(text: str) -> str:
    """Normalize whitespace but PRESERVE case. 'mM' (millimolar) must not
    collide with 'mm' (millimetre); 'M' (molar) must not collide with 'm'
    (metre)."""
    return re.sub(r"[\s ]+", " ", str(text or "").strip())


def _lookup(unit: str, role: str | None = None, label: str | None = None) -> tuple[str, float | None]:
    """Dictionary lookup with contextual disambiguation of molar vs length."""
    text = _fold(unit)
    # case-sensitive molar readings
    if text == "M":
        hint = _fold(f"{role or ''} {label or ''}")
        if any(h in hint.lower() for h in _MOLAR_HINTS):
            return "mol/L", 1.0
        return "mm", 1000.0
    if text == "mM":
        return "mol/L", 1e-3
    if text == "uM":
        return "mol/L", 1e-6
    if text in _UNITS:
        _dim, factor, canon = _UNITS[text]
        return canon, factor
    # case-insensitive fallback for unambiguous tokens (kPa, MPa, g/L, ...)
    low = text.lower()
    if low != text and low in _UNITS:
        _dim, factor, canon = _UNITS[low]
        return canon, factor
    if text.endswith(".") and text[:-1] in _UNITS:
        _dim, factor, canon = _UNITS[text[:-1]]
        return canon, factor
    return "", None


def canonicalize(unit: str, *, role: str | None = None, label: str | None = None) -> tuple[str, float | None]:
    """Return (canonical_unit, factor). factor=None means no conversion known."""
    return _lookup(unit, role, label)

# Dimensionless / special quantities that carry a unit token but no conversion.
_DIMENSIONLESS = {"od600": "dimensionless", "cfu": "dimensionless",
                  "viable_cell_ratio": "dimensionless", "percentage": "dimensionless"}

# Physically distinct MICP quantities and their roles (used by the ambiguity
# and the conflation guards). These can never be inter-converted.
_OD600_ALIASES = ("od600", "od 600", "optical density at 600", "optical density (od600)", "od")
_CFU_ALIASES = ("cfu", "cfu/ml", "cfu/ml.", "colony-forming units", "colony forming units",
                "cfu/g", "cfu g-1")
_CELL_ALIASES = ("cells/ml", "cells ml-1", "cell concentration", "cells per ml",
                 "cells/l", "cells/mg")
_UREASE_ALIASES = ("urease activity", "urease", "u/od", "u/ml", "mm urea", "mmol urea",
                   "mm h-1", "m urease")
_VIABLE_ALIASES = ("viable cell", "viability", "live cell", "viable cells")

_KNOWN_ROLES = {
    "od600": "od600",
    "cell_concentration": "cell_concentration",
    "cfu": "cfu",
    "urease_activity": "urease_activity",
    "viable_cell_ratio": "viable_cell_ratio",
}


def normalize(value: Any, unit: str, *, role: str | None = None,
              label: str | None = None) -> dict:
    """Normalize one (value, unit) pair. Returns a quantity-shaped dict.

    The returned dict always contains: value, unit, normalized_value,
    normalized_unit, acquisition_mode, and a `dimension` note. When the raw
    unit is absent or ambiguous the normalized fields are null/"" and the
    acquisition_mode becomes AMBIGUOUS (MEE-E203) — the caller must keep the
    placeholder out of arithmetic.
    """
    v: float | None = None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        v = float(value)
    raw_unit = str(unit or "").strip()
    canon, factor = canonicalize(raw_unit, role=role, label=label)

    if v is None:
        return {
            "value": None, "unit": raw_unit,
            "normalized_value": None, "normalized_unit": "",
            "acquisition_mode": "NOT_REPORTED",
            "dimension": None, "note": "no numeric value reported",
        }
    if not canon:
        return {
            "value": v, "unit": raw_unit,
            "normalized_value": None, "normalized_unit": "",
            "acquisition_mode": "AMBIGUOUS",
            "dimension": None,
            "note": f"unit {raw_unit!r} absent or ambiguous; normalized_value not derived (MEE-E203)",
        }
    nv = v * factor if factor is not None else None
    return {
        "value": v, "unit": raw_unit,
        "normalized_value": None if nv is None else round(nv, 12),
        "normalized_unit": canon,
        "acquisition_mode": "REPORTED_TEXT",
        "dimension": _dimension_of(canon, role),
        "note": None,
    }


def _dimension_of(canonical_unit: str, role: str | None) -> str | None:
    if role and role in _KNOWN_ROLES:
        return role
    for unit, (dim, _f, _c) in _UNITS.items():
        if canonical_unit == _c:
            return dim
    return None


def dimension_of(unit: str, *, role: str | None = None, label: str | None = None) -> str | None:
    """Dimension of a raw unit string, or None when unrecognized."""
    canon, _ = canonicalize(unit, role=role, label=label)
    if not canon:
        return None
    for _u, (dim, _f, c) in _UNITS.items():
        if canon == c:
            return dim
    return None


# ---------------------------------------------------------------------------
# Distinct-quantity conflation guard
# ---------------------------------------------------------------------------

def detect_distinct_conflation(quantities: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Flag any pair of distinct MICP quantities reported as if convertible.

    Input: list of quantity dicts each with a `role` (od600/cell_concentration/
    cfu/viable_cell_ratio/urease_activity) and optional `dimension`/`unit`.
    Output: issues with severity=error when a role carries a unit that belongs
    to a distinct quantity; info when the set contains several distinct roles
    (which by itself is fine).
    """
    issues: list[dict[str, Any]] = []
    roles = {q.get("role") for q in quantities if q.get("role") in _KNOWN_ROLES}

    # A single value labelled with one role but carrying another role's unit
    # is a hard conflation error.
    for q in quantities:
        role = q.get("role")
        if role not in _KNOWN_ROLES:
            continue
        unit = str(q.get("unit") or "").strip().lower()
        if role == "od600" and any(a in unit for a in ("cfu", "cell", "urease")):
            issues.append({
                "code": "OD600_CONFLATION", "severity": "error",
                "message": f"OD600 quantity tagged {role!r} carries unit {unit!r}, "
                           f"which belongs to a distinct quantity; OD600 is a turbidity proxy "
                           f"and must not be equated with CFU/cell/urease.",
                "details": {"role": role, "unit": unit}})
        if role == "urease_activity" and ("od" in unit and "urease" not in unit
                                          and "urea" not in unit and "u/" not in unit):
            issues.append({
                "code": "UREASE_UNIT_MISMATCH", "severity": "error",
                "message": f"urease_activity carries unit {unit!r} that looks like OD; "
                           f"urease activity must carry a hydrolysis-rate unit (e.g. mM urea/min/OD).",
                "details": {"role": role, "unit": unit}})
        if role == "cfu" and any(a in unit for a in ("od", "cell/ml", "urease")):
            issues.append({
                "code": "CFU_CONFLATION", "severity": "error",
                "message": f"CFU quantity carries unit {unit!r} belonging to a distinct "
                           f"quantity; CFU (viable count) is not interchangeable with OD or "
                           f"cell concentration.",
                "details": {"role": role, "unit": unit}})

    # Several distinct roles in one paper is fine — but report it so the reader
    # knows the distinction was preserved.
    if len(roles) >= 2:
        issues.append({
            "code": "DISTINCT_ROLES_PRESERVED", "severity": "info",
            "message": f"the extractor preserved {len(roles)} distinct biological "
                       f"quantities ({sorted(roles)}); they are not inter-converted.",
            "details": {"roles": sorted(roles)}})
    return issues


def classify_role(label: str, unit: str, value: Any) -> str | None:
    """Best-effort role classification of a quantity from its label + unit.

    Returns a canonical role token (od600 / cfu / cell_concentration /
    viable_cell_ratio / urease_activity / None). Never fabricates: returns
    None when nothing matches. Urease composite units (mM urea/min/OD) are
    matched BEFORE the bare "od" token so "OD" inside a urease unit is not
    mistaken for OD600.
    """
    text = _fold(f"{label} {unit}").lower()
    # urease activity: composite units take priority over the bare "od" token
    if any(a in text for a in _UREASE_ALIASES) or re.search(r"urea\s*/|mmol\s+urea|mm\s+urea|u/od|u/ml", text):
        if "urease" in text or "urea" in text or "u/od" in text or "u/ml" in text:
            return "urease_activity"
    for alias in _OD600_ALIASES:
        if alias in text:
            return "od600"
    for alias in _VIABLE_ALIASES:
        if alias in text:
            return "viable_cell_ratio"
    for alias in _CFU_ALIASES:
        if alias in text:
            return "cfu"
    for alias in _CELL_ALIASES:
        if alias in text:
            return "cell_concentration"
    return None


def convert(role: str, raw_value: float, from_unit: str, to_unit: str) -> float | None:
    """Convert within the same dimension. Returns None when impossible."""
    d_from = dimension_of(from_unit)
    d_to = dimension_of(to_unit)
    if d_from is None or d_from != d_to:
        return None
    canon, f = canonicalize(from_unit)
    if f is None:
        return None
    canon_t, f_t = canonicalize(to_unit)
    if f_t is None or f_t == 0:
        return None
    return raw_value * f / f_t
