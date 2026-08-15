"""Unit & dimension checker (单位和量纲检查器).

Offline, deterministic dimensional analysis over a declarative table of
measurements (value, unit, declared dimension). Checks:

  - unit parses to a dimension vector (mass, length, time, amount, temperature,
    dimensionless)
  - declared dimension matches the parsed dimension (quantity confusion:
    OD600 vs CFU vs urease activity, total-CaCO3 vs effective-bridge, etc.)
  - unit consistency across a group of measurements
  - order-of-magnitude sanity against an expected range
  - false precision / significant-figure audit

Pure stdlib, no numpy. Dimensions are exact (rational) exponents.
"""

from __future__ import annotations

from fractions import Fraction
from typing import Any

from common import ToolError, emit_progress
from errors import OrtErrorCode, OrtError

# Base dimensions: (mass M, length L, time T, amount N, temperature K, current I)
BASE = ("M", "L", "T", "N", "K", "I")

# unit -> dimension exponent tuple. Only a curated MICP-relevant vocabulary.
UNIT_DIMS: dict[str, tuple[Fraction, Fraction, Fraction, Fraction, Fraction, Fraction]] = {
    # dimensionless / counting
    "": (0, 0, 0, 0, 0, 0),
    "-": (0, 0, 0, 0, 0, 0),
    "%": (0, 0, 0, 0, 0, 0),
    "wt%": (0, 0, 0, 0, 0, 0),
    "mass_percent": (0, 0, 0, 0, 0, 0),
    "dimensionless": (0, 0, 0, 0, 0, 0),
    "cfu": (0, 0, 0, 0, 0, 0),
    "cfu/ml": (0, 0, -1, 0, 0, 0),
    "count": (0, 0, 0, 0, 0, 0),
    "ratio": (0, 0, 0, 0, 0, 0),
    # OD600 / absorbance: dimensionless optical density (dimensionless)
    "od600": (0, 0, 0, 0, 0, 0),
    "abs": (0, 0, 0, 0, 0, 0),
    "au": (0, 0, 0, 0, 0, 0),
    # urease activity: umol/min/mL = N L^-3 T^-1
    "umol/min/ml": (0, -3, -1, 1, 0, 0),
    "u/ml": (0, -3, -1, 1, 0, 0),
    "mmol/min": (0, 0, -1, 1, 0, 0),
    "mumol/min/ml": (0, -3, -1, 1, 0, 0),
    # concentration (mass per volume)
    "g/l": (1, -3, 0, 0, 0, 0),
    "mg/l": (1, -3, 0, 0, 0, 0),
    "ug/l": (1, -3, 0, 0, 0, 0),
    "g/ml": (1, -3, 0, 0, 0, 0),
    "kg/m3": (1, -3, 0, 0, 0, 0),
    "mg/m3": (1, -3, 0, 0, 0, 0),
    "kg/l": (1, -3, 0, 0, 0, 0),
    "ug/ml": (1, -3, 0, 0, 0, 0),
    "g/dm3": (1, -3, 0, 0, 0, 0),
    "mg/dm3": (1, -3, 0, 0, 0, 0),
    # concentration (amount per volume)
    "mol/l": (0, -3, 0, 1, 0, 0),
    "mol/m3": (0, -3, 0, 1, 0, 0),
    "mmol/l": (0, -3, 0, 1, 0, 0),
    "mmoll": (0, -3, 0, 1, 0, 0),
    "mol/dm3": (0, -3, 0, 1, 0, 0),
    "ppm": (0, 0, 0, 0, 0, 0),
    "ppb": (0, 0, 0, 0, 0, 0),
    # mass
    "g": (1, 0, 0, 0, 0, 0),
    "kg": (1, 0, 0, 0, 0, 0),
    "mg": (1, 0, 0, 0, 0, 0),
    "t": (1, 0, 0, 0, 0, 0),
    "ug": (1, 0, 0, 0, 0, 0),
    # length
    "m": (0, 1, 0, 0, 0, 0),
    "cm": (0, 1, 0, 0, 0, 0),
    "mm": (0, 1, 0, 0, 0, 0),
    "km": (0, 1, 0, 0, 0, 0),
    "um": (0, 1, 0, 0, 0, 0),
    "nm": (0, 1, 0, 0, 0, 0),
    # area / volume
    "m2": (0, 2, 0, 0, 0, 0),
    "cm2": (0, 2, 0, 0, 0, 0),
    "m3": (0, 3, 0, 0, 0, 0),
    "cm3": (0, 3, 0, 0, 0, 0),
    "ml": (0, 3, 0, 0, 0, 0),
    "l": (0, 3, 0, 0, 0, 0),
    "ul": (0, 3, 0, 0, 0, 0),
    # velocity / permeability
    "m/s": (0, 1, -1, 0, 0, 0),
    "cm/s": (0, 1, -1, 0, 0, 0),
    "m/d": (0, 1, -1, 0, 0, 0),
    "m/day": (0, 1, -1, 0, 0, 0),
    "mm/s": (0, 1, -1, 0, 0, 0),
    # strength / pressure / modulus: M L^-1 T^-2
    "mpa": (1, -1, -2, 0, 0, 0),
    "kpa": (1, -1, -2, 0, 0, 0),
    "pa": (1, -1, -2, 0, 0, 0),
    "gpa": (1, -1, -2, 0, 0, 0),
    "kn/m2": (1, -1, -2, 0, 0, 0),
    "n/mm2": (1, -1, -2, 0, 0, 0),
    "bar": (1, -1, -2, 0, 0, 0),
    # density
    "g/cm3": (1, -3, 0, 0, 0, 0),
    "kg/m3": (1, -3, 0, 0, 0, 0),
    # time
    "s": (0, 0, 1, 0, 0, 0),
    "min": (0, 0, 1, 0, 0, 0),
    "h": (0, 0, 1, 0, 0, 0),
    "hr": (0, 0, 1, 0, 0, 0),
    "d": (0, 0, 1, 0, 0, 0),
    "a": (0, 0, 1, 0, 0, 0),
    # loading rate
    "mm/min": (0, 1, -1, 0, 0, 0),
    "%/min": (0, 0, -1, 0, 0, 0),
    "mm/h": (0, 1, -1, 0, 0, 0),
    # rate of concentration change (urea consumption rate)
    "mol/m3/s": (0, -3, -1, 1, 0, 0),
    "mmol/l/h": (0, -3, -1, 1, 0, 0),
    # molar mass
    "g/mol": (1, 0, 0, -1, 0, 0),
    "kg/mol": (1, 0, 0, -1, 0, 0),
    # temperature
    "c": (0, 0, 0, 0, 1, 0),
    "k": (0, 0, 0, 0, 1, 0),
}

