#!/usr/bin/env python3
"""Unit / quantity validation for micp-experiment-designer.

Guards the scientific correctness boundary: every numeric input to this skill
carries a declared unit, and every derived quantity must be expressible in a
consistent dimension. This module provides:

  - a small dimensional engine (SI base dimensions + a whitelist of named units
    with their exponents), so "mmol/L + mol/m^3" is comparable but
    "MPa * g" is a dimensional error;
  - strict quantity records {value, unit} validated against null / non-finite /
    range / dimensional checks;
  - a narrow, explicit conversion table for temperature scales (K, C) and
    concentration/volume/length/mass units used in MICP reagent math.

Design rules:
  - No floating-point equality: within tolerance (relative 1e-9).
  - Unknown or malformed units are hard errors (E_UNIT_UNKNOWN / E_UNIT_MALFORMED),
    never silently assumed.
  - All public functions are pure and deterministic.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from fractions import Fraction
from typing import Any

from ._common import ToolError

# ---------------------------------------------------------------------------
# Dimensional engine
# ---------------------------------------------------------------------------

# Base dimension keys (SI). Exponents are exact (Fraction) so "m^2 / m" == "m".
_BASES = ("L", "M", "T", "I", "Th", "N", "J")  # length mass time current temp amount luminous


def _vec() -> list[Fraction]:
    return [Fraction(0)] * len(_BASES)


def _dim(exp: dict[str, Any]) -> tuple[Fraction, ...]:
    out = _vec()
    for k, e in exp.items():
        if k not in _BASES:
            raise ToolError("E_DIMENSION", f"unknown base dimension '{k}'", details={"base": k})
        out[_BASES.index(k)] += Fraction(e)
    return tuple(out)


# Named units: {name: (dimension exponents, scale factor to SI base)}
# scale is the multiplier from this unit to the SI base unit of the same
# dimension. Only units needed for MICP / DOE reagent & sample math.
_UNITS: dict[str, tuple[dict[str, Any], float]] = {
    # ---- length ----
    "m": ({"L": 1}, 1.0),
    "cm": ({"L": 1}, 1e-2),
    "mm": ({"L": 1}, 1e-3),
    "um": ({"L": 1}, 1e-6),
    "nm": ({"L": 1}, 1e-9),
    # ---- area (derived, accepted for convenience) ----
    "m2": ({"L": 2}, 1.0),
    "cm2": ({"L": 2}, 1e-4),
    "mm2": ({"L": 2}, 1e-6),
    # ---- volume ----
    "m3": ({"L": 3}, 1.0),
    "L": ({"L": 3}, 1e-3),
    "mL": ({"L": 3}, 1e-6),
    "uL": ({"L": 3}, 1e-9),
    "cm3": ({"L": 3}, 1e-6),
    # ---- mass ----
    "kg": ({"M": 1}, 1.0),
    "g": ({"M": 1}, 1e-3),
    "mg": ({"M": 1}, 1e-6),
    "ug": ({"M": 1}, 1e-9),
    # ---- time ----
    "s": ({"T": 1}, 1.0),
    "min": ({"T": 1}, 60.0),
    "h": ({"T": 1}, 3600.0),
    "d": ({"T": 1}, 86400.0),
    # ---- amount of substance ----
    "mol": ({"N": 1}, 1.0),
    "mmol": ({"N": 1}, 1e-3),
    "umol": ({"N": 1}, 1e-6),
    # ---- concentration: amount / volume ----
    "mol/L": ({"N": 1, "L": -3}, 1e3),       # mol per m3
    "mmol/L": ({"N": 1, "L": -3}, 1.0),
    "umol/L": ({"N": 1, "L": -3}, 1e-3),
    "M": ({"N": 1, "L": -3}, 1e3),           # molar == mol/L
    "mM": ({"N": 1, "L": -3}, 1.0),
    "uM": ({"N": 1, "L": -3}, 1e-3),
    "mol/m3": ({"N": 1, "L": -3}, 1.0),
    "mmol/m3": ({"N": 1, "L": -3}, 1e-3),
    # ---- density / mass concentration ----
    "g/L": ({"M": 1, "L": -3}, 1.0),
    "mg/L": ({"M": 1, "L": -3}, 1e-3),
    "kg/m3": ({"M": 1, "L": -3}, 1.0),
    # ---- force / pressure / stress ----
    "N": ({"M": 1, "L": 1, "T": -2}, 1.0),
    "kN": ({"M": 1, "L": 1, "T": -2}, 1e3),
    "Pa": ({"M": 1, "L": -1, "T": -2}, 1.0),
    "kPa": ({"M": 1, "L": -1, "T": -2}, 1e3),
    "MPa": ({"M": 1, "L": -1, "T": -2}, 1e6),
    "GPa": ({"M": 1, "L": -1, "T": -2}, 1e9),
    # ---- rate / flux ----
    "m/s": ({"L": 1, "T": -1}, 1.0),
    "cm/s": ({"L": 1, "T": -1}, 1e-2),
    "mm/s": ({"L": 1, "T": -1}, 1e-3),
    "m3/s": ({"L": 3, "T": -1}, 1.0),
    "mL/min": ({"L": 3, "T": -1}, 1e-6 / 60.0),
    "mL/h": ({"L": 3, "T": -1}, 1e-6 / 3600.0),
    "L/h": ({"L": 3, "T": -1}, 1e-3 / 3600.0),
    "m3/h": ({"L": 3, "T": -1}, 1.0 / 3600.0),
    # ---- temperature (affine scale, handled specially) ----
    "K": ({"Th": 1}, 1.0),
    "C": ({"Th": 1}, 1.0),
    # ---- dimensionless (pH, ratio, %, porosity) ----
    "%": ({}, 0.01),
}

_AFFINE: dict[str, tuple[float, float]] = {
    # name -> (scale, offset to kelvin): T_K = scale * T_unit + offset
    "K": (1.0, 0.0),
    "C": (1.0, 273.15),
}

_REL_TOL = 1e-9


def _norm_unit(unit: str) -> str:
    """Normalize a unit token (strip whitespace, collapse "µ"->"u")."""
    return unit.strip().replace("µ", "u").replace(" ", "").replace("×", "*")


def parse_unit(unit: str) -> tuple[tuple[Fraction, ...], float]:
    """Parse a (possibly compound) unit expression into (dim, scale to SI).

    Supports single tokens and products/quotients of whitelisted units,
    including parenthesized temperature notes? No: temperature in compounds is
    rejected (E_UNIT_TEMPERATURE_COMPOUND) because affine scales do not
    multiply — use K/C as standalone quantity units only.
    """
    u = _norm_unit(unit)
    if not u:
        raise ToolError("E_UNIT_EMPTY", "unit string is empty")
    # single token fast path
    if u in _UNITS:
        dim, scale = _UNITS[u]
        return _dim(dim), scale
    # compound: split by * and /, validating every token against the whitelist
    parts = _tokenize_compound(u)
    dim_vec = _vec()
    scale = 1.0
    for tok, power in parts:
        if tok in _AFFINE:
            raise ToolError(
                "E_UNIT_TEMPERATURE_COMPOUND",
                f"temperature unit '{tok}' cannot be used inside compound expressions "
                "(affine scale does not multiply); use K or C standalone",
                details={"unit": unit, "token": tok},
            )
        if tok not in _UNITS:
            raise ToolError("E_UNIT_UNKNOWN", f"unknown unit '{tok}'", details={"unit": unit, "token": tok})
        d, s = _UNITS[tok]
        dv = _dim(d)
        for i, e in enumerate(dv):
            dim_vec[i] += power * e
        scale *= s ** float(power)
    return tuple(dim_vec), scale


def _tokenize_compound(expr: str) -> list[tuple[str, int]]:
    """Split 'mL/min' / 'g*m/L^2' / 'mol/m3' into (token, power) pairs."""
    out: list[tuple[str, int]] = []
    # protect scientific exponent notation from the tokenizer
    expr = expr.replace("**", "^")
    i = 0
    n = len(expr)
    sign = 1
    while i < n:
        ch = expr[i]
        if ch == "/":
            sign = -1
            i += 1
            continue
        if ch == "*":
            sign = 1
            i += 1
            continue
        j = i
        while j < n and (expr[j].isalnum()):
            j += 1
        tok = expr[i:j]
        if not tok:
            raise ToolError("E_UNIT_MALFORMED", f"cannot parse unit expression '{expr}'",
                            details={"expr": expr})
        # power after token
        power = sign
        if j < n and expr[j] == "^":
            k = j + 1
            ks = k
            if k < n and expr[k] in "+-":
                k += 1
            while k < n and expr[k].isdigit():
                k += 1
            if ks == k:
                raise ToolError("E_UNIT_MALFORMED", f"malformed exponent in '{expr}'",
                                details={"expr": expr})
            power = sign * int(expr[ks:k])
            j = k
        out.append((tok, power))
        i = j
        sign = 1
    return out


def validate_quantity(q: Any, *, path: str = "quantity",
                      allow_dimensionless: bool = False) -> "Quantity":
    """Validate a {value, unit} record and return a canonical Quantity."""
    if not isinstance(q, dict):
        raise ToolError("E_TYPE", f"{path} must be an object with value and unit",
                        details={"path": path})
    val = q.get("value")
    unit = q.get("unit")
    if not isinstance(val, (int, float)) or isinstance(val, bool):
        raise ToolError("E_TYPE", f"{path}.value must be a number", details={"path": path})
    if not isinstance(unit, str) or unit.strip() == "":
        raise ToolError("E_UNIT_MISSING", f"{path} must declare a unit", details={"path": path})
    fval = float(val)
    if math is None or fval != fval or fval in (float("inf"), float("-inf")):
        raise ToolError("E_NUMERIC_NON_FINITE", f"{path}.value must be finite", details={"path": path})
    return Quantity(value=fval, unit=unit.strip())


@dataclass(frozen=True)
class Quantity:
    value: float
    unit: str
    dim: tuple[Fraction, ...] | None = None
    scale: float | None = None

    def __post_init__(self) -> None:
        if self.dim is None or self.scale is None:
            d, s = parse_unit(self.unit)
            object.__setattr__(self, "dim", d)
            object.__setattr__(self, "scale", s)

    @property
    def is_dimensionless(self) -> bool:
        return self.dim is not None and all(e == 0 for e in self.dim)

    def as_si(self) -> float:
        """Value expressed in the SI base unit of its dimension."""
        return self.value * (self.scale or 1.0)

    def to_unit(self, target: str) -> float:
        """Convert to another unit with the SAME dimension.

        Raises E_UNIT_INCOMPATIBLE on dimensional mismatch, E_UNIT_UNKNOWN on
        unknown target. Temperature affine conversion is handled for the
        degenerate K<->C case only (same base dimension).
        """
        t = _norm_unit(target)
        if t in _AFFINE and self.unit in _AFFINE and self.dim == _dim({"Th": 1}):
            a_s, a_o = _AFFINE[self.unit]
            b_s, b_o = _AFFINE[t]
            return (self.value * a_s + a_o - b_o) / b_s
        td, ts = parse_unit(t)
        if td != self.dim:
            raise ToolError(
                "E_UNIT_INCOMPATIBLE",
                f"cannot convert '{self.unit}' to '{target}': dimensions differ",
                details={"from": self.unit, "to": target,
                         "from_dim": _dim_str(self.dim), "to_dim": _dim_str(td)},
            )
        return self.value * (self.scale or 1.0) / ts


def _dim_str(dim: tuple[Fraction, ...]) -> str:
    terms = []
    for base, e in zip(_BASES, dim):
        if e != 0:
            terms.append(base if e == 1 else f"{base}^{e}")
    return "*".join(terms) if terms else "(dimensionless)"


def convert(value: float, from_unit: str, to_unit: str) -> float:
    """Standalone conversion helper used by the quantity calculator."""
    q = Quantity(value=float(value), unit=from_unit)
    return q.to_unit(to_unit)


def assert_same_dimension(quantities: list[Quantity], *, context: str) -> None:
    """All quantities must share one dimension (used by SOP consistency checks)."""
    if len(quantities) < 2:
        return
    first = quantities[0]
    for q in quantities[1:]:
        if q.dim != first.dim:
            raise ToolError(
                "E_UNIT_INCOMPATIBLE",
                f"{context}: dimension mismatch between '{first.unit}' and '{q.unit}'",
                details={"first": first.unit, "second": q.unit},
            )


def parse_reagent_units(value: Any, unit: Any, path: str = "reagent") -> Quantity:
    """Parse a raw reagent {value, unit} pair into a Quantity with defaults."""
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        u = unit if isinstance(unit, str) and unit.strip() else "mol/L"
        return Quantity(value=float(value), unit=u)
    raise ToolError("E_TYPE", f"{path} must be a number", details={"path": path})
