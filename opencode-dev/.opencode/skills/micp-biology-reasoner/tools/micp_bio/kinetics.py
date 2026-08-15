"""Growth-curve and attachment/inactivation kinetics fitting.

Two model families (spec §五.1, §五.4):
  1. first-order decay   y(t) = A0 * exp(-k t)      (retention / inactivation)
  2. logistic growth     N(t) = K / (1 + (K/N0 - 1) exp(-r t))   (biomass)

All fits use scipy.optimize.least_squares with bounded parameters and are
checked for finite results, bounded residuals and physically meaningful
parameters. A fit that does not converge raises MbrError (MBR-E302 or a
dedicated NUMERICAL failure through TOOL_UNAVAILABLE-compatible path).
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np

from ._common import ensure_finite
from .errors import MbrError, MbrErrorCode

try:  # pragma: no cover - exercised in integration tests
    from scipy.optimize import least_squares
except Exception as exc:  # pragma: no cover
    least_squares = None
    _SCIPY_IMPORT_ERROR = exc
else:
    _SCIPY_IMPORT_ERROR = None


def _require_scipy() -> None:
    if least_squares is None:
        raise MbrError(
            MbrErrorCode.TOOL_UNAVAILABLE,
            "scipy.optimize.least_squares is required for kinetics fitting but "
            "could not be imported.",
            detail={"import_error": str(_SCIPY_IMPORT_ERROR)},
        )


def _paired(xs: list[Any], ys: list[Any], x_name: str, y_name: str) -> tuple[np.ndarray, np.ndarray]:
    """Validate paired time-series; must be equal length, non-empty, finite."""
    if not isinstance(xs, list) or not isinstance(ys, list):
        raise MbrError(
            MbrErrorCode.INPUT_SCHEMA_VIOLATION,
            f"{x_name}/{y_name} must be arrays.",
            detail={"field": f"{x_name}/{y_name}"},
        )
    if len(xs) != len(ys):
        raise MbrError(
            MbrErrorCode.INPUT_SCHEMA_VIOLATION,
            f"{x_name} and {y_name} must be paired (equal length).",
            detail={"len_x": len(xs), "len_y": len(ys)},
        )
    if len(xs) < 2:
        raise MbrError(
            MbrErrorCode.INPUT_SCHEMA_VIOLATION,
            "At least two paired points are required to fit kinetics.",
            detail={"len_x": len(xs)},
        )
    x = np.asarray([ensure_finite(float(v), f"{x_name}[{i}]") for i, v in enumerate(xs)], dtype=float)
    y = np.asarray([ensure_finite(float(v), f"{y_name}[{i}]") for i, v in enumerate(ys)], dtype=float)
    if np.any(x < 0):
        raise MbrError(MbrErrorCode.NUMERIC_INVALID, f"{x_name} cannot be negative.", detail={"field": x_name})
    if np.any(y < 0):
        raise MbrError(MbrErrorCode.NUMERIC_INVALID, f"{y_name} cannot be negative.", detail={"field": y_name})
    return x, y


def fit_first_order_decay(time_points: list[Any], values: list[Any], *, y_name: str = "value") -> dict[str, Any]:
    """Fit y(t) = A0 * exp(-k t). Returns A0, k (1/h), halflife, quality."""
    _require_scipy()
    t, y = _paired(time_points, values, "time_points_h", y_name)
    if float(y[0]) <= 0.0:
        raise MbrError(
            MbrErrorCode.NUMERIC_INVALID,
            f"First-order decay requires a positive initial {y_name} (y[0]>0).",
            detail={"y0": float(y[0])},
        )
    # robust starts
    A0_guess = float(y[0])
    if t[-1] > 0.0:
        k_guess = max(1e-6, -math.log(max(float(y[-1]) / A0_guess, 1e-9)) / float(t[-1]))
    else:
        k_guess = 1e-3

    def resid(p: np.ndarray) -> np.ndarray:
        A0, k = p
        return A0 * np.exp(-k * t) - y

    try:
        res = least_squares(
            resid,
            x0=[A0_guess, k_guess],
            bounds=([1e-9, 0.0], [np.inf, np.inf]),
            max_nfev=5000,
        )
    except Exception as exc:  # pragma: no cover - solver-specific failures
        raise MbrError(
            MbrErrorCode.TOOL_UNAVAILABLE,
            f"least_squares failed for first-order decay fit: {exc}",
            retryable=True,
        ) from exc

    if not res.success:
        raise MbrError(
            MbrErrorCode.SELF_CHECK_FAILED,
            f"First-order decay fit did not converge: {res.message}",
            detail={"cost": float(res.cost)},
            retryable=True,
        )
    A0, k = float(res.x[0]), float(res.x[1])
    if not (math.isfinite(A0) and math.isfinite(k) and A0 > 0 and k >= 0):
        raise MbrError(MbrErrorCode.SELF_CHECK_FAILED, "Fit produced non-physical parameters.")
    pred = A0 * np.exp(-k * t)
    ss_res = float(np.sum((pred - y) ** 2))
    ss_tot = float(np.sum((y - np.mean(y)) ** 2))
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 0.0 else 1.0
    halflife = math.log(2.0) / k if k > 0 else math.inf
    return {
        "model": "first_order_decay",
        "A0": A0,
        "k_per_h": k,
        "halflife_h": halflife,
        "r2": r2,
        "rmse": math.sqrt(ss_res / len(t)),
        "n_points": len(t),
    }


def fit_logistic_growth(time_points: list[Any], od_values: list[Any]) -> dict[str, Any]:
    """Fit N(t) = K/(1 + (K/N0 - 1) exp(-r t)) to OD600 over time."""
    _require_scipy()
    t, n = _paired(time_points, od_values, "time_points_h", "od600")
    if float(n[0]) <= 0.0:
        raise MbrError(
            MbrErrorCode.NUMERIC_INVALID,
            "Logistic growth requires positive initial OD600.",
            detail={"od600_0": float(n[0])},
        )
    K_guess = max(float(np.max(n)) * 1.2, float(n[0]) * 1.5)
    r_guess = 0.5
    N0_guess = float(n[0])

    def resid(p: np.ndarray) -> np.ndarray:
        K, r, N0 = p
        return K / (1.0 + (K / N0 - 1.0) * np.exp(-r * t)) - n

    try:
        res = least_squares(
            resid,
            x0=[K_guess, r_guess, N0_guess],
            bounds=([max(n[0] * 0.9, 1e-9), 0.0, 1e-9], [np.inf, np.inf, np.inf]),
            max_nfev=5000,
        )
    except Exception as exc:  # pragma: no cover
        raise MbrError(
            MbrErrorCode.TOOL_UNAVAILABLE,
            f"least_squares failed for logistic fit: {exc}",
            retryable=True,
        ) from exc
    if not res.success:
        raise MbrError(
            MbrErrorCode.SELF_CHECK_FAILED,
            f"Logistic fit did not converge: {res.message}",
            detail={"cost": float(res.cost)},
            retryable=True,
        )
    K, r, N0 = (float(res.x[0]), float(res.x[1]), float(res.x[2]))
    if not (math.isfinite(K) and math.isfinite(r) and math.isfinite(N0) and K > 0 and r >= 0 and N0 > 0):
        raise MbrError(MbrErrorCode.SELF_CHECK_FAILED, "Logistic fit produced non-physical parameters.")
    pred = K / (1.0 + (K / N0 - 1.0) * np.exp(-r * t))
    ss_res = float(np.sum((pred - n) ** 2))
    ss_tot = float(np.sum((n - np.mean(n)) ** 2))
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 0.0 else 1.0
    # generation time at mid-exponential: ln(2)/r
    doubling_h = math.log(2.0) / r if r > 0 else math.inf
    return {
        "model": "logistic_growth",
        "K": K,
        "r_per_h": r,
        "N0": N0,
        "doubling_h": doubling_h,
        "r2": r2,
        "n_points": len(t),
    }


def sensitivity_elasticity(model_fn, parameter: float, delta_pct: float) -> dict[str, Any]:
    """Numerical elasticity of a scalar model output wrt one parameter.

    elasticity = (df/f) / (dp/p), evaluated by central difference:
        df ~ (f(p+h) - f(p-h)) / (2h),  h = delta_pct/100 * |p|

    model_fn: callable(parameter_value: float) -> float  (scalar model output)
    """
    p = ensure_finite(parameter, "parameter")
    d = ensure_finite(delta_pct, "delta_pct")
    if d <= 0:
        raise MbrError(MbrErrorCode.NUMERIC_INVALID, "delta_pct must be > 0.", detail={"delta_pct": d})
    if p == 0.0:
        raise MbrError(MbrErrorCode.NUMERIC_INVALID, "Elasticity is undefined at parameter == 0.", detail={"parameter": p})

    def _eval(v: float) -> float:
        out = model_fn(v)
        return ensure_finite(float(out), "model_fn output")

    f0 = _eval(p)
    if f0 == 0.0:
        raise MbrError(MbrErrorCode.NUMERIC_INVALID, "Elasticity is undefined when model output == 0.", detail={"f0": f0})

    h = (d / 100.0) * abs(p)
    fp = _eval(p + h)
    fm = _eval(p - h)
    df_dp = (fp - fm) / (2.0 * h)
    elasticity = df_dp * (p / f0)
    if not math.isfinite(elasticity):
        raise MbrError(MbrErrorCode.SELF_CHECK_FAILED, "Elasticity computed as non-finite.")
    return {
        "parameter": p,
        "delta_pct": d,
        "f(p)": f0,
        "elasticity": elasticity,
        "interpretation": (
            "|elasticity|>1: output is more than proportionally sensitive to "
            "the parameter; <1: sub-proportional; sign = direction."
        ),
    }
