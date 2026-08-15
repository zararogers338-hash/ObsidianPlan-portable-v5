"""Effect-size computation from study arms (OES-E111 guards inside).

Computes, per evidence card with two arms:
  - mean difference (raw units, converted to a common unit when comparable)
  - Cohen's d (unbiased sample sd pooled)
  - Hedges' g (small-sample bias correction, recommended for meta-analysis)

Only cards with two arms carrying n, mean, sd are poolable. Single-arm cards
carry no stand-alone effect and are excluded from pooling (their raw outcome is
still reported in the evidence matrix). All numeric inputs are checked for
non-finite values, negative sd, and n < 1.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import sqrt
from typing import Optional

from .errors import MesError, MesErrorCode
from .unit_map import comparable_unit, convert


@dataclass
class Effect:
    ref_id: str
    effect_type: str                 # 'mean_difference' | 'smd'
    effect_size: float
    variance: float
    ci95_low: Optional[float] = None
    ci95_high: Optional[float] = None
    unit: Optional[str] = None
    weight_note: str = ""            # e.g. unit-conversion or correction applied
    poolable: bool = True


def _check_finite(value, label: str) -> None:
    if value != value or value in (float("inf"), float("-inf")):
        raise MesError(MesErrorCode.NUMERIC_INVALID, f"{label} is non-finite")
    if value is not None and value < 0 and label.endswith("sd"):
        raise MesError(MesErrorCode.NUMERIC_INVALID, f"{label} must be non-negative")


def _bias_correction(df: float) -> float:
    """Hedges correction factor J = 1 - 3/(4*df - 1)."""
    return 1.0 - 3.0 / (4.0 * df - 1.0)


def _pooled_sd(sd1: float, n1: int, sd2: float, n2: int) -> float:
    var = ((n1 - 1) * sd1 * sd1 + (n2 - 1) * sd2 * sd2) / (n1 + n2 - 2)
    return sqrt(var)


def compute_effect(ref_id: str, arms: list, target_unit: Optional[str] = None,
                   bias_correction: bool = True) -> Optional[Effect]:
    """Compute an effect from a two-arm list.

    Returns None when the card cannot be pooled (missing/insufficient data or
    non-comparable units). Raises MesError on non-finite or negative sd/n.
    """
    if not isinstance(arms, list) or len(arms) != 2:
        return None
    try:
        # find treatment & control by conventional names (else order)
        name0 = (arms[0].get("name") or "").lower()
        name1 = (arms[1].get("name") or "").lower()
        def _is_treatment(n: str) -> bool:
            return any(k in n for k in ("trea", "mics", "micp", "bio", "treated", "eicp", "experiment"))
        def _is_control(n: str) -> bool:
            return any(k in n for k in ("contr", "untreated", "untreat", "water", "control", "blank"))
        if _is_treatment(name0) and _is_control(name1):
            tr, ct = arms[0], arms[1]
        elif _is_treatment(name1) and _is_control(name0):
            tr, ct = arms[1], arms[0]
        else:
            tr, ct = arms[0], arms[1]

        n_tr = tr.get("n"); m_tr = tr.get("mean"); sd_tr = tr.get("sd")
        n_ct = ct.get("n"); m_ct = ct.get("mean"); sd_ct = ct.get("sd")
        u_tr = tr.get("unit"); u_ct = ct.get("unit")
        for lbl, val in (("n_tr", n_tr), ("m_tr", m_tr), ("sd_tr", sd_tr),
                         ("n_ct", n_ct), ("m_ct", m_ct), ("sd_ct", sd_ct)):
            if val is None:
                return None
        for lbl, val in (("n_tr", n_tr), ("n_ct", n_ct)):
            if val < 1 or val != int(val):
                raise MesError(MesErrorCode.NUMERIC_INVALID, f"{lbl} must be a positive integer, got {val}")
        for lbl, val in (("sd_tr", sd_tr), ("sd_ct", sd_ct)):
            _check_finite(val, lbl)
            if val < 0:
                raise MesError(MesErrorCode.NUMERIC_INVALID, f"{lbl} must be non-negative")
        for lbl, val in (("m_tr", m_tr), ("m_ct", m_ct)):
            _check_finite(val, lbl)

        # unit harmonization for mean difference
        unit = u_tr or u_ct
        md_unit = unit
        md = m_tr - m_ct
        if u_tr and u_ct and comparable_unit(u_tr, u_ct):
            if u_tr != u_ct:
                m_ct_harm = convert(m_ct, u_ct, u_tr)
                if m_ct_harm is not None:
                    md = m_tr - m_ct_harm
                    md_unit = u_tr
        # if units not comparable, we cannot form a meaningful difference
        if u_tr and u_ct and not comparable_unit(u_tr, u_ct):
            return None

        n_tr_i, n_ct_i = int(n_tr), int(n_ct)
        pooled = _pooled_sd(sd_tr, n_tr_i, sd_ct, n_ct_i)
        if pooled == 0:
            raise MesError(MesErrorCode.NUMERIC_INVALID, f"card {ref_id}: zero pooled sd — degenerate effect")

        d = md / pooled
        J = _bias_correction(n_tr_i + n_ct_i - 2) if bias_correction else 1.0
        g = d * J
        # variance of g (Hedges & Olkin)
        var = (1.0 / n_tr_i + 1.0 / n_ct_i + g * g / (2 * (n_tr_i + n_ct_i))) * J * J
        z = 1.959964
        se = sqrt(var)
        # mean-difference variance uses original units
        md_var = pooled * pooled * (1.0 / n_tr_i + 1.0 / n_ct_i)
        md_se = sqrt(md_var)

        return Effect(
            ref_id=ref_id,
            effect_type="smd",
            effect_size=round(g, 4),
            variance=round(var, 6),
            ci95_low=round(g - z * se, 4),
            ci95_high=round(g + z * se, 4),
            weight_note="hedges_g" if bias_correction else "cohen_d",
            poolable=True,
        )
    except MesError:
        raise
    except Exception as exc:  # defensive: data-shape issues -> not poolable
        raise MesError(MesErrorCode.NUMERIC_INVALID,
                       f"card {ref_id}: could not compute effect: {exc}") from exc


def effect_from_outcome(ref_id: str, outcome: dict) -> Optional[dict]:
    """Stand-alone reported effect (no arms): reported only, never pooled.

    Returns a dict for the evidence matrix, or None if not numeric.
    """
    if not isinstance(outcome, dict):
        return None
    value = outcome.get("value")
    unit = outcome.get("unit")
    if value is None or not isinstance(value, (int, float)):
        return None
    return {"ref_id": ref_id, "effect_type": "raw_value", "effect_size": value,
            "unit": unit, "poolable": False}
