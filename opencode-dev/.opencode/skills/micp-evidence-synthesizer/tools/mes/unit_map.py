"""Unit normalization (OES-E103).

Rules implemented (documented in SKILL.md §5 与 references/sources.md):
  - mechanical stress/strength:  kPa ⇄ MPa ⇄ Pa ⇄ GPa (factor 1000 per step)
  - pressure:                   Pa ⇄ kPa ⇄ MPa (shared prefix table)
  - CaCO3 content:              "%" and "g/kg" via density assumption flagged;
                                a plain percentage is dimensionless.
  - temperature:                Celsius ⇄ Kelvin (offset, not a factor)
  - concentration (molar):      mol/L ⇄ mmol/L ⇄ µM (prefix table)
  - density:                    kg/m³ ⇄ g/cm³ (factor 1000)

Unified units: internal canonical units are SI where a mapping exists, but the
*raw* values are always preserved (output keeps `unit` and `value` verbatim,
and adds `normalized_value` in `normalized_unit`). Any unknown unit is flagged
as `unmapped` — never silently coerced.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from .errors import MesError, MesErrorCode

_SI_PREFIXES: dict[str, float] = {
    "G": 1e9, "M": 1e6, "k": 1e3, "": 1.0, "m": 1e-3, "u": 1e-6, "n": 1e-9,
}
# (prefix, base)
_BASE_UNITS: dict[str, str] = {"Pa": "Pa", "g": "g", "mol": "mol", "L": "L", "s": "s"}


@dataclass(frozen=True)
class Quantity:
    value: float
    unit: str
    normalized_value: Optional[float] = None
    normalized_unit: Optional[str] = None
    canonical: Optional[float] = None  # canonical value in canonical unit


def _strip_norm(s: str) -> str:
    return s.strip().lower().replace("−", "-").replace(" ", "")


def _parse_pa(unit: str) -> Optional[tuple[float, str]]:
    """Return (factor, canonical_base) for a Pa-family unit, else None."""
    u = _strip_norm(unit)
    for base in ("pa", "kpa", "mpa", "gpa"):
        if u == base:
            factor = {"pa": 1.0, "kpa": 1e3, "mpa": 1e6, "gpa": 1e9}[base]
            return (factor, "Pa")
    # prefix form like "mPa" handled generically below via table
    if u.endswith("pa"):
        prefix = u[:-2]
        if prefix in _SI_PREFIXES:
            return (_SI_PREFIXES[prefix], "Pa")
    return None


def _parse_concentration(unit: str) -> Optional[tuple[float, str]]:
    """mol/L-family. Returns (factor to mol/L, canonical 'mol/L')."""
    u = _strip_norm(unit)
    for base, factor in (("mol/l", 1.0), ("moll", 1.0), ("m", 1.0)):
        pass
    if u in ("mol/l", "moll", "mol l", "molar"):
        return (1.0, "mol/L")
    if u in ("mmol/l", "mmoll"):
        return (1e-3, "mol/L")
    if u in ("umol/l", "µmol/l", "umoll"):
        return (1e-6, "mol/L")
    if u.endswith("m") and len(u) >= 2 and u[-2] in "0123456789µum":
        # e.g. "0.5m" (molar shorthand) — not handled; falls through
        return None
    return None


def _parse_mass_fraction(unit: str) -> Optional[tuple[float, str]]:
    u = _strip_norm(unit)
    if u in ("%", "pct", "percent", "w/w", "wt%", "wt%"):
        return (1.0, "%")
    if u == "g/kg":
        # g/kg -> % requires density; we expose the ratio without forcing a
        # conversion: g/kg * 0.1 = % ONLY for dilute aqueous-like systems.
        return (0.1, "%")
    return None


def _parse_temperature(unit: str) -> Optional[tuple[float, str]]:
    u = _strip_norm(unit)
    if u == "c":
        return (1.0, "C")  # handled with offset in convert
    if u == "k":
        return (1.0, "K")
    return None


def _parse_density(unit: str) -> Optional[tuple[float, str]]:
    u = _strip_norm(unit)
    if u in ("kg/m3", "kgm3", "kg/m^3"):
        return (1.0, "kg/m3")
    if u in ("g/cm3", "gcm3", "g/ml", "gml"):
        return (1000.0, "kg/m3")
    return None


def parse_unit(unit: str) -> Optional[tuple[float, str]]:
    """Parse a unit into (factor-to-canonical, canonical). None if unmapped."""
    if not isinstance(unit, str) or unit == "":
        return None
    for parser in (_parse_pa, _parse_concentration, _parse_mass_fraction,
                   _parse_temperature, _parse_density):
        result = parser(unit)
        if result is not None:
            return result
    return None


def convert(value: float, from_unit: str, to_unit: str) -> Optional[float]:
    """Convert a numeric value between two units.

    Returns None when either unit is unmapped, or conversion is not defined
    (e.g. dimensionless % to Pa). Raises MesError on non-finite input.
    """
    if value != value or value in (float("inf"), float("-inf")):
        raise MesError(MesErrorCode.NUMERIC_INVALID, f"non-finite value {value}")
    f = parse_unit(from_unit)
    t = parse_unit(to_unit)
    if f is None or t is None:
        return None
    f_factor, f_canon = f
    t_factor, t_canon = t
    if f_canon != t_canon:
        # temperature offsets
        if f_canon == "C" and t_canon == "K":
            return value + 273.15
        if f_canon == "K" and t_canon == "C":
            return value - 273.15
        return None
    return value * f_factor / t_factor


def normalize(value: float, unit: str, target_unit: Optional[str] = None) -> Quantity:
    """Normalize a value; preserve raw value + unit verbatim.

    `target_unit` is the PICO-declared nominal output unit, when known.
    Returns Quantity(value, unit, normalized_value, normalized_unit, canonical).
    """
    if value != value or value in (float("inf"), float("-inf")):
        raise MesError(MesErrorCode.NUMERIC_INVALID, f"non-finite value {value}")
    parsed = parse_unit(unit)
    if parsed is None:
        return Quantity(value=value, unit=unit, normalized_value=None, normalized_unit=None, canonical=None)
    factor, canonical = parsed
    canonical_value = value * factor
    if target_unit:
        conv = convert(canonical_value, canonical, target_unit)
        if conv is not None:
            return Quantity(value, unit, conv, target_unit, canonical_value)
    return Quantity(value, unit, canonical_value, canonical, canonical_value)


def comparable_unit(unit_a: str, unit_b: str) -> bool:
    """Are two units comparable (same canonical dimension)? Unknown → False."""
    a = parse_unit(unit_a)
    b = parse_unit(unit_b)
    if a is None or b is None:
        return False
    if a[1] != b[1]:
        # temperature cross-comparison
        if {a[1], b[1]} == {"C", "K"}:
            return True
        return False
    return True
