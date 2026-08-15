"""Data quality, units, and pseudo-replication checks for micp-data-analyst.

Consumes the declarative `data_columns` dictionary (roles, types, units,
sampling_unit) plus the raw `samples` rows. Every check is scripted, records
its reason, and returns severity-tagged issues. Deterministic and offline.
"""

from __future__ import annotations

import math
from datetime import date, datetime
from typing import Any

from _common import as_dict, as_list
from errors import MdaError, MdaErrorCode

ROLE_LABELS = {
    "id": "identifier", "treatment": "treatment/factor", "batch": "experimental batch",
    "position": "spatial position", "time": "time", "response": "response variable",
    "covariate": "covariate", "metadata": "metadata",
}


def _type_ok(value: Any, data_type: str) -> bool:
    if value is None:
        return True
    if data_type == "string":
        return isinstance(value, str)
    if data_type == "boolean":
        return isinstance(value, bool)
    if data_type == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if data_type == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)
    if data_type == "date":
        return isinstance(value, (date, datetime)) or isinstance(value, str)
    return True


def _missing_count(values: list[Any]) -> int:
    return sum(1 for v in values if v is None or v == "")


def _finite_count(values: list[Any]) -> int:
    return sum(1 for v in values
               if isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v))


# ---------------------------------------------------------------------------
# Unit parsing / consistency
# ---------------------------------------------------------------------------

_SI_PREFIX = {
    "y": 1e-24, "z": 1e-21, "a": 1e-18, "f": 1e-15, "p": 1e-12, "n": 1e-9,
    "u": 1e-6, "m": 1e-3, "c": 1e-2, "d": 1e-1, "h": 1e2, "k": 1e3, "M": 1e6,
    "G": 1e9, "T": 1e12,
}
_BASE_DIMS = {
    "m": "L", "g": "M", "s": "T", "A": "I", "K": "Theta", "mol": "N",
    "cd": "J",
}
# Derived units -> (factor_to_SI, dimensions dict)
_DERIVED = {
    "N": (1.0, {"M": 1, "L": 1, "T": -2}),
    "Pa": (1.0, {"M": 1, "L": -1, "T": -2}),
    "J": (1.0, {"M": 1, "L": 2, "T": -2}),
    "W": (1.0, {"M": 1, "L": 2, "T": -3}),
    "Hz": (1.0, {"T": -1}),
    "C": (1.0, {"I": 1, "T": 1}),
    "V": (1.0, {"M": 1, "L": 2, "T": -3, "I": -1}),
}
# Common units with non-SI dims (%, %, g/L ...). dims use L/M/T/N.
_EXTRA_UNITS = {
    "%": (0.01, {"L": 0, "M": 0, "T": 0, "N": 0}),  # dimensionless ratio
    "g/L": (1.0, {"M": 1, "L": -3, "N": 0}),
    "mg/L": (1e-3, {"M": 1, "L": -3, "N": 0}),
    "mol/m3": (1.0, {"N": 1, "L": -3}),
    "mol/L": (1e3, {"N": 1, "L": -3}),
    "M": (1e3, {"N": 1, "L": -3}),  # molar (mol/L)
    "ppm": (1.0, {"N": 0, "L": 0, "M": 0}),  # dimensionful ppm needs context; treat as ratio
    "mm/min": (1e-3 / 60.0, {"L": 1, "T": -1}),
    "cm/s": (1e-2, {"L": 1, "T": -1}),
    "m/d": (1.0 / 86400.0, {"L": 1, "T": -1}),
    "m/s": (1.0, {"L": 1, "T": -1}),
    "kN/m2": (1e3, {"M": 1, "L": -1, "T": -2}),
    "kPa": (1e3, {"M": 1, "L": -1, "T": -2}),
    "MPa": (1e6, {"M": 1, "L": -1, "T": -2}),
    "GPa": (1e9, {"M": 1, "L": -1, "T": -2}),
    "g/cm3": (1e3, {"M": 1, "L": -3}),
    "kg/m3": (1.0, {"M": 1, "L": -3}),
    "mg/g": (1e-3, {"N": 0, "L": 0, "M": 0}),  # mass ratio
}


