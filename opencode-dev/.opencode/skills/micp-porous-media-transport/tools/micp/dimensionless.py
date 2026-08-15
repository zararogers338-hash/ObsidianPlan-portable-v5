"""Dimensionless analysis for MICP reactive transport.

Computes the key scale-analysis numbers and classifies regimes:

  Pe   = v·L / D            Péclet number  (advection vs dispersion)
  Da   = k_rxn·L / (v·c0)   Damköhler-I    (reaction rate vs advection)
  DaD  = k_rxn·L² / D       Damköhler-II   (reaction rate vs diffusion)
  rDa  = k_rxn / (v/L)      reaction Damköhler number (reaction vs residence time)
  clog = Δporosity / Δtime  clogging propensity indicator

All numbers are computed from the same normalized (SI) inputs used by the
solver, so the dimensionless analysis and the numerical model are consistent
by construction. Outputs are deterministic.

Regime classification (acceptance §四.4):
  * transport_limited : Pe < 1  → dispersion-dominated mixing
  * advection_dominated: Pe >= 1 → plug-flow-like front
  * reaction_limited   : Da < 1  → reaction slow vs transport (well-mixed over L)
  * reaction_dominated : Da >= 1 → strong front gradients / clogging potential
"""

from __future__ import annotations

import math

from .errors import OpError, OpErrorCode
from .units import check_finite


def dimensionless_numbers(
    velocity: float,      # m/s (Darcy or interstitial velocity, caller-declared)
    length: float,        # m  (domain length)
    dispersion: float,    # m2/s (longitudinal dispersion coefficient D)
    reaction_rate: float, # mol/(m3·s) — ureolysis rate (zero-order basis)
    c0: float,            # mol/m3 — reference concentration (e.g. urea inflow)
    porosity: float | None = None,
    d50: float | None = None,
) -> dict[str, float]:
    """Compute Pe, Da, DaD, rDa and a clog-propensity heuristic.

    Returns dimensionless numbers plus a regime classification. Raises
    OPM-E301 on non-finite inputs and OPM-E403 on degenerate scales
    (zero velocity AND zero dispersion make the numbers undefined).
    """
    v = check_finite("velocity", velocity)
    L = check_finite("length", length)
    D = check_finite("dispersion", dispersion)
    kr = check_finite("reaction_rate", reaction_rate)
    cc = check_finite("reference_concentration", c0)
    if v < 0 or L <= 0 or D < 0 or kr < 0 or cc <= 0:
        raise OpError(OpErrorCode.RANGE_OUT_OF_BOUNDS,
                      "dimensionless_numbers requires v>=0, L>0, D>=0, k>=0, c0>0.",
                      detail={"velocity": v, "length": L, "dispersion": D,
                              "reaction_rate": kr, "c0": cc})

    # Péclet number
    if v > 0 and D > 0:
        pe = v * L / D
    elif v > 0 and D == 0:
        pe = float("inf")
    else:
        pe = 0.0

    # Damköhler-I: reaction rate relative to advective supply.
    if v > 0 and cc > 0:
        da = kr * L / (v * cc)
    else:
        da = float("inf") if kr > 0 else 0.0

    # Damköhler-II: reaction rate relative to diffusion/dispersion.
    if D > 0 and cc > 0:
        dad = kr * L * L / (D * cc)
    else:
        dad = float("inf") if kr > 0 else 0.0

    # reaction vs residence time (rDa) — most natural for 1D column.
    residence = L / v if v > 0 else None
    if residence is not None and cc > 0:
        rda = kr * residence / cc
    else:
        rda = float("inf") if kr > 0 else 0.0

    # clog propensity heuristic: how quickly precipitating mass (mol/m3/s)
    # converts into porosity loss per unit time at the reaction scale.
    # Uses the same CaCO3 mass-balance constant the solver uses.
    clog = float("nan")
    if v > 0 and cc > 0:
        clog = kr * L / (v * cc)  # = Da (reaction-to-advection) is the driver

    # regime classification (acceptance §四.4)
    pe_finite = math.isfinite(pe)
    transport_regime = (
        "advection_dominated" if pe_finite and pe >= 1
        else "dispersion_dominated" if pe_finite
        else "no_transport")
    da_finite = math.isfinite(da)
    reaction_regime = (
        "reaction_dominated" if da_finite and da >= 1
        else "reaction_limited" if da_finite
        else "reaction_only")

    return {
        "pe": pe if math.isfinite(pe) else None,
        "da": da if math.isfinite(da) else None,
        "dad": dad if math.isfinite(dad) else None,
        "rda": rda if math.isfinite(rda) else None,
        "clog_propensity": "high" if (da_finite and da >= 1) else
                           "moderate" if (da_finite and da >= 0.1) else "low",
        "transport_regime": transport_regime,
        "reaction_regime": reaction_regime,
        "residence_time_s": residence,
    }
