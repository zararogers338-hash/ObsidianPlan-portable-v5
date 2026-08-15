"""MUC constants — thermodynamic data for ureolysis + carbonate chemistry.

All values are literature-sourced; every constant carries a source tag (S#),
cross-referenced in references/sources.md. Values are the *thermodynamic*
(zero-ionic-strength) constants; the speciation engine applies activity
corrections (Davies) via activity.py.

Temperature dependence uses the van't Hoff / enthalpy form:
    K(T) = K(T0) * exp( -(dH/R) * (1/T - 1/T0) )
with T in kelvin. dH is treated as constant over the small MICP range
(10–40 °C); flagged as an assumption (moderate uncertainty).

Sources (see references/sources.md for full citations):
  S20  Plummer & Busenberg (1982)  Geochim. Cosmochim. Acta 46:1011–1040
  S21  Harned & Owen (1958), The Physical Chemistry of Electrolytic Solutions
  S22  Stumm & Morgan (1996), Aquatic Chemistry (3rd ed.)
  S23  Truesdell & Jones (1974) J. Res. U.S. Geol. Surv. 2:233
  S24  De Visscher et al. (2012) Chem. Rev. 112:3053 (for NH3/NH4+ pKa)
  S25  Krajewska (2018) J. Adv. Res. 13:59–67 (ureolysis kinetics context)
  S26  Fidaleo & Lavecchia (2003) Chem. Biochem. Eng. Q. 17:311 (urea kinetics)
  S27  Whiffin (2004) PhD thesis + Whiffin et al. (2007) Geomicrobiol. J. (MICP)
  S28  Morse, Arvidson, Luttge (2007) Chem. Rev. 107:342 (calcite kinetics)
  S29  Kitano (1962) / various — vaterite/aragonite stability
  S30  Sunagawa / Meldrum & Cölfen (2008) Chem. Rev. 108:4332 (ACC)
  S31  Davies (1962) — activity coefficient model
  S32  Plummer, Wigley, Parkhurst (1978) Am. J. Sci. 278:179 (PWP rate law)
"""

from __future__ import annotations

import math

R_GAS = 8.314462618  # J/(mol·K)
T_REF = 298.15  # K
LOG10E = math.log10(math.e)

# ---------------------------------------------------------------------------
# Water
# ---------------------------------------------------------------------------
KW_25 = 10.0 ** -13.997  # ion product of water at 25 °C (S22)
KW_DH = 55700.0  # J/mol, van't Hoff enthalpy (S22)

# ---------------------------------------------------------------------------
# Carbonic acid system (S20, Plummer & Busenberg 1982)
# ---------------------------------------------------------------------------
# First dissociation:  H2CO3* (CO2(aq) + H2CO3) -> H+ + HCO3-
PKA1_25 = 6.351
DH1 = 8300.0  # J/mol

# Second dissociation:  HCO3- -> H+ + CO3 2-
PKA2_25 = 10.329
DH2 = 14800.0  # J/mol

# Henry's constant for CO2(g) -> CO2(aq): log KH (mol/L/atm) at 25 °C (S20/S22)
LOG_KH_CO2_25 = -1.468  # log10 K_H, mol/(L·atm)
DH_CO2 = -20700.0  # J/mol  (exothermic dissolution)

# ---------------------------------------------------------------------------
# Ammonia / ammonium (S24)
# ---------------------------------------------------------------------------
# NH4+ <-> H+ + NH3(aq); pKa at 25 °C
PKA_NH4_25 = 9.245
DH_NH4 = 52360.0  # J/mol (van't Hoff over 0–50 °C)

# ---------------------------------------------------------------------------
# Urea (S26 / standard)
# ---------------------------------------------------------------------------
# Urea does not appreciably acid/base-dissociate in the MICP pH range (pKa ~ 0.1);
# treated as a neutral solute. Hydrolysis is *kinetic*, handled by kinetics.py.

# ---------------------------------------------------------------------------
# Calcite & CaCO3 polymorphs (S20)
# ---------------------------------------------------------------------------
# log Ksp at 25 °C (ion product [Ca2+][CO3 2-], molar scale)
LOG_KSP_CALCITE = -8.48  # S20
LOG_KSP_ARAGONITE = -8.30  # S20 (slightly more soluble than calcite)
LOG_KSP_VATERITE = -7.91  # S20 (most soluble crystalline form)
# Amorphous calcium carbonate (ACC): 10^-6.4 to 10^-6.7 (S30); use -6.6 nominal
LOG_KSP_ACC = -6.6

