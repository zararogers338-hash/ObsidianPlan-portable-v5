"""Chemistry for micp-biosafety-environment-auditor.

Urea → total nitrogen → NH4+ → NH3 (free ammonia) mass-balance tooling, NH3
speciation across pH/temperature, and waste-stream loading calculations.

All functions are pure and offline. Units follow the SI-gram convention used
across the Obsidian MICP suite: concentrations in mmol/L (mM) or mg/L, masses
in g, volumes in L, temperatures in Celsius.

Every function rejects NaN/Inf and out-of-range values before computing.
"""

from __future__ import annotations

import math
from typing import Any

from .errors import MbsError, MbsErrorCode

# Urea (CH4N2O) molar mass, g/mol
UREA_MOLAR_MASS = 60.06
# Nitrogen molar mass, g/mol
N_MOLAR_MASS = 14.007
# NH3 molar mass, g/mol
NH3_MOLAR_MASS = 17.031
# NH4+ molar mass, g/mol
NH4_MOLAR_MASS = 18.039

# Urea hydrolysis stoichiometry: CO(NH2)2 + 2 H2O -> CO3^2- + 2 NH4+
UREA_TO_NH4_MOLES = 2.0
UREA_TO_N_MOLES = 2.0

# Mass-conservation tolerance for the nitrogen balance (fraction).
DEFAULT_MASS_BALANCE_TOLERANCE = 0.05

# Default buffer conditions assumed when only pH is given (pure water at 20 °C).
DEFAULT_IONIC_STRENGTH = 0.05  # mol/L
DEFAULT_TEMP_C = 20.0


def ensure_finite(value: float | None, name: str) -> float:
    """Reject NaN/Inf; return float."""
    if value is None:
        raise MbsError(
            MbsErrorCode.NUMERIC_INVALID,
            f"{name} is missing (None); a finite number is required.",
            detail={"field": name, "value": None},
        )
    try:
        v = float(value)
    except (TypeError, ValueError) as exc:
        raise MbsError(
            MbsErrorCode.NUMERIC_INVALID,
            f"{name} is not numeric.",
            detail={"field": name, "value": repr(value)},
        ) from exc
    if not math.isfinite(v):
        raise MbsError(
            MbsErrorCode.NUMERIC_INVALID,
            f"{name} is non-finite (NaN/Inf); refusing to compute with it.",
            detail={"field": name, "value": v},
        )
    return v


def ensure_in_range(value: float | None, name: str, low: float, high: float, *, inclusive: bool = True) -> float:
    v = ensure_finite(value, name)
    ok = (low <= v <= high) if inclusive else (low < v < high)
    if not ok:
        raise MbsError(
            MbsErrorCode.NUMERIC_INVALID,
            f"{name} must be within [{low}, {high}] (inclusive={inclusive}); got {v}.",
            detail={"field": name, "value": v, "low": low, "high": high},
        )
    return v


def urea_molar_mass() -> float:
    return UREA_MOLAR_MASS


