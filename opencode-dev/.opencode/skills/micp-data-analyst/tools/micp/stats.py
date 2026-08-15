"""Statistical inference for micp-data-analyst: descriptives, effect sizes,
confidence intervals, power estimation, and normality screening.

Pure standard library, offline, deterministic. Random draws (bootstrap) are
seeded through a user-supplied seed (default 0) so repeated runs reproduce
byte-identical output. Numerics live in _numerics.py.

Normality screening reports skewness/kurtosis z-scores against the normal
approximation, a D'Agostino-style omnibus, and an explicit sample-size caveat:
for n < 8 normality cannot be certified at any confidence. This is a screening
step, not a substitute for model diagnostics.
"""

from __future__ import annotations

import math
import random
from typing import Any, Iterable

from _common import ToolError, as_dict, as_number, as_str
from _numerics import norm_cdf, t_ppf, t_pvalue, f_sf

EPS = 1e-12


def clean_numbers(values: Iterable[Any], path: str = "$") -> list[float]:
    """Drop None/''; reject booleans and non-finite numbers loudly."""
    out: list[float] = []
    for i, v in enumerate(values):
        if v is None or v == "":
            continue
        if isinstance(v, bool):
            raise ToolError("E_TYPE", f"{path}[{i}] must be a number, got boolean")
        if not isinstance(v, (int, float)):
            raise ToolError("E_TYPE", f"{path}[{i}] must be a number, got {type(v).__name__}")
        f = float(v)
        if not math.isfinite(f):
            raise ToolError("E_NUMERIC_NON_FINITE", f"{path}[{i}] is non-finite")
        out.append(f)
    return out


def mean(x: list[float]) -> float:
    if not x:
        raise ToolError("E_EMPTY", "cannot compute mean of empty set")
    return sum(x) / len(x)


def variance(x: list[float], ddof: int = 1) -> float:
    if len(x) < 2:
        raise ToolError("E_INSUFFICIENT", "sample variance needs n >= 2", details={"n": len(x)})
    m = mean(x)
    return sum((v - m) ** 2 for v in x) / (len(x) - ddof)


def stddev(x: list[float], ddof: int = 1) -> float:
    return math.sqrt(max(variance(x, ddof), 0.0))


def quantile(x: list[float], q: float) -> float:
    """Linear-interpolation quantile (same convention as numpy.quantile default)."""
    if not x:
        raise ToolError("E_EMPTY", "cannot compute quantile of empty set")
    s = sorted(x)
    pos = q * (len(s) - 1)
    lo = math.floor(pos)
    hi = math.ceil(pos)
    if lo == hi:
        return s[lo]
    frac = pos - lo
    return s[lo] * (1 - frac) + s[hi] * frac


# ---------------------------------------------------------------------------
# Moments and normality screening
# ---------------------------------------------------------------------------

def _moments(x: list[float]) -> tuple[float, float, float, float]:
    n = len(x)
    m = mean(x)
    m2 = sum((v - m) ** 2 for v in x) / n
    m3 = sum((v - m) ** 3 for v in x) / n
    m4 = sum((v - m) ** 4 for v in x) / n
    sd = math.sqrt(m2) if m2 > 0 else 0.0
    if sd == 0:
        return m, sd, 0.0, 0.0
    g1 = m3 / (m2 ** 1.5)
    g2 = m4 / (m2 * m2) - 3.0
    return m, sd, g1, g2