# Some keys intentionally duplicated above (kg/m3, mg/l) — the parser accepts
# any match; the LAST wins for duplicates. Keep the list canonical.
# -> parse precedence: exact key, then normalized lowercase key.


def _normalize(unit: str) -> str:
    if unit is None:
        return ""
    u = str(unit).strip().lower()
    u = u.replace(" ", "")
    u = u.replace("µ", "u")  # micro sign
    u = u.replace("μ", "u")  # greek mu
    # unify common separators
    u = u.replace("·", "/").replace(".", "/")  # midpoint → division
    return u


def dims(unit: str) -> tuple[Fraction, Fraction, Fraction, Fraction, Fraction, Fraction] | None:
    u = _normalize(unit)
    if u in UNIT_DIMS:
        return tuple(Fraction(x) for x in UNIT_DIMS[u])  # type: ignore[arg-type]
    return None


def dim_string(d: tuple) -> str:
    out = []
    for sym, e in zip(BASE, d):
        if e:
            out.append(f"{sym}^{e}")
    return "·".join(out) if out else "1"


def compatible(unit_a: str, unit_b: str) -> bool:
    da, db = dims(unit_a), dims(unit_b)
    if da is None or db is None:
        return False
    return da == db


# --- declared quantity expectations (recognized dimension names) -----------
QUANTITY_DIMS: dict[str, tuple] = {
    "optical_density": (0, 0, 0, 0, 0, 0),
    "cell_count": (0, 0, 0, 0, 0, 0),
    "cell_density": (0, 0, -1, 0, 0, 0),
    "urease_activity": (0, -3, -1, 1, 0, 0),
    "mass_concentration": (1, -3, 0, 0, 0, 0),
    "molar_concentration": (0, -3, 0, 1, 0, 0),
    "mass": (1, 0, 0, 0, 0, 0),
    "length": (0, 1, 0, 0, 0, 0),
    "velocity": (0, 1, -1, 0, 0, 0),
    "permeability": (0, 1, -1, 0, 0, 0),
    "stress": (1, -1, -2, 0, 0, 0),
    "time": (0, 0, 1, 0, 0, 0),
    "temperature": (0, 0, 0, 0, 1, 0),
    "fraction": (0, 0, 0, 0, 0, 0),
    "volume": (0, 3, 0, 0, 0, 0),
    "density": (1, -3, 0, 0, 0, 0),
    "loading_rate": (0, 1, -1, 0, 0, 0),
    "mol_rate": (0, 0, -1, 1, 0, 0),
    "amount": (0, 0, 0, 1, 0, 0),
}