def urea_to_nitrogen_balance(
    *,
    urea_input_g: float,
    theoretical_total_n_g: float | None = None,
    nh4_upper_bound_g: float | None = None,
    nh3_potential_g: float | None = None,
    liquid_residual_g: float | None = None,
    sorbed_retained_g: float | None = None,
    discharged_treated_g: float | None = None,
    tolerance: float = DEFAULT_MASS_BALANCE_TOLERANCE,
) -> dict[str, Any]:
    """Nitrogen mass balance for a urea-fed MICP process.

    Computes theoretical quantities from urea_input_g alone when the measured
    paths are not supplied (an ideal upper envelope), and closes the balance
    across the user-supplied paths when they are.

    Returns a dict (also suitable as an artifact `note`):

      urea_input_g              input urea mass
      theoretical_total_n_g     total nitrogen if all urea nitrogen is accounted
      nh4_upper_bound_g         max NH4+-N if ureolysis is complete
      nh3_potential_g           max NH3-N if all nitrogen were free ammonia (theoretical)
      residual_paths            {liquid_residual_g, sorbed_retained_g, discharged_treated_g}
      accounted_g               sum of the measured paths
      balance_error_g           theoretical_total_n_g - accounted_g
      balance_error_fraction    balance_error_g / theoretical_total_n_g
      mass_balance_closed       |fraction| <= tolerance
      uses_only_theory          True when no measured path was supplied

    Raises MBS-E301 when the user supplies measured paths that do NOT close
    within tolerance: conservation failures must block environmental
    conclusions.
    """
    urea_in = ensure_finite(urea_input_g, "urea_input_g")
    if urea_in < 0:
        raise MbsError(
            MbsErrorCode.NUMERIC_INVALID,
            "urea_input_g must be >= 0.",
            detail={"field": "urea_input_g", "value": urea_in},
        )

    # Theoretical total N from urea stoichiometry: 2 N per urea.
    theoretical_n = urea_in * (2.0 * N_MOLAR_MASS) / UREA_MOLAR_MASS
    # If full ureolysis: all 2 N end up in NH4+.
    nh4_upper = urea_in * (2.0 * NH4_MOLAR_MASS) / UREA_MOLAR_MASS  # NH4+ mass upper bound
    nh4_n_upper = theoretical_n  # NH4-N upper bound (mass of N)
    # NH3 potential: if all N were volatile free NH3.
    nh3_potential = theoretical_n  # NH3-N equivalent

    # If the caller supplied an explicit theoretical_total_n_g, cross-check it.
    computed_total = theoretical_total_n_g
    if computed_total is not None:
        computed_total = ensure_finite(computed_total, "theoretical_total_n_g")
        if abs(computed_total - theoretical_n) > max(1e-6, tolerance * theoretical_n):
            raise MbsError(
                MbsErrorCode.MASS_BALANCE_CLOSED,
                "Supplied theoretical_total_n_g disagrees with urea stoichiometry. "
                "Conservation is violated before the balance is even closed.",
                detail={
                    "field": "theoretical_total_n_g",
                    "supplied": computed_total,
                    "from_urea": theoretical_n,
                },
            )
    total_n = theoretical_n

    # Caller-supplied derived quantities (nh4_upper_bound_g / nh3_potential_g)
    # are NEVER silently replaced: cross-check them against stoichiometry and
    # reject on disagreement (MBS-E301), so a measured volatilization or
    # precipitation figure cannot be dropped without a trace.
    for field, supplied, computed, desc in (
        ("nh4_upper_bound_g", nh4_upper_bound_g, nh4_upper, "NH4+ mass upper bound"),
        ("nh3_potential_g", nh3_potential_g, nh3_potential, "NH3-N potential"),
    ):
        if supplied is not None:
            supplied_v = ensure_finite(supplied, field)
            if abs(supplied_v - computed) > max(1e-6, tolerance * max(computed, 1e-9)):
                raise MbsError(
                    MbsErrorCode.MASS_BALANCE_CLOSED,
                    f"Supplied {field} ({supplied_v:g} g) disagrees with the "
                    f"stoichiometric {desc} ({computed:g} g). Conservation is violated.",
                    detail={"field": field, "supplied": supplied_v, "from_urea": computed},
                )

    # Paths that carry nitrogen out of / within the control volume.
    paths = {
        "liquid_residual_g": liquid_residual_g,
        "sorbed_retained_g": sorbed_retained_g,
        "discharged_treated_g": discharged_treated_g,
        "nh3_potential_g": nh3_potential,
    }
    measured_paths = {
        k: ensure_finite(v, k) for k, v in paths.items()
        if v is not None and k != "nh3_potential_g"
    }
    measured_paths["nh3_potential_g"] = nh3_potential

    accounted = sum(measured_paths.get(k, 0.0) for k in ("liquid_residual_g", "sorbed_retained_g", "discharged_treated_g"))
    balance_error = total_n - accounted
    # Mass-balance closure is impossible from zero nitrogen input: if total_n ==
    # 0 and any measured path carries N, the balance CANNOT be closed (N appears
    # from nothing). Never force the fraction to 0.0 on a zero total.
    uses_only_theory = all(
        v is None for v in (liquid_residual_g, sorbed_retained_g, discharged_treated_g)
    )
    if total_n == 0 and accounted > 0:
        raise MbsError(
            MbsErrorCode.MASS_BALANCE_CLOSED,
            "Nitrogen mass balance is impossible: zero urea input yet "
            f"{accounted:.4g} g N claimed across the measured paths. "
            "Environmental conclusions cannot be drawn from non-conserving data.",
            detail={
                "urea_input_g": urea_in,
                "theoretical_total_n_g": total_n,
                "accounted_g": accounted,
                "balance_error_g": -accounted,
                "tolerance": tolerance,
            },
        )
    balance_fraction = balance_error / total_n if total_n else 0.0
    closed = (total_n > 0 and abs(balance_fraction) <= tolerance) or (total_n == 0 and accounted == 0)

    # Mass conservation gate: if the caller claims to account for all paths but
    # the numbers do not close, environmental conclusions must be blocked.
    if not uses_only_theory and not closed:
        raise MbsError(
            MbsErrorCode.MASS_BALANCE_CLOSED,
            "Nitrogen mass balance does not close within tolerance "
            f"(error={balance_error:.4g} g, {balance_fraction:.2%}); "
            "environmental conclusions cannot be drawn from non-conserving data.",
            detail={
                "urea_input_g": urea_in,
                "theoretical_total_n_g": total_n,
                "accounted_g": accounted,
                "balance_error_g": balance_error,
                "balance_error_fraction": balance_fraction,
                "tolerance": tolerance,
            },
        )

    return {
        "urea_input_g": urea_in,
        "theoretical_total_n_g": total_n,
        "nh4_upper_bound_g": nh4_upper,
        "nh4_n_upper_bound_g": nh4_n_upper,
        "nh3_potential_g": nh3_potential,
        "residual_paths": {
            "liquid_residual_g": measured_paths.get("liquid_residual_g"),
            "sorbed_retained_g": measured_paths.get("sorbed_retained_g"),
            "discharged_treated_g": measured_paths.get("discharged_treated_g"),
        },
        "accounted_g": accounted,
        "balance_error_g": balance_error,
        "balance_error_fraction": balance_fraction,
        "mass_balance_closed": closed,
        "uses_only_theory": uses_only_theory,
    }