def normality_screen(x: list[float], *, alpha: float = 0.05) -> dict[str, Any]:
    """Skewness/kurtosis z-scores + omnibus chi-square, with n-caveat.

    Deterministic; no dependence on numpy/scipy. For n < 8 the omnibus is not
    run and the verdict is 'insufficient_data'.
    """
    n = len(x)
    if n < 3:
        # Degrade, never crash: a normality verdict needs at least 3 points,
        # but the analysis can continue with the caveat recorded.
        return {
            "n": n, "testable": False, "normal": None,
            "verdict": "insufficient_data",
            "note": f"n={n} < 3: normality cannot be assessed; treat any inference "
                    f"as assumption-laden",
            "skewness": None, "excess_kurtosis": None,
            "skew_z": None, "kurt_z": None, "omnibus_chi2": None, "p_value": None,
            "confidence": "none",
        }
    m, sd, g1, g2 = _moments(x)
    if n < 8:
        return {
            "n": n, "testable": False, "normal": None,
            "verdict": "insufficient_data",
            "note": f"n={n} < 8: moment-based tests have no power; do not certify normality",
            "skewness": round(g1, 6), "excess_kurtosis": round(g2, 6),
            "skew_z": None, "kurt_z": None, "omnibus_chi2": None, "p_value": None,
            "confidence": "none",
        }
    # Standard errors (D'Agostino 1970; Pearson & Hartley approximations)
    se_g1 = math.sqrt(6.0 * n * (n - 1) / ((n - 2) * (n + 1) * (n + 3)))
    se_g2 = math.sqrt(24.0 * n * (n - 1) ** 2 / ((n - 3) * (n - 2) * (n + 3) * (n + 5)))
    z1 = g1 / se_g1 if se_g1 > 0 else 0.0
    z2 = g2 / se_g2 if se_g2 > 0 else 0.0
    # omnibus: chi2 = z1^2 + z2^2 with df=2 (approximate; kurtosis z is
    # non-normal for small n — hence the confidence band below).
    chi2 = z1 * z1 + z2 * z2
    from _numerics import chi2_sf
    p = chi2_sf(chi2, 2)
    normal = p >= alpha
    confidence = "medium" if n >= 30 else "low"
    return {
        "n": n, "testable": True, "normal": normal,
        "verdict": "consistent_with_normal" if normal else "departure_from_normal",
        "note": "omnibus uses the normal approximation for kurtosis; treat as a screen",
        "skewness": round(g1, 6), "excess_kurtosis": round(g2, 6),
        "skew_z": round(z1, 6), "kurt_z": round(z2, 6),
        "omnibus_chi2": round(chi2, 6), "p_value": round(p, 6),
        "alpha": alpha, "confidence": confidence,
    }


# ---------------------------------------------------------------------------
# CIs and effect sizes
# ---------------------------------------------------------------------------

def t_ci(x: list[float], confidence: float = 0.95) -> dict[str, float]:
    n = len(x)
    if n < 2:
        raise ToolError("E_INSUFFICIENT", "CI needs n >= 2")
    m = mean(x)
    s = stddev(x)
    se = s / math.sqrt(n)
    crit = t_ppf((1.0 + confidence) / 2.0, n - 1)
    half = crit * se
    return {"n": n, "mean": round(m, 6), "sd": round(s, 6), "se": round(se, 6),
            "confidence": round(confidence, 6), "ci_lower": round(m - half, 6),
            "ci_upper": round(m + half, 6), "t_crit": round(crit, 6)}


def cohens_d(a: list[float], b: list[float]) -> dict[str, float]:
    """Unbiased effect size (Hedges' g) between two independent samples."""
    na, nb = len(a), len(b)
    if na < 2 or nb < 2:
        raise ToolError("E_INSUFFICIENT", "effect size needs n >= 2 per group")
    sp = math.sqrt(((na - 1) * variance(a) + (nb - 1) * variance(b)) / (na + nb - 2))
    if sp < EPS:
        raise ToolError("E_NUMERICAL", "pooled SD is zero; effect size undefined")
    g = (mean(a) - mean(b)) / sp
    j = 1.0 - 3.0 / (4.0 * (na + nb - 2) - 1.0)  # Hedges' correction
    g_adj = g * j
    se = math.sqrt((na + nb) / (na * nb) + g_adj * g_adj / (2 * (na + nb - 2)))
    return {"n1": na, "n2": nb, "cohens_d": round(g_adj, 6), "hedges_g": round(g_adj, 6),
            "se": round(se, 6), "ci_lower_95": round(g_adj - 1.96 * se, 6),
            "ci_upper_95": round(g_adj + 1.96 * se, 6),
            "magnitude": _d_magnitude(abs(g_adj))}


def _d_magnitude(d: float) -> str:
    if d < 0.2:
        return "negligible"
    if d < 0.5:
        return "small"
    if d < 0.8:
        return "medium"
    return "large"


def power_two_sample(n: int, d: float, alpha: float = 0.05) -> dict[str, float]:
    """Approximate power for a balanced two-sample t-test (normal approximation
    to the noncentral t). Deterministic, planning-grade."""
    if n < 2:
        raise ToolError("E_INSUFFICIENT", "power needs n >= 2 per group")
    nc = d * math.sqrt(n / 2.0)
    df = 2 * n - 2
    tcrit = t_ppf(1.0 - alpha / 2.0, df)
    var = df / max(df - 2.0, 0.01)
    power = 1.0 - norm_cdf((tcrit - nc) / math.sqrt(var))
    return {"n_per_group": n, "d": round(d, 6), "alpha": alpha, "power": round(power, 6),
            "df": df,
            "note": "normal approximation to noncentral t; simulate for critical decisions"}


