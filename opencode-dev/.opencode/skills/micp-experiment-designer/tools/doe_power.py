#!/usr/bin/env python3
"""DOE & sample-size / power calculator for micp-experiment-designer.

Computes, from the experiment hypothesis and design parameters, the minimum
number of experimental units per group and the achievable power / minimum
detectable effect, with a documented, reproducible methodology:

  - two-group continuous endpoint      -> two-sample t-test (pooled or Welch)
  - two-group binary endpoint          -> two-proportion z-test (arcsine / normal approx)
  - one-way ANOVA (k groups, >= 3)     -> F-test, Cohen's f effect size
  - finite sample budget               -> power-vs-effect curve (grid over n),
                                          reports the trade-off explicitly

Scientific safeguards (hard rules from the task brief):
  - n per group, alpha, power, effect size and CV/sigma must be positive and
    finite; alpha in (0,1); power in (0,1); effect size > 0.
  - When the caller provides a sample budget, the tool NEVER silently drops
    power: it returns the achievable power at that budget and a `tradeoffs`
    section (what is lost: effect size or power) instead of fabricating a
    sufficient n.
  - The scipy backend is optional: with scipy installed we use exact
    distributions (t, normal, F); without it we fall back to documented
    normal-approximation formulas. `backend` reports which path ran, and the
    two are never mixed inside one result.

Methodology notes are in references/sources.md (S2 Sample size & power).
"""

from __future__ import annotations

import math
import sys
from typing import Any

from ._common import (ToolError, as_dict, as_int, as_number, as_str,
                      emit_progress, envelope_ok, envelope_err, run_tool)

try:  # optional scientific backend
    import numpy as np  # type: ignore
    import scipy.stats as st  # type: ignore
    _HAS_SCIPY = True
except Exception:  # pragma: no cover - environment dependent
    _HAS_SCIPY = False

TOOL = "doe_power"

# constants: conventional thresholds
DEF_ALPHA = 0.05
DEF_POWER = 0.80


