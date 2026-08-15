"""micp-instrumentation-qc: shared utilities (error codes, numeric/unit validation, JSON I/O).

Pure Python standard library. This module is the single source of truth for error
codes and the machine-readable {code, message, retryable, details} error envelope.

All tools in this skill read a JSON document from stdin and write a JSON object to
stdout (the "envelope"). Exit codes:
  0 success, 3 input error, 4 internal/self-check error.
"""

from __future__ import annotations

import json
import math
import os
import re
import sys
from typing import Any

# ---------------------------------------------------------------------------
# Error codes (single source of truth). Controller parses `code`; humans read `message`.
# ---------------------------------------------------------------------------

ERROR_CODES: dict[str, dict[str, Any]] = {
    "MICQ-E1001": {
        "message": "输入未通过 input.schema.json 校验",
        "retryable": False,
    },
    "MICQ-E1002": {
        "message": "证据或数据引用缺失、不可读或损坏",
        "retryable": False,
    },
    "MICQ-E1003": {
        "message": "数值单位/量纲不一致或不可换算",
        "retryable": False,
    },
    "MICQ-E1004": {
        "message": "依赖工具不可用",
        "retryable": True,
    },
    "MICQ-E1005": {
        "message": "权限不足或操作被拒",
        "retryable": False,
    },
    "MICQ-E1006": {
        "message": "下游能力缺失(NEED_ADDITIONAL_SKILL)",
        "retryable": False,
    },
    "MICQ-E1007": {
        "message": "人工批准未完成",
        "retryable": False,
    },
    "MICQ-E1008": {
        "message": "结果未通过自身输出契约自检",
        "retryable": False,
    },
    "MICQ-E1009": {
        "message": "上下文/引用/模型文件损坏",
        "retryable": False,
    },
    "MICQ-E1010": {
        "message": "skill/controller 版本不受支持",
        "retryable": False,
    },
    "MICQ-E1011": {
        "message": "实现内部错误",
        "retryable": True,
    },
}

# Module-level source of truth for the error-code table (used by tests).
ERROR_CODE_IDS: tuple[str, ...] = tuple(ERROR_CODES.keys())


def error(code: str, details: Any = None) -> dict[str, Any]:
    """Build a machine-parseable error object."""
    if code not in ERROR_CODES:
        code = "MICQ-E1011"
    entry = ERROR_CODES[code]
    obj: dict[str, Any] = {
        "code": code,
        "message": entry["message"],
        "retryable": entry["retryable"],
    }
    if details is not None:
        obj["details"] = details
    return obj


# ---------------------------------------------------------------------------
# JSON envelope I/O
# ---------------------------------------------------------------------------


def read_input() -> dict[str, Any]:
    """Read a JSON document from stdin (the tool contract)."""
    raw = sys.stdin.buffer.read()
    if not raw:
        raise ValueError("MICQ-E1002: empty input")
    return json.loads(raw.decode("utf-8"))


def emit(obj: Any, exit_code: int = 0) -> None:
    """Write a JSON envelope to stdout and exit."""
    sys.stdout.write(json.dumps(obj, ensure_ascii=False, indent=2))
    sys.stdout.write("\n")
    sys.stdout.flush()
    sys.exit(exit_code)


# ---------------------------------------------------------------------------
# Numeric validation: units, emptiness, finiteness, range, dimension, precision
# ---------------------------------------------------------------------------

# Minimal unit-conversion table (MICP-relevant). Values = factor to the SI base
# (or to a canonical representative for dimensionless/percent cases).
_CONCENTRATION_TO_MOLAR = {
    "M": 1.0,
    "mol/L": 1.0,
    "mM": 1e-3,
    "mmol/L": 1e-3,
    "uM": 1e-6,
    "umol/L": 1e-6,
    "nM": 1e-9,
    "nmol/L": 1e-9,
}

# Mass-per-volume concentration (e.g. NH4+-N, Ca2+ in mg/L). Molar conversion
# requires the species' molar mass, which the tool must not guess; molar and
# mass-per-volume are therefore separate dimensions and mixing them in one
# dataset is flagged as MICQ-E1003.
_CONCENTRATION_MASS_TO_G_L = {
    "g/L": 1.0,
    "mg/L": 1e-3,
    "ug/L": 1e-6,
    "ng/L": 1e-9,
}

_MASS_TO_GRAM = {
    "g": 1.0,
    "kg": 1e3,
    "mg": 1e-3,
    "ug": 1e-6,
    "ug": 1e-6,
    "ng": 1e-9,
}

_VOLUME_TO_LITER = {
    "L": 1.0,
    "mL": 1e-3,
    "uL": 1e-6,
    "ul": 1e-6,
}

_PRESSURE_TO_PA = {
    "Pa": 1.0,
    "kPa": 1e3,
    "MPa": 1e6,
    "bar": 1e5,
    "psi": 6894.76,
    "atm": 101325.0,
}