def descriptive(x: list[float], *, unit: str | None = None, name: str | None = None,
                seed: int | None = None, bootstrap: bool = False) -> dict[str, Any]:
    if not x:
        raise ToolError("E_EMPTY", "no numeric values for descriptive statistics")
    x = clean_numbers(x)
    n = len(x)
    s = sorted(x)
    rng = random.Random(seed if seed is not None else 0)
    _m, _sd, g1, g2 = _moments(x)
    sd = stddev(x)  # sample SD (ddof=1) — matches t_ci and CV convention

    boot_ci = None
    if bootstrap and n >= 3:
        draws = []
        for _ in range(1999):
            sample = [rng.choice(s) for _ in range(n)]
            draws.append(mean(sample))
        draws.sort()
        boot_ci = [round(draws[49], 6), round(draws[1949], 6)]  # 2.5% / 97.5%

    res: dict[str, Any] = {
        "n": n, "mean": round(mean(x), 6), "median": round(quantile(s, 0.5), 6),
        "sd": round(sd, 6),
        "cv_percent": round(100.0 * sd / mean(x), 4) if abs(mean(x)) > EPS else None,
        "min": round(s[0], 6), "q1": round(quantile(s, 0.25), 6),
        "q3": round(quantile(s, 0.75), 6), "max": round(s[-1], 6),
        "iqr": round(quantile(s, 0.75) - quantile(s, 0.25), 6),
        "range": round(s[-1] - s[0], 6),
        "skewness": round(g1, 6), "excess_kurtosis": round(g2, 6),
        "bootstrap_mean_ci95": boot_ci,
        "seed_used": seed if seed is not None else 0,
    }
    if unit:
        res["unit"] = unit
    if name:
        res["name"] = name
    return res


def outlier_policies(values: list[float]) -> dict[str, Any]:
    x = clean_numbers(values)
    n = len(x)
    q1 = quantile(x, 0.25)
    q3 = quantile(x, 0.75)
    iqr = q3 - q1
    lo_iqr, hi_iqr = q1 - 1.5 * iqr, q3 + 1.5 * iqr
    m, sd = mean(x), stddev(x)
    lo_sd, hi_sd = m - 3.0 * sd, m + 3.0 * sd
    iqr_flags = [i for i, v in enumerate(x) if v < lo_iqr or v > hi_iqr]
    sd_flags = [i for i, v in enumerate(x) if v < lo_sd or v > hi_sd]
    winsorized = [max(lo_iqr, min(hi_iqr, v)) for v in x]
    return {"n": n, "q1": round(q1, 6), "q3": round(q3, 6), "iqr": round(iqr, 6),
            "bounds_iqr": [round(lo_iqr, 6), round(hi_iqr, 6)],
            "bounds_3sd": [round(lo_sd, 6), round(hi_sd, 6)],
            "flags_iqr_indices": iqr_flags, "flags_3sd_indices": sd_flags,
            "n_iqr_outliers": len(iqr_flags), "n_3sd_outliers": len(sd_flags),
            "winsorized_mean": round(mean(winsorized), 6),
            "trimmed_5pct_mean": round(mean(trimmed(x, 0.05)), 6) if n >= 10 else None,
            "low_confidence": n < 5,
            "note": (f"n={n} < 5: IQR/3SD outlier bounds are unreliable at this sample "
                     f"size; treat flags as indicative only" if n < 5
                     else "outlier bounds computed from full sample")}


def trimmed(x: list[float], frac: float) -> list[float]:
    s = sorted(x)
    k = int(len(s) * frac)
    return s[k:len(s) - k]


def sensitivity_mean(values: list[float], strategies: list[str]) -> dict[str, Any]:
    x = clean_numbers(values)
    n = len(x)
    result: dict[str, Any] = {"n": n, "strategies_run": [], "estimates": {}}
    for strat in strategies:
        if strat == "keep":
            est, label = mean(x), "mean (raw)"
        elif strat == "winsorize_1p5iqr":
            q1, q3 = quantile(x, 0.25), quantile(x, 0.75)
            lo, hi = q1 - 1.5 * (q3 - q1), q3 + 1.5 * (q3 - q1)
            est, label = mean([max(lo, min(hi, v)) for v in x]), "mean (winsorized 1.5×IQR)"
        elif strat == "winsorize_3sd":
            m, sd = mean(x), stddev(x)
            lo, hi = m - 3 * sd, m + 3 * sd
            est, label = mean([max(lo, min(hi, v)) for v in x]), "mean (winsorized 3SD)"
        elif strat == "trim_5pct":
            est, label = mean(trimmed(x, 0.05)) if n >= 10 else mean(x), "mean (trimmed 5%)"
        elif strat == "flag_only":
            est, label = mean(x), "mean (raw, outliers flagged)"
        else:
            raise ToolError("E_INPUT_RANGE", f"unknown strategy {strat!r}")
        result["estimates"][strat] = {"value": round(est, 6), "label": label}
        result["strategies_run"].append(strat)
    vals = [e["value"] for e in result["estimates"].values()]
    result["spread"] = round(max(vals) - min(vals), 6) if vals else None
    return result


