"""Conservation, numerical-stability, and grid/time-step sensitivity checks for
micp-modeling-optimizer.

These are the self-check gates the skill runs on every model before SUCCESS:

  * conservation: mass-balance residuals for urea / ammonium / calcium /
    carbonate must be below rtol of the relevant flux (default 5%).
  * numerical_stability: state finiteness, porosity bounds, CFL adherence for
    advection-dominated problems, and positivity of concentrations.
  * grid_step_sensitivity: run the same scenario at coarse / fine grid and at
    two time steps; report relative drift of the key output (e.g. precipitated
    CaCO3 mass) and fail hard above a threshold.

Every check returns {name, ok, measured, tolerance, detail}. A failed
conservation or stability check maps to status PARTIAL and MMO-E403/E404.
"""

from __future__ import annotations

import math
from typing import Any, Callable, Sequence

from _common import ToolError
from errors import MmoError, MmoErrorCode

DEFAULT_RTOL = 0.05
HARD_GRID_DRIFT = 0.40
SOFT_GRID_DRIFT = 0.15


def check_conservation(mass_balance: dict, *, rtol: float = DEFAULT_RTOL) -> dict:
    """Validate a solver-produced mass_balance dict against stoichiometry.

    Keys recognized (the OPM/kinetics mass-balance blocks):
      urea_consumed, urea_remaining, urea_in_total, urea_out_approx,
      ca_consumed, ca_remaining, ca_in_total, ca_out_approx,
      nh4_produced, carbonate_produced, caco3_mol, caco3_kg.
    """
    checks: list[dict] = []

    def check(name: str, ok: bool, measured: float, tolerance: float, detail: dict) -> None:
        checks.append({
            "name": name,
            "ok": ok,
            "measured": measured,
            "tolerance": tolerance,
            "detail": detail,
        })

    urea_in = mass_balance.get("urea_in_total", 0.0)
    urea_consumed = mass_balance.get("urea_consumed", 0.0)
    urea_remaining = mass_balance.get("urea_remaining", 0.0)
    urea_out = mass_balance.get("urea_out_approx", 0.0)
    scale_u = max(abs(urea_in), abs(urea_consumed) + abs(urea_remaining) + abs(urea_out), 1e-12)
    check(
        "urea_mass_balance",
        abs(urea_in - (urea_consumed + urea_remaining + urea_out)) <= rtol * scale_u,
        urea_in - (urea_consumed + urea_remaining + urea_out),
        rtol,
        {"urea_in": urea_in, "urea_consumed": urea_consumed,
         "urea_remaining": urea_remaining, "urea_out": urea_out},
    )

    nh4 = mass_balance.get("nh4_produced", 0.0)
    check(
        "ammonium_stoichiometry",
        abs(nh4 - 2.0 * urea_consumed) <= rtol * max(abs(nh4), abs(2.0 * urea_consumed), 1e-12),
        nh4 - 2.0 * urea_consumed,
        rtol,
        {"nh4_produced": nh4, "urea_consumed": urea_consumed},
    )

    carb = mass_balance.get("carbonate_produced", 0.0)
    check(
        "carbonate_urea_stoichiometry",
        abs(carb - urea_consumed) <= rtol * max(abs(carb), abs(urea_consumed), 1e-12),
        carb - urea_consumed,
        rtol,
        {"carbonate_produced": carb, "urea_consumed": urea_consumed},
    )

    caco3 = mass_balance.get("caco3_mol", 0.0)
    ca_consumed = mass_balance.get("ca_consumed", 0.0)
    check(
        "caco3_ca_stoichiometry",
        abs(caco3 - ca_consumed) <= rtol * max(abs(caco3), abs(ca_consumed), 1e-12),
        caco3 - ca_consumed,
        rtol,
        {"caco3_mol": caco3, "ca_consumed": ca_consumed},
    )

    ca_in = mass_balance.get("ca_in_total", 0.0)
    ca_remaining = mass_balance.get("ca_remaining", 0.0)
    ca_out = mass_balance.get("ca_out_approx", 0.0)
    scale_ca = max(abs(ca_in), abs(ca_consumed) + abs(ca_remaining) + abs(ca_out), 1e-12)
    check(
        "calcium_mass_balance",
        abs(ca_in - (ca_consumed + ca_remaining + ca_out)) <= rtol * scale_ca,
        ca_in - (ca_consumed + ca_remaining + ca_out),
        rtol,
        {"ca_in": ca_in, "ca_consumed": ca_consumed,
         "ca_remaining": ca_remaining, "ca_out": ca_out},
    )

    caco3_kg = mass_balance.get("caco3_kg", 0.0)
    check(
        "caco3_mass_consistency",
        abs(caco3_kg - caco3 * 100.0869 / 1000.0) <= rtol * max(abs(caco3_kg), abs(caco3 * 0.1000869), 1e-12),
        caco3_kg - caco3 * 100.0869 / 1000.0,
        rtol,
        {"caco3_kg": caco3_kg, "caco3_mol": caco3},
    )

    all_ok = all(c["ok"] for c in checks)
    return {
        "name": "conservation",
        "ok": all_ok,
        "checks": checks,
        "passed": all_ok,
    }


