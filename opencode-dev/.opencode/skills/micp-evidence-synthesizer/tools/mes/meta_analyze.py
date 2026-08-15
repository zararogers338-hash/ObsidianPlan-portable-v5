"""Meta-analysis pooling (fixed-effect inverse-variance + DerSimonian-Laird
random-effects). Guards: >=2 poolable studies, non-finite values, I2 ceiling
(see SKILL.md §条件化合并).

Output shape matches the output.schema.json `metaAnalysis` def:
  model, pooled_effect, ci95, between_study_variance_tau2, weights[]
"""

from __future__ import annotations

from dataclasses import dataclass
from math import sqrt
from typing import Optional

from .errors import MesError, MesErrorCode


@dataclass
class MetaResult:
    model: str
    pooled_effect: Optional[float]
    ci95: list[Optional[float]]
    between_study_variance_tau2: Optional[float]
    weights: list[dict]
    i2: Optional[float] = None
    q: Optional[float] = None
    q_p_value: Optional[float] = None
    prediction_interval: Optional[list[Optional[float]]] = None


def _check_effects(effects: list[dict]) -> None:
    if not effects or len(effects) < 2:
        raise MesError(MesErrorCode.INSUFFICIENT_POOLING,
                       f"quantitative pooling requires >=2 poolable studies, got {len(effects or [])}")
    for e in effects:
        es = e.get("effect_size")
        var = e.get("variance")
        for lbl, val in (("effect_size", es), ("variance", var)):
            if val is None or val != val or val in (float("inf"), float("-inf")):
                raise MesError(MesErrorCode.NUMERIC_INVALID, f"{lbl} non-finite in pool")
            if lbl == "variance" and val <= 0:
                raise MesError(MesErrorCode.NUMERIC_INVALID, f"variance must be > 0, got {val}")


def _p_value_from_chi2(q: float, df: float) -> float:
    """Upper-tail chi-square p via Wilson-Hilferty approximation."""
    if q <= 0 or df <= 0:
        return 1.0
    x = q / df
    z = ((x ** (1.0 / 3.0)) - (1.0 - 2.0 / (9.0 * df))) / sqrt(2.0 / (9.0 * df))
    # standard normal survivor via Abramowitz-Stegun 26.2.17
    if z > 0:
        t = 1.0 / (1.0 + 0.2316419 * z)
        pdf = 0.3989422804 * _exp(-z * z / 2.0)
        return pdf * t * (0.319381530 + t * (-0.356563782 + t * (1.781477937 + t * (-1.821255978 + t * 1.330274429))))
    return 1.0 - _p_value_from_chi2(-z, df) if False else _surv(-z)


def _surv(z: float) -> float:
    t = 1.0 / (1.0 + 0.2316419 * abs(z))
    pdf = 0.3989422804 * _exp(-z * z / 2.0)
    poly = t * (0.319381530 + t * (-0.356563782 + t * (1.781477937 + t * (-1.821255978 + t * 1.330274429))))
    return 1.0 - pdf * poly if z < 0 else pdf * poly


def _exp(x: float) -> float:
    """exp with overflow guard (kept dependency-free and stable for extreme z)."""
    import math
    if x < -745:
        return 0.0
    return math.exp(x)


def _inverse_variance_pool(effects: list[dict]) -> tuple[float, float]:
    """Weighted mean and its variance under inverse-variance weights."""
    w_sum = 0.0
    es_sum = 0.0
    for e in effects:
        w = 1.0 / e["variance"]
        w_sum += w
        es_sum += w * e["effect_size"]
    if w_sum == 0:
        raise MesError(MesErrorCode.NUMERIC_INVALID, "zero total weight in pooling")
    pooled = es_sum / w_sum
    return pooled, 1.0 / w_sum


def _tau2_dl(effects: list[dict], pooled_fe: float, q: float, df: float) -> float:
    """DerSimonian-Laird between-study variance estimator."""
    w_sum = sum(1.0 / e["variance"] for e in effects)
    w2_sum = sum((1.0 / e["variance"]) ** 2 for e in effects)
    num = q - df
    denom = w_sum - w2_sum / w_sum
    if denom <= 0:
        return 0.0
    return max(0.0, num / denom)


