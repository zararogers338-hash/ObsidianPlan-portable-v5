"""Normalization tools (spec §四.4): synonyms, abbreviations, and unit checks.

Everything here is pure and deterministic. None of it contacts the network.
The normalization dictionary is deliberately small and domain-focused; it is
authoritative only for the entries it contains. Unrecognized tokens are
passed through unchanged (never silently rewritten to a guess).
"""

from __future__ import annotations

import math
import re
from typing import Any

from .errors import KgeError, KgeErrorCode

# ---------------------------------------------------------------------------
# Name / synonym normalization
# ---------------------------------------------------------------------------

# Canonical strain names for well-known MICP strains (project convention;
# authoritative external references are in references/sources.md).
STRAIN_CANONICAL: dict[str, str] = {
    "sporosarcina pasteurii": "Sporosarcina pasteurii",
    "sporosarcina pasteurii dsm 33": "Sporosarcina pasteurii",
    "sporosarcina pasteurii atcc 11859": "Sporosarcina pasteurii",
    "sporosarcina pasteurii atcc 6453": "Sporosarcina pasteurii",
    "s. pasteurii": "Sporosarcina pasteurii",
    "sp. pasteurii": "Sporosarcina pasteurii",
    "bacillus pasteurii": "Sporosarcina pasteurii",  # former name, still widely used
    "b. pasteurii": "Sporosarcina pasteurii",
    "bacillus pasteurii dsm 33": "Sporosarcina pasteurii",
    "bacillus megaterium": "Bacillus megaterium",
    "b. megaterium": "Bacillus megaterium",
    "bacillus subtilis": "Bacillus subtilis",
    "b. subtilis": "Bacillus subtilis",
    "escherichia coli": "Escherichia coli",
    "e. coli": "Escherichia coli",
}

# Canonical mineral-phase names (mineralogy convention; XRD phase ID).
MINERAL_CANONICAL: dict[str, str] = {
    "caco3": "calcium carbonate (CaCO3)",
    "calcium carbonate": "calcium carbonate (CaCO3)",
    "calcite": "calcite",
    "caco3-calcite": "calcite",
    "aragonite": "aragonite",
    "vaterite": "vaterite",
    "amorphous calcium carbonate": "amorphous calcium carbonate (ACC)",
    "acc": "amorphous calcium carbonate (ACC)",
    "dolomite": "dolomite",
    "magnesite": "magnesite",
}

# Canonical chemical ion / species names.
ION_CANONICAL: dict[str, str] = {
    "ca2+": "Ca2+",
    "ca(2+)": "Ca2+",
    "calcium ion": "Ca2+",
    "nh4+": "NH4+",
    "nh4": "NH4+",
    "ammonium": "NH4+",
    "ammonium ion": "NH4+",
    "co32-": "CO3(2-)",
    "co3(2-)": "CO3(2-)",
    "carbonate ion": "CO3(2-)",
    "hco3-": "HCO3-",
    "bicarbonate": "HCO3-",
    "oh-": "OH-",
    "hydroxide": "OH-",
    "urea": "urea",
    "carbamide": "urea",
}

# Canonical MICP / environmental terms.
TERM_CANONICAL: dict[str, str] = {
    "micp": "microbially induced calcium carbonate precipitation",
    "microbial induced calcite precipitation": "microbially induced calcium carbonate precipitation",
    "biocementation": "biocementation",
    "biomineralization": "biomineralization",
    "ureolysis": "ureolysis (urea hydrolysis)",
    "urease": "urease (EC 3.5.1.5)",
    "ec 3.5.1.5": "urease (EC 3.5.1.5)",
    "uds": "urea dosing solution",
    "toc": "total organic carbon",
    "tds": "total dissolved solids",
    "xrd": "X-ray diffraction (XRD)",
    "sem": "scanning electron microscopy (SEM)",
    "icp-oes": "inductively coupled plasma optical emission spectrometry (ICP-OES)",
    "icp-ms": "inductively coupled plasma mass spectrometry (ICP-MS)",
    "ucs": "unconfined compressive strength",
}

_CANONICAL_TABLES: list[tuple[dict[str, str], str]] = [
    (STRAIN_CANONICAL, "strain"),
    (MINERAL_CANONICAL, "mineral"),
    (ION_CANONICAL, "ion"),
    (TERM_CANONICAL, "term"),
]


def normalize_name(raw: str) -> str:
    """Lowercase, strip punctuation, collapse whitespace — then table-lookup.

    Returns the canonical name when the input maps to a known canonical form,
    otherwise a lightly cleaned copy of the input. Never a guess.
    """
    if not raw:
        return raw
    key = _clean_key(raw)
    if not key:
        return raw.strip()
    for table, _kind in _CANONICAL_LOOKUP:
        if key in table:
            return table[key]
    return raw.strip()