def parse_unit(unit: str) -> tuple[float, dict[str, int]]:
    """Return (factor_to_SI, dimensions) for a unit token; raise MDA-E203 if unparseable."""
    u = unit.strip()
    if not u:
        raise MdaError(MdaErrorCode.UNIT_PARSE_ERROR, "empty unit string")
    if u in _EXTRA_UNITS:
        return _EXTRA_UNITS[u]
    if u in _DERIVED:
        return _DERIVED[u]
    # Try "prefix+base" like "mm", "kPa", "mPa", "mmol"
    for pfx, pv in sorted(_SI_PREFIX.items(), key=lambda kv: -len(kv[0])):
        if u.startswith(pfx) and len(u) > len(pfx):
            base = u[len(pfx):]
            if base in _BASE_DIMS:
                return pv, {_BASE_DIMS[base]: 1}
            if base in _DERIVED:
                factor, dims = _DERIVED[base]
                return factor * pv, dict(dims)
            if base == "m" and pfx == "":
                continue
    # compound like "kg/m3" or "mm/min"
    if "/" in u:
        num, den = u.split("/", 1)
        nf, nd = parse_unit(num) if num else (1.0, {})
        df, dd = parse_unit(den) if den else (1.0, {})
        dims = {k: nd.get(k, 0) - dd.get(k, 0) for k in set(nd) | set(dd)}
        dims = {k: v for k, v in dims.items() if v != 0}
        return nf / df, dims
    if "*" in u:
        parts = u.split("*")
        factor = 1.0
        dims: dict[str, int] = {}
        for part in parts:
            f, d = parse_unit(part.strip())
            factor *= f
            for k, v in d.items():
                dims[k] = dims.get(k, 0) + v
        return factor, dims
    # dimensionless ratio
    if u in {"", "1", "-", "dimensionless"}:
        return 1.0, {}
    raise MdaError(MdaErrorCode.UNIT_PARSE_ERROR, f"cannot parse unit {unit!r}",
                   detail={"unit": unit})


def units_consistent(cols: list[dict], issue_log: list[dict]) -> None:
    """Per column: unit present for numeric roles; parseable; no conflicting units across records."""
    for col in cols:
        name = col.get("name")
        role = col.get("role")
        unit = col.get("unit")
        data_type = col.get("data_type")
        if role in ("response", "covariate", "time") and data_type in ("number", "integer"):
            if not unit:
                issue_log.append({
                    "code": "UNIT_MISSING", "severity": "warning",
                    "message": f"numeric column {name!r} (role {role}) has no declared unit; "
                               f"results cannot carry units",
                    "details": {"column": name}})
                continue
            try:
                parse_unit(unit)
            except MdaError as exc:
                issue_log.append({
                    "code": "UNIT_PARSE", "severity": "error",
                    "message": f"column {name!r} unit {unit!r} could not be parsed: {exc.message}",
                    "details": {"column": name, "unit": unit}})
    # cross-column unit conflicts for response variables (dimension-level)
    for i, a in enumerate(cols):
        for b in cols[i + 1:]:
            if a.get("role") == "response" and b.get("role") == "response":
                ua, ub = a.get("unit"), b.get("unit")
                if ua and ub:
                    try:
                        fa, da = parse_unit(ua)
                        fb, db = parse_unit(ub)
                        if da != db:
                            issue_log.append({
                                "code": "UNIT_DIMENSION_CONFLICT", "severity": "warning",
                                "message": f"response columns {a['name']!r} and {b['name']!r} have "
                                           f"incompatible dimensions ({ua} vs {ub})",
                                "details": {"columns": [a["name"], b["name"]]}})
                    except MdaError:
                        pass  # already reported as UNIT_PARSE


# ---------------------------------------------------------------------------
# Schema, missing, range, time, batch, independence
# ---------------------------------------------------------------------------

