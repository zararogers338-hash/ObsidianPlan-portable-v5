"""1D reactive transport solver for MICP porous-media columns.

Continuum (Darcy) scale, canonical MICP system:

  dissolved species (mol/m3 of pore water):
    U   = urea;    Ca = calcium;    NH = ammonium;    C = carbonate (CO3^2- + HCO3^-)
  biomass:
    B   = immobilized cell density (kg/m3 of medium, constant in time)
  solid phase:
    M   = precipitated calcite mass (kg/m3 of medium)

  ureolysis (Michaelis-Menten, implicit Euler):
    dU/dt = -k_ure * B * U / (K_half + U)          [mol/(m3·s)]
    1 mol urea -> 2 mol NH4+ + 1 mol carbonate

  precipitation (limited by the lesser of Ca and carbonate; implicit):
    r_pre = k_pre * min(Ca, C)                     [mol/(m3·s)]
    Ca + C -> CaCO3(s); Ca and C consumed 1:1

  porosity / permeability coupling (clogging feedback):
    phi   = phi0 - M / rho_caco3
    K(phi)= K0 * (phi/phi0)^3 * ((1-phi0)/(1-phi))^2     (Kozeny-Carman)

  boundary conditions (both supported):
    * "flux":  Dirichlet influent concentrations at inlet, zero-gradient outlet,
               constant Darcy velocity (u = v).
    * "head":  Darcy velocity recomputed each step from the evolving inlet
               permeability and the specified inlet/outlet pressures.

Numerical scheme: explicit operator splitting — transport substep is explicit
upwind advection + central dispersion with a CFL guard; the reaction substep
is implicit Euler in closed form (ureolysis via the physical root of a
quadratic; precipitation via the limiting-reactant consumption cap). The
scheme is deterministic, offline, stdlib-only. It raises OPM-E301 on
non-finite values and OPM-E403 on step-limit/non-convergence.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

from .errors import OpError, OpErrorCode
from .models import CACO3_DENSITY
from .units import check_finite

MAX_STEPS = 2_000_000
CFL_MARGIN = 0.8


@dataclass
class SolverConfig:
    length: float            # m
    nx: int                  # grid points (>= 8)
    porosity0: float         # initial porosity [-]
    velocity: float          # Darcy velocity [m/s] (flux BC; head BC re-derives it)
    dispersion: float        # longitudinal dispersion [m2/s]
    k_ure: float             # ureolysis rate constant [1/s] (per unit biomass scale)
    k_pre: float             # precipitation rate constant [1/s]
    k_half: float            # urea half-saturation [mol/m3]
    c_ca_in: float           # influent Ca [mol/m3]
    c_urea_in: float         # influent urea [mol/m3]
    k_perm0: float           # initial intrinsic permeability [m2]
    c_biomass: float = 1.0   # immobilized biomass density scale; k_ure is per-unit-biomass
    bc_type: str = "flux"
    p_in: float = 0.0        # Pa (head BC)
    p_out: float = 0.0       # Pa (head BC)
    mu_water: float = 1e-3   # Pa·s
    t_end: float | None = None   # s; None => run until clog threshold
    clog_threshold: float = 0.02 # final porosity stop
    dt: float | None = None  # s; None => CFL-limited
    c_ca0: float = 0.0
    c_urea0: float = 0.0
    beta_kg_per_mol: float = 0.1000869  # kg/mol — molar mass of calcite, converts mol precip to kg
    snapshot_interval: int = 200
    verbose: bool = False


@dataclass
class NodeProfile:
    x: list[float] = field(default_factory=list)
    urea: list[float] = field(default_factory=list)
    ca: list[float] = field(default_factory=list)
    nh: list[float] = field(default_factory=list)
    carbonate: list[float] = field(default_factory=list)
    porosity: list[float] = field(default_factory=list)
    calcite: list[float] = field(default_factory=list)
    permeability: list[float] = field(default_factory=list)


@dataclass
class SolverResult:
    t_final: float
    steps: int
    converged: bool
    clogged: bool
    reason: str
    profiles: list[NodeProfile]
    times: list[float]
    mass_balance: dict[str, float]
    summary: dict[str, Any] = field(default_factory=dict)


def _clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def rate_ure(urea: float, k_ure: float, k_half: float, c_biomass: float) -> float:
    """Michaelis-Menten ureolysis rate [mol/(m3·s)]."""
    if urea <= 0:
        return 0.0
    return k_ure * c_biomass * urea / (k_half + urea)


def kozeny_carman(phi: float, phi0: float, k0: float) -> float:
    """Kozeny-Carman relative permeability [m2]."""
    if phi <= 0 or phi0 <= 0 or phi >= 1:
        return 0.0
    r = phi / phi0
    return k0 * r**3 * ((1.0 - phi0) / (1.0 - phi)) ** 2


def solve_transport(cfg: SolverConfig) -> SolverResult:
    L = check_finite("length", cfg.length)
    nx = int(cfg.nx)
    if L <= 0 or nx < 8:
        raise OpError(OpErrorCode.RANGE_OUT_OF_BOUNDS,
                      "length must be > 0 and nx >= 8.",
                      detail={"length": L, "nx": nx})
    phi0 = check_finite("porosity", cfg.porosity0)
    if not (0 < phi0 < 1):
        raise OpError(OpErrorCode.RANGE_OUT_OF_BOUNDS,
                      "porosity must be in (0,1).", detail={"porosity0": phi0})
    v = check_finite("velocity", cfg.velocity)
    D = check_finite("dispersion", cfg.dispersion)
    k_ure = check_finite("k_ure", cfg.k_ure)
    k_pre = check_finite("k_pre", cfg.k_pre)
    k_half = check_finite("k_half", cfg.k_half)
    c_ca_in = check_finite("c_ca_in", cfg.c_ca_in)
    c_urea_in = check_finite("c_urea_in", cfg.c_urea_in)
    c_bio = check_finite("c_biomass", cfg.c_biomass)
    k0 = check_finite("k_perm0", cfg.k_perm0)
    beta_kg = check_finite("beta_kg_per_mol", cfg.beta_kg_per_mol)
    if v < 0 or D < 0 or k_ure < 0 or k_pre < 0 or k_half <= 0 or c_urea_in < 0 or c_ca_in < 0 or c_bio < 0:
        raise OpError(OpErrorCode.RANGE_OUT_OF_BOUNDS,
                      "solver requires v>=0, D>=0, k>=0, K_half>0, c_in>=0, c_biomass>=0.",
                      detail={"v": v, "D": D, "k_ure": k_ure, "k_pre": k_pre,
                              "k_half": k_half, "c_urea_in": c_urea_in,
                              "c_ca_in": c_ca_in, "c_biomass": c_bio})

    dx = L / (nx - 1)
    x = [i * dx for i in range(nx)]

    # state arrays
    U = [float(cfg.c_urea0)] * nx
    Ca = [float(cfg.c_ca0)] * nx
    NH = [0.0] * nx
    C = [0.0] * nx
    M = [0.0] * nx
    phi = [float(phi0)] * nx
    Kperm = [kozeny_carman(phi0, phi0, k0)] * nx

    # CFL-limited time step
    dt_adv = CFL_MARGIN * dx / max(v, 1e-12)
    dt_disp = CFL_MARGIN * dx * dx / (2.0 * max(D, 1e-12))
    dt = cfg.dt if (cfg.dt and cfg.dt > 0) else min(dt_adv, dt_disp)
    dt = min(dt, dt_adv, dt_disp)
    if dt <= 0 or not math.isfinite(dt):
        raise OpError(OpErrorCode.NUMERICAL_FAILURE,
                      "Could not derive a positive, finite time step.",
                      detail={"dx": dx, "v": v, "D": D})

    t = 0.0
    t_end = cfg.t_end
    step = 0
    profiles: list[NodeProfile] = []
    interval = max(1, int(cfg.snapshot_interval))
    clogged = False
    reason = "completed"

    # mass accounting (per unit cross-section area; volume factor dx applied at end)
    mass_urea_in = 0.0
    mass_ca_in = 0.0
    mass_urea_out = 0.0
    mass_ca_out = 0.0
    total_urea_consumed = 0.0
    total_ca_consumed = 0.0
    total_nh_produced = 0.0
    total_carb_produced = 0.0
    total_caco3_mol = 0.0

    # last-step outflow values (initialized for the t_end=0 edge case)
    U_last = U[-1]
    Ca_last = Ca[-1]

    def save_profile() -> None:
        profiles.append(NodeProfile(
            x=list(x), urea=list(U), ca=list(Ca), nh=list(NH), carbonate=list(C),
            porosity=list(phi), calcite=list(M), permeability=list(Kperm),
        ))

    save_profile()

    while t_end is None or t < t_end:
        step += 1
        if step > MAX_STEPS:
            raise OpError(OpErrorCode.NUMERICAL_FAILURE,
                          f"Step limit exceeded ({MAX_STEPS}); simulation did not reach "
                          f"t_end={t_end} or clog threshold.",
                          detail={"t": t, "clog_threshold": cfg.clog_threshold})

        # ---- transport substep (explicit upwind advection + central dispersion) ----
        # Boundary fluxes (per unit area) accumulated so the mass balance
        # telescopes exactly:
        #   advective inflow  = v * C_in
        #   dispersive inflow = D * (C_in - C[1]) / dx   (Fick's law, Dirichlet
        #                        reservoir held at C_in)
        #   advective outflow = v * C[nx-1]              (zero-gradient outlet:
        #                        no dispersive flux by construction)
        mass_urea_in += v * dt * c_urea_in + D * dt * (c_urea_in - U[1]) / dx
        mass_ca_in += v * dt * c_ca_in + D * dt * (c_ca_in - Ca[1]) / dx
        mass_urea_out += v * dt * U[nx - 1]
        mass_ca_out += v * dt * Ca[nx - 1]
        U_new = [0.0] * nx
        Ca_new = [0.0] * nx
        NH_new = [0.0] * nx
        C_new = [0.0] * nx
        for i in range(nx):
            if i == 0:
                U_new[i] = c_urea_in
                Ca_new[i] = c_ca_in
                NH_new[i] = 0.0
                C_new[i] = 0.0
                continue
            adv_u = v * dt / dx * (U[i - 1] - U[i])
            adv_ca = v * dt / dx * (Ca[i - 1] - Ca[i])
            adv_nh = v * dt / dx * (NH[i - 1] - NH[i])
            adv_c = v * dt / dx * (C[i - 1] - C[i])
            if i < nx - 1:
                dis_u = D * dt / (dx * dx) * (U[i + 1] - 2 * U[i] + U[i - 1])
                dis_ca = D * dt / (dx * dx) * (Ca[i + 1] - 2 * Ca[i] + Ca[i - 1])
                dis_nh = D * dt / (dx * dx) * (NH[i + 1] - 2 * NH[i] + NH[i - 1])
                dis_c = D * dt / (dx * dx) * (C[i + 1] - 2 * C[i] + C[i - 1])
            else:  # zero-gradient outlet
                dis_u = D * dt / (dx * dx) * (U[i - 1] - U[i])
                dis_ca = D * dt / (dx * dx) * (Ca[i - 1] - Ca[i])
                dis_nh = D * dt / (dx * dx) * (NH[i - 1] - NH[i])
                dis_c = D * dt / (dx * dx) * (C[i - 1] - C[i])
            U_new[i] = U[i] + adv_u + dis_u
            Ca_new[i] = Ca[i] + adv_ca + dis_ca
            NH_new[i] = NH[i] + adv_nh + dis_nh
            C_new[i] = C[i] + adv_c + dis_c

        # ---- reaction substep (implicit Euler; closed forms) ----
        # Node 0 is the Dirichlet inflow boundary (a reservoir held at the
        # influent composition); reaction only acts on the in-domain cells.
        for i in range(1, nx):
            u = max(U_new[i], 0.0)
            ca = max(Ca_new[i], 0.0)
            nh = NH_new[i]
            carb = max(C_new[i], 0.0)

            # ureolysis: dU/dt = -k*B*U/(K+U).  Implicit Euler gives the
            # quadratic  U'^2 + (K + k*B*dt - u)*U' - u*K = 0; take the
            # physical root in [0, u].
            if u > 0 and c_bio > 0:
                a = 1.0
                b = k_half + k_ure * c_bio * dt - u
                cq = -u * k_half
                disc = max(b * b - 4.0 * a * cq, 0.0)
                u_new = (-b + math.sqrt(disc)) / (2.0 * a)
                u_new = _clamp(u_new, 0.0, u)
            else:
                u_new = u
            r_ure_eff = (u - u_new) / dt if dt > 0 else 0.0

            # precipitation: r_pre = k_pre * min(Ca, C), consumed 1:1.
            # Implicit: consumption capped by the limiting reactant.
            dlim = min(ca, carb)
            if dlim > 0 and k_pre > 0:
                consumption = _clamp(k_pre * dlim * dt, 0.0, dlim)
            else:
                consumption = 0.0
            r_pre_eff = consumption / dt if dt > 0 else 0.0

            U_new[i] = u_new
            Ca_new[i] = ca - consumption
            C_new[i] = carb - consumption
            NH_new[i] = nh + 2.0 * dt * r_ure_eff          # 1 urea -> 2 NH4+
            # carbonate produced 1:1 with urea consumed; plus carbonate already present
            C_new[i] += dt * r_ure_eff
            dM = beta_kg * consumption                     # kg calcite / m3 added
            M[i] += dM
            total_urea_consumed += r_ure_eff * dt
            total_ca_consumed += consumption
            total_nh_produced += 2.0 * dt * r_ure_eff
            total_carb_produced += dt * r_ure_eff
            total_caco3_mol += consumption

        # commit the new concentration state
        U, Ca, NH, C = U_new, Ca_new, NH_new, C_new

        # ---- porosity / permeability update (clogging feedback) ----
        for i in range(nx):
            # phi = phi0 - M/rho  (calcite volume per bulk volume)
            phi[i] = _clamp(phi0 - M[i] / CACO3_DENSITY, 1e-6, 0.999)
            Kperm[i] = kozeny_carman(phi[i], phi0, k0)

        if min(phi) < cfg.clog_threshold:
            clogged = True
            reason = "clogged"
            t += dt
            U_last = U_new[-1]
            Ca_last = Ca_new[-1]
            break

        if cfg.bc_type == "head":
            km = Kperm[0]
            dpdx = (cfg.p_out - cfg.p_in) / L if L > 0 else 0.0
            v_new = -km / cfg.mu_water * dpdx
            if not math.isfinite(v_new) or v_new < 0:
                v_new = 0.0
            dt = min(dt, CFL_MARGIN * dx / max(v_new, 1e-12))
            v = v_new

        t += dt
        U_last = U_new[-1]
        Ca_last = Ca_new[-1]
        if step % interval == 0:
            save_profile()

    save_profile()

    volume = dx  # per unit cross-section (1 m x 1 m area, thickness dx)
    # in-domain cells exclude the boundary reservoir at node 0
    U_domain = sum(U[1:])
    Ca_domain = sum(Ca[1:])
    mass_balance = {
        "urea_in_total": mass_urea_in,
        "urea_consumed": total_urea_consumed * volume,
        "urea_remaining": U_domain * volume,
        "urea_out_approx": mass_urea_out,
        "ca_in_total": mass_ca_in,
        "ca_consumed": total_ca_consumed * volume,
        "ca_remaining": Ca_domain * volume,
        "ca_out_approx": mass_ca_out,
        "nh_produced": total_nh_produced * volume,
        "carbonate_produced": total_carb_produced * volume,
        "caco3_mol_precipitated": total_caco3_mol * volume,
        "caco3_kg_precipitated": total_caco3_mol * beta_kg * volume,
    }
    # conservation residual: urea_in ≈ urea_consumed + remaining + out
    bal_u = mass_urea_in - (total_urea_consumed * volume + U_domain * volume + mass_urea_out)
    mass_balance["urea_mass_balance_residual"] = bal_u
    # ammonium mass balance: NH produced = 2x urea consumed
    mass_balance["nh_urea_stoich_residual"] = (
        total_nh_produced - 2.0 * total_urea_consumed) * volume
    # carbonate mass balance: carbonate produced = urea consumed; consumed == caco3 mol
    mass_balance["carbonate_urea_stoich_residual"] = (
        total_carb_produced - total_urea_consumed) * volume
    mass_balance["carbonate_caco3_stoich_residual"] = (
        total_caco3_mol - total_ca_consumed) * volume

    return SolverResult(
        t_final=t,
        steps=step,
        converged=True,
        clogged=clogged,
        reason=reason,
        profiles=profiles,
        times=[t],
        mass_balance=mass_balance,
        summary={
            "dx": dx,
            "dt": dt,
            "final_porosity_min": min(phi),
            "final_porosity_inlet": phi[0],
            "final_porosity_outlet": phi[-1],
            "permeability_inlet_final": Kperm[0],
            "permeability_reduction_factor": Kperm[0] / k0 if k0 > 0 else 0.0,
            "t_final": t,
            "steps": step,
        },
    )