def check_numerical_stability(
    state: dict,
    *,
    porosity_min: float = 0.001,
    porosity_max: float = 0.999,
    cfl: float | None = None,
) -> dict:
    """Validate a state snapshot: finiteness, porosity bounds, concentration
    non-negativity, and (optionally) CFL adherence."""
    checks: list[dict] = []

    def check(name: str, ok: bool, detail: dict) -> None:
        checks.append({"name": name, "ok": ok, "detail": detail})

    # finiteness over all numeric leaves
    non_finite = _scan_non_finite(state)
    check("finite_state", not non_finite, {"non_finite_paths": non_finite[:10]})

    phi = _dig(state, "porosity")
    if isinstance(phi, list):
        bad = [p for p in phi if not (porosity_min <= p <= porosity_max)]
        check("porosity_bounds", not bad, {"out_of_bounds_count": len(bad), "porosity": phi[:8]})
    elif isinstance(phi, (int, float)):
        check("porosity_bounds", porosity_min <= phi <= porosity_max, {"porosity": phi})

    for key in ("urea", "ca", "nh4", "carbonate", "calcite"):
        v = _dig(state, key)
        if isinstance(v, list):
            neg = [x for x in v if x < -1e-9]
            check(f"{key}_non_negative", not neg, {"negative_count": len(neg)})
        elif isinstance(v, (int, float)):
            check(f"{key}_non_negative", v >= -1e-9, {"value": v})

    if cfl is not None:
        check("cfl_adherence", cfl <= 1.0, {"cfl": cfl})

    all_ok = all(c["ok"] for c in checks)
    return {"name": "numerical_stability", "ok": all_ok, "checks": checks, "passed": all_ok}


def check_grid_step_sensitivity(
    run: Callable[[dict], float],
    base_config: dict,
    *,
    key: str = "caco3_mass",
    coarse: int = 32,
    fine: int = 128,
    soft_drift: float = SOFT_GRID_DRIFT,
    hard_drift: float = HARD_GRID_DRIFT,
    dt_factor: float = 2.0,
) -> dict:
    """Re-run the same scenario at coarse/fine grid and two time steps; report
    relative drift of the scalar `key` output.

    run(config) -> scalar. base_config must carry a 'nx' and 'dt' the caller
    can vary (the function keys 'nx'/'dt' overrides in).
    """
    cfg_coarse = dict(base_config)
    cfg_coarse["nx"] = coarse
    cfg_fine = dict(base_config)
    cfg_fine["nx"] = fine

    y_c = run(cfg_coarse)
    y_f = run(cfg_fine)
    denom = max(abs(y_f), 1e-12)
    grid_drift = abs(y_f - y_c) / denom

    cfg_dt = dict(base_config)
    if "dt" in cfg_dt and cfg_dt.get("dt"):
        cfg_dt["dt"] = float(cfg_dt["dt"]) * dt_factor
    else:
        cfg_dt["dt"] = dt_factor  # placeholder if no dt in config
    y_dt = run(cfg_dt)
    dt_drift = abs(y_dt - y_f) / max(abs(y_f), 1e-12)

    return {
        "name": "grid_step_sensitivity",
        "key": key,
        "coarse_nx": coarse,
        "fine_nx": fine,
        "coarse_value": y_c,
        "fine_value": y_f,
        "grid_drift": grid_drift,
        "dt_factor": dt_factor,
        "dt_drift": dt_drift,
        "soft_threshold": soft_drift,
        "hard_threshold": hard_drift,
        "converged": grid_drift <= soft_drift and dt_drift <= soft_drift,
        "ok": grid_drift <= hard_drift and dt_drift <= hard_drift,
    }


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _dig(state: dict, key: str) -> Any:
    if key in state:
        return state[key]
    for v in state.values():
        if isinstance(v, dict):
            r = _dig(v, key)
            if r is not None:
                return r
    return None


def _scan_non_finite(obj: Any, path: str = "") -> list[str]:
    out: list[str] = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            out.extend(_scan_non_finite(v, f"{path}.{k}" if path else k))
    elif isinstance(obj, (list, tuple)):
        for i, v in enumerate(obj):
            out.extend(_scan_non_finite(v, f"{path}[{i}]"))
    elif isinstance(obj, (int, float)) and not isinstance(obj, bool):
        if not math.isfinite(float(obj)):
            out.append(path or "<value>")
    return out
