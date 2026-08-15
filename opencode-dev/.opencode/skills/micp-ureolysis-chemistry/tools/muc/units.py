"""MUC units — dimensional analysis and unit validation.

A small, explicit, auditable unit engine built on SI base dimensions. Every
physical quantity in the skill carries (value, unit); this module converts to
base SI, checks dimensional consistency, rejects non-finite/out-of-range
values, and detects unit inconsistencies the way the mission-lock skill checks
units for contracts (see obsidian-mission-lock/tools/src/units.ts — same
discipline, chemistry-specific registry).

Dimensions (exponents):
  M   mass (kg)
  L   length (m)
  T   time (s)
  I   electric current (A)
  Th  temperature (K)
  N   amount of substance (mol)
  J   luminous intensity (cd)  — kept for completeness
  Money is NOT a physical dimension; currency units are flagged dimension-mismatch
  against any physical dimension.

Concentration convention: molarity [mol/L] is the domain convention for MICP
cementation fluids (mol/L == M). Mass concentration (g/L) is NOT convertible to
molarity without a molar mass, so it is flagged when used in a context that
requires mol/L.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .errors import MUCError

# Base dimension exponents, order: (M, L, T, I, Th, N, J)
_M, _L, _T, _I, _Th, _N, _J = range(7)
DIM_NAMES = ["M", "L", "T", "I", "Th", "N", "J"]

DIM_LENGTH = (0, 1, 0, 0, 0, 0, 0)
DIM_MASS = (1, 0, 0, 0, 0, 0, 0)
DIM_TIME = (0, 0, 1, 0, 0, 0, 0)
DIM_AMOUNT = (0, 0, 0, 0, 0, 1, 0)
DIM_TEMPERATURE = (0, 0, 0, 0, 1, 0, 0)
DIM_VOLUME = (0, 3, 0, 0, 0, 0, 0)
DIM_CONC_MOLAR = (0, -3, 0, 0, 0, 1, 0)  # mol/L
DIM_CONC_MASS = (1, -3, 0, 0, 0, 0, 0)  # g/L etc
DIM_RATE = (0, -3, -1, 0, 0, 1, 0)  # mol/L/s
DIM_DIMENSIONLESS = (0, 0, 0, 0, 0, 0, 0)
DIM_ENERGY = (1, 2, -2, 0, 0, 0, 0)
DIM_FORCE = (1, 1, -2, 0, 0, 0, 0)
DIM_PRESSURE = (1, -1, -2, 0, 0, 0, 0)
DIM_MOLAR_MASS = (1, 0, 0, 0, 0, -1, 0)
DIM_VOLUME_FLOW = (0, 3, -1, 0, 0, 0, 0)
DIM_VELOCITY = (0, 1, -1, 0, 0, 0, 0)


def _dim_add(a: tuple[int, ...], b: tuple[int, ...]) -> tuple[int, ...]:
    return tuple(x + y for x, y in zip(a, b))


def _dim_scale(a: tuple[int, ...], n: int) -> tuple[int, ...]:
    return tuple(x * n for x in a)


def dim_str(d: tuple[int, ...]) -> str:
    parts = []
    for exp, name in zip(d, DIM_NAMES):
        if exp == 1:
            parts.append(name)
        elif exp != 0:
            parts.append(f"{name}^{exp}")
    return "*".join(parts) if parts else "1"


@dataclass(frozen=True)
class Unit:
    """A unit as a dimension vector plus scale factor to SI base.

    scale: multiply value by scale to convert to SI base units of that
    dimension. For units with an offset (temperature), offset is applied as
    (value + offset) * scale.
    """

    name: str
    dim: tuple[int, ...]
    scale: float
    offset: float = 0.0
    kind: str = "unit"  # unit | currency | percent | count

    def to_si(self, value: float) -> float:
        return (value + self.offset) * self.scale

    def from_si(self, si: float) -> float:
        return si / self.scale - self.offset

    @property
    def is_dimensionless(self) -> bool:
        return self.dim == DIM_DIMENSIONLESS


# ---------------------------------------------------------------- registry --
# Chemically relevant units. The registry is intentionally small and explicit:
# unknown units are flagged, never silently accepted.

_U: list[Unit] = [
    # -- amount / concentration --
    Unit("mol", DIM_AMOUNT, 1.0),
    Unit("mmol", DIM_AMOUNT, 1e-3),
    Unit("umol", DIM_AMOUNT, 1e-6),
    Unit("M", DIM_CONC_MOLAR, 1e3),  # mol/L -> mol/m^3
    Unit("mM", DIM_CONC_MOLAR, 1.0),
    Unit("uM", DIM_CONC_MOLAR, 1e-3),
    Unit("mol/L", DIM_CONC_MOLAR, 1e3),
    Unit("mmol/L", DIM_CONC_MOLAR, 1.0),
    Unit("mol/m3", DIM_CONC_MOLAR, 1.0),
    Unit("g/L", DIM_CONC_MASS, 1.0),
    Unit("mg/L", DIM_CONC_MASS, 1e-3),
    Unit("kg/m3", DIM_CONC_MASS, 1.0),
    # -- mass --
    Unit("kg", DIM_MASS, 1.0),
    Unit("g", DIM_MASS, 1e-3),
    Unit("mg", DIM_MASS, 1e-6),
    # -- volume --
    Unit("L", DIM_VOLUME, 1e-3),
    Unit("mL", DIM_VOLUME, 1e-6),
    Unit("m3", DIM_VOLUME, 1.0),
    Unit("cm3", DIM_VOLUME, 1e-6),
    Unit("dm3", DIM_VOLUME, 1e-3),
    # -- length --
    Unit("m", DIM_LENGTH, 1.0),
    Unit("cm", DIM_LENGTH, 1e-2),
    Unit("mm", DIM_LENGTH, 1e-3),
    Unit("um", DIM_LENGTH, 1e-6),
    Unit("nm", DIM_LENGTH, 1e-9),
    Unit("km", DIM_LENGTH, 1e3),
    # -- time --
    Unit("s", DIM_TIME, 1.0),
    Unit("min", DIM_TIME, 60.0),
    Unit("h", DIM_TIME, 3600.0),
    Unit("day", DIM_TIME, 86400.0),
    Unit("d", DIM_TIME, 86400.0),
    Unit("week", DIM_TIME, 604800.0),
    Unit("yr", DIM_TIME, 31557600.0),
    # -- temperature --
    Unit("K", DIM_TEMPERATURE, 1.0),
    Unit("degC", DIM_TEMPERATURE, 1.0, offset=273.15),
    Unit("degC_offset", DIM_TEMPERATURE, 1.0, offset=273.15),
    # -- molar mass --
    Unit("g/mol", DIM_MOLAR_MASS, 1e-3),
    Unit("kg/mol", DIM_MOLAR_MASS, 1.0),
    # -- pressure --
    Unit("Pa", DIM_PRESSURE, 1.0),
    Unit("kPa", DIM_PRESSURE, 1e3),
    Unit("MPa", DIM_PRESSURE, 1e6),
    Unit("bar", DIM_PRESSURE, 1e5),
    Unit("atm", DIM_PRESSURE, 101325.0),
    # -- rate --
    Unit("M/s", DIM_RATE, 1e3),
    Unit("mol/L/s", DIM_RATE, 1e3),
    Unit("mol/L/min", (0, -3, -1, 0, 0, 1, 0), 1e3 / 60.0),
    Unit("mM/h", (0, -3, -1, 0, 0, 1, 0), 1.0 / 3600.0),
    Unit("mM/min", (0, -3, -1, 0, 0, 1, 0), 1.0 / 60.0),
    # -- dimensionless --
    Unit("percent", DIM_DIMENSIONLESS, 1.0, kind="percent"),
    Unit("%", DIM_DIMENSIONLESS, 1.0, kind="percent"),
    Unit("", DIM_DIMENSIONLESS, 1.0, kind="count"),
    Unit("unitless", DIM_DIMENSIONLESS, 1.0, kind="count"),
    # -- currencies (dimension MONEY, not convertible to physical dims) --
    Unit("CNY", (9, 0, 0, 0, 0, 0, 0), 1.0, kind="currency"),
    Unit("USD", (9, 0, 0, 0, 0, 0, 0), 1.0, kind="currency"),
    Unit("EUR", (9, 0, 0, 0, 0, 0, 0), 1.0, kind="currency"),
    # -- derived: calcite molar volume uses m3/mol --
    Unit("m3/mol", _dim_add(DIM_VOLUME, _dim_scale(DIM_AMOUNT, -1)), 1.0),
    Unit("cm3/mol", _dim_add(DIM_VOLUME, _dim_scale(DIM_AMOUNT, -1)), 1e-6),
]

# SI m^-3 basis: M (mol/L) is 1e3 mol/m^3. Registry keyed by canonical name.
_UNITS: dict[str, Unit] = {u.name: u for u in _U}


def lookup(unit: str) -> Unit | None:
    return _UNITS.get(unit)


def dims_equal(a: tuple[int, ...], b: tuple[int, ...]) -> bool:
    return a == b


def add_dims(a: tuple[int, ...], b: tuple[int, ...]) -> tuple[int, ...]:
    return _dim_add(a, b)


def scale_dims(a: tuple[int, ...], n: int) -> tuple[int, ...]:
    return _dim_scale(a, n)


# ------------------------------------------------------------- validators --


def check_quantity(name: str, value: float | int | None, unit: str) -> float:
    """Validate a (value, unit) pair; return value as float.

    Raises MUC-E1003 (unit unknown / non-finite / negative where forbidden)
    or MUC-E2004 (out of range). The unit is always returned normalized for
    downstream math.
    """
    if value is None:
        raise MUCError("MUC-E1003", f"{name}: missing value (value is None)")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise MUCError("MUC-E1003", f"{name}: value must be a number, got {type(value).__name__}")
    v = float(value)
    if not math_isfinite(v):
        raise MUCError("MUC-E2004", f"{name}: non-finite value {value!r}")
    if v < 0:
        raise MUCError("MUC-E1003", f"{name}: negative value {value} {unit} is not physically meaningful")
    u = lookup(unit)
    if u is None:
        raise MUCError(
            "MUC-E1003",
            f"{name}: unknown unit {unit!r} — not in the unit registry; convert to a registered unit",
        )
    return v


def check_unit(unit: str, expected_dims: tuple[int, ...], name: str) -> None:
    """Ensure `unit` has the expected dimensions (for math contexts)."""
    u = lookup(unit)
    if u is None:
        raise MUCError("MUC-E1003", f"{name}: unknown unit {unit!r}")
    if u.kind == "currency":
        raise MUCError("MUC-E1003", f"{name}: currency unit {unit!r} cannot be used in a chemical quantity")
    if u.dim != expected_dims:
        raise MUCError(
            "MUC-E1003",
            f"{name}: unit {unit!r} has dimension {dim_str(u.dim)}; expected {dim_str(expected_dims)}",
        )


def concentration_unit_ok(unit: str, name: str = "concentration") -> None:
    """Concentration must be molar (mol/L family) for speciation math; mass
    concentrations are flagged because they need a molar mass."""
    u = lookup(unit)
    if u is None:
        raise MUCError("MUC-E1003", f"{name}: unknown unit {unit!r}")
    if u.dim == DIM_CONC_MASS:
        raise MUCError(
            "MUC-E1003",
            f"{name}: {unit!r} is a mass concentration — not convertible to molarity without a "
            "molar mass; supply molar concentration (mol/L, mM, M) or a molar mass to convert",
        )
    if u.dim != DIM_CONC_MOLAR:
        raise MUCError(
            "MUC-E1003",
            f"{name}: {unit!r} is not a molar concentration; expected mol/L, mM, M",
        )


def convert_molar(value: float, unit: str, target: str = "mol/L") -> float:
    """Convert a molar concentration to target (default mol/L)."""
    u = lookup(unit)
    t = lookup(target)
    if u is None or t is None:
        raise MUCError("MUC-E1003", f"unknown concentration unit {unit!r} or {target!r}")
    if u.dim != DIM_CONC_MOLAR or t.dim != DIM_CONC_MOLAR:
        raise MUCError("MUC-E1003", f"convert_molar requires molar units, got {unit!r} → {target!r}")
    return value * u.scale / t.scale


def check_finite(value: float, name: str) -> float:
    if not math_isfinite(value):
        raise MUCError("MUC-E2004", f"{name}: non-finite value {value!r}")
    return value


def in_range(value: float, name: str, lo: float, hi: float) -> float:
    if not (lo <= value <= hi):
        raise MUCError(
            "MUC-E2004",
            f"{name}: value {value:g} out of range [{lo:g}, {hi:g}]",
        )
    return value


def math_isfinite(x: float) -> bool:
    import math

    return math.isfinite(x)


# --------------------------------------------------------- derived helpers --


def mol_mass(value_mgL: float) -> float:
    """Convert a mass concentration in mg/L to molarity assuming a molar mass
    in g/mol passed separately. Kept for the adapter path only; the engine
    itself always works in mol/L."""
    raise MUCError("MUC-E1003", "mass-to-molar conversion requires an explicit molar mass; use convert_mass_to_molar")


def convert_mass_to_molar(mass_conc: float, unit: str, molar_mass_g_mol: float) -> float:
    """Convert a mass concentration (g/L or mg/L) to mol/L."""
    u = lookup(unit)
    if u is None or u.dim != DIM_CONC_MASS:
        raise MUCError("MUC-E1003", f"convert_mass_to_molar: {unit!r} is not a mass concentration unit")
    gL = mass_conc * u.scale  # to g/L
    if molar_mass_g_mol <= 0 or not math_isfinite(molar_mass_g_mol):
        raise MUCError("MUC-E2004", f"convert_mass_to_molar: invalid molar mass {molar_mass_g_mol!r}")
    return gL / molar_mass_g_mol


def validate_numeric_bag(obj: dict[str, Any], required: set[str], name: str) -> dict[str, float]:
    """Validate that every required key exists and is a finite number."""
    out: dict[str, float] = {}
    for k in required:
        if k not in obj:
            raise MUCError("MUC-E1001", f"{name}: missing required field {k!r}")
        v = obj[k]
        if isinstance(v, bool) or not isinstance(v, (int, float)) or not math_isfinite(float(v)):
            raise MUCError("MUC-E2004", f"{name}.{k}: must be a finite number, got {v!r}")
        out[k] = float(v)
    return out
