"""Unit & dimension handling, and functional-unit / reference-flow conversion.

Pure stdlib, no third-party units library. Two layers:

1. `convert(value, from_unit, to_unit)` — linear conversions across known
   dimensions: mass (kg/g/t), volume (m3/L/cm3), length (m/cm/mm/km),
   area (m2), energy (MJ/GJ/kWh), money (CNY/USD/EUR via pinned rates),
   intensity (kg CO2eq/t-km, USD/m3, ...), concentration (mol/L, g/L), etc.
2. Functional-unit normalization: a scenario's flows are scaled so that its
   *reference flow* matches the declared functional unit. For example, if the
   functional unit is "stabilize 1 m3 of sand to UCS >= 1.0 MPa" and the
   scenario was costed for a 100 m3 pilot, every inventory line is divided by
   100.

Design rules:
- Every conversion must be reversible and deterministic.
- Money conversion uses fixed, versioned rates (RATES_VERSION); local prices
  stay in local currency and are only converted for reporting, never
  mid-analysis, unless the caller asks.
- Unknown conversions raise ToolError (LCA-E205) instead of guessing.
"""

from __future__ import annotations

import math

from _common import ToolError, as_number
from errors import LcaErrorCode

RATES_VERSION = "2026-08-r1"
# Pinned reference rates for reporting convenience. These are NOT market
# feeds — see references/sources.md "Money". Prices are analysed in the
# currency they were declared in; conversion is display-only.
PINNED_RATES: dict[str, float] = {
    "CNY_to_USD": 0.14,   # ~7.15 CNY/USD (2026 reference; see sources)
    "EUR_to_USD": 1.08,
    "USD_to_CNY": 7.15,
    "EUR_to_CNY": 7.72,
}

# ---------------------------------------------------------------------------
# Dimension system
# ---------------------------------------------------------------------------

_MASS = {
    "kg": 1.0, "g": 1e-3, "mg": 1e-6, "t": 1e3, "ton": 1e3, "tonne": 1e3,
    "mt": 1e3,  # metric ton
    "lb": 0.45359237,
    "oz": 0.028349523125,
}
_VOLUME = {
    "m3": 1.0, "L": 1e-3, "l": 1e-3, "dm3": 1e-3, "cm3": 1e-6, "ml": 1e-6,
    "mL": 1e-6, "gal": 3.785411784e-3, "US_gal": 3.785411784e-3,
}
_LENGTH = {"m": 1.0, "cm": 1e-2, "mm": 1e-3, "km": 1e3, "ft": 0.3048}
_AREA = {"m2": 1.0, "cm2": 1e-4, "ha": 1e4, "km2": 1e6}
_ENERGY = {"MJ": 1.0, "GJ": 1e3, "kWh": 3.6, "MWh": 3.6e3, "J": 1e-6, "kcal": 4.184e-3}
_TIME = {"h": 1.0, "min": 1.0 / 60.0, "s": 1.0 / 3600.0, "day": 24.0, "yr": 8760.0}
_MONEY = {"CNY": 1.0, "USD": PINNED_RATES["USD_to_CNY"], "EUR": PINNED_RATES["EUR_to_CNY"]}
_PRESSURE = {"MPa": 1.0, "kPa": 1e-3, "Pa": 1e-6, "bar": 0.1}
_CONC = {"mol/L": 1.0, "mM": 1e-3, "mol/m3": 1e-3, "g/L": None, "mg/L": None}  # mass-based needs molar mass


def _lookup(table: dict[str, float], unit: str) -> float | None:
    return table.get(unit)


def _dimension_for(unit: str) -> str | None:
    """Return the dimension a bare unit belongs to, or None."""
    for dim, table in (
        ("mass", _MASS), ("volume", _VOLUME), ("length", _LENGTH),
        ("area", _AREA), ("energy", _ENERGY), ("time", _TIME),
        ("money", _MONEY), ("pressure", _PRESSURE),
    ):
        if unit in table:
            return dim
    return None


def is_mass(unit: str) -> bool: return _dimension_for(unit) == "mass"
def is_volume(unit: str) -> bool: return _dimension_for(unit) == "volume"
def is_money(unit: str) -> bool: return _dimension_for(unit) == "money"
def is_energy(unit: str) -> bool: return _dimension_for(unit) == "energy"


def normalize_quantity(value: float, unit: str) -> tuple[float, str]:
    """Return (value_in_si_base, canonical_unit) for a bare unit."""
    v = as_number(value, "value")
    base = _lookup(_MASS, unit) or _lookup(_VOLUME, unit) or _lookup(_LENGTH, unit) \
        or _lookup(_AREA, unit) or _lookup(_ENERGY, unit) or _lookup(_MONEY, unit) \
        or _lookup(_PRESSURE, unit)
    if base is None:
        raise ToolError(LcaErrorCode.UNIT_PARSE_ERROR.code,
                        f"unit {unit!r} is not in the supported dimension tables",
                        details={"unit": unit, "supported": sorted(
                            set(_MASS) | set(_VOLUME) | set(_LENGTH) | set(_AREA)
                            | set(_ENERGY) | set(_MONEY) | set(_PRESSURE))})
    canonical = {"kg": 1.0, "m3": 1.0, "m": 1.0, "m2": 1.0, "MJ": 1.0, "CNY": 1.0, "MPa": 1.0}
    if unit in _MASS:
        return v * base, "kg"
    if unit in _VOLUME:
        return v * base, "m3"
    if unit in _LENGTH:
        return v * base, "m"
    if unit in _AREA:
        return v * base, "m2"
    if unit in _ENERGY:
        return v * base, "MJ"
    if unit in _MONEY:
        return v * base, "CNY"
    if unit in _PRESSURE:
        return v * base, "MPa"
    return v, unit  # pragma: no cover


