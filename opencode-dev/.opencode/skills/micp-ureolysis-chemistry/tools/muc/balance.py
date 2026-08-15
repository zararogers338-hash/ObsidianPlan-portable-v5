"""MUC balance — elemental (atomic) and charge conservation checks.

Enforces the skill's hard acceptance rule: if elemental or charge conservation
fails, no engineering recommendation may be issued.

Urea hydrolysis stoichiometry (S10, S25):
    CO(NH2)2 + H2O  ->  2 NH3 + CO2

Conservation invariants across a closed batch:
  - Nitrogen:  N_tot = 2 * [urea] + [NH4+] + [NH3(aq)]   (urea N = 2 per molecule)
  - Carbon:    C_tot = [urea] + [CO2(aq)] + [HCO3-] + [CO3 2-] + (precipitated C)
  - Calcium:   Ca_tot = [Ca2+ free] + [CaCO3(s) precipitated]
  - Charge:    sum(z_i * c_i) = 0  (electroneutrality)

The checker compares a reported before/after state (or an instantaneous
species snapshot) against stoichiometric expectation and reports absolute and
relative residuals, in both mol and mmol/L, with machine-readable pass/fail.
"""

from __future__ import annotations

import math

from .errors import MUCError
from .units import check_finite

# Species -> (element, atoms-per-molecule) for conservation bookkeeping.
# Charge of each species used in the electroneutrality check.
_SPECIES_CHARGE: dict[str, int] = {
    "urea": 0,
    "CO2(aq)": 0,
    "HCO3-": -1,
    "CO3 2-": -2,
    "Ca2+": 2,
    "Mg2+": 2,
    "NH4+": 1,
    "NH3(aq)": 0,
    "OH-": -1,
    "H+": 1,
    "Cl-": -1,
    "Na+": 1,
    "CaCO3(s)": 0,
    "NO3-": -1,
    "H2PO4-": -1,
    "HPO4 2-": -2,
    "PO4 3-": -3,
}


def charge_of(species: str) -> int:
    return _SPECIES_CHARGE.get(species, 0)


def _n_contribution(species: str) -> float:
    """Nitrogen atoms contributed by one molecule of species (0 if none)."""
    if species in ("urea",):
        return 2.0
    if species in ("NH4+", "NH3(aq)"):
        return 1.0
    return 0.0


def _c_contribution(species: str) -> float:
    """Carbon atoms contributed by one molecule of species."""
    if species in ("urea", "CO2(aq)", "HCO3-", "CO3 2-", "CaCO3(s)"):
        return 1.0
    return 0.0


def _ca_contribution(species: str) -> float:
    if species in ("Ca2+", "CaCO3(s)"):
        return 1.0
    return 0.0


def check_elemental_balance(
    *,
    species: dict[str, float],  # concentration (mol/L) of each species
    total_n: float | None = None,  # externally supplied N total (mol/L)
    total_c: float | None = None,
    total_ca: float | None = None,
    tol_rel: float = 1e-6,
) -> dict:
    """Check elemental (N, C, Ca) conservation across a species snapshot.

    If a *total* is supplied, the checker validates that the species sum equals
    it. If not supplied, the checker reports the implied total from the species
    (self-consistency) and flags only imbalances that violate stoichiometry of
    the ureolysis reaction (see check_ureolysis_stoichiometry).
    """
    for nm, v in species.items():
        check_finite(v, f"species.{nm}")
    if any(v < 0 for v in species.values()):
        raise MUCError(
            "MUC-E2002",
            "negative species concentration in elemental balance — infeasible system",
        )

    n_from_species = sum(_n_contribution(k) * v for k, v in species.items())
    c_from_species = sum(_c_contribution(k) * v for k, v in species.items())
    ca_from_species = sum(_ca_contribution(k) * v for k, v in species.items())

    def _cmp(name: str, computed: float, total: float | None) -> dict:
        if total is None:
            return {"name": name, "computed": computed, "total": None, "passed": True,
                    "abs_residual": 0.0, "rel_residual": 0.0, "note": "no external total; self-consistent"}
        residual = computed - total
        rel = residual / total if abs(total) > 1e-300 else float("inf")
        passed = abs(rel) <= tol_rel
        return {
            "name": name,
            "computed": computed,
            "total": total,
            "passed": passed,
            "abs_residual": residual,
            "rel_residual": rel,
            "note": "ok" if passed else f"|rel|={abs(rel):.2e} > tol {tol_rel:.0e}",
        }

    result = {
        "N": _cmp("N", n_from_species, total_n),
        "C": _cmp("C", c_from_species, total_c),
        "Ca": _cmp("Ca", ca_from_species, total_ca),
    }
    result["passed"] = all(result[k]["passed"] for k in ("N", "C", "Ca"))
    return result


def check_charge_balance(species: dict[str, float], tol_rel: float = 1e-6) -> dict:
    """Electroneutrality: sum(z_i c_i) = 0."""
    for nm, v in species.items():
        check_finite(v, f"species.{nm}")
    total = 0.0
    for k, v in species.items():
        total += charge_of(k) * v
    # Scale for the relative residual: use the sum of positive charge magnitude.
    pos = sum(max(charge_of(k), 0) * v for k, v in species.items())
    base = max(pos, 1e-30)
    rel = total / base
    return {
        "charge_imbalance_eq_L": total,
        "rel_charge_imbalance": rel,
        "passed": abs(rel) <= tol_rel,
        "note": "ok" if abs(rel) <= tol_rel else f"rel charge imbalance {rel:.2e} > tol",
    }


def check_ureolysis_stoichiometry(
    *,
    urea_hydrolyzed: float,  # mol/L urea consumed
    co2_produced: float | None = None,  # mol/L CO2 produced
    nh3_produced: float | None = None,  # mol/L NH3 produced (NH3 + NH4)
) -> dict:
    """Check that the ureolysis products match the 1:1:2 stoichiometry.

    CO(NH2)2 + H2O -> 2 NH3 + CO2
    So: n(NH3 total produced) == 2 * n(urea hydrolyzed),
        n(CO2 total produced) == 1 * n(urea hydrolyzed).
    """
    if urea_hydrolyzed < 0:
        raise MUCError("MUC-E2004", f"check_ureolysis_stoichiometry: negative urea_hydrolyzed {urea_hydrolyzed}")
    out: dict = {}
    out["urea_hydrolyzed"] = urea_hydrolyzed
    if co2_produced is not None:
        expected = urea_hydrolyzed * 1.0
        out["co2_expected"] = expected
        out["co2_actual"] = co2_produced
        out["co2_passed"] = abs(co2_produced - expected) <= max(1e-9, abs(expected) * 1e-6)
    if nh3_produced is not None:
        expected = urea_hydrolyzed * 2.0
        out["nh3_expected"] = expected
        out["nh3_actual"] = nh3_produced
        out["nh3_passed"] = abs(nh3_produced - expected) <= max(1e-9, abs(expected) * 1e-6)
    out["passed"] = all(out.get(k, True) for k in ("co2_passed", "nh3_passed"))
    return out


def ureolysis_product_amounts(urea_hydrolyzed: float) -> dict:
    """Stoichiometric product amounts for a given urea conversion."""
    return {
        "urea_hydrolyzed": urea_hydrolyzed,
        "CO2_produced": urea_hydrolyzed,
        "NH3_produced": 2.0 * urea_hydrolyzed,
        "NH4_max_from_ammonia": 2.0 * urea_hydrolyzed,
    }
