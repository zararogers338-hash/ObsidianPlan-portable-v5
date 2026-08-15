"""Unit and parameter validation for micp-scaleup-injection-engineer.

Provides a small but rigorous quantity system (mirrors the porous-media
transport skill):
  - Quantity(value, unit): a scalar with an explicit unit string.
  - parse_quantity(): accepts either {"value": x, "unit": "m"} or a bare
    number (dimensionless, default unit "-").
  - validate_parameter(): range + unit checks against a spec of physical
    dimensions, returning normalized SI values.

The unit grammar is deliberately closed (a lookup table). Unknown units raise
MSI-E203 so the controller never sees silently-converted nonsense. All checks
are offline and deterministic.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Any

from .errors import OpError, OpErrorCode

# dims: (length, time, mass, amount, temperature)
_UNITS: dict[str, tuple[float, float, float, float, float]] = {
    "m": (1, 0, 0, 0, 0), "cm": (1, 0, 0, 0, 0), "mm": (1, 0, 0, 0, 0),
    "um": (1, 0, 0, 0, 0), "nm": (1, 0, 0, 0, 0),
    "m2": (2, 0, 0, 0, 0), "cm2": (2, 0, 0, 0, 0), "mm2": (2, 0, 0, 0, 0),
    "m3": (3, 0, 0, 0, 0), "cm3": (3, 0, 0, 0, 0), "L": (3, 0, 0, 0, 0),
    "mL": (3, 0, 0, 0, 0),
    "s": (0, 1, 0, 0, 0), "min": (0, 1, 0, 0, 0), "h": (0, 1, 0, 0, 0),
    "d": (0, 1, 0, 0, 0),
    "kg": (0, 0, 1, 0, 0), "g": (0, 0, 1, 0, 0), "mg": (0, 0, 1, 0, 0),
    "mol": (0, 0, 0, 1, 0), "mmol": (0, 0, 0, 1, 0), "umol": (0, 0, 0, 1, 0),
    "K": (0, 0, 0, 0, 1), "degC": (0, 0, 0, 0, 1),
    "m/s": (1, -1, 0, 0, 0), "cm/s": (1, -1, 0, 0, 0),
    "m/d": (1, -1, 0, 0, 0), "m/h": (1, -1, 0, 0, 0),
    "m3/s": (3, -1, 0, 0, 0), "L/min": (3, -1, 0, 0, 0),
    "L/h": (3, -1, 0, 0, 0), "m3/h": (3, -1, 0, 0, 0),
    "mol/L": (0, 0, 0, 1, 0), "M": (0, 0, 0, 1, 0), "mM": (0, 0, 0, 1, 0),
    "mol/m3": (0, 0, 0, 1, 0), "mmol/L": (0, 0, 0, 1, 0),
    "kg/m3": (-3, 0, 1, 0, 0), "g/cm3": (-3, 0, 1, 0, 0), "g/L": (-3, 0, 1, 0, 0),
    "Pa": (-1, -2, 1, 0, 0), "kPa": (-1, -2, 1, 0, 0), "MPa": (-1, -2, 1, 0, 0),
    "atm": (-1, -2, 1, 0, 0), "bar": (-1, -2, 1, 0, 0),
    "m2/s": (2, -1, 0, 0, 0), "cm2/s": (2, -1, 0, 0, 0),
    "m2/d": (2, -1, 0, 0, 0),
    "mS/cm": (-1, 0, 1, 0, 0), "uS/cm": (-1, 0, 1, 0, 0),
    "D": (2, 0, 0, 0, 0),
    "-": (0, 0, 0, 0, 0),
}

_SI_FACTOR: dict[str, float] = {
    "m": 1.0, "cm": 1e-2, "mm": 1e-3, "um": 1e-6, "nm": 1e-9,
    "m2": 1.0, "cm2": 1e-4, "mm2": 1e-6,
    "m3": 1.0, "cm3": 1e-6, "L": 1e-3, "mL": 1e-6,
    "s": 1.0, "min": 60.0, "h": 3600.0, "d": 86400.0,
    "kg": 1.0, "g": 1e-3, "mg": 1e-6,
    "mol": 1.0, "mmol": 1e-3, "umol": 1e-6,
    "K": 1.0, "degC": 1.0,
    "m/s": 1.0, "cm/s": 1e-2, "m/d": 1.0 / 86400.0, "m/h": 1.0 / 3600.0,
    "m3/s": 1.0, "L/min": 1e-3 / 60.0, "L/h": 1e-3 / 3600.0, "m3/h": 1.0 / 3600.0,
    "mol/L": 1e3, "M": 1e3, "mM": 1.0, "mol/m3": 1.0, "mmol/L": 1.0,
    "kg/m3": 1.0, "g/cm3": 1e3, "g/L": 1.0,
    "Pa": 1.0, "kPa": 1e3, "MPa": 1e6, "atm": 101325.0, "bar": 1e5,
    "m2/s": 1.0, "cm2/s": 1e-4, "m2/d": 1.0 / 86400.0,
    "mS/cm": 0.1, "uS/cm": 1e-4,  # S/m
    "D": 9.869233e-13,  # Darcy to m2
    "-": 1.0,
}

# parameter -> (dims, allowed units, (vmin, vmax, vmin_unit, vmax_unit))
_PARAM_SPEC: dict[str, dict[str, Any]] = {
    "length": {"dims": (1, 0, 0, 0, 0), "units": ["m", "cm", "mm"], "range": (1e-4, 1e3, "m", "m")},
    "depth": {"dims": (1, 0, 0, 0, 0), "units": ["m", "cm", "mm"], "range": (1e-4, 2e3, "m", "m")},
    "radius": {"dims": (1, 0, 0, 0, 0), "units": ["m", "cm", "mm"], "range": (1e-4, 1e2, "m", "m")},
    "volume": {"dims": (3, 0, 0, 0, 0), "units": ["m3", "L", "mL", "cm3"], "range": (1e-9, 1e8, "m3", "m3")},
    "flow_rate": {"dims": (3, -1, 0, 0, 0), "units": ["m3/s", "L/min", "L/h", "m3/h"], "range": (1e-12, 10.0, "m3/s", "m3/s")},
    "velocity": {"dims": (1, -1, 0, 0, 0), "units": ["m/s", "cm/s", "m/d", "m/h"], "range": (1e-9, 10.0, "m/s", "m/s")},
    "pressure": {"dims": (-1, -2, 1, 0, 0), "units": ["Pa", "kPa", "MPa", "atm", "bar"], "range": (0.0, 1e9, "Pa", "Pa")},
    "permeability": {"dims": (2, 0, 0, 0, 0), "units": ["m2", "cm2", "mm2", "D"], "range": (1e-20, 1e-6, "m2", "m2")},
    "hydraulic_conductivity": {"dims": (1, -1, 0, 0, 0), "units": ["m/s", "cm/s", "m/d", "m/h"], "range": (1e-12, 10.0, "m/s", "m/s")},
    "concentration": {"dims": (0, 0, 0, 1, 0), "units": ["mol/m3", "M", "mM", "mol/L", "mmol/L"], "range": (1e-6, 1e4, "mol/m3", "mol/m3")},
    "d50": {"dims": (1, 0, 0, 0, 0), "units": ["m", "cm", "mm", "um"], "range": (1e-6, 1e-2, "m", "m")},
    "temperature": {"dims": (0, 0, 0, 0, 1), "units": ["K", "degC"], "range": (253.0, 373.0, "K", "K")},
    "mass_per_volume": {"dims": (-3, 0, 1, 0, 0), "units": ["kg/m3", "g/L", "g/cm3", "kg/L"], "range": (0.0, 1e4, "kg/m3", "kg/m3")},
    "time": {"dims": (0, 1, 0, 0, 0), "units": ["s", "min", "h", "d"], "range": (0.0, 1e10, "s", "s")},
}

_SI_UNIT: dict[str, str] = {
    "length": "m", "depth": "m", "radius": "m", "volume": "m3", "flow_rate": "m3/s",
    "velocity": "m/s", "pressure": "Pa", "permeability": "m2",
    "hydraulic_conductivity": "m/s", "concentration": "mol/m3", "d50": "m",
    "temperature": "K", "mass_per_volume": "kg/m3", "time": "s",
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


@dataclass(frozen=True)
class Quantity:
    value: float
    unit: str

    def to_si(self) -> float:
        return self.value * _SI_FACTOR[self.unit]


@dataclass(frozen=True)
class DimensionedParam:
    key: str
    value_si: float
    unit_si: str
    value_raw: float
    unit_raw: str


def _parse_unit_safe(unit: str) -> tuple[float, float, float, float, float]:
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
    numeric string. Non-finite values raise MSI-E301."""
    if isinstance(raw, (int, float)):
        if not math.isfinite(float(raw)):
            raise OpError(OpErrorCode.CONTEXT_CORRUPT,
                          f"{key}: non-finite numeric value {raw!r}.", detail={"key": key})
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
                          f"{key}: non-finite numeric value {raw!r}.", detail={"key": key})
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
                              f"{key}: non-numeric 'value' string {val!r}.", detail={"key": key})
        if not isinstance(val, (int, float)) or not math.isfinite(float(val)):
            raise OpError(OpErrorCode.CONTEXT_CORRUPT,
                          f"{key}: non-finite numeric value {val!r}.", detail={"key": key})
        unit = str(raw.get("unit", "-"))
        _parse_unit_safe(unit)
        return Quantity(float(val), unit)
    raise OpError(OpErrorCode.INPUT_SCHEMA_VIOLATION,
                  f"{key}: expected a number or {{value, unit}} object, got {type(raw).__name__}.",
                  detail={"key": key})


def _to_si(value: float, unit: str) -> float:
    return value * _SI_FACTOR[unit]


def validate_parameter(key: str, raw: Any) -> DimensionedParam:
    """Validate a named parameter against its spec: unit family + physical range."""
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
            f"[{lo} {lo_unit}, {hi} {hi_unit}] for this scale level.",
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


def check_finite(name: str, value: float) -> float:
    if not isinstance(value, (int, float)) or not math.isfinite(float(value)):
        raise OpError(OpErrorCode.CONTEXT_CORRUPT,
                      f"Non-finite value for '{name}': {value!r}.", detail={"name": name})
    return float(value)


def safe_project_id(pid: str) -> str:
    if not isinstance(pid, str) or not (1 <= len(pid) <= 64):
        raise OpError(OpErrorCode.INPUT_SCHEMA_VIOLATION,
                      "project_id must be a string of 1..64 characters.",
                      detail={"project_id": pid})
    if not re.match(r"^[A-Za-z0-9._-]+$", pid):
        raise OpError(OpErrorCode.INPUT_SCHEMA_VIOLATION,
                      "project_id may only contain [A-Za-z0-9._-].",
                      detail={"project_id": pid})
    return pid