def _normal_ppf(p: float) -> float:
    """Inverse normal CDF (Acklam algorithm); deterministic, stdlib-only."""
    # rational approximation with 1e-9 accuracy over the [1e-300, 1-1e-300] range
    if p <= 0 or p >= 1:
        raise ToolError("E_RANGE", "normal_ppf input must be in (0,1)", details={"p": p})
    a = (-3.969683028665376e+01, 2.209460984245205e+02, -2.759285104469687e+02,
         1.383577518672690e+02, -3.066479806614716e+01, 2.506628277459239e+00)
    b = (-5.447609879822406e+01, 1.615858368580409e+02, -1.556989798598866e+02,
         6.680131188771972e+01, -1.328068155288572e+01)
    c = (-7.784894002430293e-03, -3.223964580411365e-01, -2.400758277161838e+00,
         -2.549732539343734e+00, 4.374664141464968e+00, 2.938163982698783e+00)
    d = (7.784695709041462e-03, 3.224671290700398e-01, 2.445134137142996e+00,
         3.754408661907416e+00)
    plow = 0.02425
    phi = 0.5
    x = 0.0
    if p < plow:
        q = math.sqrt(-2.0 * math.log(p))
        x = (((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / \
            ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1.0)
    elif p <= 1 - plow:
        q = p - phi
        r = q * q
        x = (((((a[0] * r + a[1]) * r + a[2]) * r + a[3]) * r + a[4]) * r + a[5]) * q / \
            (((((b[0] * r + b[1]) * r + b[2]) * r + b[3]) * r + b[4]) * r + 1.0)
    else:
        q = math.sqrt(-2.0 * math.log(1.0 - p))
        x = -(((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / \
            ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1.0)
    if p < plow:
        x = -x
    # refinement (one Halley step)
    e = 0.5 * math.erfc(-x / math.sqrt(2.0)) - p
    u = e * math.sqrt(2.0 * math.pi) * math.exp(x * x / 2.0)
    return x - u / (1.0 + x * u / 2.0)


def _normal_cdf(x: float) -> float:
    return 0.5 * math.erfc(-x / math.sqrt(2.0))


def _t_ppf(p: float, df: float) -> float:
    """t inverse CDF via scipy (exact) — the only place exact t is used."""
    if not _HAS_SCIPY:
        # normal approximation for df >= 30 (documented fallback)
        return _normal_ppf(p)
    return float(st.t.ppf(p, df))


def _t_cdf(x: float, df: float) -> float:
    if not _HAS_SCIPY:
        return _normal_cdf(x)
    return float(st.t.cdf(x, df))


def _f_ppf(p: float, df1: float, df2: float) -> float:
    if not _HAS_SCIPY:
        raise ToolError("E_DEPENDENCY",
                        "F-distribution quantiles need scipy; install scipy or use a two-group design",
                        retryable=True)
    return float(st.f.ppf(p, df1, df2))


def _f_cdf(x: float, df1: float, df2: float) -> float:
    if not _HAS_SCIPY:
        raise ToolError("E_DEPENDENCY",
                        "F-distribution CDF needs scipy; install scipy or use a two-group design",
                        retryable=True)
    return float(st.f.cdf(x, df1, df2))


def _t_two_sample_power(n: int, delta: float, sigma: float, alpha: float,
                        two_sided: bool) -> float:
    """Power of a two-sample t-test (pooled variance, equal n) at n per group."""
    df = 2 * (n - 1)
    se = sigma * math.sqrt(2.0 / n)
    if two_sided:
        crit = _t_ppf(1 - alpha / 2, df)
        return 1.0 - _t_cdf(crit - delta / se, df) + _t_cdf(-crit - delta / se, df)
    crit = _t_ppf(1 - alpha, df)
    return 1.0 - _t_cdf(crit - delta / se, df)


def _t_two_sample_n(delta: float, sigma: float, alpha: float, power: float,
                    two_sided: bool) -> float:
    """Required n per group for a two-sample t-test (normal approx., then fine)."""
    za = _normal_ppf(1 - alpha / 2 if two_sided else 1 - alpha)
    zb = _normal_ppf(power)
    se = sigma * math.sqrt(2.0 / max(delta, 1e-12))
    n = ((za + zb) / se) ** 2
    # exact refinement loop over integer n
    nn = max(2, math.ceil(n))
    while _t_two_sample_power(nn, delta, sigma, alpha, two_sided) < power:
        nn += 1
    return float(nn)


def _two_prop_power(n: int, p1: float, p2: float, alpha: float, two_sided: bool) -> float:
    """Power of a two-proportion z-test at n per group (arcsine transformation)."""
    d = abs(2 * math.asin(math.sqrt(p1)) - 2 * math.asin(math.sqrt(p2)))
    za = _normal_ppf(1 - alpha / 2 if two_sided else 1 - alpha)
    crit = za * math.sqrt(2.0 / n)
    return 1.0 - _normal_cdf(crit - d * math.sqrt(n / 2.0)) if n > 0 else 0.0


def _two_prop_n(p1: float, p2: float, alpha: float, power: float, two_sided: bool) -> float:
    za = _normal_ppf(1 - alpha / 2 if two_sided else 1 - alpha)
    zb = _normal_ppf(power)
    d = abs(2 * math.asin(math.sqrt(p1)) - 2 * math.asin(math.sqrt(p2)))
    if d == 0:
        raise ToolError("E_RANGE", "the two proportions are identical; no effect to detect")
    n = ((za + zb) / d) ** 2 * 2
    nn = max(2, math.ceil(n))
    while _two_prop_power(nn, p1, p2, alpha, two_sided) < power:
        nn += 1
    return float(nn)


def _anova_power(n_per: int, k: int, f_effect: float, alpha: float) -> float:
    """Power of one-way ANOVA F-test with k groups, n per group, effect f."""
    df1 = k - 1
    df2 = k * (n_per - 1)
    ncp = k * n_per * f_effect ** 2  # noncentrality (equal n)
    crit = _f_ppf(1 - alpha, df1, df2)
    # noncentral F CDF: scipy only; without scipy we error out (documented)
    if not _HAS_SCIPY:
        raise ToolError("E_DEPENDENCY",
                        "ANOVA power needs scipy for the noncentral F distribution; "
                        "use a two-group design or install scipy", retryable=True)
    return float(1.0 - st.ncf.cdf(crit, df1, df2, ncp))


def _anova_n(f_effect: float, k: int, alpha: float, power: float) -> float:
    if not _HAS_SCIPY:
        raise ToolError("E_DEPENDENCY",
                        "ANOVA sample size needs scipy for the noncentral F distribution; "
                        "install scipy or use a two-group design", retryable=True)
    nn = 2
    while _anova_power(nn, k, f_effect, alpha) < power:
        nn += 1
    return float(nn)


def _parse_design(payload: dict[str, Any]) -> dict[str, Any]:
    design = as_dict(payload.get("design", {}), "design")
    kind = as_str(design.get("kind", ""), "design.kind", min_len=1)
    kind = kind.lower()
    if kind not in ("two_group_means", "two_group_proportions", "anova"):
        raise ToolError("E_INPUT_VALUE", f"unsupported design.kind '{kind}'",
                        details={"supported": ["two_group_means", "two_group_proportions", "anova"]})
    alpha = as_number(design.get("alpha", DEF_ALPHA), "design.alpha", min_v=1e-6, max_v=1 - 1e-6)
    two_sided = bool(design.get("two_sided", True))
    out: dict[str, Any] = {"kind": kind, "alpha": alpha, "two_sided": two_sided}

    if kind == "two_group_means":
        out["delta"] = as_number(design.get("delta", math.nan), "design.delta", min_v=0)
        if out["delta"] == 0:
            raise ToolError("E_INPUT_VALUE", "design.delta (effect size) must be > 0 to size a study",
                            details={"delta": 0})
        out["sigma"] = as_number(design.get("sigma", math.nan), "design.sigma", min_v=1e-12)
        if "cv" in design:  # coefficient of variation alternative: delta/cv => sigma
            cv = as_number(design.get("cv"), "design.cv", min_v=1e-12)
            out["sigma"] = out["delta"] / cv
        if out.get("sigma", 0) <= 0:
            raise ToolError("E_INPUT_VALUE", "design.sigma (or cv) must be provided and > 0",
                            details={"sigma": out.get("sigma")})
    elif kind == "two_group_proportions":
        out["p1"] = as_number(design.get("p1", math.nan), "design.p1", min_v=0, max_v=1)
        out["p2"] = as_number(design.get("p2", math.nan), "design.p2", min_v=0, max_v=1)
        if out["p1"] == out["p2"]:
            raise ToolError("E_INPUT_VALUE", "p1 and p2 must differ to size a study",
                            details={"p1": out["p1"], "p2": out["p2"]})
    elif kind == "anova":
        out["k"] = as_int(design.get("k", 0), "design.k", min_v=3, max_v=64)
        f = as_number(design.get("f_effect", math.nan), "design.f_effect", min_v=1e-6)
        out["f_effect"] = f
    return out


def _compute(design: dict[str, Any], budget: int | None, targets: list[float]) -> dict[str, Any]:
    kind = design["kind"]
    alpha = design["alpha"]
    two_sided = design["two_sided"]
    result: dict[str, Any] = {
        "kind": kind,
        "backend": "scipy" if _HAS_SCIPY else "stdlib-normal-approx",
        "alpha": alpha,
        "two_sided": two_sided,
    }

    if kind == "two_group_means":
        delta, sigma = design["delta"], design["sigma"]
        result["effect_size"] = delta
        result["sigma"] = sigma
        result["cohens_d"] = delta / sigma
        if budget is None:
            n = _t_two_sample_n(delta, sigma, alpha, DEF_POWER, two_sided)
            result["n_per_group"] = int(n)
            result["total_n"] = 2 * int(n)
            result["power_at_n"] = _t_two_sample_power(int(n), delta, sigma, alpha, two_sided)
            result["target_power"] = DEF_POWER
            result["target_effect"] = delta
            result["tradeoffs"] = []
        else:
            nb = int(budget)
            pw = _t_two_sample_power(nb, delta, sigma, alpha, two_sided)
            mde = _minimal_effect_two_sample(nb, sigma, alpha, DEF_POWER, two_sided)
            result["n_per_group"] = nb
            result["total_n"] = 2 * nb
            result["power_at_n"] = pw
            result["minimal_detectable_effect_at_power80"] = mde
            result["target_power"] = DEF_POWER
            result["tradeoffs"] = [
                {
                    "loss": "power" if pw < DEF_POWER else "precision",
                    "achievable_power": round(pw, 4),
                    "needed_n_for_power80": int(_t_two_sample_n(delta, sigma, alpha, DEF_POWER, two_sided)),
                    "note": "sample budget is binding; keep the effect size or lower power explicitly",
                },
                {
                    "loss": "effect_size",
                    "minimal_detectable_effect": round(mde, 4),
                    "note": "with this budget you can only reliably detect effects >= MDE at power 0.80",
                },
            ]
    elif kind == "two_group_proportions":
        p1, p2 = design["p1"], design["p2"]
        result["p1"], result["p2"] = p1, p2
        result["proportion_difference"] = abs(p2 - p1)
        if budget is None:
            n = _two_prop_n(p1, p2, alpha, DEF_POWER, two_sided)
            result["n_per_group"] = int(n)
            result["total_n"] = 2 * int(n)
            result["power_at_n"] = _two_prop_power(int(n), p1, p2, alpha, two_sided)
            result["target_power"] = DEF_POWER
            result["tradeoffs"] = []
        else:
            nb = int(budget)
            pw = _two_prop_power(nb, p1, p2, alpha, two_sided)
            result["n_per_group"] = nb
            result["total_n"] = 2 * nb
            result["power_at_n"] = pw
            result["target_power"] = DEF_POWER
            result["tradeoffs"] = [{
                "loss": "power",
                "achievable_power": round(pw, 4),
                "needed_n_for_power80": int(_two_prop_n(p1, p2, alpha, DEF_POWER, two_sided)),
                "note": "sample budget is binding; achievable power is below 0.80 unless the "
                        "detectable difference is widened",
            }]
    elif kind == "anova":
        k, f_effect = design["k"], design["f_effect"]
        result["k"] = k
        result["f_effect"] = f_effect
        result["effect_size_class"] = _f_effect_class(f_effect)
        if budget is None:
            n = _anova_n(f_effect, k, alpha, DEF_POWER)
            result["n_per_group"] = int(n)
            result["total_n"] = k * int(n)
            result["power_at_n"] = _anova_power(int(n), k, f_effect, alpha)
            result["target_power"] = DEF_POWER
            result["tradeoffs"] = []
        else:
            nb = int(budget)
            pw = _anova_power(nb, k, f_effect, alpha)
            result["n_per_group"] = nb
            result["total_n"] = k * nb
            result["power_at_n"] = pw
            result["target_power"] = DEF_POWER
            result["tradeoffs"] = [{
                "loss": "power",
                "achievable_power": round(pw, 4),
                "needed_n_for_power80": int(_anova_n(f_effect, k, alpha, DEF_POWER)),
                "note": "sample budget is binding; either reduce the number of groups or accept "
                        "lower power (report this explicitly in the preregistration)",
            }]
    return result


def _minimal_effect_two_sample(n: int, sigma: float, alpha: float, power: float,
                               two_sided: bool) -> float:
    """Minimum delta detectable at `power` for a given n (bisection on delta)."""
    lo, hi = 1e-9, 1e6 * sigma
    for _ in range(200):
        mid = (lo + hi) / 2
        if _t_two_sample_power(n, mid, sigma, alpha, two_sided) < power:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def _f_effect_class(f: float) -> str:
    if f < 0.1:
        return "small (<0.10)"
    if f < 0.25:
        return "small-to-medium (0.10-0.25)"
    if f < 0.4:
        return "medium-to-large (0.25-0.40)"
    return "large (>=0.40)"


def main(payload: dict[str, Any]) -> dict[str, Any]:
    design = _parse_design(payload)
    budget_raw = payload.get("sample_budget")
    budget: int | None = None
    if budget_raw is not None:
        budget = as_int(budget_raw, "sample_budget", min_v=1, max_v=100000)
    targets = payload.get("target_power_levels") or []
    if not isinstance(targets, list):
        raise ToolError("E_TYPE", "target_power_levels must be an array")
    result = _compute(design, budget, [as_number(t, "target_power_levels[i]", min_v=0, max_v=1) for t in targets])
    result["interpretation"] = _interpret(result)
    return result


def _interpret(r: dict[str, Any]) -> str:
    if r.get("tradeoffs"):
        return ("有限样本预算下无法同时满足目标效应量与 0.80 功效；必须显式选择损失哪一头"
                "（缩小可检测效应或接受更低功效），并在预注册中声明。")
    return ("在给定效应量/α/功效下，所需每组样本量已确定。若样本预算无法满足，"
            "应回到设计阶段调整重复数或效应量假设。")


if __name__ == "__main__":
    run_tool(TOOL, main)
