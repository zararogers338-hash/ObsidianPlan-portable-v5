"""Numerical primitives for micp-data-analyst.

Pure standard-library, deterministic, offline. Uses published closed-form
approximations with bounded error so the whole tool suite runs without numpy,
scipy, or network:

  - Normal quantile: Acklam's algorithm (rational approximation, max |err| ~
    1.15e-9 over 1e-300..1-1e-300). Verified against R qnorm on a grid.
  - Normal CDF: Abramowitz & Stegun 7.1.26 erf (|err| < 1.5e-7).
  - Student-t / F / chi-square survival: incomplete beta / gamma via Numerical
    Recipes betacf + Lanczos log-gamma.

Every function is pure and deterministic; nothing here consumes RNG state.
"""

from __future__ import annotations

import math

from _common import ToolError

EPS = 1e-12


# ---------------------------------------------------------------------------
# Normal distribution
# ---------------------------------------------------------------------------

def norm_ppf(p: float) -> float:
    """Standard normal quantile (Acklam, ~1.15e-9 accuracy)."""
    if not 0.0 < p < 1.0:
        raise ToolError("E_RANGE", "norm_ppf argument must be in (0, 1)")
    a = [-3.969683028665376e+01, 2.209460984245205e+02, -2.759285104469687e+02,
         1.383577518672690e+02, -3.066479806614716e+01, 2.506628277459239e+00]
    b = [-5.447609879822406e+01, 1.615858368580409e+02, -1.556989798598866e+02,
         6.680131188771972e+01, -1.328068155288572e+01]
    c = [-7.784894002430293e-03, -3.223964580411365e-01, -2.400758277161838e+00,
         -2.549732539343734e+00, 4.374664141464968e+00, 2.938163982698783e+00]
    d = [7.784695709041462e-03, 3.224671290700398e-01, 2.445134137142996e+00,
         3.754408661907416e+00]
    plow, phigh = 0.02425, 1.0 - 0.02425
    if p < plow:
        q = math.sqrt(-2.0 * math.log(p))
        return (((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / \
            ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1.0)
    if p > phigh:
        q = math.sqrt(-2.0 * math.log(1.0 - p))
        return -(((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / \
            ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1.0)
    q = p - 0.5
    r = q * q
    return (((((a[0] * r + a[1]) * r + a[2]) * r + a[3]) * r + a[4]) * r + a[5]) * q / \
        (((((b[0] * r + b[1]) * r + b[2]) * r + b[3]) * r + b[4]) * r + 1.0)


def norm_cdf(z: float) -> float:
    """Standard normal CDF via A&S 7.1.26 erf approximation (|err| < 1.5e-7)."""
    sign = 1.0 if z >= 0 else -1.0
    x = abs(z) / math.sqrt(2.0)
    t = 1.0 / (1.0 + 0.3275911 * x)
    y = 1.0 - (((((1.061405429 * t - 1.453152027) * t) + 1.421413741) * t
                - 0.284496736) * t + 0.254829592) * t * math.exp(-x * x)
    return 0.5 * (1.0 + sign * y)


def norm_pdf(z: float) -> float:
    return math.exp(-0.5 * z * z) / math.sqrt(2.0 * math.pi)


# ---------------------------------------------------------------------------
# Gamma / beta / t / F / chi-square
# ---------------------------------------------------------------------------

def lgamma_ln(z: float) -> float:
    """Log-gamma (Lanczos, g=7). Valid for z > 0."""
    if z <= 0:
        raise ToolError("E_RANGE", "lgamma requires z > 0")
    g = 7.0
    c = [0.99999999999980993, 676.5203681218851, -1259.1392167224028,
         771.32342877765313, -176.61502916214059, 12.507343278686905,
         -0.13857109526572012, 9.9843695780195716e-6, 1.5056327351493116e-7]
    if z < 0.5:
        return math.log(math.pi) - math.log(math.sin(math.pi * z)) - lgamma_ln(1.0 - z)
    z -= 1.0
    a = c[0]
    t = z + g + 0.5
    for i in range(1, 9):
        a += c[i] / (z + i)
    return 0.5 * math.log(2.0 * math.pi) + (z + 0.5) * math.log(t) - t + math.log(a)


def _betacf(a: float, b: float, x: float) -> float:
    """Continued fraction for the incomplete beta (Numerical Recipes betacf)."""
    maxit = 200
    eps = 3e-14
    fpmin = 1e-300
    qab = a + b
    qap = a + 1.0
    qam = a - 1.0
    c = 1.0
    d = 1.0 - qab * x / qap
    if abs(d) < fpmin:
        d = fpmin
    d = 1.0 / d
    h = d
    for m in range(1, maxit + 1):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1.0 + aa * d
        if abs(d) < fpmin:
            d = fpmin
        c = 1.0 + aa / c
        if abs(c) < fpmin:
            c = fpmin
        d = 1.0 / d
        h *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1.0 + aa * d
        if abs(d) < fpmin:
            d = fpmin
        c = 1.0 + aa / c
        if abs(c) < fpmin:
            c = fpmin
        d = 1.0 / d
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < eps:
            break
    return h


def betai(a: float, b: float, x: float) -> float:
    """Regularized incomplete beta I_x(a, b)."""
    if not 0.0 <= x <= 1.0:
        raise ToolError("E_RANGE", "betai x must be in [0, 1]")
    if x == 0.0:
        return 0.0
    if x == 1.0:
        return 1.0
    bt = math.exp(lgamma_ln(a + b) - lgamma_ln(a) - lgamma_ln(b) +
                  a * math.log(x) + b * math.log(1.0 - x))
    if x < (a + 1.0) / (a + b + 2.0):
        return bt * _betacf(a, b, x) / a
    return 1.0 - bt * _betacf(b, a, 1.0 - x) / b


def t_ppf(p: float, df: float) -> float:
    """Student-t quantile: returns x with P(T <= x) = p (two-tailed symmetric).

    Solves betai(df/2, 1/2, df/(df+x²)) = 2·(1−p) by bisection; the LHS is
    P(|T| > x). Deterministic, stdlib-only.
    """
    if not 0.0 < p < 1.0:
        raise ToolError("E_RANGE", "t_ppf argument must be in (0, 1)")
    if df <= 0:
        raise ToolError("E_RANGE", "t_ppf requires df > 0")
    if p < 0.5:
        return -t_ppf(1.0 - p, df)
    target = 2.0 * (1.0 - p)  # P(|T| > x)
    lo, hi = 0.0, 1e6
    for _ in range(140):
        mid = 0.5 * (lo + hi)
        val = betai(df / 2.0, 0.5, df / (df + mid * mid))
        if abs(val - target) < 1e-12:
            lo = mid
            break
        if val < target:  # x too large -> decrease x
            hi = mid
        else:             # x too small -> increase x
            lo = mid
    return lo


def t_pvalue(t: float, df: float) -> float:
    """Two-tailed p-value for Student-t."""
    if df <= 0:
        raise ToolError("E_RANGE", "t_pvalue requires df > 0")
    x = df / (df + t * t)
    return betai(0.5 * df, 0.5, x)


def f_sf(f: float, d1: float, d2: float) -> float:
    """P(F_{d1,d2} > f) = I_{d2/(d2+d1·f)}(d2/2, d1/2)."""
    if f <= 0:
        return 1.0
    x = d2 / (d2 + d1 * f)
    return betai(0.5 * d2, 0.5 * d1, x)


def chi2_sf(x: float, k: int) -> float:
    """P(chi²_k > x) via the upper incomplete gamma (NR gammq, series + CF)."""
    if x < 0:
        raise ToolError("E_RANGE", "chi2_sf x must be >= 0")
    if x == 0:
        return 1.0
    a = k / 2.0
    b = x / 2.0
    eps = 3e-14
    fpmin = 1e-300
    if b < a + 1.0:
        ap = a
        summ = 1.0 / a
        delta = summ
        for _ in range(200):
            ap += 1.0
            delta *= b / ap
            summ += delta
            if abs(delta) < abs(summ) * eps:
                break
        gam = summ * math.exp(-b + a * math.log(b) - lgamma_ln(a))
        return 1.0 - gam
    b0 = b + 1.0 - a
    c = 1.0 / fpmin
    d = 1.0 / b0
    h = d
    for i in range(1, 200):
        an = -i * (i - a)
        b0 += 2.0
        d = an * d + b0
        if abs(d) < fpmin:
            d = fpmin
        c = b0 + an / c
        if abs(c) < fpmin:
            c = fpmin
        d = 1.0 / d
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < eps:
            break
    return math.exp(-b + a * math.log(b) - lgamma_ln(a)) * h