def lookup_synonyms(raw: str) -> list[str]:
    """Return known synonyms (aliases) for a name, or [] when unknown."""
    key = _clean_key(raw)
    for table, _kind in _CANONICAL_LOOKUP:
        if key in table:
            canon = table[key]
            return sorted({alias for alias, t in table.items() if t == canon})
    return []


def _clean_key(raw: str) -> str:
    """The match key: lowercase, Unicode-strip diacritics, drop non-alnum."""
    s = raw.lower().strip()
    s = "".join(c for c in s if c.isalnum() or c.isspace())
    s = " ".join(s.split())
    return s


def _indexed_canonical_tables() -> list[tuple[dict[str, str], str]]:
    """Return the canonical tables augmented with cleaned-key aliases.

    Keys are written human-friendly ("s. pasteurii") but matching uses the
    cleaned form ("s pasteurii"); every entry gets both so either spelling
    resolves. Deterministic and pure.
    """
    result: list[tuple[dict[str, str], str]] = []
    for table, kind in _CANONICAL_TABLES:
        merged: dict[str, str] = {}
        for key, canon in table.items():
            merged[key] = canon
            cleaned = _clean_key(key)
            if cleaned and cleaned != key:
                merged[cleaned] = canon
        result.append((merged, kind))
    return result


_CANONICAL_LOOKUP = _indexed_canonical_tables()


def entity_display_name(entity: dict[str, Any]) -> str:
    """Display name: canonical_name if set, else the id."""
    return str(entity.get("canonical_name") or entity.get("id"))


# ---------------------------------------------------------------------------
# Unit normalization and checks (spec §四.4, §五: all numeric tools must check
# units, empty values, non-finite values, range, dimension, and precision).
# ---------------------------------------------------------------------------

# Dimension -> canonical SI base. All members of a dimension class must convert
# into the canonical base; anything not listed is treated as "unknown
# dimension" and only exact-string matches are comparable.
_UNIT_TABLE: dict[str, dict[str, float]] = {
    # canonical base: "g", "m", "s", "mol", "K", "m^3", "m/s", "Pa", "-"
    "g": {"g": 1.0, "mg": 1e-3, "kg": 1e3, "ug": 1e-6},
    "m": {"m": 1.0, "mm": 1e-3, "cm": 1e-2, "um": 1e-6, "nm": 1e-9},
    "mol": {"mol": 1.0, "mmol": 1e-3, "umol": 1e-6},
    "pa": {"Pa": 1.0, "kPa": 1e3, "MPa": 1e6, "GPa": 1e9, "bar": 1e5, "psi": 6894.757},
    "m3": {"m3": 1.0, "cm3": 1e-6, "L": 1e-3, "mL": 1e-6, "uL": 1e-9},
    "m_s": {"m/s": 1.0, "cm/s": 1e-2, "mm/s": 1e-3, "m/d": 1.0 / 86400.0, "cm/d": 1e-2 / 86400.0},
    "s": {"s": 1.0, "min": 60.0, "h": 3600.0, "hr": 3600.0, "day": 86400.0},
    "k": {"K": 1.0, "degC": 1.0, "C": 1.0},  # degC handled specially (offset)
    "dimensionless": {"": 1.0, "-": 1.0, "%": 1.0, "percent": 1.0},
}

_UNIT_ALIASES: dict[str, str] = {
    "kg/m3": "kg/m^3", "g/cm3": "g/cm^3", "mg/L": "mg/L", "g/L": "g/L",
    "mmol/L": "mmol/L", "mol/L": "mol/L", "mm/min": "mm/min", "%/min": "%/min",
}


def _split_compound(unit: str) -> list[str]:
    """Split a compound unit into numerator/denominator factors.

    Handles: "kg/m^3", "mg/L", "mmol/L", "m/s", "cm/s", "m/d", "g/cm^3",
    "MPa", "mm/min", "%", "-", "". Unknown tokens are returned as-is and later
    cause a UNIT_INCONSISTENT rejection.
    """
    unit = (unit or "").strip()
    if not unit:
        return ["dimensionless"]
    num, _, den = unit.partition("/")
    if not den:
        return [unit]
    return [t.strip() for t in num.split("*") if t.strip()] + \
           [t.strip() for t in den.split("*") if t.strip()]


def _factor(unit: str) -> float | None:
    """Return the conversion factor into the canonical dimension base, or None."""
    u = unit.strip()
    if u == "":
        return 1.0
    if u in ("K", "degC", "C"):
        return 1.0
    for base, table in _UNIT_TABLE.items():
        if u in table:
            return table[u]
    return None