def linear_regression(x: list[float], y: list[float]) -> dict[str, Any]:
    if len(x) != len(y):
        raise ToolError("E_TYPE", "x and y lengths differ")
    n = len(x)
    if n < 3:
        raise ToolError("E_INSUFFICIENT", "regression needs n >= 3")
    xbar, ybar = mean(x), mean(y)
    sxx = sum((v - xbar) ** 2 for v in x)
    if sxx < EPS:
        raise ToolError("E_NUMERICAL", "x has zero variance; slope undefined")
    sxy = sum((xi - xbar) * (yi - ybar) for xi, yi in zip(x, y))
    slope = sxy / sxx
    intercept = ybar - slope * xbar
    resid = [yi - (intercept + slope * xi) for xi, yi in zip(x, y)]
    sse = sum(r * r for r in resid)
    sst = sum((yi - ybar) ** 2 for yi in y)
    r2 = 1.0 - sse / sst if sst > EPS else 1.0
    se_slope = math.sqrt(sse / (n - 2) / sxx) if n > 2 else 0.0
    if se_slope > EPS:
        t = slope / se_slope
    elif abs(slope) > EPS:
        t = float("inf")  # perfect fit: undefined ratio, treat as unbounded
    else:
        t = 0.0
    p = t_pvalue(t, n - 2) if n > 2 else None
    return {"n": n, "slope": round(slope, 6), "intercept": round(intercept, 6),
            "r2": round(r2, 6), "r": round(math.copysign(math.sqrt(abs(r2)), slope), 6),
            "se_slope": round(se_slope, 6), "t_stat": round(t, 6),
            "p_value": round(p, 6) if p is not None else None,
            "residual_mean": round(mean(resid), 8), "residual_sd": round(stddev(resid), 6),
            "notes": ["OLS; verify normality/heteroscedasticity before inference"]}


def oneway_anova(groups: list[list[float]]) -> dict[str, Any]:
    valid = [clean_numbers(g) for g in groups if g]
    k = len(valid)
    if k < 2:
        raise ToolError("E_INSUFFICIENT", "ANOVA needs >= 2 groups")
    ns = [len(g) for g in valid]
    n = sum(ns)
    grand = mean([v for g in valid for v in g])
    ssb = sum(len(g) * (mean(g) - grand) ** 2 for g in valid)
    ssw = sum((v - mean(g)) ** 2 for g in valid for v in g)
    dfb, dfw = k - 1, n - k
    if dfw <= 0 or ssw <= EPS:
        raise ToolError("E_NUMERICAL", "ANOVA needs within-group variance")
    msb, msw = ssb / dfb, ssw / dfw
    f = msb / msw if msw > 0 else float("inf")
    p = f_sf(f, dfb, dfw)
    return {"k": k, "n_total": n, "n_per_group": ns, "ss_between": round(ssb, 6),
            "ss_within": round(ssw, 6), "df_between": dfb, "df_within": dfw,
            "F": round(f, 6), "p_value": round(p, 6) if math.isfinite(p) else 0.0,
            "eta_squared": round(ssb / (ssb + ssw), 6) if (ssb + ssw) > 0 else None,
            "group_means": [round(mean(g), 6) for g in valid]}