# Dissolution enthalpy for calcite (S20); used for van't Hoff correction.
DH_CALCITE = -9480.0  # J/mol  (exothermic dissolution -> Ksp decreases with T)

# Ca2+ activity coefficient corrections handled in activity.py.

# ---------------------------------------------------------------------------
# Ureolysis stoichiometry
# ---------------------------------------------------------------------------
# CO(NH2)2 + H2O -> 2 NH3 + CO2
# Stoichiometry per mol urea consumed: 2 mol NH3, 1 mol CO2.
UREA_TO_NH3 = 2.0
UREA_TO_CO2 = 1.0

# ---------------------------------------------------------------------------
# Molar masses (g/mol) for mass<->molar conversions (standard atomic weights)
# ---------------------------------------------------------------------------
MOLAR_MASS: dict[str, float] = {
    "urea": 60.06,
    "calcite": 100.09,
    "CaCl2": 110.98,
    "NH4Cl": 53.49,
    "NH3": 17.03,
    "NH4+": 18.04,
    "CO2": 44.01,
    "CaCO3": 100.09,
    "NaCl": 58.44,
    "MgCl2": 95.21,
}

# Calcite molar volume (m^3/mol)
V_M_CALCITE = 3.69e-5


# ---------------------------------------------------------------------------
# Temperature corrections
# ---------------------------------------------------------------------------
def kt_vanthoff(k_ref: float, dh: float, t_k: float) -> float:
    """van't Hoff correction: K(T) = K_ref * exp(-(dH/R)(1/T - 1/T_ref))."""
    return k_ref * math.exp(-(dh / R_GAS) * (1.0 / t_k - 1.0 / T_REF))


def pka_vanthoff(pka_ref: float, dh: float, t_k: float) -> float:
    """pKa(T) from reference pKa and enthalpy (both dissociation enthalpies are
    positive — pKa decreases with temperature)."""
    k_ref = 10.0 ** -pka_ref
    return -math.log10(kt_vanthoff(k_ref, dh, t_k))


def equilibrium_constants(t_k: float) -> dict[str, float]:
    """Compute all equilibrium constants at a given temperature (K).

    Returns a dict with keys:
      kw, pkw, ka1, pka1, ka2, pka2, kh_co2, ksp_calcite, log_ksp_calcite,
      ksp_aragonite, ksp_vaterite, ksp_acc, pka_nh4, ka_nh4, log_kh_co2
    Constants are *conditional at zero ionic strength*; activity corrections are
    applied by the speciation engine.
    """
    kw = kt_vanthoff(KW_25, KW_DH, t_k)
    ka1 = 10.0 ** -pka_vanthoff(PKA1_25, DH1, t_k)
    ka2 = 10.0 ** -pka_vanthoff(PKA2_25, DH2, t_k)
    kh = kt_vanthoff(10.0 ** LOG_KH_CO2_25, DH_CO2, t_k)
    ka_nh4 = 10.0 ** -pka_vanthoff(PKA_NH4_25, DH_NH4, t_k)
    ksp_cal = kt_vanthoff(10.0 ** LOG_KSP_CALCITE, DH_CALCITE, t_k)
    ksp_ara = kt_vanthoff(10.0 ** LOG_KSP_ARAGONITE, DH_CALCITE, t_k)
    ksp_vat = kt_vanthoff(10.0 ** LOG_KSP_VATERITE, DH_CALCITE, t_k)
    ksp_acc = 10.0 ** LOG_KSP_ACC  # ACC has no well-defined dH; fixed

    return {
        "kw": kw,
        "pkw": -math.log10(kw),
        "ka1": ka1,
        "pka1": -math.log10(ka1),
        "ka2": ka2,
        "pka2": -math.log10(ka2),
        "kh_co2": kh,
        "log_kh_co2": math.log10(kh),
        "ksp_calcite": ksp_cal,
        "log_ksp_calcite": math.log10(ksp_cal),
        "ksp_aragonite": ksp_ara,
        "ksp_vaterite": ksp_vat,
        "ksp_acc": ksp_acc,
        "pka_nh4": -math.log10(ka_nh4),
        "ka_nh4": ka_nh4,
    }
