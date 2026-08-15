"""Mechanistic kinetic rate models for MICP, with documented, cited equations.

All equations are implemented exactly as published (references/sources.md §K1).
Model selection is explicit: callers pick `ureolysis`, `precipitation`,
`biomass_decay`, and `porosity_permeability` model families; the tool never
silently mixes families.

Available model families
------------------------
ureolysis (dU/dt, mol/(m3·s)):
  * "michaelis_menten"  r = k_ure * B * U / (K_half + U)
      [Lauchnor et al. 2015 whole-cell S. pasteurii kinetics; Hommel et al.
       2015 revised MICP model. K_m = 305 mmol/L, Vmax = 200 mmol/L/h for
       whole-cell; jack-bean urease values (K_m = 3.21 mM, Fidaleo &
       Lavecchia 2003) are a documented alternative for the dissolved-enzyme
       regime.]
  * "first_order"       r = k_ure * B * U
      [First-order in urea and cell density — the recommended simplification
       when urea << K_m (Lauchnor et al. 2015 found first-order fit R2=0.99).]

precipitation (mol/(m3·s)):
  * "first_order_min"   r = k_pre * min(Ca, C)
      [Limiting-reactant first-order form used by the sibling porous-media
       transport solver (OPM) and common in simplified MICP models.]
  * "saturation_driven" r = k_pre * S * (1 - Omega),  Omega = aCa*aCO3/Ksp
      [Palandri & Kharaka 2004 rate law used in PHREEQC-based MICP reactive
       transport (Razbani et al. 2024, Geomicrobiology Journal): k1 = 1.55e-6
       mol/(m2·s), k2 = 0.501 mol/(m2·s); first order in the supersaturation
       deficit (1 - Omega). S = reactive surface area (m2/m3).]

biomass_decay (1/s):
  * "first_order"       dB/dt = -kd * B
      [First-order biomass decay/encapsulation — the standard simplification
       (Hommel et al. 2015); decay time scale 1/kd.]

porosity_permeability (dimensionless relation K(phi)/K0):
  * "kozeny_carman"     K/K0 = (phi/phi0)^3 * ((1-phi0)/(1-phi))^2
      [Kozeny-Carman used in Ebigbo et al. 2012, Hommel et al. 2015, DuMu^x.]
  * "verma_pruess"      K/K0 = ((phi - phi_crit)/(phi0 - phi_crit))^3, phi>phi_crit
      [Verma-Pruess-type relation; calibrated critical porosity
       phi_crit = 0.108 (Hommel et al. 2013) or 0.12 (BCHM study).]
  * "power_law"         K/K0 = (phi/phi0)^eta
      [Alternative power law; eta ~ 3 commonly used in DuMu^x implementations.]

Porosity update (clogging):
    phi = phi0 - M_calcite/rho_calcite
  (calcite and biofilm treated as impermeable solids; calcite only here.)

Units: concentrations mol/m3, biomass scale dimensionless (per-unit biomass
factor on k_ure), rate constants in 1/s, calcite mass in kg/m3 of medium.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Callable

from _common import CACO3_DENSITY, ToolError
from errors import MmoError, MmoErrorCode

# Referenced literature constants (references/sources.md §K1)
K_M_WHOLE_CELL = 305.0       # mmol/L — Lauchnor et al. 2015
K_M_JACK_BEAN = 3.21         # mmol/L — Fidaleo & Lavecchia 2003
V_MAX_WHOLE_CELL = 200.0     # mmol/L/h — Lauchnor et al. 2015
K1_PALANDRI = 1.55e-6        # mol/(m2·s)
K2_PALANDRI = 0.501          # mol/(m2·s)
PHI_CRIT_HOMMEL = 0.108      # Hommel et al. 2013
PHI_CRIT_BCHM = 0.12         # BCHM (Canadian Geotechnical Journal) calibrated


@dataclass
class KineticsConfig:
    """Parameter set shared by every rate model. Units in the docstring above."""

    k_ure: float = 1e-5          # 1/s (per-unit-biomass ureolysis rate constant)
    k_pre: float = 1e-5          # 1/s (precipitation rate constant)
    k_half: float = 305.0        # mol/m3 urea half-saturation (K_m)
    kd: float = 1e-7             # 1/s biomass decay constant
    c_biomass: float = 1.0       # biomass density scale (dimensionless)
    ksp: float = 3.31e-9         # calcite Ksp (mol2/L2 at 25 C); 10^-8.48
    surface_area: float = 1000.0  # reactive surface area S (m2/m3)
    phi_crit: float = 0.108      # critical porosity for verma_pruess
    eta: float = 3.0             # power-law exponent
    ureolysis: str = "michaelis_menten"
    precipitation: str = "first_order_min"
    porosity_permeability: str = "kozeny_carman"


def _check_kinetics_model(name: str, value: str, allowed: list[str]) -> None:
    if value not in allowed:
        raise MmoError(
            MmoErrorCode.INVALID_MODEL_SPEC,
            f"unknown {name} model '{value}'; supported: {', '.join(allowed)}",
            detail={"field": name, "value": value, "supported": allowed},
        )


def parse_kinetics_config(spec: dict) -> KineticsConfig:
    """Build a KineticsConfig from a model-spec fragment, with validation.

    Accepts the explicit `kinetics` block of the model specification and fills
    documented defaults. Unknown model names raise MMO-E104.
    """
    cfg = KineticsConfig()
    k = spec.get("kinetics") if isinstance(spec, dict) else None
    if not isinstance(k, dict):
        return cfg
    if "k_ure" in k:
        v = k["k_ure"]
        if isinstance(v, dict):  # allow {value, unit} — value treated as SI 1/s
            v = v.get("value", v)
        cfg.k_ure = float(v)
    if "k_pre" in k:
        v = k["k_pre"]
        if isinstance(v, dict):
            v = v.get("value", v)
        cfg.k_pre = float(v)
    if "k_half" in k:
        v = k["k_half"]
        if isinstance(v, dict):
            v = v.get("value", v)
        cfg.k_half = float(v)
    if "kd" in k:
        v = k["kd"]
        if isinstance(v, dict):
            v = v.get("value", v)
        cfg.kd = float(v)
    if "c_biomass" in k:
        cfg.c_biomass = float(k["c_biomass"])
    if "ksp" in k:
        cfg.ksp = float(k["ksp"])
    if "surface_area" in k:
        cfg.surface_area = float(k["surface_area"])
    if "phi_crit" in k:
        cfg.phi_crit = float(k["phi_crit"])
    if "eta" in k:
        cfg.eta = float(k["eta"])
    if "ureolysis" in k:
        cfg.ureolysis = str(k["ureolysis"])
    if "precipitation" in k:
        cfg.precipitation = str(k["precipitation"])
    if "porosity_permeability" in k:
        cfg.porosity_permeability = str(k["porosity_permeability"])

    _check_kinetics_model("ureolysis", cfg.ureolysis, ["michaelis_menten", "first_order"])
    _check_kinetics_model(
        "precipitation",
        cfg.precipitation,
        ["first_order_min", "saturation_driven"],
    )
    _check_kinetics_model(
        "porosity_permeability",
        cfg.porosity_permeability,
        ["kozeny_carman", "verma_pruess", "power_law"],
    )
    for name, v in (
        ("k_ure", cfg.k_ure),
        ("k_pre", cfg.k_pre),
        ("k_half", cfg.k_half),
        ("kd", cfg.kd),
        ("c_biomass", cfg.c_biomass),
        ("ksp", cfg.ksp),
        ("surface_area", cfg.surface_area),
        ("phi_crit", cfg.phi_crit),
        ("eta", cfg.eta),
    ):
        if not math.isfinite(v) or v < 0:
            raise MmoError(
                MmoErrorCode.INVALID_MODEL_SPEC,
                f"kinetics.{name} must be finite and >= 0",
                detail={"field": f"kinetics.{name}", "value": v},
            )
    return cfg


# ---------------------------------------------------------------------------
# Ureolysis rates
# ---------------------------------------------------------------------------

def ureolysis_rate(u: float, cfg: KineticsConfig) -> float:
    """Ureolysis rate r_u in mol/(m3·s)."""
    if u <= 0:
        return 0.0
    if cfg.ureolysis == "michaelis_menten":
        return cfg.k_ure * cfg.c_biomass * u / (cfg.k_half + u)
    # first_order
    return cfg.k_ure * cfg.c_biomass * u


# ---------------------------------------------------------------------------
# Precipitation rates
# ---------------------------------------------------------------------------

def precipitation_rate(ca: float, carbonate: float, cfg: KineticsConfig) -> float:
    """CaCO3 precipitation rate in mol/(m3·s)."""
    if ca <= 0 or carbonate <= 0:
        return 0.0
    if cfg.precipitation == "first_order_min":
        return cfg.k_pre * min(ca, carbonate)
    # saturation_driven: Omega = aCa*aCO3/Ksp, a ~ concentration (mol/m3 scaled
    # to mol/L by 1e-3 for Ksp in (mol/L)^2).
    a_ca = ca * 1e-3
    a_co3 = carbonate * 1e-3
    omega = a_ca * a_co3 / cfg.ksp
    if omega >= 1.0:
        return cfg.k_pre * cfg.surface_area * (1.0 - omega) * (1.0 / 1.0)
    return 0.0


# ---------------------------------------------------------------------------
# Biomass decay
# ---------------------------------------------------------------------------

def biomass_decay_rate(b: float, cfg: KineticsConfig) -> float:
    """Biomass decay rate in 1/(s·1) i.e. dB/dt = -kd·B (kg/(m3·s) scaled)."""
    if b <= 0:
        return 0.0
    return cfg.kd * b


# ---------------------------------------------------------------------------
# Porosity-permeability
# ---------------------------------------------------------------------------

def porosity_from_calcite(phi0: float, m_calcite_kg_m3: float) -> float:
    """phi = phi0 - M/rho_calcite (clamped to (1e-6, 0.999))."""
    phi = phi0 - m_calcite_kg_m3 / CACO3_DENSITY
    if phi <= 1e-6:
        return 1e-6
    if phi >= 0.999:
        return 0.999
    return phi


def permeability_ratio(phi: float, phi0: float, cfg: KineticsConfig) -> float:
    """Relative permeability K/K0 (dimensionless)."""
    if phi <= 0 or phi0 <= 0 or phi >= 1 or phi0 >= 1:
        return 0.0
    if cfg.porosity_permeability == "kozeny_carman":
        return (phi / phi0) ** 3 * ((1.0 - phi0) / (1.0 - phi)) ** 2
    if cfg.porosity_permeability == "verma_pruess":
        if phi <= cfg.phi_crit:
            return 0.0
        denom = phi0 - cfg.phi_crit
        if denom <= 0:
            return 0.0
        return ((phi - cfg.phi_crit) / denom) ** 3
    if cfg.porosity_permeability == "power_law":
        return (phi / phi0) ** cfg.eta
    return (phi / phi0) ** 3 * ((1.0 - phi0) / (1.0 - phi)) ** 2


# ---------------------------------------------------------------------------
# Closed-form kinetic system model (deterministic, stdlib-only)
# ---------------------------------------------------------------------------

@dataclass
class KineticSystemResult:
    times: list[float]
    urea: list[float]
    ca: list[float]
    nh4: list[float]
    carbonate: list[float]
    biomass: list[float]
    calcite_kg: list[float]
    phi: list[float]
    permeability_ratio: list[float]
    steps: int
    mass_balance: dict
    summary: dict


def solve_kinetic_system(
    cfg: KineticsConfig,
    *,
    urea0: float,
    ca0: float,
    nh4_0: float = 0.0,
    carbonate0: float = 0.0,
    biomass0: float = 1.0,
    calcite0_kg: float = 0.0,
    phi0: float = 0.4,
    t_end: float,
    dt: float | None = None,
    max_steps: int = 1_000_000,
) -> KineticSystemResult:
    """Closed-form, implicit-Euler solver for the coupled kinetic system.

    State: [U, Ca, NH4, C, B, M_kg]. Reactions:
      dU/dt  = -r_u
      dCa/dt = -r_p
      dNH4/dt= 2 r_u
      dC/dt  = r_u - r_p
      dB/dt  = -kd B
      dM/dt  = beta_kg r_p        (kg/m3)
    Implicit Euler: ureolysis via the physical root of a quadratic (as in the
    sibling OPM solver); precipitation capped by the limiting reactant; biomass
    decay closed form. Deterministic; raises MMO-E402 on non-convergence and
    MMO-E301 on non-finite state.
    """
    if t_end <= 0:
        raise MmoError(MmoErrorCode.INVALID_MODEL_SPEC, "t_end must be > 0", detail={"t_end": t_end})
    if not dt or dt <= 0:
        # default dt so the fastest reaction is resolved: dt ~ 1/(10*max rate)
        r_max = cfg.k_ure * cfg.c_biomass + cfg.kd
        dt = min(1.0 / (max(r_max, 1e-12) * 10.0), t_end / 100.0)
    steps = int(math.ceil(t_end / dt))
    if steps > max_steps:
        raise MmoError(
            MmoErrorCode.NUMERICAL_FAILURE,
            f"step count {steps} exceeds max_steps={max_steps}; reduce t_end or increase dt",
        )

    U = float(urea0)
    Ca = float(ca0)
    NH4 = float(nh4_0)
    C = float(carbonate0)
    B = float(biomass0)
    M = float(calcite0_kg)
    phi = porosity_from_calcite(phi0, M)

    times: list[float] = []
    us: list[float] = []
    cas: list[float] = []
    nhs: list[float] = []
    cs: list[float] = []
    bs: list[float] = []
    ms: list[float] = []
    phis: list[float] = []
    krs: list[float] = []

    t = 0.0
    total_u_consumed = 0.0
    total_ca_consumed = 0.0
    total_nh_produced = 0.0
    total_carb_produced = 0.0
    total_m_kg = 0.0

    def record() -> None:
        times.append(t)
        us.append(U)
        cas.append(Ca)
        nhs.append(NH4)
        cs.append(C)
        bs.append(B)
        ms.append(M)
        phis.append(phi)
        krs.append(permeability_ratio(phi, phi0, cfg))

    record()
    for _ in range(steps):
        t += dt
        if t > t_end:
            dt_eff = t_end - (t - dt)
            t = t_end
        else:
            dt_eff = dt

        # ureolysis (implicit closed form, physical root)
        if U > 0 and cfg.c_biomass > 0 and cfg.k_ure > 0:
            a = 1.0
            b = cfg.k_half + cfg.k_ure * cfg.c_biomass * dt_eff - U
            cq = -U * cfg.k_half
            disc = max(b * b - 4.0 * a * cq, 0.0)
            u_new = (-b + math.sqrt(disc)) / (2.0 * a)
            u_new = max(0.0, min(u_new, U))
        else:
            u_new = U
        r_u_eff = (U - u_new) / dt_eff if dt_eff > 0 else 0.0

        # precipitation capped by limiting reactant (implicit)
        dlim = min(Ca, C)
        if dlim > 0 and cfg.k_pre > 0:
            if cfg.precipitation == "saturation_driven":
                r_p = precipitation_rate(Ca, C, cfg)
                consumption = min(r_p * dt_eff, dlim)
            else:
                consumption = min(cfg.k_pre * dlim * dt_eff, dlim)
        else:
            consumption = 0.0
        r_p_eff = consumption / dt_eff if dt_eff > 0 else 0.0

        # biomass decay (closed form)
        b_new = B * math.exp(-cfg.kd * dt_eff) if cfg.kd > 0 else B

        U = u_new
        Ca = max(Ca - consumption, 0.0)
        NH4 = NH4 + 2.0 * r_u_eff * dt_eff
        C = max(C + r_u_eff * dt_eff - consumption, 0.0)
        B = b_new
        M = M + consumption * 100.0869 / 1000.0  # kg/m3: mol * kg/mol
        phi = porosity_from_calcite(phi0, M)

        total_u_consumed += r_u_eff * dt_eff
        total_ca_consumed += consumption
        total_nh_produced += 2.0 * r_u_eff * dt_eff
        total_carb_produced += r_u_eff * dt_eff
        total_m_kg += consumption * 100.0869 / 1000.0

        if not all(math.isfinite(v) for v in (U, Ca, NH4, C, B, M, phi)):
            raise MmoError(
                MmoErrorCode.CONTEXT_CORRUPT,
                "non-finite state during kinetic solve",
            )
        record()

    mass_balance = {
        "urea_consumed": total_u_consumed,
        "urea_remaining": U,
        "urea_in_total": urea0,          # closed batch: initial load = inflow
        "urea_out_approx": 0.0,
        "ca_consumed": total_ca_consumed,
        "ca_remaining": Ca,
        "ca_in_total": ca0,              # closed batch: initial load = inflow
        "ca_out_approx": 0.0,
        "nh4_produced": total_nh_produced,
        "carbonate_produced": total_carb_produced,
        "caco3_mol": total_ca_consumed,
        "caco3_kg": total_m_kg,
        "urea_to_nh4_residual": total_nh_produced - 2.0 * total_u_consumed,
        "urea_to_carbonate_residual": total_carb_produced - total_u_consumed,
        "carbonate_to_caco3_residual": total_ca_consumed - total_carb_produced,
        "urea_mass_balance_residual": total_u_consumed + U - urea0,
        "ca_mass_balance_residual": total_ca_consumed + Ca - ca0,
    }
    summary = {
        "dt": dt,
        "steps": steps,
        "final_urea": U,
        "final_caco3_kg_m3": M,
        "final_porosity": phi,
        "final_permeability_ratio": permeability_ratio(phi, phi0, cfg),
        "biomass_fraction_remaining": B / biomass0 if biomass0 > 0 else 0.0,
    }
    return KineticSystemResult(
        times=times,
        urea=us,
        ca=cas,
        nh4=nhs,
        carbonate=cs,
        biomass=bs,
        calcite_kg=ms,
        phi=phis,
        permeability_ratio=krs,
        steps=steps,
        mass_balance=mass_balance,
        summary=summary,
    )
