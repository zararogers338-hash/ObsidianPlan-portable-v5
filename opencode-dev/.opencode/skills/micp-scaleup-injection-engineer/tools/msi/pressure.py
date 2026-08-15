"""Boundary (constant-flux vs constant-head) checks and injection-pressure risk.

Engineering rules (REPORTED anchors in references/sources.md):
  - Constant-flux (constant rate): as clogging reduces permeability the
    pressure rises for a given rate; the binding constraint is the allowable
    injection pressure. Risky near inlet clogging.
  - Constant-head (constant pressure): as permeability falls the flow rate
    decays; the binding constraint is treatment time and uniformity (front
    slows). Preferable when formation is delicate.
  - Fracture pressure ~ 2x overburden (classic borehole criterion); modern
    grouting caps injection pressure at ~80% of measured fracture pressure
    (OEGG 2017), with low rates (5-15 L/min) and volume-limited rounds.

Darcy radial/longitudinal pressure drop for a homogeneous equivalent layer:
    dP = (Q * mu * L) / (k * A)            [1D]
    dP = (Q * mu) / (2 * pi * k * H) * ln(r2/r1)   [radial to extraction]
where Q [m3/s], mu [Pa s] ~ 1.0e-3 water, L [m], A [m2], k [m2].
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from .errors import OpError, OpErrorCode
from .models import (
    CLOG_PRESSURE_WARNING_FRACTION,
    FLOW_RATE_HIGH_M3_S,
    FLOW_RATE_LOW_M3_S,
    FRAC_PRESSURE_OVERBURDEN_FACTOR,
    MAX_HYDRAULIC_GRADIENT_PILOT,
    SAFE_INJECTION_FRACTION_OF_FRAC,
)
from .scenario import NormalizedScenario
from .units import check_finite

MU_WATER_PA_S = 1.002e-3
RHO_WATER_KG_M3 = 1000.0


@dataclass
class BoundaryCheck:
    flow_mode: str
    darcy_velocity_m_s: float | None
    injection_flow_m3_s: float | None
    hydraulic_gradient: float | None
    pressure_drop_pa: float | None
    pressure_drop_bar: float | None
    overburden_pressure_pa: float | None
    fracture_pressure_pa: float | None
    safe_limit_pa: float | None
    allowable_pressure_pa: float | None
    margin_ratio: float | None
    clogging_warning: bool
    verdict: str
    notes: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "flow_mode": self.flow_mode,
            "darcy_velocity_m_s": self.darcy_velocity_m_s,
            "injection_flow_m3_s": self.injection_flow_m3_s,
            "hydraulic_gradient": self.hydraulic_gradient,
            "pressure_drop_pa": self.pressure_drop_pa,
            "pressure_drop_bar": self.pressure_drop_bar,
            "overburden_pressure_pa": self.overburden_pressure_pa,
            "fracture_pressure_pa": self.fracture_pressure_pa,
            "safe_limit_pa": self.safe_limit_pa,
            "allowable_pressure_pa": self.allowable_pressure_pa,
            "margin_ratio": self.margin_ratio,
            "clogging_warning": self.clogging_warning,
            "verdict": self.verdict,
            "notes": self.notes,
        }


def _derive_injection_area(s: NormalizedScenario) -> float | None:
    """Cross-sectional / characteristic area [m2] for Darcy flow."""
    if s.target_radius_m is not None:
        return math.pi * s.target_radius_m ** 2
    if s.target_length_m is not None and s.target_depth_m is not None:
        return s.target_length_m * s.target_depth_m
    if s.target_volume_m3 is not None and s.target_length_m is not None:
        return s.target_volume_m3 / s.target_length_m
    return None


def boundary_check(s: NormalizedScenario) -> BoundaryCheck:
    notes: list[str] = []
    mode = s.lab_flow_mode or "constant_flux"

    k = s.effective_permeability_m2
    area = _derive_injection_area(s)
    length = s.target_length_m or s.target_depth_m

    # ---- flow rate ----
    flow = s.lab_flow_rate_m3_s
    darcy_v = None
    if flow is None and k is not None and area is not None and length is not None and s.allowed_injection_pressure_pa is not None:
        # Back-calculate a rate that keeps pressure under the allowable limit.
        flow = (s.allowed_injection_pressure_pa * k * area) / (MU_WATER_PA_S * length)
        notes.append("injection rate not given: back-calculated from allowable pressure "
                     "so that dP ~ allowable (Darcy).")
    if flow is not None:
        flow = check_finite("flow", flow)
        if area is not None and area > 0:
            darcy_v = flow / area
        if not (FLOW_RATE_LOW_M3_S - 1e-12 <= flow <= FLOW_RATE_HIGH_M3_S + 1e-12):
            notes.append(
                f"injection rate {flow * 60e3:.1f} L/min is outside the practical 5-15 L/min "
                "field range (OEGG 2017); field pumps may not deliver this uniformly.")

    # ---- pressure drop ----
    pressure_drop = None
    gradient = None
    if flow is not None and k is not None and area is not None and length is not None:
        if k > 0 and area > 0 and length > 0:
            pressure_drop = (flow * MU_WATER_PA_S * length) / (k * area)
            gradient = pressure_drop / (RHO_WATER_KG_M3 * 9.81 * length) if length > 0 else None

    # ---- overburden / fracture / safe limits ----
    overburden = None
    frac_pressure = None
    safe_limit = None
    if s.target_depth_m is not None:
        # Assume saturated bulk density ~ 2000 kg/m3 for shallow ground
        overburden = s.target_depth_m * 2000.0 * 9.81
        frac_pressure = overburden * FRAC_PRESSURE_OVERBURDEN_FACTOR
        safe_limit = frac_pressure * SAFE_INJECTION_FRACTION_OF_FRAC
    allowable = s.allowed_injection_pressure_pa
    if allowable is None:
        allowable = safe_limit  # fallback: 80% of estimated fracture pressure
        if allowable is not None:
            notes.append("allowed_injection_pressure not provided: used 80% of estimated "
                         "fracture pressure (2x overburden) — VERIFY by in-situ frac test.")

    # ---- margin ----
    margin = None
    if pressure_drop is not None and allowable is not None and allowable > 0:
        margin = allowable / pressure_drop
    clogging_warning = False
    if pressure_drop is not None and allowable is not None and allowable > 0:
        clogging_warning = pressure_drop > allowable * CLOG_PRESSURE_WARNING_FRACTION

    # ---- verdict ----
    if pressure_drop is None or allowable is None:
        verdict = "incomplete"
        notes.append("cannot reach a pressure verdict without permeability and/or "
                     "allowable pressure.")
    elif pressure_drop > allowable:
        verdict = "EXCEEDS"
    elif clogging_warning:
        verdict = "MARGINAL"
    else:
        verdict = "OK"

    if mode == "constant_head":
        notes.append("constant-head boundary: as clogging builds, flow decays; the binding "
                     "constraint is treatment time/uniformity, not peak pressure. Volume per "
                     "round should be capped to control spread (grouting practice).")
    else:
        notes.append("constant-flux boundary: as clogging builds, pressure rises for fixed "
                     "rate; monitor inlet pressure closely (inlet clogging is the classic "
                     "MICP failure mode, VP2010).")

    return BoundaryCheck(
        flow_mode=mode,
        darcy_velocity_m_s=darcy_v,
        injection_flow_m3_s=flow,
        hydraulic_gradient=gradient,
        pressure_drop_pa=pressure_drop,
        pressure_drop_bar=(pressure_drop / 1e5) if pressure_drop is not None else None,
        overburden_pressure_pa=overburden,
        fracture_pressure_pa=frac_pressure,
        safe_limit_pa=safe_limit,
        allowable_pressure_pa=allowable,
        margin_ratio=margin,
        clogging_warning=clogging_warning,
        verdict=verdict,
        notes=notes,
    )
