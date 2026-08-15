"""Clogging criteria and permeability-evolution module.

Defines the thresholds and rules the skill uses to declare a column "clogged"
or to rank scenarios by clogging propensity. These are engineering criteria
backed by the Kozeny-Carman relation in solver.py and by the literature in
references/sources.md (a factor-of-ten permeability drop is the common MICP
practical limit; porosity loss depends on initial porosity).

All functions are pure, deterministic, and offline.
"""

from __future__ import annotations

import math
from typing import Any

from .errors import OpError, OpErrorCode


class ClogCriteria:
    """Configurable clogging thresholds with documented defaults.

    Attributes
    ----------
    porosity_min : float
        Stop/signal when porosity anywhere falls below this (default 0.02).
    permeability_ratio : float
        Signal when K/K0 anywhere falls below this (default 1e-2).
    """

    def __init__(self, porosity_min: float = 0.02,
                 permeability_ratio: float = 1e-2) -> None:
        if not (0.0 < porosity_min < 1.0):
            raise OpError(OpErrorCode.RANGE_OUT_OF_BOUNDS,
                          "porosity_min must be in (0,1).", detail={"porosity_min": porosity_min})
        if not (0.0 < permeability_ratio <= 1.0):
            raise OpError(OpErrorCode.RANGE_OUT_OF_BOUNDS,
                          "permeability_ratio must be in (0,1].", detail={"permeability_ratio": permeability_ratio})
        self.porosity_min = porosity_min
        self.permeability_ratio = permeability_ratio

    def evaluate(self, porosity: list[float], permeability: list[float],
                 permeability0: float) -> dict[str, Any]:
        """Evaluate clogging status on final-node arrays.

        Returns
        -------
        dict with keys:
          clogged            bool
          reason             str
          porosity_min       float
          porosity_loss_max  float  (fraction of initial porosity lost)
          perm_ratio_min     float  (min K/K0)
          rule_hit           str    ("porosity" | "permeability" | "none")
          warnings           list[str]
        """
        if not porosity or not permeability:
            raise OpError(OpErrorCode.INPUT_SCHEMA_VIOLATION,
                          "clogging.evaluate requires non-empty arrays.")
        if permeability0 <= 0:
            raise OpError(OpErrorCode.RANGE_OUT_OF_BOUNDS,
                          "permeability0 must be > 0.", detail={"permeability0": permeability0})

        pmin = min(porosity)
        ratios = [k / permeability0 for k in permeability]
        rmin = min(ratios)
        warnings: list[str] = []

        if pmin < self.porosity_min:
            rule = "porosity"
            reason = (f"porosity fell to {pmin:.4g} < {self.porosity_min} "
                      f"(clogging threshold)")
        elif rmin < self.permeability_ratio:
            rule = "permeability"
            reason = (f"K/K0 fell to {rmin:.3g} < {self.permeability_ratio} "
                      f"(practical permeability-limit threshold)")
        else:
            rule = "none"
            reason = "no clogging criterion triggered"

        if pmin < 0.05:
            warnings.append(
                f"porosity {pmin:.3g} < 0.05: near-zero effective porosity; "
                "continuum (Darcy) assumption is breaking down — treat results "
                "as qualitative beyond this point.")

        return {
            "clogged": rule != "none",
            "reason": reason,
            "porosity_min": float(pmin),
            "porosity_loss_max": float(1.0 - pmin),
            "perm_ratio_min": float(rmin),
            "rule_hit": rule,
            "warnings": warnings,
        }


def clogging_propensity(dimensionless: dict[str, Any]) -> str:
    """Rank clogging propensity from the dimensionless-analysis output."""
    da = dimensionless.get("da")
    if da is None:
        return "unknown"
    if da >= 1.0:
        return "high"
    if da >= 0.1:
        return "moderate"
    return "low"


def permeability_reduction_factor(k_perm: float, k0: float) -> float:
    """K/K0; NaN-safe."""
    if k0 <= 0 or not math.isfinite(k_perm):
        return float("nan")
    return k_perm / k0


def estimate_permeability_drop(phi: float, phi0: float) -> float:
    """Kozeny-Carman drop factor K/K0 for a given porosity pair.

    Used for quick "what-if" checks without running the solver.
    """
    if phi0 <= 0 or phi >= 1 or phi <= 0:
        return float("nan")
    r = phi / phi0
    return r**3 * ((1.0 - phi0) / (1.0 - phi)) ** 2