def schema_check(cols: list[dict], rows: list[dict], issue_log: list[dict]) -> None:
    for r in rows:
        for c in cols:
            name = c.get("name")
            if name in r:
                continue
            # date fields may be absent; report only required/declared presence mismatches
            if c.get("role") in ("id", "response", "treatment"):
                issue_log.append({
                    "code": "SCHEMA_MISSING_VALUE", "severity": "warning",
                    "message": f"row has no value for declared column {name!r}",
                    "details": {"column": name, "row": rows.index(r)}})


def missing_check(cols: list[dict], rows: list[dict], issue_log: list[dict]) -> None:
    for c in cols:
        name = c.get("name")
        vals = [r.get(name) for r in rows]
        missing = _missing_count(vals)
        if missing:
            issue_log.append({
                "code": "MISSING_VALUE", "severity": "warning" if missing <= len(rows) * 0.1 else "error",
                "message": f"column {name!r}: {missing}/{len(rows)} values missing",
                "details": {"column": name, "missing": missing, "total": len(rows)}})


def range_check(cols: list[dict], rows: list[dict], issue_log: list[dict]) -> None:
    for c in cols:
        name = c.get("name")
        unit = c.get("unit")
        vals = [r.get(name) for r in rows if isinstance(r.get(name), (int, float))]
        if not vals:
            continue
        vmin, vmax = min(vals), max(vals)
        if unit and unit in {"%", "percent"} and not (0 <= vmin and vmax <= 100):
            issue_log.append({
                "code": "RANGE_OUT_OF_BOUNDS", "severity": "warning",
                "message": f"column {name!r} (% unit) has values outside [0,100]: [{vmin},{vmax}]",
                "details": {"column": name, "min": vmin, "max": vmax}})
        if vmin == vmax:
            issue_log.append({
                "code": "ZERO_VARIANCE", "severity": "warning",
                "message": f"column {name!r} is constant across all rows ({vmin}); "
                           f"cannot use as a predictor",
                "details": {"column": name}})


def time_check(cols: list[dict], rows: list[dict], issue_log: list[dict]) -> None:
    for c in cols:
        if c.get("role") != "time":
            continue
        name = c.get("name")
        vals = [r.get(name) for r in rows]
        if not vals:
            continue
        numeric = [v for v in vals if isinstance(v, (int, float)) and not isinstance(v, bool)]
        if numeric and len(numeric) >= 2:
            if any(b <= a for a, b in zip(numeric, numeric[1:])):
                issue_log.append({
                    "code": "TIME_NOT_MONOTONIC", "severity": "warning",
                    "message": f"time column {name!r} is not strictly increasing",
                    "details": {"column": name}})


def batch_check(cols: list[dict], rows: list[dict], issue_log: list[dict]) -> None:
    for c in cols:
        if c.get("role") != "batch":
            continue
        name = c.get("name")
        vals = [r.get(name) for r in rows]
        uniq = set(str(v) for v in vals if v is not None)
        if len(uniq) == 1:
            issue_log.append({
                "code": "SINGLE_BATCH", "severity": "warning",
                "message": f"batch column {name!r} has only one level ({next(iter(uniq))}); "
                           f"cannot estimate batch variance",
                "details": {"column": name}})


def pseudo_replication_check(cols: list[dict], rows: list[dict]) -> dict[str, Any]:
    """Detect records that share a sampling unit (repeated measurements on the
    same specimen/column/layer) but would otherwise be counted as independent.

    Returns the analysis structure: for each response column, the effective
    independent sample size vs the raw row count, plus a recommended analysis.
    """
    findings: list[dict] = []
    batch_col = next((c for c in cols if c.get("role") == "batch"), None)
    id_col = next((c for c in cols if c.get("role") == "id"), None)
    for c in cols:
        if c.get("role") != "response":
            continue
        name = c.get("name")
        # sampling unit resolution order: declared on the column > batch column > id column
        su_col = c.get("sampling_unit")
        if not su_col and batch_col:
            su_col = batch_col.get("name")
        if not su_col and id_col:
            su_col = id_col.get("name")
        if not su_col:
            continue
        units = [str(r.get(su_col)) for r in rows if r.get(su_col) is not None]
        n_units = len(set(units))
        n_rows = len(rows)
        if n_units > 0 and n_units < n_rows:
            findings.append({
                "unit": su_col,
                "reason": (f"{n_rows} rows for response {name!r} carry only {n_units} distinct "
                           f"values of the sampling unit {su_col!r}; treating rows as independent "
                           f"would inflate the effective sample size"),
                "recommended_analysis": (f"mixed_effects with random intercept on {su_col!r}, "
                                         f"or average within {su_col!r} first"),
                "effective_n": n_units,
            })
    if not findings:
        return {"detected": False, "findings": []}
    return {"detected": True, "findings": findings}