def convert(value: float, from_unit: str, to_unit: str) -> float:
    """Linear conversion between two units of the same dimension.

    Raises LCA-E205 (unit parse / not convertible) or LCA-E206 (dimension
    mismatch) instead of guessing.
    """
    if from_unit == to_unit:
        return value
    dim_from = _dimension_for(from_unit)
    dim_to = _dimension_for(to_unit)
    if dim_from is None or dim_to is None:
        raise ToolError(LcaErrorCode.UNIT_PARSE_ERROR.code,
                        f"unit {from_unit if dim_from is None else to_unit!r} is not in the supported dimension tables",
                        details={"from": from_unit, "to": to_unit})
    if dim_from != dim_to:
        raise ToolError(LcaErrorCode.UNIT_INCONSISTENT.code,
                        f"dimension mismatch: {from_unit} ({dim_from}) vs {to_unit} ({dim_to})",
                        details={"from": from_unit, "to": to_unit, "from_dim": dim_from, "to_dim": dim_to})
    v, _ = normalize_quantity(value, from_unit)
    base = normalize_quantity(1.0, to_unit)[0]
    if base == 0:
        raise ToolError(LcaErrorCode.UNIT_PARSE_ERROR.code,
                        f"cannot convert to unit {to_unit!r}",
                        details={"from": from_unit, "to": to_unit})
    return v / base


def unit_dimension(unit: str) -> str:
    """Dimension label of a bare unit: mass|volume|length|area|energy|money|pressure|other."""
    d = _dimension_for(unit)
    return d or "other"


def money_rate(from_cur: str, to_cur: str) -> float | None:
    """Cross-currency factor; returns None when not pinned."""
    if from_cur not in _MONEY or to_cur not in _MONEY:
        return None
    return _MONEY[from_cur] / _MONEY[to_cur]


def convert_money(value: float, from_cur: str, to_cur: str) -> float:
    rate = money_rate(from_cur, to_cur)
    if rate is None:
        raise ToolError(LcaErrorCode.UNIT_PARSE_ERROR.code,
                        f"money conversion {from_cur}->{to_cur} not supported",
                        details={"from": from_cur, "to": to_cur, "rates_version": RATES_VERSION})
    return value * rate


# ---------------------------------------------------------------------------
# Functional-unit normalization
# ---------------------------------------------------------------------------

def reference_flow_ratio(functional_unit: dict, scope: dict) -> float:
    """Ratio that scales scenario flows to the functional unit.

    The functional unit declares a `reference_flow` (e.g. 1 m3 of sand
    treated) and the scenario scope declares its `analysis_size`
    (e.g. 100 m3 pilot). All inventory lines are multiplied by
    reference_flow / analysis_size so every scenario answers the same
    "per functional unit" question.

    Returns 1.0 when no scaling is declared (already per-FU).
    Raises LCA-E103 when functional_unit lacks a usable reference flow.
    """
    ref = functional_unit.get("reference_flow")
    size = scope.get("analysis_size")
    if ref is None:
        # Functional unit may be expressed as an intensity directly; caller
        # must still pass a non-empty functional unit — checked in scope gate.
        return 1.0
    rf_value = ref.get("value") if isinstance(ref, dict) else None
    if rf_value is None:
        raise ToolError(LcaErrorCode.MISSING_FUNCTIONAL_UNIT.code,
                        "functional_unit.reference_flow.value is required to scale inventory",
                        details={"functional_unit": functional_unit})
    if size is None:
        return 1.0
    size_value = size.get("value") if isinstance(size, dict) else size
    if isinstance(size_value, (int, float)) and isinstance(rf_value, (int, float)):
        if size_value == 0:
            raise ToolError(LcaErrorCode.CONTEXT_CORRUPT.code,
                            "analysis_size.value must be non-zero",
                            details={"analysis_size": size})
        return float(rf_value) / float(size_value)
    # Units may differ (e.g. FU 1 m3 vs pilot 100 L): normalize dimensions.
    rf_unit = ref.get("unit") if isinstance(ref, dict) else None
    size_unit = size.get("unit") if isinstance(size, dict) else None
    if rf_unit and size_unit:
        try:
            rf_norm, _ = normalize_quantity(float(rf_value), rf_unit)
            sz_norm, _ = normalize_quantity(float(size_value), size_unit)
            return rf_norm / sz_norm
        except ToolError as exc:
            raise ToolError(exc.code, f"cannot align functional unit and analysis size: {exc.message}",
                            details={"functional_unit": functional_unit, "analysis_size": size})
    raise ToolError(LcaErrorCode.MISSING_FUNCTIONAL_UNIT.code,
                    "functional unit scaling needs comparable reference_flow and analysis_size",
                    details={"functional_unit": functional_unit, "analysis_size": size})


def describe_functional_unit(functional_unit: dict) -> str:
    """Human-readable functional-unit statement used in every output."""
    fu = functional_unit.get("description") if isinstance(functional_unit, dict) else None
    if fu:
        return str(fu)
    return "undescribed functional unit"