def normalize_unit(unit: str) -> str:
    """Return a canonical unit label for a known unit, else the input."""
    u = (unit or "").strip()
    if u in _UNIT_ALIASES:
        return _UNIT_ALIASES[u]
    if _factor(u) is not None:
        return u
    return u


def _dimension(unit: str) -> tuple[str, ...] | None:
    """Dimension signature (sorted factor dimensions), or None if unknown."""
    if unit == "dimensionless":
        return ("-",)
    if (unit or "").strip() in ("", "-", "%"):
        return ("-",)
    factors = _split_compound(unit)
    sig: list[str] = []
    for f in factors:
        # temperature offset units only allowed alone
        if f in ("K", "degC", "C"):
            sig.append("K")
            continue
        base = None
        for b, table in _UNIT_TABLE.items():
            if f in table:
                base = b
                break
        if base is None:
            return None
        sig.append(base)
    return tuple(sorted(sig))


def units_compatible(a: str, b: str) -> bool:
    """Whether two unit strings are dimensionally compatible."""
    da, db = _dimension(a), _dimension(b)
    if da is None or db is None:
        # unknown dimension: only exact-string equality is comparable
        return (a or "").strip().lower() == (b or "").strip().lower()
    return da == db


def to_base(value: float, unit: str) -> tuple[float, str] | None:
    """Convert a value to its canonical base (base, base-unit). Returns None
    for unknown/unsupported units or non-finite values."""
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return None
    if not math.isfinite(value):
        return None
    u = (unit or "").strip()
    if u in ("K", "degC", "C"):
        if u in ("degC", "C"):
            return value + 273.15, "K"
        return value, "K"
    factors = _split_compound(u)
    if len(factors) != 1:
        return None
    f = _factor(factors[0])
    if f is None:
        return None
    for base, table in _UNIT_TABLE.items():
        if factors[0] in table:
            return value * f, base
    return None


def check_quantity(quantity: dict[str, Any]) -> dict[str, Any]:
    """Validate a {value, unit} quantity dict.

    Raises KGE-E203 on: missing value/unit, non-numeric value, non-finite
    value, or out-of-domain range (temperature/percentage sanity bounds).
    Returns a normalized copy with an added `_base` when convertible.
    """
    if not isinstance(quantity, dict):
        raise KgeError(KgeErrorCode.UNIT_INCONSISTENT,
                       "quantity must be an object with {value, unit}.",
                       detail={"got": type(quantity).__name__})
    value = quantity.get("value")
    unit = quantity.get("unit")
    if value is None or unit is None:
        raise KgeError(KgeErrorCode.UNIT_INCONSISTENT,
                       "quantity requires both 'value' and 'unit'.",
                       detail={"keys": sorted(quantity.keys())})
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise KgeError(KgeErrorCode.UNIT_INCONSISTENT,
                       f"quantity.value must be numeric, got {type(value).__name__}.",
                       detail={"value": value})
    if not math.isfinite(value):
        raise KgeError(KgeErrorCode.UNIT_INCONSISTENT,
                       f"quantity.value is not finite ({value}); NaN/Inf rejected.",
                       detail={"value": value})
    base = to_base(value, unit)
    normalized = dict(quantity)
    if base is not None:
        normalized["_base"] = {"value": base[0], "unit": base[1]}
    return normalized


def check_value_range(value: float, unit: str, *, low: float | None = None,
                      high: float | None = None, label: str = "value") -> None:
    """Range check in the given unit. Raises KGE-E203 on violation."""
    if not math.isfinite(value):
        raise KgeError(KgeErrorCode.UNIT_INCONSISTENT,
                       f"{label} is not finite; NaN/Inf rejected.", detail={"value": value})
    if low is not None and value < low:
        raise KgeError(KgeErrorCode.UNIT_INCONSISTENT,
                       f"{label} {value} is below the domain floor {low} {unit}.",
                       detail={"value": value, "unit": unit, "min": low})
    if high is not None and value > high:
        raise KgeError(KgeErrorCode.UNIT_INCONSISTENT,
                       f"{label} {value} is above the domain ceiling {high} {unit}.",
                       detail={"value": value, "unit": unit, "max": high})


# Default domain ranges used by claim ingestion (configurable per claim).
DOMAIN_RANGES: dict[str, tuple[float, float, str]] = {
    "temperature": (0.0, 100.0, "degC"),      # mesophilic MICP lab/field window
    "caco3_content_percent": (0.0, 100.0, "%"),
    "urea_conc_mol_l": (0.0, 5.0, "mol/L"),
    "ph": (0.0, 14.0, "-"),
}