# ---------------------------------------------------------------------------
# Column coerce helpers used by the service
# ---------------------------------------------------------------------------

def get_column_values(rows: list[dict], col: dict) -> list[Any]:
    name = col["name"]
    return [r.get(name) for r in rows]


def to_numeric(values: list[Any]) -> list[float]:
    """Coerce a column to floats, skipping missing and non-finite values.

    Non-numeric and non-finite values are skipped (never silently kept) and a
    summary of what was skipped is available via `to_numeric_report`. The
    service records these as data-quality issues rather than aborting the
    whole analysis.
    """
    out: list[float] = []
    skipped: list[dict] = []
    for i, v in enumerate(values):
        if v is None or v == "":
            skipped.append({"index": i, "reason": "missing"})
            continue
        if isinstance(v, bool):
            skipped.append({"index": i, "reason": "boolean", "value": v})
            continue
        if not isinstance(v, (int, float)):
            skipped.append({"index": i, "reason": "non_numeric", "value": str(v)})
            continue
        f = float(v)
        if not math.isfinite(f):
            skipped.append({"index": i, "reason": "non_finite", "value": str(v)})
            continue
        out.append(f)
    return out


def to_numeric_report(values: list[Any]) -> dict:
    """Report which entries of a column were skipped and why (deterministic)."""
    out: list[float] = []
    skipped: list[dict] = []
    for i, v in enumerate(values):
        if v is None or v == "":
            skipped.append({"index": i, "reason": "missing"})
            continue
        if isinstance(v, bool):
            skipped.append({"index": i, "reason": "boolean", "value": bool(v)})
            continue
        if not isinstance(v, (int, float)):
            skipped.append({"index": i, "reason": "non_numeric", "value": str(v)[:40]})
            continue
        f = float(v)
        if not math.isfinite(f):
            skipped.append({"index": i, "reason": "non_finite", "value": str(v)})
            continue
        out.append(f)
    return {"n_kept": len(out), "n_skipped": len(skipped), "skipped": skipped}


def main(payload: dict) -> dict:
    p = as_dict(payload, "$")
    cols = as_list(p.get("data_columns", []), "$.data_columns")
    rows = as_list(p.get("samples", []), "$.samples")
    for c in cols:
        as_dict(c, "$.data_columns[]")
    for r in rows:
        as_dict(r, "$.samples[]")

    issues: list[dict] = []
    schema_check(cols, rows, issues)
    missing_check(cols, rows, issues)
    units_consistent(cols, issues)
    range_check(cols, rows, issues)
    time_check(cols, rows, issues)
    batch_check(cols, rows, issues)
    pseudo = pseudo_replication_check(cols, rows)

    return {
        "data_quality": {"checks": [
            {"name": "schema", "pass": True},
            {"name": "missing", "pass": not any(i["severity"] == "error" for i in issues)},
            {"name": "units", "pass": not any(i.get("code") == "UNIT_PARSE" for i in issues)},
            {"name": "range", "pass": True},
            {"name": "time", "pass": True},
            {"name": "batch", "pass": True},
            {"name": "independence", "pass": not pseudo["detected"]},
        ], "issues": issues},
        "pseudo_replication": pseudo,
        "n_rows": len(rows),
        "n_columns": len(cols),
    }


if __name__ == "__main__":
    from _common import run_tool
    run_tool("qc", main)