def meta_analyze(effects: list[dict], model: str = "random_effects") -> MetaResult:
    """Pool effect sizes. `model` in {fixed_effect, random_effects}.

    Raises MesError for <2 poolable studies or non-finite inputs. I2 and Q are
    computed in both models from the fixed-effect moments; tau2 applies to the
    random-effects model only.
    """
    _check_effects(effects)
    k = len(effects)
    df = k - 1

    fe_pooled, fe_var = _inverse_variance_pool(effects)
    q = sum((e["effect_size"] - fe_pooled) ** 2 / e["variance"] for e in effects)
    if q < 0:
        q = 0.0
    i2 = max(0.0, (q - df) / q * 100.0) if q > 0 else 0.0
    q_p = _p_value_from_chi2(q, df)

    if model == "fixed_effect":
        pooled, var = fe_pooled, fe_var
        tau2 = None
    else:
        tau2 = _tau2_dl(effects, fe_pooled, q, df)
        w_sum = sum(1.0 / (e["variance"] + tau2) for e in effects)
        pooled = sum((e["effect_size"] / (e["variance"] + tau2)) for e in effects) / w_sum
        var = 1.0 / w_sum

    z = 1.959964
    se = sqrt(var)
    ci = [round(pooled - z * se, 4), round(pooled + z * se, 4)]

    weights = []
    for e in effects:
        w = 1.0 / e["variance"] if model == "fixed_effect" else 1.0 / (e["variance"] + (tau2 or 0.0))
        weights.append({"ref_id": e.get("ref_id"), "effect_size": e["effect_size"],
                        "variance": e["variance"], "weight": round(w, 6)})

    result = MetaResult(
        model=model,
        pooled_effect=round(pooled, 4),
        ci95=ci,
        between_study_variance_tau2=round(tau2, 6) if tau2 is not None else None,
        weights=weights,
        i2=round(i2, 2),
        q=round(q, 4),
        q_p_value=round(q_p, 6),
    )

    if model == "random_effects" and tau2 is not None:
        # prediction interval: pooled ± t_{k-2,0.975} * sqrt(tau2 + var)
        t_df = df - 1
        t_crit = _t_critical(t_df) if t_df >= 1 else 1.96
        pi_se = sqrt((tau2 or 0.0) + var)
        result.prediction_interval = [round(pooled - t_crit * pi_se, 4),
                                      round(pooled + t_crit * pi_se, 4)]
    return result


def _t_critical(df: float) -> float:
    """Approximate two-tailed t_{df,0.975} (normal-mixing approximation)."""
    import math
    if df >= 30:
        return 1.96
    # Abramowitz-Stegun 26.7.5 (slightly conservative)
    a = 1.0 / (1.0 + df)
    return 1.96 * math.exp(0.33 * a * (1.0 + 0.3 * a))


def can_pool(effects: list[dict], min_studies: int = 2, i2_ceiling: float = 75.0) -> tuple[bool, str]:
    """Decision gate: is quantitative pooling admissible?

    Returns (admissible, reason). I2 ceiling default 75% (SKILL.md §条件化合并);
    exceeding it forces narrative synthesis (or random-effects + explicit caveat).
    """
    if not effects or len(effects) < min_studies:
        return False, f"fewer than {min_studies} poolable studies"
    try:
        fe_pooled, _ = _inverse_variance_pool(effects)
        df = len(effects) - 1
        q = sum((e["effect_size"] - fe_pooled) ** 2 / e["variance"] for e in effects)
        i2 = max(0.0, (q - df) / q * 100.0) if q > 0 else 0.0
        if i2 > i2_ceiling:
            return False, f"I2={i2:.1f}% exceeds ceiling {i2_ceiling}%"
        return True, f"admissible (I2={i2:.1f}%)"
    except MesError:
        return False, "pooling not admissible"
