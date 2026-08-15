"""Scenario normalization: raw scenario dict -> validated, SI, solver-ready.

The scenario is the domain payload of the skill (geometry, porosity, particle
size, saturation, flow/pressure boundary, initial permeability, scale). It is
validated here against physical ranges/units (via units.validate_parameter) and
against completeness. Missing key boundary conditions raise MODEL_BLOCKED
(OPM-E102) — the service maps that to status BLOCKED with per-field guidance
(spec §十一: 缺失字段、为何关键、如何获得).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .errors import OpError, OpErrorCode
from .solver import SolverConfig
from .units import parse_quantity, validate_parameter

# Required scenario keys -> (why critical, how to obtain).
_REQUIRED = {
    "geometry": "确定流动维度与空间尺度;缺少则无法建立网格与网格敏感性与守恒误差",
    "porosity": "初始孔隙率 phi0,是 Kozeny-Carman 渗透率演化的基线;缺少则模型无法闭合",
    "flow": "流量或压力边界(恒流/恒压);缺少则对流输运不可定义",
    "permeability": "初始渗透率 K0;缺少则无法演化渗透率与评估堵塞",
    "species": "参与输运的溶质与生物量;缺少则无反应-输运耦合",
}

# Geometry sub-fields (all SI after validation).
_GEOMETRY_KEYS = ("length", "diameter", "nx")

# Flow sub-fields.
_FLOW_KEYS = ("velocity", "flux", "p_in", "p_out", "mu", "mode")


@dataclass
class NormalizedScenario:
    geometry: dict[str, float] = field(default_factory=dict)   # length_m, diameter_m, nx
    porosity: float = 0.0
    permeability: float = 0.0          # intrinsic [m2]
    flow_mode: str = "flux"            # "flux" | "head"
    velocity: float | None = None      # m/s (flux mode)
    p_in: float | None = None          # Pa
    p_out: float | None = None         # Pa
    mu: float = 1e-3                   # Pa·s
    species: dict[str, float] = field(default_factory=dict)    # c_urea_in, c_ca_in, c_biomass, etc.
    scale: str = "column"              # column | sand-pack | core | field
    validation: dict[str, Any] = field(default_factory=dict)   # param -> DimensionedParam dict
    raw: dict[str, Any] = field(default_factory=dict)

    def to_solver_config(self, *, k_ure: float, k_pre: float, k_half: float,
                         t_end: float | None, clog_threshold: float,
                         dt: float | None = None) -> SolverConfig:
        """Build a SolverConfig from the normalized scenario.

        Derives a conservative default dispersion from length and velocity
        (0.1 * v * L, capped) if the caller does not supply one.
        """
        L = self.geometry["length_m"]
        nx = int(self.geometry.get("nx", 64))
        v = self.velocity if self.velocity is not None else 0.0
        D = 0.1 * v * L if v > 0 else 1e-9
        return SolverConfig(
            length=L,
            nx=nx,
            porosity0=self.porosity,
            velocity=v,
            dispersion=D,
            k_ure=k_ure,
            k_pre=k_pre,
            k_half=k_half,
            c_ca_in=self.species.get("c_ca_in", 0.0),
            c_urea_in=self.species.get("c_urea_in", 0.0),
            c_biomass=self.species.get("c_biomass", 1.0),
            k_perm0=self.permeability,
            bc_type=self.flow_mode,
            p_in=self.p_in or 0.0,
            p_out=self.p_out or 0.0,
            mu_water=self.mu,
            t_end=t_end,
            clog_threshold=clog_threshold,
            dt=dt,
            c_ca0=self.species.get("c_ca0", 0.0),
            c_urea0=self.species.get("c_urea0", 0.0),
        )


def check_required(scenario: dict[str, Any]) -> list[dict[str, str]]:
    """Return missing required scenario fields with guidance (MODEL_BLOCKED)."""
    missing = []
    for key in _REQUIRED:
        if key not in scenario or scenario[key] is None:
            missing.append({
                "field": key,
                "why_critical": _REQUIRED[key],
                "how_to_obtain": _obtain_hint(key),
            })
    return missing


def _obtain_hint(key: str) -> str:
    hints = {
        "geometry": "column length/diameter and grid nx from the experiment design (e.g. 10 cm x 3 cm); "
                    "nx defaults to 64 if absent",
        "porosity": "dry/wet density measurement, or saturation-method porosity; typical clean sand 0.3-0.45",
        "flow": "pump rate Q (m3/s) over cross-section A gives velocity u=Q/A; or inlet/outlet pressures",
        "permeability": "constant-head permeameter, falling-head test, or Kozeny-Carman estimate from d50 and phi0",
        "species": "influent concentrations (urea, CaCl2) and injected OD/CFU of S. pasteurii; convert to kg/m3",
    }
    return hints.get(key, "from the experiment design / controller context")


def normalize_scenario(scenario: dict[str, Any]) -> NormalizedScenario:
    """Validate and normalize a scenario dict into SI solver inputs.

    Raises OPM-E102 (MODEL_BLOCKED) for missing key boundary conditions and
    OPM-E204 / OPM-E202 / OPM-E203 for out-of-range / unit / parse problems.
    """
    missing = check_required(scenario)
    if missing:
        raise OpError(
            OpErrorCode.MISSING_REQUIRED_FIELD,
            "Scenario is missing key boundary conditions required to build the model.",
            detail={"missing_fields": missing},
        )

    # geometry
    geometry_raw = scenario.get("geometry") or {}
    geom: dict[str, float] = {}
    if "length" not in geometry_raw:
        raise OpError(OpErrorCode.MISSING_REQUIRED_FIELD,
                      "scenario.geometry.length is required (domain length).",
                      detail={"missing_fields": [{
                          "field": "geometry.length",
                          "why_critical": "spatial scale for the mesh and dimensionless analysis",
                          "how_to_obtain": "column length from the experiment design"}]})
    for key in ("length", "diameter"):
        if key in geometry_raw:
            p = validate_parameter("length", geometry_raw[key])
            geom["length_m" if key == "length" else "diameter_m"] = p.value_si
    geom["nx"] = int(geometry_raw.get("nx", 64))
    if geom["nx"] < 8:
        raise OpError(OpErrorCode.RANGE_OUT_OF_BOUNDS,
                      "geometry.nx must be >= 8.", detail={"nx": geom["nx"]})

    # porosity
    porosity = validate_parameter("porosity", scenario["porosity"]).value_si

    # permeability (intrinsic, m2)
    perm_raw = scenario["permeability"]
    if isinstance(perm_raw, dict) and perm_raw.get("kind") == "hydraulic":
        # hydraulic conductivity K [m/s] -> intrinsic k = K*mu/(rho*g) with
        # default water; requires rho, g, mu.
        raise OpError(
            OpErrorCode.UNIT_INCONSISTENT,
            "Hydraulic-conductivity input requires rho, g, and mu to convert to intrinsic "
            "permeability. Provide intrinsic permeability in m2, or include fluid density.",
            detail={"how_to_fix": "pass permeability as intrinsic m2, or add fluid density/gravity/mu"},
        )
    perm = validate_parameter("permeability_abs", perm_raw).value_si

    # flow
    flow_raw = scenario.get("flow") or {}
    mode = flow_raw.get("mode", "flux")
    if mode not in ("flux", "head"):
        raise OpError(OpErrorCode.INPUT_SCHEMA_VIOLATION,
                      f"flow.mode must be 'flux' or 'head', got {mode!r}.",
                      detail={"mode": mode})
    velocity = None
    p_in = p_out = None
    if mode == "flux":
        if "velocity" not in flow_raw and "flux" not in flow_raw:
            raise OpError(
                OpErrorCode.MISSING_REQUIRED_FIELD,
                "Constant-flux BC requires flow.velocity or flow.flux (Darcy velocity).",
                detail={"missing_fields": [{
                    "field": "flow.velocity/flux",
                    "why_critical": "advective transport and CFL time step depend on the flow rate",
                    "how_to_obtain": "pump rate Q / cross-section A (u=Q/A)"}]})
        key = "velocity" if "velocity" in flow_raw else "flux"
        velocity = validate_parameter(key, flow_raw[key]).value_si
    else:
        if "p_in" not in flow_raw or "p_out" not in flow_raw:
            raise OpError(
                OpErrorCode.MISSING_REQUIRED_FIELD,
                "Constant-head BC requires flow.p_in and flow.p_out.",
                detail={"missing_fields": [{
                    "field": "flow.p_in/p_out",
                    "why_critical": "pressure gradient drives Darcy flow; with evolving "
                                    "permeability this is what couples clogging to flow",
                    "how_to_obtain": "pump/manometer readings at inlet and outlet"}]})
        p_in = validate_parameter("pressure", flow_raw["p_in"]).value_si
        p_out = validate_parameter("pressure", flow_raw["p_out"]).value_si
    mu = 1e-3
    if "mu" in flow_raw:
        # dynamic viscosity [Pa·s]: dimensionally L^-1 M T^-1; the pressure
        # table shares (L,T,M) exponents and Pa is the correct family here.
        mu = validate_parameter("pressure", flow_raw["mu"]).value_si

    # species
    species_raw = scenario.get("species") or {}
    species: dict[str, float] = {}
    for key in ("c_urea_in", "c_ca_in", "c_urea0", "c_ca0"):
        if key in species_raw:
            species[key] = validate_parameter("concentration", species_raw[key]).value_si
    if "c_biomass" in species_raw:
        species["c_biomass"] = validate_parameter("density", species_raw["c_biomass"]).value_si

    scale = str(scenario.get("scale", "column"))

    validation = {k: p for k, p in _validated_params(scenario).items()}
    return NormalizedScenario(
        geometry=geom,
        porosity=porosity,
        permeability=perm,
        flow_mode=mode,
        velocity=velocity,
        p_in=p_in,
        p_out=p_out,
        mu=mu,
        species=species,
        scale=scale,
        validation=validation,
        raw=dict(scenario),
    )


def _validated_params(scenario: dict[str, Any]) -> dict[str, Any]:
    """Re-validate every parameter for the validation report (best-effort)."""
    out: dict[str, Any] = {}
    geometry = scenario.get("geometry") or {}
    for key in ("length", "diameter"):
        if key in geometry:
            try:
                out[f"geometry.{key}"] = validate_parameter("length", geometry[key]).__dict__
            except OpError:
                pass
    for key in ("porosity", "permeability"):
        if key in scenario:
            spec = "porosity" if key == "porosity" else "permeability_abs"
            try:
                out[key] = validate_parameter(spec, scenario[key]).__dict__
            except OpError:
                pass
    flow = scenario.get("flow") or {}
    for key in ("velocity", "flux", "p_in", "p_out"):
        if key in flow:
            spec = {"velocity": "velocity", "flux": "flux",
                    "p_in": "pressure", "p_out": "pressure"}[key]
            try:
                out[f"flow.{key}"] = validate_parameter(spec, flow[key]).__dict__
            except OpError:
                pass
    return out
