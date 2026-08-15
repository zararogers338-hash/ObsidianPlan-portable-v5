"""MUC activity — activity coefficients for ionic-strength correction.

Davies equation (S31) for single-ion activity coefficients at 25 °C:

    log10(gamma_i) = -A z_i^2 ( sqrt(I)/(1+sqrt(I)) - 0.3 I )

with A = 0.509 (molal scale, 25 °C). The Davies form avoids species-specific
ion-size parameters, which is the right trade for a transportable MICP model
with modest salinity. Ionic strength I is on the MOLAR scale (mol/L).

Limits: valid roughly I < 0.5 M. Beyond that the model degrades; the skill
flags high-I inputs as a warning rather than silently extrapolating.

Uncharged species (urea, CO2(aq), NH3(aq)) get gamma = 1 (Setchenow constants
for CO2/NH3 are known but ignored at MICP-relevant ionic strengths; flagged).
"""

from __future__ import annotations

import math

from .errors import MUCError

# Debye–Hückel limiting coefficient at 25 °C, molar scale (S22/S31).
A_DEBYE = 0.509

# Species charge for activity corrections (S31).
_CHARGES: dict[str, int] = {
    "H+": 1,
    "OH-": -1,
    "Ca2+": 2,
    "Mg2+": 2,
    "Na+": 1,
    "K+": 1,
    "Cl-": -1,
    "NH4+": 1,
    "HCO3-": -1,
    "CO3 2-": -2,
    "NO3-": -1,
    "PO4 3-": -3,
    "HPO4 2-": -2,
    "H2PO4-": -1,
}


def charge_of(species: str) -> int:
    return _CHARGES.get(species, 0)


def ionic_strength_from_concs(
    concs: dict[str, float],
    charge: dict[str, int] | None = None,
) -> float:
    """Ionic strength I = 0.5 * sum(c_i z_i^2), concentrations in mol/L."""
    if charge is None:
        charge = {k: charge_of(k) for k in concs}
    total = 0.0
    for k, c in concs.items():
        if c < 0:
            raise MUCError("MUC-E2004", f"ionic_strength: negative concentration for {k}")
        z = charge.get(k, 0)
        total += c * z * z
    return 0.5 * total


def davies_log10_gamma(z: int, ionic_strength: float, t_k: float = 298.15) -> float:
    """log10 of single-ion activity coefficient by the Davies equation.

    Temperature enters only through A(T) ≈ A(25 °C) * (298.15/T)^(3/2) for the
    dielectric term; the 0.3·I term is empirical and T-independent.
    """
    if ionic_strength < 0:
        raise MUCError("MUC-E2004", f"davies: negative ionic strength {ionic_strength}")
    # A(T) scaling (S22)
    a_t = A_DEBYE * math.pow(298.15 / t_k, 1.5)
    sq = math.sqrt(ionic_strength)
    return -a_t * z * z * (sq / (1.0 + sq) - 0.3 * ionic_strength)


def activity_coefficient(species: str, ionic_strength: float, t_k: float = 298.15) -> float:
    """Activity coefficient for a species at given ionic strength (Davies)."""
    if species in ("urea", "CO2(aq)", "NH3(aq)", "H2CO3*", "H2O"):
        return 1.0  # neutral species
    z = charge_of(species)
    if z == 0:
        return 1.0
    return 10.0 ** davies_log10_gamma(z, ionic_strength, t_k)


def compute_activities(
    concs: dict[str, float],
    charge: dict[str, int] | None = None,
    t_k: float = 298.15,
) -> dict[str, float]:
    """Given molar concentrations, return activities a_i = gamma_i * c_i."""
    if charge is None:
        charge = {k: charge_of(k) for k in concs}
    I = ionic_strength_from_concs(concs, charge)
    out: dict[str, float] = {}
    for k, c in concs.items():
        if k in ("urea", "H2O"):
            out[k] = c
            continue
        g = activity_coefficient(k, I, t_k)
        out[k] = g * c
    return out


def check_ionic_strength_ok(I: float) -> None:
    """Warn-boundary: Davies degrades above ~0.5 M."""
    if I > 0.5:
        raise MUCError(
            "MUC-E2004",
            f"ionic strength {I:.3f} M exceeds the Davies-equation validity bound "
            "(~0.5 M); results carry elevated activity-coefficient uncertainty",
        )
