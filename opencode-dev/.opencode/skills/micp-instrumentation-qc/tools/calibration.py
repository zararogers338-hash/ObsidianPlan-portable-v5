"""micp-instrumentation-qc: calibration curve, LOD/LOQ, expanded uncertainty.

Pure Python standard library. Implements:
  - Ordinary least squares linear calibration  y = intercept + slope * x
  - Residual standard error, R^2, LOD (3.3 s_y/x / slope) and LOQ (10 s_y/x / slope)
  - Inverse prediction of concentration from a sample response with expanded
    uncertainty (GUM-style linear inversion; k=2, ~95% level)
  - Basic input validation (finite values, >=2 standards, positive slope)

The statistics are deliberately simple and fully deterministic. They follow the
commonly applied formulas in analytical chemistry (see references/sources.md).
This is NOT a substitute for a laboratory's validated LIMS; it is a QC aid.
"""

from __future__ import annotations

import math
from typing import Any

from _common import check_numeric

SUPPORTED_METHODS = ("linear",)


def linear_regression(xs: list[float], ys: list[float]) -> dict[str, float]:
    """OLS fit of y = b0 + b1*x. Raises ValueError on degenerate input."""
    n = len(xs)
    if n < 2:
        raise ValueError("MICQ-E1001: at least 2 calibration standards required")
    mean_x = sum(xs) / n
    mean_y = sum(ys) / n
    sxx = sum((x - mean_x) ** 2 for x in xs)
    if sxx <= 0:
        raise ValueError("MICQ-E1003: calibration standards are collinear (zero variance in x)")
    sxy = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys))
    slope = sxy / sxx
    intercept = mean_y - slope * mean_x
    resid = [y - (intercept + slope * x) for x, y in zip(xs, ys)]
    syx = math.sqrt(sum(r * r for r in resid) / (n - 2)) if n > 2 else 0.0
    ss_tot = sum((y - mean_y) ** 2 for y in ys)
    ss_res = sum(r * r for r in resid)
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else 0.0
    return {"slope": slope, "intercept": intercept, "syx": syx, "r2": r2, "n": float(n)}


def lod_loq(slope: float, syx: float) -> tuple[float, float]:
    """LOD = 3.3*syx/slope, LOQ = 10*syx/slope (in concentration units)."""
    if slope <= 0:
        raise ValueError("MICQ-E1003: slope must be positive to compute LOD/LOQ")
    return (3.3 * syx / slope, 10.0 * syx / slope)


def predict_uncertainty(
    fit: dict[str, float], xs: list[float], ys: list[float], y_sample: float, k: float = 2.0
) -> dict[str, float]:
    """Inverse prediction: concentration x for a sample response y, with expanded
    uncertainty at coverage factor k (GUM-style linear inversion).

    Returns {'x': x_pred, 'expanded_uncertainty': u_x} where u_x is the
    expanded (k-fold) uncertainty of the predicted concentration.
    """
    n = float(fit["n"])
    slope = fit["slope"]
    if slope == 0:
        raise ValueError("MICQ-E1003: slope is zero; cannot invert calibration")
    syx = fit["syx"]
    mean_x = sum(xs) / n
    sxx = sum((x - mean_x) ** 2 for x in xs)
    mean_y = sum(ys) / n
    x_pred = (y_sample - fit["intercept"]) / slope
    # std error of the inverse-predicted x (classic analytical-chemistry result).
    inside = 1.0 / n + (y_sample - mean_y) ** 2 / (slope * slope * sxx)
    u_x = k * (syx / abs(slope)) * math.sqrt(inside)
    return {"x": x_pred, "expanded_uncertainty": u_x}


def compute(data: dict[str, Any]) -> dict[str, Any]:
    """Compute a calibration report from a calibration object.

    Input keys: calibration_id, instrument_id, method, standards[{concentration, response, unit}].
    Returns machine-readable result with slope, intercept, r2, lod, loq, n,
    per-standard residuals, and expanded_uncertainty.
    """
    method = data.get("method", "linear")
    if method not in SUPPORTED_METHODS:
        raise ValueError(
            f"MICQ-E1003: unsupported calibration method '{method}'; supported: {list(SUPPORTED_METHODS)}"
        )
    standards = data.get("standards")
    if not standards or len(standards) < 2:
        raise ValueError("MICQ-E1001: calibration requires at least 2 standards")

    problems: list[dict[str, Any]] = []
    xs: list[float] = []
    ys: list[float] = []
    for i, st in enumerate(standards):
        problems.extend(check_numeric(st.get("concentration"), f"standards[{i}].concentration", nonnegative=True))
        problems.extend(check_numeric(st.get("response"), f"standards[{i}].response", finite=True))
    if problems:
        raise ValueError("MICQ-E1001: invalid calibration standard values: " + ", ".join(p["problem"] for p in problems))

    for st in standards:
        xs.append(float(st["concentration"]))
        ys.append(float(st["response"]))

    fit = linear_regression(xs, ys)
    lod, loq = lod_loq(fit["slope"], fit["syx"])

    # Optional expanded uncertainty of an inverse-predicted concentration.
    expanded: dict[str, Any] | None = None
    sample_resp = data.get("sample_response")
    if sample_resp is not None:
        check_numeric(sample_resp, "sample_response", finite=True)
        expanded = predict_uncertainty(fit, xs, ys, float(sample_resp))

    residuals = [{"concentration": x, "response": y, "residual": round(y - (fit["intercept"] + fit["slope"] * x), 9)}
                 for x, y in zip(xs, ys)]

    return {
        "calibration_id": data.get("calibration_id"),
        "instrument_id": data.get("instrument_id"),
        "method": method,
        "status": data.get("status", "passed"),
        "slope": round(fit["slope"], 9),
        "intercept": round(fit["intercept"], 9),
        "syx": round(fit["syx"], 9),
        "r2": round(fit["r2"], 9),
        "lod": round(lod, 9),
        "loq": round(loq, 9),
        "n": int(fit["n"]),
        "residuals": residuals,
        "expanded_uncertainty": (
            {"concentration": expanded["x"], "expanded_uncertainty": round(expanded["expanded_uncertainty"], 9)}
            if expanded is not None
            else None
        ),
    }
