"""MUC simulate — coupled time-dependent ureolysis + carbonate + precipitation.

This is the *kinetic* model (not an equilibrium shortcut). It integrates the
closed-batch ODE system for a cementation fluid / pore volume:

  d[urea]/dt      = -v_hydrolysis
  d[NH3_tot]/dt   =  +2 v_hydrolysis
  d[CT]/dt        =  +v_hydrolysis            (total inorganic carbon)
  d[Ca2+]/dt      =  -v_precip                (dissolved Ca loss to solid)
  d[CaCO3(s)]/dt  =  +v_precip

where:
  v_hydrolysis = Michaelis-Menten (or first-order) ureolysis rate
  v_precip     = precipitation rate law, applied only when SI > SI_threshold.

The carbonate system is re-speciated at every step from (CT, NH3_tot, Ca2+,
fixed Cl, temperature) using the closed-system carbonate equilibrium — i.e.,
the ODE advances mass, and speciation is the equilibrium *closure* that yields
pH, SI, and species distribution at each time. This is the standard MICP
batch-model architecture (S28, Morse et al.; S32, PWP rate law family).

Precipitation rate law (flagged: MUST be calibrated — see references S28):
    v_precip = k_precip * A_specific * (Omega - 1)     for Omega > 1
    Omega = IAP/Ksp = 10^SI.
  k_precip   : precipitation rate constant (mol/m^2/s), literature range
               1e-10..1e-8 for calcite (S28)
  A_specific : reactive surface area per volume (m^2/L)
These are model parameters; the skill labels their use as CALCULATED with a
parameter-source note, never as OBSERVED values.

The output separates:
  - equilibrium precipitateable amount  (mass-balance bound: min(Ca, C) that can
    precipitate at SI=1)
  - finite-time actual precipitated amount (from the kinetic integration)
so the skill never conflates "SI > 1" with "CaCO3 was produced" (spec §4.6/§9.4).
"""

from __future__ import annotations

import math

from . import constants as C
from .balance import check_ureolysis_stoichiometry
from .errors import MUCError
from .kinetics import mm_rate
from .speciate import alkalinity_to_pH

# Default integration parameters
_DEFAULT_DT = 60.0  # s
_DEFAULT_NSTEPS = 1441  # 1 day at 60 s
_DEFAULT_T = 86400.0  # s (1 day)


def _speciate_step(
    *,
    urea: float,
    nh3_tot: float,
    ct: float,
    ca: float,
    cl: float,
    t_k: float,
    mg: float = 0.0,
) -> dict:
    """Equilibrium closure at a given mass state: return pH, SI, species.

    NH3_tot = [NH4+] + [NH3(aq)]; total ammonia is consumed as an alkalinity
    contributor through its acid/base pair, so we pass it to the carbonate
    solve as a component that shifts the proton balance.
    """
    # Total alkalinity in the closed system: carbonate alkalinity + ammonia
    # contribution (NH3(aq) acts as base). We solve the carbonate system at the
    # charge-balance level: the alkalinity seen by the carbonate equilibria is
    # the *total* alkalinity minus the NH3 term. For a batch ureolysis model the
    # rigorous formulation uses the proton balance; here we use the standard
    # approximation that the ammonia pair contributes an alkalinity of
    # [NH3(aq)] (base form), i.e. Alk_total = Alk_carb + [NH3(aq)].
    # Because pH is what we need, we solve:  pH s.t.  CarbAlk(pH) = Alk_total - NH3_base(pH)
    eq = C.equilibrium_constants(t_k)
    ka_nh4 = eq["ka_nh4"]

    # Closed-system closure is the charge balance over all species:
    #   [H+] + 2[Ca2+] + [NH4+] = [OH-] + [HCO3-] + 2[CO3 2-] + [Cl-]
    # Solve for pH from that (physically correct; total alkalinity is NOT
    # conserved once precipitation removes carbonate).
    def charge_residual(pH: float) -> float:
        h = 10.0**-pH
        a0, a1, a2 = _alpha(h, eq["ka1"], eq["ka2"])
        hco3 = ct * a1
        co3 = ct * a2
        oh = eq["kw"] / h
        nh4 = nh3_tot * h / (h + ka_nh4)
        lhs = h + 2.0 * ca + nh4  # + Na+ (not tracked) + Mg2+
        rhs = oh + hco3 + 2.0 * co3 + cl
        return lhs - rhs

    lo, hi = 2.0, 13.0
    flo, fhi = charge_residual(lo), charge_residual(hi)
    if flo * fhi > 0:
        # Extend the bracket for very dilute or very alkaline systems.
        lo, hi = 0.0, 14.0
        flo, fhi = charge_residual(lo), charge_residual(hi)
        if flo * fhi > 0:
            raise MUCError("MUC-E2001", "simulate: cannot bracket pH from charge balance")
    for _ in range(200):
        mid = 0.5 * (lo + hi)
        fm = charge_residual(mid)
        if abs(fm) < 1e-11:
            lo = hi = mid
            break
        if flo * fm <= 0:
            hi = mid
            fhi = fm
        else:
            lo = mid
            flo = fm
    pH = 0.5 * (lo + hi)
    h = 10.0**-pH
    a0, a1, a2 = _alpha(h, eq["ka1"], eq["ka2"])
    hco3 = ct * a1
    co3 = ct * a2
    oh = eq["kw"] / h
    nh4 = nh3_tot * h / (h + ka_nh4)
    nh3_aq = nh3_tot - nh4
    iap = ca * co3  # activity-corrected in the SI below
    from .activity import activity_coefficient

    I = 0.5 * (h + oh + 4 * ca + nh4 + 4 * co3 + hco3 + cl)
    gam_ca = activity_coefficient("Ca2+", I, t_k)
    gam_co3 = activity_coefficient("CO3 2-", I, t_k)
    iap_act = (gam_ca * ca) * (gam_co3 * co3)
    si = math.log10(iap_act / eq["ksp_calcite"]) if iap_act > 0 else float("-inf")
    return {
        "ph": pH,
        "si": si,
        "omega": 10.0**si,
        "hco3": hco3,
        "co3": co3,
        "co2": ct * a0,
        "nh4": nh4,
        "nh3": nh3_aq,
        "oh": oh,
        "ionic_strength": I,
    }


