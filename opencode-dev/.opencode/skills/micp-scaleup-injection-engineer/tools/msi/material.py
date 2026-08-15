"""Material balance for MICP scale-up.

Computes, from a normalized scenario:
  - pore volume [m3] (treatment volume * effective porosity)
  - required CaCO3 mass [kg] from target content, or from lab recipe
  - required urea / Ca mols and cementation solution volume
  - NH4+/NH4-N production (1 urea -> 2 NH4+; per CaCO3 -> 2 mol NH4-N)
  - flow rate (constant flux) and total duration
  - concentration of produced NH4-N in effluent vs site discharge limit

Chemistry (ureolysis path, urease MICP):
    CO(NH2)2 + 2H2O -> 2NH4+ + CO3^2-          (urea -> 2 NH4+)
    Ca2+ + CO3^2-   -> CaCO3(s)
    => per mol CaCO3: 1 mol urea, 1 mol Ca, 2 mol NH4+ (= 2 mol NH4-N)

Literature anchors (REPORTED; see references/sources.md):
  - VP2010: >= 60 kg CaCO3/m3 for meaningful reinforcement; 30-600 kg/m3 range
  - VP2010: 1 m3 box achieved only ~12% reagent conversion -> conversion
    efficiency is a design parameter (site-scale default 0.3-0.5, adjusted by
    pilot evidence).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from .errors import OpError, OpErrorCode
from .models import (
    AMMONIUM_MOL_PER_CACO3,
    M_CaCO3,
    M_N,
    M_Urea,
    MOL_CA_PER_CACO3,
    MOL_NH4_PER_CACO3,
    MOL_UREA_PER_CACO3,
    TARGET_CACO3_CONTENT_ANCHOR_KG_M3,
)
from .scenario import NormalizedScenario
from .units import check_finite


@dataclass
class MaterialBalance:
    treatment_volume_m3: float
    pore_volume_m3: float | None
    effective_porosity: float | None
    target_caco3_content_kg_m3: float | None
    caco3_required_kg: float | None
    caco3_mol: float | None
    urea_mol: float | None
    ca_mol: float | None
    cementation_volume_m3: float | None
    bacteria_volume_m3: float | None
    total_injection_volume_m3: float | None
    nh4_n_mol: float | None
    nh4_precip_tied_mol: float | None
    nh4_n_kg: float | None
    nh4_n_conc_in_porewater_mol_m3: float | None
    nh4_n_conc_mg_L: float | None
    conversion_efficiency: float | None
    injection_flow_m3_s: float | None
    injection_duration_days: float | None
    rounds: int | None
    warnings: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "treatment_volume_m3": self.treatment_volume_m3,
            "pore_volume_m3": self.pore_volume_m3,
            "effective_porosity": self.effective_porosity,
            "target_caco3_content_kg_m3": self.target_caco3_content_kg_m3,
            "caco3_required_kg": self.caco3_required_kg,
            "caco3_mol": self.caco3_mol,
            "urea_mol": self.urea_mol,
            "ca_mol": self.ca_mol,
            "urea_kg": (self.urea_mol * M_Urea) if self.urea_mol is not None else None,
            "cementation_volume_m3": self.cementation_volume_m3,
            "bacteria_volume_m3": self.bacteria_volume_m3,
            "total_injection_volume_m3": self.total_injection_volume_m3,
            "nh4_n_mol": self.nh4_n_mol,
            "nh4_precip_tied_mol": self.nh4_precip_tied_mol,
            "nh4_n_kg": self.nh4_n_kg,
            "nh4_n_conc_in_porewater_mol_m3": self.nh4_n_conc_in_porewater_mol_m3,
            "nh4_n_conc_mg_L": self.nh4_n_conc_mg_L,
            "conversion_efficiency": self.conversion_efficiency,
            "injection_flow_m3_s": self.injection_flow_m3_s,
            "injection_duration_days": self.injection_duration_days,
            "rounds": self.rounds,
            "warnings": self.warnings,
        }


def _calc_caco3_target(s: NormalizedScenario) -> tuple[float, str | None]:
    """Required CaCO3 mass [kg]. Priority: explicit target content > lab recipe
    cumulative expectation. Returns (mass_kg, basis)."""
    if s.target_volume_m3 is None:
        return math.nan, "target_volume missing"

    if s.target_caco3_content_kg_m3 is not None:
        content = s.target_caco3_content_kg_m3
        basis = "constraints.target_caco3_content_kg_m3"
    elif (s.lab_pv_per_treatment is not None and s.lab_urea_conc_mol_m3 is not None
          and s.lab_rounds is not None and s.pore_volume_m3 is not None):
        # Lab recipe cumulative expectation: each round precipitates up to
        # urea * PV mols CaCO3 (conversion-limited).
        eff = s.conversion_efficiency or 0.5
        mol_per_round = s.lab_urea_conc_mol_m3 * s.pore_volume_m3 * eff
        content = (mol_per_round * s.lab_rounds * M_CaCO3) / s.target_volume_m3
        basis = "lab.recipe cumulative (conversion-limited)"
    else:
        # Fall back to the anchor threshold (VP2010).
        content = TARGET_CACO3_CONTENT_ANCHOR_KG_M3
        basis = f"anchor {TARGET_CACO3_CONTENT_ANCHOR_KG_M3} kg/m3 (VP2010)"
    return content, basis


def material_balance(s: NormalizedScenario, flow_override_m3_s: float | None = None) -> MaterialBalance:
    treatment_volume = s.target_volume_m3
    if treatment_volume is None or not math.isfinite(treatment_volume) or treatment_volume <= 0:
        raise OpError(
            OpErrorCode.MISSING_REQUIRED_FIELD,
            "material_balance requires target.geometry.volume (>0).",
            detail={"missing_fields": [{
                "field": "target.geometry.volume",
                "why_critical": "treatment volume drives pore volume, mass and schedule",
                "how_to_obtain": "treatment zone geometry (depth x radius / footprint)"}]},
        )

    warnings = list(getattr(s, "warnings", []) or [])
    content, basis = _calc_caco3_target(s)
    if math.isnan(content):
        raise OpError(OpErrorCode.MISSING_REQUIRED_FIELD,
                      "cannot determine required CaCO3 content: give "
                      "constraints.target_caco3_content_kg_m3 or a complete lab recipe.",
                      detail={"how_to_obtain": "specify target content, or lab.recipe with "
                              "urea_conc + pore_volumes_per_treatment + rounds"})
    content = check_finite("target_caco3_content_kg_m3", content)
    caco3_kg = content * treatment_volume
    caco3_mol = caco3_kg / M_CaCO3

    eff = s.conversion_efficiency
    if eff is None:
        # Site/pilot default conversion: 0.5 (engineering design) — REPORTED
        # anchor that the 1 m3 box achieved ~0.12 (VP2010); we design at 0.5
        # and warn the difference.
        eff = 0.5
        warnings.append(
            "conversion_efficiency not provided; design uses 0.5 (engineering default). "
            "VP2010 reports only ~12% in a 1 m3 single-point injection box — verify at pilot.")

    # Stoichiometric reagent requirement (conversion-limited).
    urea_mol = caco3_mol / eff * MOL_UREA_PER_CACO3
    ca_mol = caco3_mol / eff * MOL_CA_PER_CACO3

    # Cementation solution volume: bounded by the smaller of (urea-limited,
    # Ca-limited) — the limiting reagent defines the volume.
    cementation_volume = None
    if s.lab_urea_conc_mol_m3 is not None:
        cementation_volume = urea_mol / s.lab_urea_conc_mol_m3
    elif s.lab_ca_conc_mol_m3 is not None:
        cementation_volume = ca_mol / s.lab_ca_conc_mol_m3
    if cementation_volume is not None and cementation_volume <= 0:
        raise OpError(OpErrorCode.INVALID_SCENARIO,
                      "cementation solution volume must be positive.",
                      detail={"volume": cementation_volume})

    # Bacteria suspension volume: fraction of pore volume (field anchor:
    # Gomez 2017 used 0.5 PV injection; bacteria stage typically ~0.2-0.5 PV).
    bacteria_volume = None
    if s.pore_volume_m3 is not None:
        bacteria_volume = 0.5 * s.pore_volume_m3  # design default (0.5 PV)

    total_injection_volume = None
    if cementation_volume is not None:
        total_injection_volume = cementation_volume
        if bacteria_volume is not None:
            total_injection_volume += bacteria_volume

    # NH4+ production. Environmental accounting is CONSERVATIVE: all injected
    # urea that is delivered is assumed to hydrolyze (urease MICP), producing
    # 2 mol NH4-N per mol urea. Injected urea = caco3_mol/eff (reagent
    # requirement), so NH4-N = 2 * urea_mol = 2 * caco3_mol / eff.
    # (VP2010 observed only ~12% conversion in a 1 m3 box — at that efficiency
    # the ammonium load from the injected urea dwarfs the precipitated CaCO3.)
    nh4_n_mol = urea_mol * AMMONIUM_MOL_PER_CACO3
    nh4_precip_mol = caco3_mol * MOL_NH4_PER_CACO3  # stoichiometric tie to CaCO3
    nh4_n_kg = nh4_n_mol * M_N
    nh4_n_conc_porewater = None
    nh4_n_conc_mgL = None
    if s.pore_volume_m3 is not None and s.pore_volume_m3 > 0:
        nh4_n_conc_porewater = nh4_n_mol / s.pore_volume_m3
        nh4_n_conc_mgL = nh4_n_conc_porewater * M_N * 1e3  # mol/m3 * g/mol * 1000 = mg/L
    if (s.ammonia_limit_mg_L is not None and nh4_n_conc_mgL is not None
            and nh4_n_conc_mgL > s.ammonia_limit_mg_L):
        warnings.append(
            f"produced NH4-N in porewater {nh4_n_conc_mgL:.0f} mg/L exceeds site limit "
            f"{s.ammonia_limit_mg_L:.0f} mg/L — effluent treatment / dilution / struvite "
            "recovery is REQUIRED before discharge.")

    # Injection flow & duration: use the boundary-derived flow when the caller
    # gave none (the boundary check back-calculates a rate from the allowable
    # pressure) so the schedule is never silently zero-duration.
    flow = flow_override_m3_s if flow_override_m3_s is not None else s.lab_flow_rate_m3_s
    duration_days = None
    if flow is not None:
        flow = check_finite("injection_flow", flow)
        if total_injection_volume is not None:
            duration_days = (total_injection_volume / flow) / 86400.0
    rounds = s.lab_rounds

    return MaterialBalance(
        treatment_volume_m3=treatment_volume,
        pore_volume_m3=s.pore_volume_m3,
        effective_porosity=s.effective_porosity,
        target_caco3_content_kg_m3=content,
        caco3_required_kg=caco3_kg,
        caco3_mol=caco3_mol,
        urea_mol=urea_mol,
        ca_mol=ca_mol,
        cementation_volume_m3=cementation_volume,
        bacteria_volume_m3=bacteria_volume,
        total_injection_volume_m3=total_injection_volume,
        nh4_n_mol=nh4_n_mol,
        nh4_precip_tied_mol=nh4_precip_mol,
        nh4_n_kg=nh4_n_kg,
        nh4_n_conc_in_porewater_mol_m3=nh4_n_conc_porewater,
        nh4_n_conc_mg_L=nh4_n_conc_mgL,
        conversion_efficiency=eff,
        injection_flow_m3_s=flow,
        injection_duration_days=duration_days,
        rounds=rounds,
        warnings=warnings,
    )