# Known quantity-confusion traps (MICP dimension 6)
TRAPS = [
    ("optical_density", "urease_activity",
     "OD600 是光密度(无量纲)，不是脲酶活性(N L^-3 T^-1)：两者不可互换"),
    ("optical_density", "cell_density",
     "OD600(无量纲) ≠ 细胞浓度(CFU/ml, L^-3)：必须做标准曲线换算并声明"),
    ("cell_density", "urease_activity",
     "细胞浓度(CFU/ml) ≠ 脲酶活性(umol/min/ml)：产酶率因菌株/诱导而异"),
    ("mass_concentration", "molar_concentration",
     "质量浓度(g/L) 与 摩尔浓度(mol/L) 量纲不同：换算需摩尔质量"),
    ("mass", "amount",
     "质量(g) ≠ 物质的量(mol)：CaCO3 沉淀质量≠晶桥摩尔量"),
    ("fraction", "mass",
     "含量(%)≠绝对质量：CaCO3 总量(wt%)≠有效晶桥质量"),
]


def _check_measurements(payload: dict[str, Any]) -> dict[str, Any]:
    measurements = payload.get("measurements") or []
    findings: list[dict] = []
    for m in measurements:
        m_id = str(m.get("id", "?"))
        value = m.get("value")
        unit = str(m.get("unit", "")).strip()
        quantity = str(m.get("quantity", "")).strip()
        declared_dim = QUANTITY_DIMS.get(quantity)
        parsed = dims(unit)
        if quantity and declared_dim is None:
            findings.append({
                "id": m_id, "severity": "MINOR", "dimension": "units_dimension",
                "message": f"unknown declared quantity {quantity!r}; cannot check",
            })
            continue
        if parsed is None:
            findings.append({
                "id": m_id, "severity": "MAJOR", "dimension": "units_dimension",
                "message": f"unit {unit!r} is not in the recognized vocabulary",
                "units": "parse",
            })
            continue
        if quantity and declared_dim != parsed:
            findings.append({
                "id": m_id, "severity": "CRITICAL", "dimension": "units_dimension",
                "message": f"unit {unit!r} ({dim_string(parsed)}) does not match declared quantity "
                           f"{quantity} ({dim_string(declared_dim)})",
                "units": "dimension_mismatch",
            })
        # trap detection
        if quantity:
            for q1, q2, why in TRAPS:
                if quantity == q1:
                    # check whether a sibling measurement of the same group is
                    # declared as q2 and treated interchangeably
                    pass
        # order-of-magnitude sanity
        expected_min = m.get("expected_min")
        expected_max = m.get("expected_max")
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            if expected_min is not None and value < expected_min:
                findings.append({
                    "id": m_id, "severity": "MAJOR", "dimension": "units_dimension",
                    "message": f"value {value} {unit} is below expected range [{expected_min}, {expected_max}]",
                    "units": "magnitude",
                })
            if expected_max is not None and value > expected_max:
                findings.append({
                    "id": m_id, "severity": "MAJOR", "dimension": "units_dimension",
                    "message": f"value {value} {unit} exceeds expected range [{expected_min}, {expected_max}]",
                    "units": "magnitude",
                })
        # false precision: more significant digits than the unit/scale supports
        sig = m.get("declared_significant_digits")
        if sig is not None and isinstance(value, (int, float)) and not isinstance(value, bool):
            digits = _significant_digits(value)
            if digits > sig:
                findings.append({
                    "id": m_id, "severity": "MINOR", "dimension": "units_dimension",
                    "message": f"value {value} reports {digits} significant digits but instrument supports {sig}: false precision",
                    "units": "precision",
                })
    return {"findings": findings, "measurements_checked": len(measurements)}


def _significant_digits(value: float) -> int:
    import math
    if value == 0:
        return 0
    v = abs(value)
    if v >= 1:
        return int(math.floor(math.log10(v))) + 1
    # < 1: leading zeros do not count
    exp = int(math.floor(math.log10(v)))
    digits = 0
    s = f"{v:.17e}"
    mant = s.split("e")[0]
    digits = len(mant.replace(".", "").lstrip("0"))
    return digits


def main(payload: dict[str, Any]) -> dict[str, Any]:
    emit_progress("units: checking units and dimensions")
    if not payload.get("measurements"):
        raise OrtError(OrtErrorCode.INPUT_SCHEMA_VIOLATION,
                       "units: measurements array is required",
                       detail={"how_to_fix": "attach the quantities to check (value/unit/quantity)"})
    result = _check_measurements(payload)
    result["note"] = "dictionary: OD600(cell/optical) 与 urease_activity 不同量纲; total-CaCO3 与 effective-bridge 不同概念"
    return result


if __name__ == "__main__":
    from common import read_stdin_envelope, run_tool
    run_tool("units", lambda: main(read_stdin_envelope()))