def spatial_uniformity(values: list[float], positions: list[str] | None = None,
                       segments: int | None = None) -> dict[str, Any]:
    x = clean_numbers(values)
    if len(x) < 2:
        raise ToolError("E_INSUFFICIENT", "uniformity needs >= 2 values")
    if positions is not None and len(positions) != len(x):
        raise ToolError("E_TYPE", "positions length must equal values length")
    if segments is None and positions is not None:
        uniq = sorted(set(positions))
        seg = {p: [v for p_, v in zip(positions, x) if p_ == p] for p in uniq}
    elif segments is not None:
        seg = {}
        chunk = max(1, math.ceil(len(x) / segments))
        for i in range(0, len(x), chunk):
            seg[f"seg{i // chunk + 1}"] = x[i:i + chunk]
    else:
        # no positions, no segments: treat each value as its own unit so the
        # across-unit dispersion is meaningful (each index = one spatial unit)
        seg = {f"pos{i + 1}": [v] for i, v in enumerate(x)}
    seg_means = {k: mean(v) for k, v in seg.items()}
    m = mean(list(seg_means.values()))
    s = stddev(list(seg_means.values()))
    cv = 100.0 * s / m if abs(m) > EPS else None
    return {"n": len(x), "segments": list(seg.keys()),
            "segment_means": {k: round(v, 6) for k, v in seg_means.items()},
            "overall_mean": round(m, 6), "segment_sd": round(s, 6),
            "cv_percent": round(cv, 4) if cv is not None else None,
            "uniformity_index": round(1.0 - cv / 100.0, 6) if cv is not None else None,
            "recommendation": ("uniform" if cv is not None and cv < 15
                               else "moderately_non_uniform" if cv is not None and cv < 30
                               else "non_uniform")}


def reproducibility_hash(frames: dict[str, Any]) -> dict[str, Any]:
    import hashlib
    import json as _json
    raw = _json.dumps(frames, sort_keys=True, ensure_ascii=False, default=str)
    return {"sha256": hashlib.sha256(raw.encode("utf-8")).hexdigest(),
            "frame_size_chars": len(raw)}


def main(payload: dict) -> dict:
    p = as_dict(payload, "$")
    op = as_str(p.get("op", ""), "$.op")
    seed = p.get("seed")
    if seed is not None:
        as_number(seed, "$.seed", min_v=0)
        seed = int(seed)

    if op == "descriptive":
        x = clean_numbers(p.get("values", []), "$.values")
        return {"descriptive": descriptive(
            x, unit=p.get("unit"), name=p.get("name"), seed=seed,
            bootstrap=bool(p.get("bootstrap", False)))}
    if op == "ci":
        x = clean_numbers(p.get("values", []), "$.values")
        conf = p.get("confidence", 0.95)
        as_number(conf, "$.confidence", min_v=0.5, max_v=0.9999)
        return {"ci": t_ci(x, conf)}
    if op == "cohens_d":
        a = clean_numbers(p.get("a", []), "$.a")
        b = clean_numbers(p.get("b", []), "$.b")
        return {"effect_size": cohens_d(a, b)}
    if op == "power":
        n, d, alpha = p.get("n", 0), p.get("d", 0.0), p.get("alpha", 0.05)
        as_number(n, "$.n", min_v=2)
        as_number(d, "$.d")
        as_number(alpha, "$.alpha", min_v=0.001, max_v=0.5)
        return {"power": power_two_sample(int(n), float(d), float(alpha))}
    if op == "normality":
        x = clean_numbers(p.get("values", []), "$.values")
        return {"normality": normality_screen(x, alpha=float(p.get("alpha", 0.05)))}
    if op == "outliers":
        x = clean_numbers(p.get("values", []), "$.values")
        return {"outliers": outlier_policies(x)}
    if op == "sensitivity":
        x = clean_numbers(p.get("values", []), "$.values")
        strats = p.get("strategies", ["keep", "winsorize_1p5iqr", "winsorize_3sd", "trim_5pct"])
        if not isinstance(strats, list) or not strats:
            raise ToolError("E_INPUT_RANGE", "sensitivity needs a non-empty strategies list")
        return {"sensitivity": sensitivity_mean(x, strats)}
    if op == "regression":
        x = clean_numbers(p.get("x", []), "$.x")
        y = clean_numbers(p.get("y", []), "$.y")
        return {"regression": linear_regression(x, y)}
    if op == "anova":
        groups = p.get("groups", [])
        if not isinstance(groups, list):
            raise ToolError("E_TYPE", "$.groups must be an array")
        return {"anova": oneway_anova(groups)}
    if op == "uniformity":
        values = clean_numbers(p.get("values", []), "$.values")
        positions = p.get("positions")
        segments = p.get("segments")
        if segments is not None:
            as_number(segments, "$.segments", min_v=2, max_v=10000)
        return {"uniformity": spatial_uniformity(values, positions,
                                                 int(segments) if segments else None)}
    if op == "repro_hash":
        return {"reproducibility": reproducibility_hash(p.get("frames", {}))}
    raise ToolError("E_INPUT_RANGE", f"unknown op {op!r}", details={
        "op": op, "allowed": ["descriptive", "ci", "cohens_d", "power", "normality",
                              "outliers", "sensitivity", "regression", "anova",
                              "uniformity", "repro_hash"]})


if __name__ == "__main__":
    from _common import run_tool
    run_tool("stats", main)