def pka_ammonium(temp_c: float) -> float:
    """Temperature-corrected pKa of NH4+ (Bates & Pinching, 1949)."""
    t = ensure_finite(temp_c, "temp_c")
    tk = t + 273.15
    # pKa = 0.09018 + 2729.92/T (K), valid ~0-50 °C.
    return 0.09018 + 2729.92 / tk


def nh3_fraction(pH: float, temp_c: float = DEFAULT_TEMP_C, ionic_strength: float = DEFAULT_IONIC_STRENGTH) -> float:
    """Fraction of total ammonia present as free NH3, given pH, T, ionic strength.

    Includes an activity-coefficient correction (Davies equation) so the tool
    is not silent on the well-known overestimate from using pKa alone.
    """
    ph = ensure_in_range(pH, "pH", 0.0, 14.0)
    t = ensure_finite(temp_c, "temp_c")
    if not (0.0 <= t <= 60.0):
        raise MbsError(
            MbsErrorCode.NUMERIC_INVALID,
            "temp_c out of validated range [0, 60] °C for the pKa correlation.",
            detail={"field": "temp_c", "value": t},
        )
    ionic = ensure_finite(ionic_strength, "ionic_strength")
    if ionic < 0:
        raise MbsError(
            MbsErrorCode.NUMERIC_INVALID,
            "ionic_strength must be >= 0.",
            detail={"field": "ionic_strength", "value": ionic},
        )
    pka = pka_ammonium(t)
    # Davies activity correction for monovalent NH4+ at the given ionic strength.
    sqrt_i = math.sqrt(max(ionic, 0.0))
    log_gamma = -0.5 * sqrt_i / (1.0 + sqrt_i) + 0.3 * max(ionic, 0.0)
    gamma = 10.0 ** (-log_gamma)  # activity coefficient for monovalent ions
    # Effective dissociation: alpha(NH3) = 1 / (1 + 10^(pKa - pH) / gamma)
    # With gamma<1, [NH3]/[NH4+] = K*gamma ... derived: alpha = 1/(1 + 10^(pKa-pH)*gamma)
    ratio = 10.0 ** (pka - ph) * gamma
    alpha = 1.0 / (1.0 + ratio)
    return alpha


def nh3_concentration(
    total_ammonia_mgL: float,
    pH: float,
    temp_c: float = DEFAULT_TEMP_C,
    ionic_strength: float = DEFAULT_IONIC_STRENGTH,
) -> dict[str, float]:
    """Split total ammonia-N into free NH3-N and ionized NH4+-N (mg/L as N)."""
    total = ensure_finite(total_ammonia_mgL, "total_ammonia_mgL")
    if total < 0:
        raise MbsError(
            MbsErrorCode.NUMERIC_INVALID,
            "total_ammonia_mgL must be >= 0.",
            detail={"field": "total_ammonia_mgL", "value": total},
        )
    alpha = nh3_fraction(pH, temp_c, ionic_strength)
    nh3_n = total * alpha
    return {
        "total_ammonia_n_mgL": total,
        "nh3_n_mgL": nh3_n,
        "nh4_n_mgL": total - nh3_n,
        "nh3_fraction": alpha,
        "pka": pka_ammonium(temp_c),
        "temp_c": temp_c,
        "pH": pH,
    }


