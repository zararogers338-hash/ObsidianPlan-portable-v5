"""Tracer breakthrough analysis for scale-up validation.

Given a normalized tracer breakthrough curve (time_s, conc) and the injected
concentration, estimates:
  - mean residence time (first moment) and pore volume
  - Peclet number from the width of the breakthrough curve (axial dispersion)
  - recovered mass fraction (mass balance of the tracer)
  - a verdict on flow bypass / dead zones: early breakthrough or low recovery
    indicates preferential flow or trapped volume.

No fabricated data: the tracer arrays come from the caller; this module only
analyzes what it is given.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from .errors import OpError, OpErrorCode
from .units import check_finite


@dataclass
class TracerAnalysis:
    recovered_fraction: float
    mean_residence_time_s: float
    peak_time_s: float
    peclet_number: float | None
    early_breakthrough: bool
    low_recovery: bool
    verdict: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "recovered_fraction": self.recovered_fraction,
            "mean_residence_time_s": self.mean_residence_time_s,
            "peak_time_s": self.peak_time_s,
            "peclet_number": self.peclet_number,
            "early_breakthrough": self.early_breakthrough,
            "low_recovery": self.low_recovery,
            "verdict": self.verdict,
        }


def tracer_analysis(raw_tracer: dict[str, Any]) -> TracerAnalysis:
    if not raw_tracer or not isinstance(raw_tracer, dict):
        raise OpError(OpErrorCode.MISSING_REQUIRED_FIELD,
                      "tracer analysis requires tracer.time_s and tracer.conc arrays.",
                      detail={"missing_fields": [{
                          "field": "tracer.time_s / tracer.conc",
                          "why_critical": "breakthrough curve is the input to transport analysis",
                          "how_to_obtain": "run a tracer (e.g. NaCl or fluorescent) pulse and "
                                           "record breakthrough at monitoring points"}]})
    t = raw_tracer.get("time_s")
    c = raw_tracer.get("conc")
    c0 = raw_tracer.get("injected_conc")
    if not isinstance(t, list) or not isinstance(c, list) or len(t) != len(c) or len(t) < 2:
        raise OpError(OpErrorCode.INVALID_SCENARIO,
                      "tracer.time_s and tracer.conc must be equal-length arrays (>= 2).",
                      detail={"n_time": len(t) if isinstance(t, list) else None,
                              "n_conc": len(c) if isinstance(c, list) else None})
    if c0 is None:
        raise OpError(OpErrorCode.MISSING_REQUIRED_FIELD,
                      "tracer requires injected_conc.",
                      detail={"missing_fields": [{
                          "field": "tracer.injected_conc",
                          "why_critical": "recovery fraction = integral(c)/integral(c0)",
                          "how_to_obtain": "record the injected tracer concentration"}]})

    t = [check_finite("tracer.time_s[i]", float(x)) for x in t]
    c = [check_finite("tracer.conc[i]", float(x)) for x in c]
    c0 = check_finite("tracer.injected_conc", float(c0))

    # trapezoidal moments
    n = len(t)
    m0 = sum((t[i] - t[i - 1]) * (c[i] + c[i - 1]) / 2.0 for i in range(1, n))
    m1 = sum((t[i] - t[i - 1]) * (t[i] * c[i] + t[i - 1] * c[i - 1]) / 2.0 for i in range(1, n))
    recovered = m0 / (c0 * (t[-1] - t[0])) if (c0 > 0 and t[-1] != t[0]) else math.nan
    mrt = m1 / m0 if m0 > 0 else math.nan
    peak_idx = max(range(n), key=lambda i: c[i])
    peak_t = t[peak_idx]

    # Peclet from variance of breakthrough: sigma_t^2 = 2 (D/v^2) * ... For an
    # approximate 1D response, Pe ~ 2 * (mrt / sigma_t)^2 (unit-step basis).
    peclet = None
    if mrt and mrt > 0 and m0 > 0:
        sigma2 = sum((t[i] - t[i - 1]) * ((t[i] - mrt) ** 2 * c[i] + (t[i - 1] - mrt) ** 2 * c[i - 1]) / 2.0
                     for i in range(1, n)) / m0
        if sigma2 > 0:
            peclet = 2.0 * mrt ** 2 / sigma2

    early = False
    if s := raw_tracer.get("distance_m"):
        s = check_finite("tracer.distance_m", float(s))
        if peclet and peclet is not None:
            early = peclet < 5.0  # very high dispersion -> suspected bypass
    low_recovery = recovered < 0.7
    if not math.isfinite(recovered):
        recovered = None
    if recovered is None:
        verdict = "tracer recovery could not be computed (zero injected concentration " \
                  "or zero area under curve) — cannot assess flow bypass"
    elif recovered > 1.05:
        verdict = "recovery > 105% — check tracer mass balance (possible tail integration)"
    elif low_recovery:
        verdict = ("low tracer recovery and/or high dispersion: flow bypass / trapped "
                   "zones suspected — site-scale heterogeneity confirmed")
    else:
        verdict = "tracer mass balance acceptable; transport moderately dispersive"

    return TracerAnalysis(
        recovered_fraction=round(recovered, 4) if recovered is not None else None,
        mean_residence_time_s=round(mrt, 2) if math.isfinite(mrt) else None,
        peak_time_s=round(peak_t, 2),
        peclet_number=round(peclet, 2) if peclet is not None else None,
        early_breakthrough=early,
        low_recovery=bool(low_recovery),
        verdict=verdict,
    )