_FLOW_TO_SI = {
    "L/min": 1e-3 / 60.0,
    "mL/min": 1e-6 / 60.0,
    "uL/min": 1e-9 / 60.0,
    "L/h": 1e-3 / 3600.0,
}

_EC_TO_US_CM = {
    "uS/cm": 1.0,
    "us/cm": 1.0,
    "mS/cm": 1e3,
    "S/m": 1e4,
    "dS/m": 1e3,
}

_OD = {"OD": 1.0, "AU": 1.0, "A": 1.0}
_PH = {"pH": 1.0}
_UCS = {"MPa": 1e6, "kPa": 1e3, "Pa": 1.0, "psi": 6894.76}
_ENERGY_ACT = {"U/mL": 1.0, "U/L": 1.0, "IU/mL": 1.0, "IU/L": 1.0}

# Map a canonical unit name to its conversion table.
UNITS: dict[str, dict[str, float]] = {
    "concentration": _CONCENTRATION_TO_MOLAR,
    "concentration_mass": _CONCENTRATION_MASS_TO_G_L,
    "mass": _MASS_TO_GRAM,
    "volume": _VOLUME_TO_LITER,
    "pressure": _PRESSURE_TO_PA,
    "flow": _FLOW_TO_SI,
    "ec": _EC_TO_US_CM,
    "od": _OD,
    "ph": _PH,
    "ucs": _UCS,
    "enzyme": _ENERGY_ACT,
}

# Units that carry no dimension (dimensionless / log scales / ratios).
DIMENSIONLESS = {"%", "ratio", "N/A", "none", "dimensionless", "ppm", "ppb", "unitless", ""}


def normalize_unit(unit: str, dim: str) -> str:
    """Return the canonical unit name for a unit string in a given dimension.

    Raises ValueError (MICQ-E1003) if the unit is unknown for that dimension.
    """
    if dim not in UNITS:
        raise ValueError(f"MICQ-E1003: unknown dimension '{dim}'")
    table = UNITS[dim]
    key = unit.strip()
    if key in table:
        return key
    # case-fold some common variants
    lower = key.lower()
    for k, v in table.items():
        if k.lower() == lower:
            return k
    raise ValueError(f"MICQ-E1003: unit '{unit}' not recognized for dimension '{dim}'")


def to_si(value: float, unit: str, dim: str) -> float:
    """Convert a value to the canonical SI unit for a dimension."""
    if dim not in UNITS:
        raise ValueError(f"MICQ-E1003: unknown dimension '{dim}'")
    table = UNITS[dim]
    key = normalize_unit(unit, dim)
    return value * table[key]


def is_dimensionless(unit: str) -> bool:
    return unit.strip().lower() in DIMENSIONLESS


def check_numeric(value: Any, name: str, *, finite: bool = True,
                  nonnegative: bool = False, lower: float | None = None,
                  upper: float | None = None) -> list[dict[str, Any]]:
    """Validate a single numeric value. Returns a list of human-readable problems."""
    problems: list[dict[str, Any]] = []
    if value is None:
        problems.append({"field": name, "problem": "null/empty value"})
        return problems
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        problems.append({"field": name, "problem": f"non-numeric type {type(value).__name__}"})
        return problems
    if finite and not math.isfinite(float(value)):
        problems.append({"field": name, "problem": "non-finite value (NaN/Inf)"})
        return problems
    if nonnegative and float(value) < 0:
        problems.append({"field": name, "problem": "negative value where non-negative required"})
        return problems
    if lower is not None and float(value) < lower:
        problems.append({"field": name, "problem": f"value below allowed lower bound {lower}"})
    if upper is not None and float(value) > upper:
        problems.append({"field": name, "problem": f"value above allowed upper bound {upper}"})
    return problems


def unit_invariant(v1: float, u1: str, v2: float, u2: str, dim: str) -> bool:
    """True if the two (value, unit) pairs represent the same physical quantity."""
    return math.isclose(to_si(v1, u1, dim), to_si(v2, u2, dim), rel_tol=1e-6, abs_tol=1e-12)


# ---------------------------------------------------------------------------
# General helpers
# ---------------------------------------------------------------------------

SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+$")


def is_semver(s: str) -> bool:
    return bool(SEMVER_RE.match(s))


def parse_semver(s: str) -> tuple[int, int, int]:
    return tuple(int(x) for x in s.split("."))  # type: ignore[return-value]


def path_exists(p: str) -> bool:
    return bool(p) and os.path.isfile(p)


def read_text_or_path(value: Any) -> str:
    """If value is a string that names an existing file, return its content;
    otherwise return the value as-is (inline content or JSON object)."""
    if isinstance(value, str) and path_exists(value):
        with open(value, "r", encoding="utf-8") as f:
            return f.read()
    if isinstance(value, dict) or isinstance(value, list):
        return json.dumps(value, ensure_ascii=False)
    return str(value)