def _alpha(h: float, ka1: float, ka2: float) -> tuple[float, float, float]:
    d = h * h + ka1 * h + ka1 * ka2
    return h * h / d, ka1 * h / d, ka1 * ka2 / d


def simulate_batch(
    *,
    initial: dict,
    kinetics: dict,
    precipitation: dict,
    t_end_s: float = _DEFAULT_T,
    dt_s: float = _DEFAULT_DT,
    t_k: float = 298.15,
    cl: float = 0.0,
    mg: float = 0.0,
) -> dict:
    """Integrate the coupled batch model.

    initial keys (mol/L): urea, ca, ct, nh3_tot (all >= 0).
    kinetics keys: mode in ("mm","first"), vmax (mol/L/s), km (mol/L),
                   optional ki (mol/L), k (1/s) for first-order.
    precipitation keys: enabled (bool), k_precip (mol/m^2/s), a_specific
                   (m^2/L), si_threshold (default 1.0). When enabled=False the
                   run is an equilibrium-scenario run (no solid forms).

    Returns a dict with times, trajectories, final speciation, and the
    equilibrium-precipitateable vs kinetic-precipitated comparison.
    """
    urea0 = initial.get("urea", 0.0)
    ca0 = initial.get("ca", 0.0)
    ct0 = initial.get("ct", 0.0)
    nh3_0 = initial.get("nh3_tot", 0.0)
    for nm, v in (("urea", urea0), ("ca", ca0), ("ct", ct0), ("nh3_tot", nh3_0)):
        if v < 0 or not math.isfinite(v):
            raise MUCError("MUC-E2004", f"simulate_batch: initial.{nm} must be finite and >= 0")
    if t_end_s <= 0 or not math.isfinite(t_end_s):
        raise MUCError("MUC-E2004", f"simulate_batch: t_end_s must be > 0, got {t_end_s}")
    if dt_s <= 0 or not math.isfinite(dt_s):
        raise MUCError("MUC-E2004", f"simulate_batch: dt_s must be > 0, got {dt_s}")

    mode = kinetics.get("mode", "mm")
    if mode not in ("mm", "first"):
        raise MUCError("MUC-E1001", f"simulate_batch: kinetics.mode must be 'mm' or 'first', got {mode!r}")
    vmax = kinetics.get("vmax", 0.0)
    km = kinetics.get("km", 1e-6)
    ki = kinetics.get("ki")
    k_first = kinetics.get("k", 0.0)
    if mode == "mm" and vmax <= 0:
        raise MUCError("MUC-E1001", "simulate_batch: kinetics.vmax must be > 0 for mode 'mm'")
    if mode == "first" and k_first <= 0:
        raise MUCError("MUC-E1001", "simulate_batch: kinetics.k must be > 0 for mode 'first'")

    precip = precipitation.get("enabled", True)
    k_precip = precipitation.get("k_precip", 1e-9)  # mol/m^2/s
    a_spec = precipitation.get("a_specific", 10.0)  # m^2/L
    si_thr = precipitation.get("si_threshold", 1.0)
    if precip and k_precip <= 0:
        raise MUCError("MUC-E1001", "simulate_batch: precipitation.k_precip must be > 0")

    n = int(math.ceil(t_end_s / dt_s))
    times = [i * dt_s for i in range(n + 1)]
    urea = urea0
    ca = ca0
    ct = ct0
    nh3_tot = nh3_0
    solid = 0.0  # mol/L CaCO3(s)

    traj = {
        "t": times,
        "urea": [urea],
        "ca": [ca],
        "ct": [ct],
        "nh3_tot": [nh3_tot],
        "solid": [solid],
        "ph": [],
        "si": [],
    }

    # RK4 fixed-step integration.
    for i in range(n):
        def deriv(y: list[float]) -> list[float]:
            u, c_ca, c_ct, n_tot, s = y
            if mode == "mm":
                v_hyd = mm_rate(urea_conc=u, vmax=vmax, km=km, ki=ki)
            else:
                v_hyd = k_first * u
            # Precipitation rate (only when supersaturated past threshold).
            if precip:
                sp = _speciate_step(urea=u, nh3_tot=n_tot, ct=c_ct, ca=c_ca, cl=cl, t_k=t_k, mg=mg)
                si_now = sp["si"]
                if si_now > si_thr:
                    omega = 10.0**si_now
                    v_p = k_precip * a_spec * (omega - 1.0)  # mol/L/s
                    # Bound by available Ca (never precipitate more than present).
                    v_p = min(v_p, max(0.0, c_ca / dt_s))
                else:
                    v_p = 0.0
            else:
                v_p = 0.0
            return [-v_hyd, -v_p, v_hyd, 2.0 * v_hyd, v_p]

        y0 = [urea, ca, ct, nh3_tot, solid]
        k1 = deriv(y0)
        y1 = [y0[j] + 0.5 * dt_s * k1[j] for j in range(5)]
        k2 = deriv(y1)
        y2 = [y0[j] + 0.5 * dt_s * k2[j] for j in range(5)]
        k3 = deriv(y2)
        y3 = [y0[j] + dt_s * k3[j] for j in range(5)]
        k4 = deriv(y3)
        for j in range(5):
            y0[j] += dt_s / 6.0 * (k1[j] + 2.0 * k2[j] + 2.0 * k3[j] + k4[j])
            if y0[j] < 0 and abs(y0[j]) < 1e-12:
                y0[j] = 0.0
        urea, ca, ct, nh3_tot, solid = y0
        sp = _speciate_step(urea=urea, nh3_tot=nh3_tot, ct=ct, ca=ca, cl=cl, t_k=t_k, mg=mg)
        traj["urea"].append(urea)
        traj["ca"].append(ca)
        traj["ct"].append(ct)
        traj["nh3_tot"].append(nh3_tot)
        traj["solid"].append(solid)
        traj["ph"].append(sp["ph"])
        traj["si"].append(sp["si"])

    # --- equilibrium precipitateable bound ---
    # Maximum CaCO3 that could form if the system were pushed to SI=1 at the
    # final mass state. This is a mass-balance bound, NOT a kinetic prediction.
    # Each CaCO3 uses 1 Ca and 1 C; ureolysis adds one C per urea hydrolyzed.
    eq_bound = min(ca0, ct0 + urea0)

    stoich = check_ureolysis_stoichiometry(
        urea_hydrolyzed=urea0 - urea,
        nh3_produced=nh3_tot - nh3_0,
        co2_produced=ct - ct0,
    )

    final_sp = _speciate_step(urea=urea, nh3_tot=nh3_tot, ct=ct, ca=ca, cl=cl, t_k=t_k, mg=mg)

    return {
        "times": times,
        "trajectories": {
            "urea": traj["urea"],
            "ca2plus": traj["ca"],
            "ct": traj["ct"],
            "nh3_tot": traj["nh3_tot"],
            "caco3_solid": traj["solid"],
            "ph": traj["ph"],
            "si": traj["si"],
        },
        "final": {
            "t_s": t_end_s,
            "urea": urea,
            "urea_hydrolyzed": urea0 - urea,
            "ca2plus": ca,
            "ct": ct,
            "nh3_tot": nh3_tot,
            "caco3_solid": solid,
            "ph": final_sp["ph"],
            "si": final_sp["si"],
            "urea_conversion_frac": (urea0 - urea) / urea0 if urea0 > 0 else 0.0,
        },
        "kinetic_precipitated": solid,
        "equilibrium_bound_precipitable": eq_bound,
        "stoichiometry_check": stoich,
        "model": {
            "mode": mode,
            "precipitation_enabled": precip,
            "parameters": {
                "vmax": vmax,
                "km": km,
                "ki": ki,
                "k_first": k_first,
                "k_precip": k_precip,
                "a_specific": a_spec,
                "si_threshold": si_thr,
                "t_k": t_k,
            },
            "parameter_source": "CALIBRATION_REQUIRED",
        },
    }
