"""MUC speciation — carbonate equilibrium, pH, and saturation index.

Solves the closed-system carbonate equilibrium at a fixed total inorganic
carbon (CT) and total calcium, given pH, or solves for pH given alkalinity.
The system is the standard four-reaction carbonate model with activity
corrections (Davies) applied via Newton iteration on the master variable.

Reactions (equilibrium constants from constants.py, T-corrected):
  CO2(aq) + H2O <-> H+ + HCO3-            Ka1
  HCO3-      <-> H+ + CO3 2-             Ka2
  H2O        <-> H+ + OH-                 Kw
  CaCO3(s)   <-> Ca2+ + CO3 2-           Ksp_calcite

Master-variable solve: given pH, compute speciation directly (closed form).
Given alkalinity instead, solve for pH by root-finding on the charge balance.
Saturation index SI = log10( IAP / Ksp ), IAP = {Ca2+}{CO3 2-} (activities).
"""

from __future__ import annotations

import math

from . import constants as C
from .activity import activity_coefficient, ionic_strength_from_concs
from .errors import MUCError

MASS_BALANCE_REL_TOL = 1e-9


def _alpha_factors(h: float, ka1: float, ka2: float) -> tuple[float, float, float]:
    """Dissociation fractions alpha0 (CO2), alpha1 (HCO3), alpha2 (CO3)."""
    d = h * h + ka1 * h + ka1 * ka2
    return h * h / d, ka1 * h / d, ka1 * ka2 / d


def speciate_at_ph(
    *,
    pH: float,
    c_total: float,  # mol/L total inorganic carbon
    ca_total: float,  # mol/L total calcium (dissolved, before precipitation)
    t_k: float = 298.15,
    mg_total: float = 0.0,
    nh4_total: float = 0.0,
    cl_total: float = 0.0,
    na_total: float = 0.0,
) -> dict:
    """Speciate the carbonate system at fixed pH.

    Returns a dict with all species concentrations (mol/L), activities,
    saturation index, ionic strength, and carbonate-alkalinity breakdown.
    """
    if not (0 <= pH <= 14):
        raise MUCError("MUC-E2004", f"speciate_at_ph: pH {pH} out of range [0,14]")
    for nm, v in (("c_total", c_total), ("ca_total", ca_total), ("mg_total", mg_total), ("nh4_total", nh4_total)):
        if v < 0 or not math.isfinite(v):
            raise MUCError("MUC-E2004", f"speciate_at_ph: {nm} must be finite and >= 0, got {v!r}")

    eq = C.equilibrium_constants(t_k)
    h = 10.0 ** -pH
    a0, a1, a2 = _alpha_factors(h, eq["ka1"], eq["ka2"])

    co2 = c_total * a0
    hco3 = c_total * a1
    co3 = c_total * a2
    oh = eq["kw"] / h
    ca = ca_total
    mg = mg_total
    nh4 = nh4_total * h / (h + eq["ka_nh4"])
    nh3 = nh4_total - nh4

    # Ionic strength from the major charged species (mol/L). Computed from the
    # dissolved species present; it feeds back into activities used for SI.
    I = _compute_ionic_strength(
        h, oh, ca, mg, nh4, co3, hco3, cl_total, na_total
    )

    gam_ca = activity_coefficient("Ca2+", I, t_k)
    gam_co3 = activity_coefficient("CO3 2-", I, t_k)
    iap = (gam_ca * ca) * (gam_co3 * co3)
    si = math.log10(iap / eq["ksp_calcite"]) if iap > 0 else float("-inf")

    # Carbonate alkalinity (equiv/L): [HCO3-] + 2[CO3 2-] + [OH-] - [H+]
    alk = hco3 + 2 * co3 + oh - h

    return {
        "ph": pH,
        "t_k": t_k,
        "speciation": {
            "CO2(aq)": co2,
            "HCO3-": hco3,
            "CO3 2-": co3,
            "Ca2+": ca,
            "Mg2+": mg,
            "OH-": oh,
            "H+": h,
            "NH4+": nh4,
            "NH3(aq)": nh3,
        },
        "ionic_strength": I,
        "carbonate_alkalinity_eq_L": alk,
        "iap_calcite": iap,
        "si_calcite": si,
        "log_ksp_calcite": eq["log_ksp_calcite"],
    }


def _compute_ionic_strength(
    h: float, oh: float, ca: float, mg: float, nh4: float, co3: float, hco3: float, cl: float, na: float
) -> float:
    """Ionic strength from major charged species (mol/L)."""
    return 0.5 * (
        h * 1
        + oh * 1
        + ca * 4
        + mg * 4
        + nh4 * 1
        + co3 * 4
        + hco3 * 1
        + cl * 1
        + na * 1
    )


def alkalinity_to_pH(
    *,
    alkalinity_eq_L: float,
    c_total: float,
    ca_total: float = 0.0,
    t_k: float = 298.15,
    mg_total: float = 0.0,
    nh4_total: float = 0.0,
) -> dict:
    """Solve for pH given total alkalinity (carbonate + borate-free system).

    Root-finds pH so that Alk(pH) == alkalinity_eq_L. Returns the same dict as
    speciate_at_ph plus `pH`.
    """
    eq = C.equilibrium_constants(t_k)

    def alk_at(h: float) -> float:
        a0, a1, a2 = _alpha_factors(h, eq["ka1"], eq["ka2"])
        hco3 = c_total * a1
        co3 = c_total * a2
        oh = eq["kw"] / h
        return hco3 + 2 * co3 + oh - h

    # Bracketing search on pH in [0,14].
    def f(pH: float) -> float:
        return alk_at(10.0 ** -pH) - alkalinity_eq_L

    lo, hi = 0.0, 14.0
    flo, fhi = f(lo), f(hi)
    if flo * fhi > 0:
        raise MUCError(
            "MUC-E2001",
            f"alkalinity_to_pH: no pH in [0,14] gives Alk={alkalinity_eq_L} eq/L "
            f"(f(0)={flo:.4g}, f(14)={fhi:.4g})",
        )
    for _ in range(200):
        mid = 0.5 * (lo + hi)
        fm = f(mid)
        if abs(fm) < 1e-10:
            break
        if flo * fm <= 0:
            hi = mid
            fhi = fm
        else:
            lo = mid
            flo = fm
    pH = 0.5 * (lo + hi)
    return speciate_at_ph(
        pH=pH,
        c_total=c_total,
        ca_total=ca_total,
        t_k=t_k,
        mg_total=mg_total,
        nh4_total=nh4_total,
    )


def closed_system_ph(
    *,
    c_total: float,
    alkalinity_eq_L: float,
    t_k: float = 298.15,
    ca_total: float = 0.0,
) -> dict:
    """Convenience wrapper: closed-system carbonate pH from CT and Alk."""
    return alkalinity_to_pH(
        alkalinity_eq_L=alkalinity_eq_L,
        c_total=c_total,
        ca_total=ca_total,
        t_k=t_k,
    )
