"""Lab–pilot–field similarity matrix for MICP scale-up.

Establishes, parameter by parameter, whether a quantity is:
  - SCALED (linear by pore volume / geometry): volume, PV, mass requirements
  - CONSERVED (must stay identical): concentration, pore velocity,
    dimensionless numbers (Pe, Da), relative retention time
  - RE-DERIVED (must be recomputed): injection flow (with cross-section),
    injection pressure (with path length & permeability), rounds (with
    residence time vs reaction time), uniformity target.

Non-scalable factors (the ones that must NEVER scale linearly by volume):
  concentrations, flow velocity, injection pressure, treatment rounds,
  uniformity, clogging behavior, gradient.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from .scenario import NormalizedScenario

# Scale-level multipliers used ONLY for illustration of geometry growth:
#   pilot_column -> metre -> site -> field (order-of-magnitude, caller sets
#   actual geometry; these are reference ratios for the similarity display).
SCALE_GEOMETRY_HINT = {
    "pilot_column": {"typical_volume_m3": 0.05, "typical_length_m": 1.0},
    "metre": {"typical_volume_m3": 1.0, "typical_length_m": 3.0},
    "site": {"typical_volume_m3": 100.0, "typical_length_m": 10.0},
    "field": {"typical_volume_m3": 1000.0, "typical_length_m": 30.0},
}


@dataclass
class SimilarityRow:
    parameter: str
    scaling_rule: str
    lab_value: Any
    pilot_value: Any
    field_value: Any
    scalable: bool
    notes: str


def _conc_label(v: float | None) -> str | None:
    return f"{v:.0f} mol/m3" if v is not None else None


def build_similarity(s: NormalizedScenario) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    non_scalable: list[dict[str, Any]] = []

    conc_urea = s.lab_urea_conc_mol_m3
    conc_ca = s.lab_ca_conc_mol_m3
    lab_rounds = s.lab_rounds
    lab_pv = s.lab_pv_per_treatment
    lab_flow = s.lab_flow_rate_m3_s
    lab_mode = s.lab_flow_mode or "constant_flux"

    # Pore velocity is conserved: v_pore = flow/(area*porosity). Across scales
    # we target the SAME pore velocity; the flow then scales with cross-section.
    pore_v = None
    if lab_flow is not None and s.target_radius_m is not None and s.effective_porosity:
        area = math.pi * s.target_radius_m ** 2
        if area > 0 and s.effective_porosity > 0:
            pore_v = lab_flow / (area * s.effective_porosity)

    rows.append({
        "parameter": "urea concentration",
        "scaling_rule": "CONSERVED (do NOT scale by volume)",
        "lab_value": _conc_label(conc_urea),
        "pilot_value": _conc_label(conc_urea),
        "field_value": _conc_label(conc_urea),
        "scalable": False,
        "notes": "AS2013: 0.5 M optimum; >0.75 M risks clogging and lower UCS",
    })
    rows.append({
        "parameter": "calcium concentration",
        "scaling_rule": "CONSERVED (do NOT scale by volume)",
        "lab_value": _conc_label(conc_ca),
        "pilot_value": _conc_label(conc_ca),
        "field_value": _conc_label(conc_ca),
        "scalable": False,
        "notes": "paired with urea 1:1 (stoichiometry); concentration window applies",
    })
    rows.append({
        "parameter": "treatment volume / pore volume",
        "scaling_rule": "SCALED (linear with geometry)",
        "lab_value": s.target_volume_m3,
        "pilot_value": None,
        "field_value": None,
        "scalable": True,
        "notes": "mass requirements and solution volumes scale linearly with pore volume",
    })
    rows.append({
        "parameter": "PV per treatment round",
        "scaling_rule": "CONSERVED (PV count)",
        "lab_value": lab_pv,
        "pilot_value": lab_pv,
        "field_value": lab_pv,
        "scalable": False,
        "notes": "PV count is dimensionless; keep the same PV per round across scales",
    })
    rows.append({
        "parameter": "pore velocity",
        "scaling_rule": "CONSERVED (m/s)",
        "lab_value": pore_v,
        "pilot_value": pore_v,
        "field_value": pore_v,
        "scalable": False,
        "notes": "conserve pore velocity; flow rate then scales with cross-sectional area",
    })
    rows.append({
        "parameter": "injection flow rate",
        "scaling_rule": "RE-DERIVED (scales with cross-section)",
        "lab_value": f"{lab_flow * 60e3:.1f} L/min" if lab_flow else None,
        "pilot_value": None,
        "field_value": None,
        "scalable": True,
        "notes": "Q = v_pore * A * phi; NOT constant — re-derive per geometry",
    })
    rows.append({
        "parameter": "treatment rounds",
        "scaling_rule": "RE-DERIVED (residence/reaction balance)",
        "lab_value": lab_rounds,
        "pilot_value": None,
        "field_value": None,
        "scalable": False,
        "notes": "rounds depend on retention time vs ureolysis rate at the target length — "
                "recompute, do not reuse the lab count",
    })
    rows.append({
        "parameter": "hydraulic gradient",
        "scaling_rule": "RE-DERIVED (pressure vs path)",
        "lab_value": None,
        "pilot_value": None,
        "field_value": None,
        "scalable": False,
        "notes": "VP2010 kept gradient < 1 in the 5 m column; gradient grows with path "
                "length for fixed velocity — the binding constraint is pressure",
    })
    rows.append({
        "parameter": "injection pressure",
        "scaling_rule": "RE-DERIVED (Darcy, path & permeability)",
        "lab_value": s.lab_pressure_drop_pa,
        "pilot_value": None,
        "field_value": None,
        "scalable": False,
        "notes": "dP grows with path length / k; cap at ~80% fracture pressure (OEGG 2017)",
    })
    rows.append({
        "parameter": "uniformity / homogeneity",
        "scaling_rule": "NEVER SCALES (degrades with scale)",
        "lab_value": "high (small specimen)",
        "pilot_value": "degraded",
        "field_value": "heterogeneous by default",
        "scalable": False,
        "notes": "VP2010 m3 box: 12% conversion, CaCO3 in corners/bottom; plan zoning + "
                "monitoring, do not expect lab uniformity",
    })

    # dimensionless anchors
    if conc_urea is not None and pore_v is not None and s.target_length_m:
        # reaction rate basis: ureolysis rate surrogate (assume ~2.5e-4 mol/m3/s
        # per unit urea for illustration of Da; do not present as measured).
        pass

    # non-scalable factors table
    non_scalable = [
        {"factor": "cementation concentration", "reason": "AS2013: 0.5 M optimum, >0.75 M "
         "reduces strength ~50% and clogs; concentration is a chemical design variable, "
         "not a volume fraction.", "action": "keep at lab-validated concentration window; "
         "verify at pilot before any change"},
        {"factor": "pore velocity", "reason": "reaction-transport balance (Pe, Da) must be "
         "preserved; scaling velocity by volume changes regime.", "action": "conserve pore "
         "velocity; scale only flow rate with cross-section"},
        {"factor": "injection pressure", "reason": "pressure rises with path length and "
         "falls with permeability; linearly scaling it invites hydrofracture.",
         "action": "recompute from Darcy; cap at ~80% fracture pressure"},
        {"factor": "treatment rounds", "reason": "rounds = f(residence time, ureolysis "
         "rate, target content); the lab count is specific to lab path length.",
         "action": "recompute rounds from material balance + retention time"},
        {"factor": "uniformity", "reason": "heterogeneity, preferential flow and clogging "
         "worsen monotonically with scale (VP2010).", "action": "zone-based treatment, "
         "flux control, monitoring wells, Vs/CPT verification"},
    ]

    return {
        "rows": rows,
        "non_scalable_factors": non_scalable,
        "conserved_quantities": ["concentration", "pore velocity", "PV count",
                                 "Pe", "Da", "relative retention time"],
        "scaled_quantities": ["volume", "pore volume", "reagent mass", "solution volumes",
                              "total injection volume"],
        "re_derived_quantities": ["flow rate", "injection pressure", "rounds", "gradient",
                                  "schedule duration"],
    }
