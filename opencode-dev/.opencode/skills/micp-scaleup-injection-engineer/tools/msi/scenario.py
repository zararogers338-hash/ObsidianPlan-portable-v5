"""Scenario normalization for micp-scaleup-injection-engineer.

Parses the raw input into a validated SI engineering configuration:
  - lab recipe -> SI concentrations / PV / rounds / flow
  - target scale level + geometry -> treatment volume [m3]
  - site layers -> effective porosity, permeability distribution

Key rules:
  - scale_level in {pilot_column, metre, site, field}
  - site/field scale REQUIRES site.layers with permeability per layer,
    else BLOCKED (MSI-E102) naming the missing field.
  - concentrations are validated against the design window (Al Qabany & Soga
    2013: 0.5 M optimum, >0.75 M clogging risk) but NOT auto-adjusted — the
    caller is warned, the recipe is respected.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

from .errors import OpError, OpErrorCode
from .models import (
    CACO3_CONTENT_RANGE_KG_M3,
    CONC_ECONOMIC_LOW_MOL_M3,
    CONC_OPTIMUM_MOL_M3,
    CONC_UPPER_SAFE_MOL_M3,
    SCALE_LEVELS,
)
from .units import check_finite, parse_quantity, validate_parameter


@dataclass
class Layer:
    name: str
    thickness_m: float
    d50_m: float | None = None
    fines_content: float | None = None
    porosity: float | None = None
    permeability_m2: float | None = None
    saturation: float | None = None

    def __post_init__(self) -> None:
        if self.porosity is not None:
            check_finite(f"layer.{self.name}.porosity", self.porosity)
        if self.permeability_m2 is not None:
            check_finite(f"layer.{self.name}.permeability", self.permeability_m2)


@dataclass
class NormalizedScenario:
    scale_level: str = "pilot_column"
    target_volume_m3: float | None = None
    target_depth_m: float | None = None
    target_radius_m: float | None = None
    target_length_m: float | None = None

    # lab recipe (SI)
    lab_urea_conc_mol_m3: float | None = None
    lab_ca_conc_mol_m3: float | None = None
    lab_biomass: float | None = None
    lab_pv_per_treatment: float | None = None
    lab_rounds: int | None = None
    lab_flow_mode: str | None = None
    lab_flow_rate_m3_s: float | None = None
    lab_pressure_drop_pa: float | None = None
    lab_treatment_length_m: float | None = None

    # site
    layers: list[Layer] = field(default_factory=list)
    effective_porosity: float | None = None
    effective_permeability_m2: float | None = None
    min_permeability_m2: float | None = None
    max_permeability_m2: float | None = None
    groundwater_level_m: float | None = None
    anisotropy: float | None = None
    preferential_flow_notes: str | None = None

    # constraints
    allowed_injection_pressure_pa: float | None = None
    target_caco3_content_kg_m3: float | None = None
    ammonia_limit_mg_L: float | None = None
    conversion_efficiency: float | None = None
    pulse_strategy: str | None = None
    retention_time_s: float | None = None
    flushing_pv: float | None = None

    warnings: list[str] = field(default_factory=list)

    @property
    def pore_volume_m3(self) -> float | None:
        if self.target_volume_m3 is None or self.effective_porosity is None:
            return None
        return self.target_volume_m3 * self.effective_porosity


def _q(raw: Any, key: str, param_spec: str) -> float | None:
    if raw is None:
        return None
    return validate_parameter(param_spec, raw).value_si


def _parse_layer(name: str, raw: dict[str, Any]) -> Layer:
    return Layer(
        name=name,
        thickness_m=_q(raw.get("thickness"), f"{name}.thickness", "length") or 0.0,
        d50_m=_q(raw.get("d50"), f"{name}.d50", "d50"),
        fines_content=check_finite(f"{name}.fines_content", raw["fines_content"])
        if raw.get("fines_content") is not None else None,
        porosity=check_finite(f"{name}.porosity", raw["porosity"])
        if raw.get("porosity") is not None else None,
        permeability_m2=_q(raw.get("permeability"), f"{name}.permeability", "permeability"),
        saturation=check_finite(f"{name}.saturation", raw["saturation"])
        if raw.get("saturation") is not None else None,
    )


def normalize_scenario(raw: dict[str, Any]) -> NormalizedScenario:
    s = NormalizedScenario()

    # ---- target ----
    target = raw.get("target") or {}
    s.scale_level = target.get("scale_level")
    if s.scale_level not in SCALE_LEVELS:
        raise OpError(
            OpErrorCode.INVALID_SCENARIO,
            f"target.scale_level must be one of {list(SCALE_LEVELS)}, got {s.scale_level!r}.",
            detail={"scale_level": s.scale_level, "allowed": list(SCALE_LEVELS)},
        )

    geom = target.get("geometry") or {}
    s.target_volume_m3 = _q(geom.get("volume"), "target.geometry.volume", "volume")
    s.target_depth_m = _q(geom.get("depth"), "target.geometry.depth", "depth")
    s.target_radius_m = _q(geom.get("radius"), "target.geometry.radius", "radius")
    s.target_length_m = _q(geom.get("length"), "target.geometry.length", "length")

    # ---- lab recipe ----
    recipe = (raw.get("lab") or {}).get("recipe") or {}
    if recipe:
        s.lab_urea_conc_mol_m3 = _q(recipe.get("urea_conc"), "lab.recipe.urea_conc", "concentration")
        s.lab_ca_conc_mol_m3 = _q(recipe.get("ca_conc"), "lab.recipe.ca_conc", "concentration")
        s.lab_biomass = parse_quantity(recipe["biomass"], key="lab.recipe.biomass").value \
            if recipe.get("biomass") is not None else None
        s.lab_pv_per_treatment = check_finite("lab.recipe.pore_volumes_per_treatment",
                                               recipe["pore_volumes_per_treatment"]) \
            if recipe.get("pore_volumes_per_treatment") is not None else None
        r = recipe.get("rounds")
        if r is not None:
            r = int(r)
            if r < 1:
                raise OpError(OpErrorCode.INVALID_SCENARIO, "lab.recipe.rounds must be >= 1.",
                              detail={"rounds": r})
            s.lab_rounds = r
        s.lab_flow_mode = recipe.get("flow_mode")
        s.lab_flow_rate_m3_s = _q(recipe.get("flow_rate"), "lab.recipe.flow_rate", "flow_rate")
        s.lab_pressure_drop_pa = _q(recipe.get("pressure_drop"), "lab.recipe.pressure_drop", "pressure")
        s.lab_treatment_length_m = _q(recipe.get("treatment_length"), "lab.recipe.treatment_length", "length")

        # concentration design-window warnings (Al Qabany & Soga 2013) — never
        # silently "correct" the recipe.
        for ckey, cval in (("urea", s.lab_urea_conc_mol_m3), ("calcium", s.lab_ca_conc_mol_m3)):
            if cval is None:
                continue
            if cval > CONC_UPPER_SAFE_MOL_M3:
                s.warnings.append(
                    f"lab {ckey} concentration {cval:.0f} mol/m3 exceeds the safe window "
                    f"({CONC_UPPER_SAFE_MOL_M3:.0f} mol/m3); literature (AS2013) shows "
                    ">0.75 M risks localized clogging and lower UCS. Do NOT scale this "
                    "concentration up by volume.")
            elif cval < CONC_ECONOMIC_LOW_MOL_M3:
                s.warnings.append(
                    f"lab {ckey} concentration {cval:.0f} mol/m3 is below ~100 mol/m3; "
                    "field-scale flushing would need many pore volumes (uneconomic per VP2010).")

    # ---- site layers ----
    site = raw.get("site") or {}
    layers_raw = site.get("layers")
    if layers_raw:
        for i, lr in enumerate(layers_raw):
            name = lr.get("name") or f"layer{i + 1}"
            s.layers.append(_parse_layer(name, lr))

    # ---- critical gate: site/field scale needs per-layer permeability ----
    if s.scale_level in ("site", "field"):
        if not s.layers:
            raise OpError(
                OpErrorCode.MISSING_REQUIRED_FIELD,
                f"scale_level '{s.scale_level}' requires site.layers (layer geometry + "
                "permeability). Without it, injection pressure, flow, uniformity and "
                "schedule cannot be determined.",
                detail={"missing_fields": [{
                    "field": "site.layers",
                    "why_critical": "injection pressure/flow/rate and uniformity depend on "
                                    "stratigraphy and permeability",
                    "how_to_obtain": "site investigation: boreholes, packer/falling-head or "
                                     "pumping tests per layer"}]},
            )
        missing_perm = [lyr.name for lyr in s.layers if lyr.permeability_m2 is None]
        if missing_perm:
            raise OpError(
                OpErrorCode.MISSING_REQUIRED_FIELD,
                f"scale_level '{s.scale_level}' requires permeability for every layer; "
                f"missing: {missing_perm}.",
                detail={"missing_fields": [
                    {"field": f"site.layers[{lyr}].permeability",
                     "why_critical": "Darcy flow, pressure drop and injection rate are "
                                     "proportional to permeability",
                     "how_to_obtain": "pumping / slug / falling-head test, or permeability "
                                      "probe in the borehole"}
                    for lyr in missing_perm]},
            )

    # effective porosity / permeability (thickness-weighted)
    if s.layers:
        total_h = sum(lyr.thickness_m for lyr in s.layers)
        if total_h > 0:
            por_weighted = 0.0
            por_any = False
            for lyr in s.layers:
                if lyr.porosity is not None:
                    por_weighted += lyr.porosity * lyr.thickness_m
                    por_any = True
            if por_any:
                s.effective_porosity = por_weighted / total_h
            # harmonic mean for permeability in the flow direction is conservative
            perm_list = [lyr.permeability_m2 for lyr in s.layers
                         if lyr.permeability_m2 is not None]
            if perm_list:
                inv = [lyr.thickness_m / lyr.permeability_m2 for lyr in s.layers
                       if lyr.permeability_m2 is not None]
                if all(v > 0 for v in inv):
                    s.effective_permeability_m2 = total_h / sum(inv)
                s.min_permeability_m2 = min(perm_list)
                s.max_permeability_m2 = max(perm_list)
    elif recipe:
        # pilot/metre fallback: use lab-scale permeability if provided in lab recipe
        pass

    s.groundwater_level_m = _q(site.get("groundwater_level"), "site.groundwater_level", "depth")
    anis = site.get("anisotropy")
    if anis is not None:
        s.anisotropy = check_finite("site.anisotropy", anis)
    s.preferential_flow_notes = site.get("preferential_flow_notes")

    # ---- constraints ----
    cons = raw.get("constraints") or {}
    s.allowed_injection_pressure_pa = _q(cons.get("allowed_injection_pressure"),
                                         "constraints.allowed_injection_pressure", "pressure")
    caco3 = cons.get("target_caco3_content_kg_m3")
    if caco3 is not None:
        caco3 = check_finite("constraints.target_caco3_content_kg_m3", caco3)
        lo, hi = CACO3_CONTENT_RANGE_KG_M3
        if not (lo <= caco3 <= hi):
            s.warnings.append(
                f"target CaCO3 content {caco3:.1f} kg/m3 is outside the reported range "
                f"[{lo:.0f}, {hi:.0f}] kg/m3 (VP2010); verify against site objective.")
        s.target_caco3_content_kg_m3 = caco3
    amm = cons.get("ammonia_limit_mg_L")
    if amm is not None:
        s.ammonia_limit_mg_L = check_finite("constraints.ammonia_limit_mg_L", amm)
    eff = cons.get("conversion_efficiency")
    if eff is not None:
        eff = check_finite("constraints.conversion_efficiency", eff)
        if not (0.0 < eff <= 1.0):
            raise OpError(OpErrorCode.INVALID_SCENARIO,
                          "constraints.conversion_efficiency must be in (0, 1].",
                          detail={"conversion_efficiency": eff})
        s.conversion_efficiency = eff
    s.pulse_strategy = cons.get("pulse_strategy")
    s.retention_time_s = _q(cons.get("retention_time"), "constraints.retention_time", "time")
    fl = cons.get("flushing_pv")
    if fl is not None:
        s.flushing_pv = check_finite("constraints.flushing_pv", fl)

    return s
