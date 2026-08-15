"""Clogging risk and uniformity assessment for MICP scale-up.

Signals assessed:
  - inlet clogging risk: high concentration (>0.75 M), high gradient, fine
    sand (low d50), high fines, high aspect ratio (long path vs radius).
  - preferential-flow / bypass risk: permeability contrast between layers,
    anisotropy, low saturation.
  - uniformity estimator: combines contrast/anisotropy/concentration signals
    into a qualitative uniformity score with a verdict.

Literature anchors:
  - AS2013: >0.5-0.75 M causes localized clogging; 1 M drops permeability fast.
  - VP2010: inlet clogging is the classic failure; sequential injection +
    low gradient (<1) mitigated it in the 5 m column.
  - WN2020: pore-throat clogging dominates permeability loss (effective
    porosity), not bulk porosity.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from .errors import OpError, OpErrorCode
from .models import CONC_OPTIMUM_MOL_M3, CONC_UPPER_SAFE_MOL_M3, MAX_HYDRAULIC_GRADIENT_PILOT
from .scenario import NormalizedScenario
from .units import check_finite


@dataclass
class CloggingRisk:
    inlet_clogging_risk: str      # LOW / MEDIUM / HIGH
    preferential_flow_risk: str   # LOW / MEDIUM / HIGH
    uniformity_score: float       # 0..1 (higher = more uniform expected)
    uniformity_verdict: str
    drivers: list[str]
    mitigations: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "inlet_clogging_risk": self.inlet_clogging_risk,
            "preferential_flow_risk": self.preferential_flow_risk,
            "uniformity_score": self.uniformity_score,
            "uniformity_verdict": self.uniformity_verdict,
            "drivers": self.drivers,
            "mitigations": self.mitigations,
        }


def _risk_label(x: float) -> str:
    if x >= 0.66:
        return "HIGH"
    if x >= 0.33:
        return "MEDIUM"
    return "LOW"


def clogging_risk(s: NormalizedScenario) -> CloggingRisk:
    drivers: list[str] = []
    mitigations: list[str] = []

    # ---- inlet clogging ----
    inlet_score = 0.0
    n_signal = 0

    # concentration signal (AS2013)
    conc = None
    if s.lab_urea_conc_mol_m3 is not None:
        conc = s.lab_urea_conc_mol_m3
    elif s.lab_ca_conc_mol_m3 is not None:
        conc = s.lab_ca_conc_mol_m3
    if conc is not None:
        n_signal += 1
        if conc > CONC_UPPER_SAFE_MOL_M3:
            inlet_score += 1.0
            drivers.append(f"cementation concentration {conc:.0f} mol/m3 > {CONC_UPPER_SAFE_MOL_M3:.0f} "
                           "(localized clogging window, AS2013)")
        elif conc > CONC_OPTIMUM_MOL_M3:
            inlet_score += 0.6
            drivers.append(f"concentration {conc:.0f} mol/m3 above the 0.5 M optimum (AS2013)")

    # gradient signal (VP2010: gradient < 1 in the successful 5 m column)
    if s.lab_flow_rate_m3_s is not None and s.effective_permeability_m2 is not None and s.target_length_m:
        k = s.effective_permeability_m2
        area = None
        if s.target_radius_m is not None:
            area = math.pi * s.target_radius_m ** 2
        elif s.target_volume_m3 is not None and s.target_length_m is not None:
            area = s.target_volume_m3 / s.target_length_m
        if area:
            length = s.target_length_m or s.target_depth_m or 1.0
            dP = (s.lab_flow_rate_m3_s * 1.002e-3 * length) / (k * area)
            grad = dP / (1000.0 * 9.81 * length)
            n_signal += 1
            if grad > MAX_HYDRAULIC_GRADIENT_PILOT:
                inlet_score += 1.0
                drivers.append(f"hydraulic gradient ~{grad:.2f} > {MAX_HYDRAULIC_GRADIENT_PILOT} "
                               "(VP2010 kept gradient < 1)")
            elif grad > 0.3:
                inlet_score += 0.5

    # fines / d50 signal
    fines = max((lyr.fines_content or 0.0) for lyr in s.layers) if s.layers else None
    if fines is not None and fines > 0.15:
        n_signal += 1
        inlet_score += 0.7
        drivers.append(f"fines content up to {fines * 100:.0f}% — bacteria straining and "
                       "pore-throat clogging risk (bacteria 0.5-3 um, VP2010)")

    # aspect ratio (long treatment path vs injection radius) — long paths
    # concentrate precipitation near the inlet.
    if s.target_length_m is not None and s.target_radius_m is not None and s.target_radius_m > 0:
        ar = s.target_length_m / s.target_radius_m
        if ar > 10:
            n_signal += 1
            inlet_score += 0.5
            drivers.append(f"aspect ratio {ar:.0f} (length/radius): long single-point path "
                           "concentrates calcite near inlet (VP2010 m3 box)")

    inlet_norm = inlet_score / max(n_signal, 1)
    inlet_label = _risk_label(inlet_norm)

    # ---- preferential flow ----
    pref_score = 0.0
    n_pref = 0
    if s.layers and len(s.layers) >= 2:
        perms = [lyr.permeability_m2 for lyr in s.layers if lyr.permeability_m2 is not None]
        if len(perms) >= 2 and min(perms) > 0:
            n_pref += 1
            contrast = max(perms) / min(perms)
            if contrast >= 10:
                pref_score += 1.0
                drivers.append(f"inter-layer permeability contrast ~{contrast:.0f}x — "
                               "preferential flow through the most permeable layer (bypass)")
            elif contrast >= 3:
                pref_score += 0.5
                drivers.append(f"inter-layer permeability contrast ~{contrast:.0f}x")
    if s.anisotropy is not None:
        n_pref += 1
        if s.anisotropy >= 10:
            pref_score += 1.0
            drivers.append(f"anisotropy (kh/kv) ~{s.anisotropy:.0f} — horizontal channelling")
        elif s.anisotropy >= 3:
            pref_score += 0.5
    if s.preferential_flow_notes:
        n_pref += 1
        pref_score += 0.8
        drivers.append(f"caller-reported preferential flow: {s.preferential_flow_notes}")
    saturations = [lyr.saturation for lyr in s.layers if lyr.saturation is not None]
    if saturations and min(saturations) < 0.7:
        n_pref += 1
        pref_score += 0.6
        drivers.append(f"partial saturation (min {min(saturations) * 100:.0f}%) — "
                       "wetting-front instability and uneven cementation")
    pref_norm = pref_score / max(n_pref, 1)
    pref_label = _risk_label(pref_norm)

    # ---- uniformity score ----
    # Uniformity degrades with scale (VP2010: 1 m3 box achieved 12% conversion
    # with calcite concentrated at corners/bottom; lab uniformity is NOT
    # representative). Penalty grows with scale level.
    scale_penalty = {
        "pilot_column": 0.0,
        "metre": 0.15,
        "site": 0.30,
        "field": 0.45,
    }.get(s.scale_level, 0.15)
    uniformity = max(0.0, 1.0 - 0.5 * inlet_norm - 0.5 * pref_norm - scale_penalty)
    if uniformity >= 0.66:
        uverdict = "likely uniform (pilot-verifiable)"
    elif uniformity >= 0.33:
        uverdict = "moderately heterogeneous — zoning/flux control advised"
    else:
        uverdict = "expected strongly heterogeneous — zone-based treatment + monitoring required"
    if scale_penalty > 0:
        drivers.append(f"scale penalty {scale_penalty:.2f} (uniformity degrades with "
                       f"scale — VP2010)")

    # mitigations
    if inlet_label != "LOW":
        mitigations.extend([
            "lower cementation concentration toward 0.5 M (AS2013)",
            "reduce injection rate / use pulsed injection to lower peak gradient",
            "sequential bacteria+fixation injection (VP2010)",
        ])
    if pref_label != "LOW":
        mitigations.extend([
            "zone-based (layer-selective) injection with packers",
            "balanced extraction to pull flow through low-k layers",
            "perforated intervals per layer rather than a single screen",
        ])

    return CloggingRisk(
        inlet_clogging_risk=inlet_label,
        preferential_flow_risk=pref_label,
        uniformity_score=round(uniformity, 3),
        uniformity_verdict=uverdict,
        drivers=drivers,
        mitigations=mitigations,
    )