def ureolysis_ammonium(
    urea_mM: float,
    urea_hydrolyzed_fraction: float = 1.0,
) -> dict[str, float]:
    """NH4+ produced by ureolysis: 1 mol urea -> 2 mol NH4+.

    Returns mmol/L of NH4+ and mg/L of NH4-N, plus the NH3-potential mg/L
    (if all NH4+ were free NH3-N — an upper bound for volatility risk).
    """
    urea = ensure_finite(urea_mM, "urea_mM")
    if urea < 0:
        raise MbsError(
            MbsErrorCode.NUMERIC_INVALID,
            "urea_mM must be >= 0.",
            detail={"field": "urea_mM", "value": urea},
        )
    frac = ensure_in_range(urea_hydrolyzed_fraction, "urea_hydrolyzed_fraction", 0.0, 1.0)
    nh4_mM = urea * UREA_TO_NH4_MOLES * frac
    nh4_n_mgL = nh4_mM * N_MOLAR_MASS
    nh3_n_potential_mgL = nh4_n_mgL
    return {
        "urea_mM": urea,
        "urea_hydrolyzed_fraction": frac,
        "nh4_mM": nh4_mM,
        "nh4_n_mgL": nh4_n_mgL,
        "nh3_n_potential_mgL": nh3_n_potential_mgL,
        "stoichiometry": "CO(NH2)2 + 2 H2O -> 2 NH4+ + CO3^2-",
    }


def waste_loading(
    *,
    waste_volume_l: float,
    nh4_n_conc_mgL: float,
    urea_conc_mgL: float = 0.0,
    temperature_c: float = DEFAULT_TEMP_C,
    pH: float | None = None,
) -> dict[str, Any]:
    """Waste-stream volume & pollution-load calculator.

    Loads are reported in grams of N (NH4-N and total N) and, when pH is
    supplied, grams of free NH3-N (volatility / odour / inhalation driver).
    """
    vol = ensure_finite(waste_volume_l, "waste_volume_l")
    if vol < 0:
        raise MbsError(
            MbsErrorCode.NUMERIC_INVALID,
            "waste_volume_l must be >= 0.",
            detail={"field": "waste_volume_l", "value": vol},
        )
    nh4 = ensure_finite(nh4_n_conc_mgL, "nh4_n_conc_mgL")
    if nh4 < 0:
        raise MbsError(
            MbsErrorCode.NUMERIC_INVALID,
            "nh4_n_conc_mgL must be >= 0.",
            detail={"field": "nh4_n_conc_mgL", "value": nh4},
        )
    urea = ensure_finite(urea_conc_mgL, "urea_conc_mgL")
    if urea < 0:
        raise MbsError(
            MbsErrorCode.NUMERIC_INVALID,
            "urea_conc_mgL must be >= 0.",
            detail={"field": "urea_conc_mgL", "value": urea},
        )
    # Urea carries N too: g N = mg/L * vol / 1000 * (2*N/urea_mm)
    urea_n_mgL = urea * (2.0 * N_MOLAR_MASS) / UREA_MOLAR_MASS
    nh4_n_g = nh4 * vol / 1000.0
    urea_n_g = urea_n_mgL * vol / 1000.0
    total_n_g = nh4_n_g + urea_n_g
    result: dict[str, Any] = {
        "waste_volume_l": vol,
        "nh4_n_conc_mgL": nh4,
        "urea_conc_mgL": urea,
        "urea_n_conc_mgL": urea_n_mgL,
        "nh4_n_load_g": nh4_n_g,
        "urea_n_load_g": urea_n_g,
        "total_n_load_g": total_n_g,
    }
    if pH is not None:
        split = nh3_concentration(nh4, pH, temperature_c)
        result["nh3_n_load_g"] = split["nh3_n_mgL"] * vol / 1000.0
        result["nh3_fraction"] = split["nh3_fraction"]
        result["pka"] = split["pka"]
        result["pH"] = pH
    return result
