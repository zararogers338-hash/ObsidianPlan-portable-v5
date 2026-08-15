"""MUC kinetics — urease-catalyzed urea hydrolysis kinetics.

Two-regime empirical model of urease kinetics (S26, Fidaleo & Lavecchia 2003;
S25, Krajewska 2018):

  1. First-order regime:  -d[urea]/dt = k1 [urea]   (low [urea])
  2. Zero-order regime:   -d[urea]/dt = Vmax         (saturating [urea])

The transition is governed by a half-saturation concentration KM, giving the
Michaelis-Menten form:

    v = Vmax * [urea] / (KM + [urea])

with optional substrate inhibition (Haldane):
    v = Vmax * [urea] / (KM + [urea] + [urea]^2/Ki)

Vmax depends on urease activity and amount: Vmax = A_urease * [urease], where
A_urease is the specific activity. In MICP literature (S27 Whiffin et al.), the
urease activity is often reported as mmol urea hydrolyzed / L / min per unit
bacterial/urease concentration; we parametrize by:
    Vmax [mol/L/s] = a0 * U,  where U is the urease concentration in standard
    units (U/L, 1 U = 1 umol urea/min at 25 °C, pH 7).

This yields a directly interpretable parameter for lab calibration: a0 converts
urease activity units to mol/(L·s). For a batch ureolysis-only study we also
support the simpler first-order decay with rate constant k (per second).

pH dependence: urease activity peaks near pH 7–8 and drops at high pH; we
apply an optional bell-shaped pH factor (flag when used). Default: no pH
factor (activity reported at the operating pH), matching how MICP kinetics
constants are normally fitted.

Temperature dependence (optional): Arrhenius factor with Ea ~ 44 kJ/mol
typical for urease (S25). Applied only when t_k is given and the user asks.
"""

from __future__ import annotations

import math

from .errors import MUCError

# Typical Arrhenius activation energy for urease-catalyzed urea hydrolysis,
# kJ/mol (S25). Used only when temperature scaling is requested.
UREASE_EA_KJ = 44.0
UREASE_EA_J = UREASE_EA_KJ * 1000.0
R_GAS = 8.314462618


def mm_rate(
    *,
    urea_conc: float,  # mol/L
    vmax: float,  # mol/L/s
    km: float,  # mol/L
    ki: float | None = None,  # mol/L (Haldane substrate inhibition)
) -> float:
    """Michaelis-Menten (optionally Haldane-inhibited) hydrolysis rate, mol/L/s."""
    if urea_conc < 0:
        raise MUCError("MUC-E2004", f"mm_rate: negative urea concentration {urea_conc}")
    if vmax <= 0:
        raise MUCError("MUC-E2004", f"mm_rate: vmax must be > 0, got {vmax}")
    if km <= 0:
        raise MUCError("MUC-E2004", f"mm_rate: km must be > 0, got {km}")
    denom = km + urea_conc
    if ki is not None:
        if ki <= 0:
            raise MUCError("MUC-E2004", f"mm_rate: ki must be > 0, got {ki}")
        denom += urea_conc * urea_conc / ki
    return vmax * urea_conc / denom


def vmax_from_urease(
    *,
    urease_units_per_L: float,  # U/L (1 U = 1 umol urea/min at 25 °C)
    a0: float = 1.0,  # conversion factor, mol/(L·s) per U/L
) -> float:
    """Convert urease activity (U/L) to a Vmax in mol/L/s."""
    # 1 U = 1 umol/min = 1e-6 mol/60 s = 1.667e-8 mol/s
    return urease_units_per_L * 1.667e-8 * a0


def arrhenius_factor(t_k: float) -> float:
    """Relative activity vs 25 °C (298.15 K) via Arrhenius with UREASE_EA."""
    if t_k <= 0:
        raise MUCError("MUC-E2004", f"arrhenius_factor: invalid T {t_k}")
    return math.exp(-(UREASE_EA_J / R_GAS) * (1.0 / t_k - 1.0 / 298.15))


def ph_factor(pH: float, *, ph_opt: float = 7.5, sigma: float = 1.2) -> float:
    """Optional bell-shaped pH dependence of urease activity (empirical).

    Activity is 1 at pH_opt and decays as exp(-(pH-pH_opt)^2 / (2 sigma^2)).
    Used only when the user requests pH-dependent kinetics; otherwise the
    fitted Vmax is assumed to already reflect operating conditions.
    """
    return math.exp(-((pH - ph_opt) ** 2) / (2.0 * sigma * sigma))


def first_order_rate(urea_conc: float, k: float) -> float:
    """First-order hydrolysis rate: k [urea], mol/L/s."""
    if k <= 0:
        raise MUCError("MUC-E2004", f"first_order_rate: k must be > 0, got {k}")
    return k * urea_conc
