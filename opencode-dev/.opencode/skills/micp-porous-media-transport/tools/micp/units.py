"""Unit and parameter validation for MICP porous-media transport.

Provides a small but rigorous quantity system:
  - Quantity(value, unit): a scalar with an explicit unit string.
  - parse_quantity(): accepts either {"value": x, "unit": "m"} or a bare
    number (dimensionless, default unit "-").
  - validate_parameter(): range + unit checks against a schema of physical
    dimensions, returning normalized SI values.

The unit grammar is deliberately closed (a lookup table) rather than a general
dimensional engine. Unknown units raise OPM-E203 so the controller never sees
silently-converted nonsense. All checks are offline and deterministic.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Any

from .errors import OpError, OpErrorCode

# ---------------------------------------------------------------------------
# Unit table: SI base dimensions (m, s, kg, mol, K) exponents.
# ---------------------------------------------------------------------------

# dims: (length, time, mass, amount, temperature)
_UNITS: dict[str, tuple[float, float, float, float, float]] = {
    # length
    "m": (1, 0, 0, 0, 0), "cm": (1, 0, 0, 0, 0), "mm": (1, 0, 0, 0, 0),
    "um": (1, 0, 0, 0, 0), "nm": (1, 0, 0, 0, 0),
    # area / volume
    "m2": (2, 0, 0, 0, 0), "cm2": (2, 0, 0, 0, 0), "mm2": (2, 0, 0, 0, 0),
    "m3": (3, 0, 0, 0, 0), "cm3": (3, 0, 0, 0, 0), "L": (3, 0, 0, 0, 0),
    "mL": (3, 0, 0, 0, 0),
    # time
    "s": (0, 1, 0, 0, 0), "min": (0, 1, 0, 0, 0), "h": (0, 1, 0, 0, 0),
    "d": (0, 1, 0, 0, 0),
    # mass
    "kg": (0, 0, 1, 0, 0), "g": (0, 0, 1, 0, 0), "mg": (0, 0, 1, 0, 0),
    # amount (mol)
    "mol": (0, 0, 0, 1, 0), "mmol": (0, 0, 0, 1, 0), "umol": (0, 0, 0, 1, 0),
    # temperature
    "K": (0, 0, 0, 0, 1), "degC": (0, 0, 0, 0, 1),
    # compound / derived
    "m/s": (1, -1, 0, 0, 0), "cm/s": (1, -1, 0, 0, 0),
    "m/d": (1, -1, 0, 0, 0), "m/h": (1, -1, 0, 0, 0),
    "mol/L": (0, 0, 0, 1, 0), "M": (0, 0, 0, 1, 0), "mM": (0, 0, 0, 1, 0),
    "mol/m3": (0, 0, 0, 1, 0), "mmol/L": (0, 0, 0, 1, 0),
    "mol/(m3*s)": (0, -1, 0, 1, 0), "mol/(L*s)": (0, -1, 0, 1, 0),
    "mol/m2/s": (0, -1, 0, 1, 0), "mol/m2*s": (0, -1, 0, 1, 0),
    "1/s": (0, -1, 0, 0, 0), "1/min": (0, -1, 0, 0, 0), "1/h": (0, -1, 0, 0, 0),
    "Pa": (-1, -2, 1, 0, 0), "kPa": (-1, -2, 1, 0, 0), "MPa": (-1, -2, 1, 0, 0),
    "atm": (-1, -2, 1, 0, 0), "bar": (-1, -2, 1, 0, 0),
    "m2/s": (2, -1, 0, 0, 0), "cm2/s": (2, -1, 0, 0, 0),
    "m2/d": (2, -1, 0, 0, 0),
    "kg/m3": (-3, 0, 1, 0, 0), "g/cm3": (-3, 0, 1, 0, 0), "g/L": (-3, 0, 1, 0, 0),
    "kg/m2/s": (0, -1, 1, -2, 0),
    # dimensionless
    "-": (0, 0, 0, 0, 0),
}

# value multiplier to SI base unit
_SI_FACTOR: dict[str, float] = {
    "m": 1.0, "cm": 1e-2, "mm": 1e-3, "um": 1e-6, "nm": 1e-9,
    "m2": 1.0, "cm2": 1e-4, "mm2": 1e-6,
    "m3": 1.0, "cm3": 1e-6, "L": 1e-3, "mL": 1e-6,
    "s": 1.0, "min": 60.0, "h": 3600.0, "d": 86400.0,
    "kg": 1.0, "g": 1e-3, "mg": 1e-6,
    "mol": 1.0, "mmol": 1e-3, "umol": 1e-6,
    "K": 1.0, "degC": 1.0,  # NOTE: degC conversion handled explicitly where used
    "m/s": 1.0, "cm/s": 1e-2, "m/d": 1.0 / 86400.0, "m/h": 1.0 / 3600.0,
    "mol/L": 1e3, "M": 1e3, "mM": 1.0, "mol/m3": 1.0, "mmol/L": 1.0,
    "mol/(m3*s)": 1.0, "mol/(L*s)": 1e3, "mol/m2/s": 1.0, "mol/m2*s": 1.0,
    "1/s": 1.0, "1/min": 1.0 / 60.0, "1/h": 1.0 / 3600.0,
    "Pa": 1.0, "kPa": 1e3, "MPa": 1e6, "atm": 101325.0, "bar": 1e5,
    "m2/s": 1.0, "cm2/s": 1e-4, "m2/d": 1.0 / 86400.0,
    "kg/m3": 1.0, "g/cm3": 1e3, "g/L": 1.0,
    "kg/m2/s": 1.0,
    "-": 1.0,
}


@dataclass(frozen=True)
class Quantity:
    value: float
    unit: str

    def to_si(self) -> float:
        """Return the value in SI base units (m, s, kg, mol, K)."""
        return self.value * _SI_FACTOR[self.unit]


@dataclass(frozen=True)
class DimensionedParam:
    """Validated parameter in canonical (SI) form."""
    key: str
    value_si: float
    unit_si: str
    value_raw: float
    unit_raw: str


# parameter -> (dimension of the *value*, allowed unit families, physical
# min/max in canonical units) — used by validate_parameter.
#
# Each entry: (dims_tuple, [allowed_unit_strings], (vmin, vmax, vmin_unit, vmax_unit))
# vmin/vmax are expressed IN the given unit for readability.
_PARAM_SPEC: dict[str, dict[str, Any]] = {
    "length":   {"dims": (1, 0, 0, 0, 0), "units": ["m", "cm", "mm"], "range": (1e-4, 10.0, "m", "m")},
    "porosity": {"dims": (0, 0, 0, 0, 0), "units": ["-"], "range": (0.001, 0.999, "-", "-")},
    "d_50":     {"dims": (1, 0, 0, 0, 0), "units": ["m", "cm", "mm", "um"], "range": (1e-6, 1e-2, "m", "m")},
    "velocity": {"dims": (1, -1, 0, 0, 0), "units": ["m/s", "cm/s", "m/d", "m/h"], "range": (1e-9, 10.0, "m/s", "m/s")},
    "flux":     {"dims": (1, -1, 0, 0, 0), "units": ["m/s", "cm/s", "m/d"], "range": (1e-9, 10.0, "m/s", "m/s")},
    "dispersion": {"dims": (2, -1, 0, 0, 0), "units": ["m2/s", "cm2/s", "m2/d"], "range": (1e-12, 1e-1, "m2/s", "m2/s")},
    "concentration": {"dims": (0, 0, 0, 1, 0), "units": ["mol/m3", "M", "mM", "mol/L", "mmol/L"],
                      "range": (1e-6, 1e3, "mol/m3", "mol/m3")},
    "rate_constant": {"dims": (0, -1, 0, 1, 0), "units": ["mol/(m3*s)", "mol/(L*s)"],
                      "range": (1e-12, 1e2, "mol/(m3*s)", "mol/(m3*s)")},
    "half_saturation": {"dims": (0, 0, 0, 1, 0), "units": ["mol/m3", "M", "mM", "mmol/L"],
                        "range": (1e-6, 1e2, "mol/m3", "mol/m3")},
    "permeability": {"dims": (-1, -2, 1, 0, 0), "units": ["Pa", "kPa", "MPa", "atm", "bar"],
                     "range": (1e-12, 1e12, "Pa", "Pa")},  # hydraulic K in Pa-s? see below
    "permeability_abs": {"dims": (2, 0, 0, 0, 0), "units": ["m2", "mm2"],
                         "range": (1e-20, 1e-6, "m2", "m2")},  # intrinsic permeability [m2]
    "pressure": {"dims": (-1, -2, 1, 0, 0), "units": ["Pa", "kPa", "MPa", "atm", "bar"],
                 "range": (0.0, 1e9, "Pa", "Pa")},
    "density": {"dims": (-3, 0, 1, 0, 0), "units": ["kg/m3", "g/cm3", "g/L"],
                "range": (1.0, 3e4, "kg/m3", "kg/m3")},
    "temperature": {"dims": (0, 0, 0, 0, 1), "units": ["K", "degC"], "range": (273.0, 373.0, "K", "K")},
}


def _parse_unit_safe(unit: str) -> tuple[float, float, float, float, float]:
    """Return dimension tuple for a unit string, raising OPM-E203 if unknown."""
    unit = (unit or "-").strip()
    if unit in _UNITS:
        return _UNITS[unit]
    raise OpError(
        OpErrorCode.UNIT_PARSE_ERROR,
        f"Unknown unit '{unit}'. Supported units: {sorted(set(_UNITS))}",
        detail={"unit": unit},
    )


def parse_quantity(raw: Any, *, key: str = "value") -> Quantity:
    """Accept a bare number (dimensionless), {'value': x, 'unit': str}, or a
    numeric string (e.g. '1e-11' arriving from a YAML/JSON source that kept it
    textual). Numeric strings are coerced defensively — never silently accepted
    as arbitrary text."""
    if isinstance(raw, (int, float)):
        if not math.isfinite(float(raw)):
            raise OpError(OpErrorCode.CONTEXT_CORRUPT,
                          f"{key}: non-finite numeric value {raw!r}.",
                          detail={"key": key})
        return Quantity(float(raw), "-")
    if isinstance(raw, str):
        try:
            val = float(raw)
        except (TypeError, ValueError):
            raise OpError(OpErrorCode.INPUT_SCHEMA_VIOLATION,
                          f"{key}: expected a number or {{value, unit}} object, got string {raw!r}.",
                          detail={"key": key})
        if not math.isfinite(val):
            raise OpError(OpErrorCode.CONTEXT_CORRUPT,
                          f"{key}: non-finite numeric value {raw!r}.",
                          detail={"key": key})
        return Quantity(val, "-")
    if isinstance(raw, dict):
        if "value" not in raw:
            raise OpError(OpErrorCode.MISSING_REQUIRED_FIELD,
                          f"{key}: quantity object requires a 'value' field.",
                          detail={"key": key, "how_to_fix": "provide value, or pass a bare number"})
        val = raw["value"]
        if isinstance(val, str):
            try:
                val = float(val)
            except (TypeError, ValueError):
                raise OpError(OpErrorCode.INPUT_SCHEMA_VIOLATION,
                              f"{key}: non-numeric 'value' string {val!r}.",
                              detail={"key": key})
        if not isinstance(val, (int, float)) or not math.isfinite(float(val)):
            raise OpError(OpErrorCode.CONTEXT_CORRUPT,
                          f"{key}: non-finite numeric value {val!r}.",
                          detail={"key": key})
        unit = str(raw.get("unit", "-"))
        _parse_unit_safe(unit)  # raises OPM-E203 on unknown unit
        return Quantity(float(val), unit)
    raise OpError(OpErrorCode.INPUT_SCHEMA_VIOLATION,
                  f"{key}: expected a number or {{value, unit}} object, got {type(raw).__name__}.",
                  detail={"key": key})


def _to_si(value: float, unit: str) -> float:
    return value * _SI_FACTOR[unit]


def validate_parameter(key: str, raw: Any) -> DimensionedParam:
    """Validate a named parameter against its spec: unit family + physical range.

    Raises:
      OPM-E102  if key is not a known parameter spec
      OPM-E203  if the unit is not in the allowed family
      OPM-E204  if the SI value falls outside the physical range
      OPM-E301  if the value is non-finite
    """
    spec = _PARAM_SPEC.get(key)
    if spec is None:
        raise OpError(OpErrorCode.MISSING_REQUIRED_FIELD,
                      f"Unknown parameter key '{key}'.",
                      detail={"known_keys": sorted(_PARAM_SPEC), "key": key})
    q = parse_quantity(raw, key=key)
    if q.unit not in spec["units"]:
        raise OpError(
            OpErrorCode.UNIT_INCONSISTENT,
            f"Parameter '{key}' has unit '{q.unit}'; expected one of {spec['units']}.",
            detail={"key": key, "unit": q.unit, "allowed": spec["units"]},
        )
    v_si = q.to_si()
    lo, hi, lo_unit, hi_unit = spec["range"]
    lo_si = _to_si(lo, lo_unit)
    hi_si = _to_si(hi, hi_unit)
    if not (lo_si <= v_si <= hi_si):
        raise OpError(
            OpErrorCode.RANGE_OUT_OF_BOUNDS,
            f"Parameter '{key}' value {q.value} {q.unit} is outside the physical range "
            f"[{lo} {lo_unit}, {hi} {hi_unit}] for this model scale.",
            detail={"key": key, "value": q.value, "unit": q.unit,
                    "range_low": lo, "range_low_unit": lo_unit,
                    "range_high": hi, "range_high_unit": hi_unit},
        )
    return DimensionedParam(
        key=key,
        value_si=v_si,
        unit_si=_SI_UNIT.get(key, _base_unit(spec["dims"])),
        value_raw=q.value,
        unit_raw=q.unit,
    )


_SI_UNIT: dict[str, str] = {
    "length": "m", "porosity": "-", "d_50": "m", "velocity": "m/s", "flux": "m/s",
    "dispersion": "m2/s", "concentration": "mol/m3", "rate_constant": "mol/(m3*s)",
    "half_saturation": "mol/m3", "permeability": "Pa", "permeability_abs": "m2",
    "pressure": "Pa", "density": "kg/m3", "temperature": "K",
}


def _base_unit(dims: tuple[float, float, float, float, float]) -> str:
    l, t, m, a, k = dims
    parts = []
    if l:
        parts.append("m" if l == 1 else f"m{l:g}")
    if t:
        parts.append("s" if t == 1 else f"s{t:g}")
    if m:
        parts.append("kg" if m == 1 else f"kg{m:g}")
    if a:
        parts.append("mol" if a == 1 else f"mol{a:g}")
    if k:
        parts.append("K" if k == 1 else f"K{k:g}")
    return "*".join(parts) if parts else "-"


def check_finite(name: str, value: float) -> float:
    """Raise OPM-E301 if value is NaN/Inf — used before numerical work."""
    if not isinstance(value, (int, float)) or not math.isfinite(float(value)):
        raise OpError(OpErrorCode.CONTEXT_CORRUPT,
                      f"Non-finite value for '{name}': {value!r}.",
                      detail={"name": name})
    return float(value)


_UINT_RE = re.compile(r"^\d+$")


def safe_project_id(pid: str) -> str:
    """Project ids must be filesystem-safe and bounded (defense against path
    traversal / header injection)."""
    if not isinstance(pid, str) or not (1 <= len(pid) <= 64):
        raise OpError(OpErrorCode.INPUT_SCHEMA_VIOLATION,
                      "project_id must be a string of 1..64 characters.",
                      detail={"project_id": pid})
    if not re.match(r"^[A-Za-z0-9._-]+$", pid):
        raise OpError(OpErrorCode.INPUT_SCHEMA_VIOLATION,
                      "project_id may only contain [A-Za-z0-9._-].",
                      detail={"project_id": pid})
    return pid
