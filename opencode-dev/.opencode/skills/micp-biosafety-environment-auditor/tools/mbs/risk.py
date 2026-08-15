"""Risk assessment for micp-biosafety-environment-auditor.

Risk model (per task brief):
  HAZARD · EXPOSURE · LIKELIHOOD · SEVERITY · CONTROL · RESIDUAL_RISK

Levels: LOW / MODERATE / HIGH / CRITICAL.

The auditor NEVER downgrades a strain's risk because it is commonly used in
MICP. Site- and context-specific evidence is required before any LOW verdict.

Also implements:
  - risk-matrix generation (likelihood x severity -> risk level),
  - monitoring thresholds & alarm rules,
  - emergency-response checklist generation.
"""

from __future__ import annotations

import math
from typing import Any

from .errors import MbsError, MbsErrorCode
from .chemistry import ensure_finite, ensure_in_range

RISK_LEVELS = ["LOW", "MODERATE", "HIGH", "CRITICAL"]
LIKELIHOOD_LEVELS = ["RARE", "UNLIKELY", "POSSIBLE", "LIKELY", "ALMOST_CERTAIN"]
SEVERITY_LEVELS = ["NEGLIGIBLE", "MINOR", "MODERATE", "MAJOR", "SEVERE"]

# likelihood x severity -> risk (5x5). Indexed by integer codes 1..5.
_RISK_MATRIX: list[list[str]] = [
    # severity 1..5
    ["LOW", "LOW", "MODERATE", "MODERATE", "HIGH"],      # likelihood 1 (RARE)
    ["LOW", "LOW", "MODERATE", "HIGH", "HIGH"],          # likelihood 2 (UNLIKELY)
    ["LOW", "MODERATE", "MODERATE", "HIGH", "CRITICAL"],  # likelihood 3 (POSSIBLE)
    ["MODERATE", "MODERATE", "HIGH", "CRITICAL", "CRITICAL"],  # likelihood 4 (LIKELY)
    ["MODERATE", "HIGH", "HIGH", "CRITICAL", "CRITICAL"],      # likelihood 5 (ALMOST_CERTAIN)
]

_LIKELIHOOD_CODE = {l: i + 1 for i, l in enumerate(LIKELIHOOD_LEVELS)}
_SEVERITY_CODE = {l: i + 1 for i, l in enumerate(SEVERITY_LEVELS)}

# Category-level alarm thresholds (engineered defaults; site/regulatory limits
# override them when verified).
MONITORING_THRESHOLDS: dict[str, dict[str, float]] = {
    "ph": {"min": 5.5, "max": 9.0, "warning": 0.5},
    "temperature_c": {"min": 0.0, "max": 50.0, "warning": 5.0},
    "ammonia_n_mgL": {"max": 5.0, "warning": 0.8},           # surface-water / receiving-context alarm band
    "nh4_n_mgL": {"max": 5.0, "warning": 0.8},               # canonical NH4-N field — MUST have a threshold (G7)
    "nh3_n_mgL": {"max": 0.5, "warning": 0.8},               # free ammonia in effluent alarm band
    "tn_mgL": {"max": 15.0, "warning": 0.8},
    "urea_mgL": {"max": 100.0, "warning": 0.8},
    "ec_ms_cm": {"max": 3000.0, "warning": 0.8},             # salinity alarm band
    "total_n_load_kg": {"max": 1.0, "warning": 0.8},         # cumulative load alarm (kg) placeholder
}


def risk_level(likelihood: str, severity: str) -> str:
    """5x5 matrix lookup."""
    if likelihood not in _LIKELIHOOD_CODE or severity not in _SEVERITY_CODE:
        raise MbsError(
            MbsErrorCode.INPUT_SCHEMA_VIOLATION,
            f"likelihood {likelihood!r} or severity {severity!r} not in matrix axes.",
            detail={"likelihood": likelihood, "severity": severity,
                    "likelihood_axis": LIKELIHOOD_LEVELS, "severity_axis": SEVERITY_LEVELS},
        )
    return _RISK_MATRIX[_LIKELIHOOD_CODE[likelihood] - 1][_SEVERITY_CODE[severity] - 1]


def risk_matrix() -> dict[str, Any]:
    """Serializable 5x5 risk matrix for the artifact."""
    return {
        "likelihood_axis": LIKELIHOOD_LEVELS,
        "severity_axis": SEVERITY_LEVELS,
        "matrix": _RISK_MATRIX,
        "cell": {
            f"{l}/{s}": risk_level(l, s) for l in LIKELIHOOD_LEVELS for s in SEVERITY_LEVELS
        },
    }


def rank_risk(level: str) -> int:
    return RISK_LEVELS.index(level) if level in RISK_LEVELS else 99


def residual_risk(level: str, control_effectiveness: str) -> str:
    """Residual risk after a control. control_effectiveness in {none, low, moderate, high}.

    Conservative floors: a CRITICAL hazard never drops below MODERATE, and a
    HIGH hazard never drops below MODERATE either (max one step of reduction is
    permitted only for CRITICAL; HIGH can reduce at most one step to MODERATE,
    never to LOW). The hazard itself remains — the auditor never defaults a
    serious hazard to safe based on claimed controls alone.
    """
    idx = rank_risk(level)
    eff = {"none": 0, "low": 1, "moderate": 2, "high": 3}.get(str(control_effectiveness).lower(), 0)
    residual_idx = max(0, idx - eff)
    if level == "CRITICAL":
        residual_idx = max(1, residual_idx)  # floor at MODERATE
    elif level == "HIGH":
        residual_idx = max(1, residual_idx)  # HIGH never drops below MODERATE
    return RISK_LEVELS[residual_idx]


# ------------------------------------------------------------------------- #
# Hazard & exposure screening
# ------------------------------------------------------------------------- #

HAZARD_CATALOG: dict[str, dict[str, Any]] = {
    "strain_pathogenicity": {
        "label": "菌株致病性",
        "example": "Potential human/animal pathogenicity of the ureolytic strain.",
        "affected_by": ["strain_biosafety"],
    },
    "environmental_release": {
        "label": "环境释放",
        "example": "Release of live ureolytic bacteria into the environment.",
        "affected_by": ["release_type", "groundwater_injection"],
    },
    "aerosolization": {
        "label": "气溶胶",
        "example": "Aerosol generation during mixing, pumping, spraying, or off-gassing.",
        "affected_by": ["aerosol_potential"],
    },
    "waterborne_transport": {
        "label": "水体传播",
        "example": "Transport of bacteria or nitrogen to surface water / groundwater.",
        "affected_by": ["groundwater_injection", "hydraulic_connectivity"],
    },
    "ammonia_toxicity": {
        "label": "氨毒性(NH3)",
        "example": "Free ammonia (NH3) toxic to aquatic biota / human inhalation hazard.",
        "affected_by": ["nh3_risk"],
    },
    "nitrogen_loading": {
        "label": "氮负荷",
        "example": "Ammonium-N / total-N loading to receiving water.",
        "affected_by": ["nh4_n_conc_mgL", "discharge_volume"],
    },
    "salt_load": {
        "label": "盐负荷",
        "example": "Calcium / ammonium salt accumulation in soil and groundwater.",
        "affected_by": ["calcium_chloride_use", "salinity"],
    },
    "calcium_salt_scale": {
        "label": "钙盐结垢",
        "example": "Calcium carbonate / ammonium scaling of equipment and piping.",
        "affected_by": ["equipment_scaling"],
    },
    "antibiotic_resistance_mobilization": {
        "label": "抗性基因风险",
        "example": "Potential for ARG mobilization in released communities.",
        "affected_by": ["arg_concern"],
    },
    "soil_ecology_disruption": {
        "label": "土壤生态扰动",
        "example": "Alkalinity / salinity / ammonia shifts disrupting soil ecology.",
        "affected_by": ["site_sensitive_ecology"],
    },
    "odour": {
        "label": "气味",
        "example": "Ammonia odour nuisance near populated areas.",
        "affected_by": ["odour_exposure"],
    },
    "confined_space_exposure": {
        "label": "密闭空间暴露",
        "example": "Worker exposure in confined spaces (tanks, sumps, trenches).",
        "affected_by": ["confined_space"],
    },
}


def _rate_bool_like(value: Any) -> bool:
    return bool(value) and str(value).lower() not in ("false", "no", "none", "0")


def identify_hazards(
    site: dict[str, Any],
    *,
    computed_nh3_n_mgL: float | None = None,
    strain_biosafety: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Screen a site profile against the hazard catalog.

    `site` is the caller's site context object. Only hazards with evidence are
    returned; the absence of a flag does not assert safety (it just means the
    screen found no explicit trigger).

    `computed_nh3_n_mgL`: free-NH3-N computed by the chemistry module from the
    plan's pH/temperature/ammonium — used so a high-NH4-N plan at alkaline pH
    ALWAYS raises the ammonia hazard even when the caller omitted site.nh3_risk.
    `strain_biosafety`: the classify_biosafety result, so an unconfirmed or
    pathogenic-genus strain ALWAYS raises the pathogenicity hazard.
    """
    hazards: list[dict[str, Any]] = []
    strain_cls = site.get("strain_biosafety") or strain_biosafety or {}
    release = str(site.get("release_type") or "contained").lower()
    groundwater = _rate_bool_like(site.get("groundwater_injection"))
    sensitive_ecology = _rate_bool_like(site.get("site_sensitive_ecology"))
    nh3_n = float(site.get("nh3_n_mgL") or 0)
    if computed_nh3_n_mgL is not None:
        nh3_n = max(nh3_n, float(computed_nh3_n_mgL))

    if (strain_cls or {}).get("needs_regulatory_confirmation") or (strain_cls or {}).get("pathogenic_marker"):
        hazards.append({
            "id": "strain_pathogenicity",
            "label": "菌株致病性",
            "present": True,
            "evidence": "Strain biosafety not confirmed against site pathogen list.",
            "base_level": "CRITICAL" if (strain_cls or {}).get("pathogenic_marker") else "MODERATE",
        })
    if release in ("open_environment", "injection"):
        hazards.append({
            "id": "environmental_release",
            "label": "环境释放",
            "present": True,
            "evidence": f"release_type={release} implies live-cell environmental release.",
            "base_level": "HIGH",
        })
    if groundwater:
        hazards.append({
            "id": "waterborne_transport",
            "label": "水体传播",
            "present": True,
            "evidence": "On-site groundwater injection declared.",
            "base_level": "CRITICAL",
        })
    if _rate_bool_like(site.get("aerosol_potential")):
        hazards.append({
            "id": "aerosolization",
            "label": "气溶胶",
            "present": True,
            "evidence": "Aerosol potential flagged for mixing/pumping/spraying.",
            "base_level": "MODERATE",
        })
    if _rate_bool_like(site.get("nh3_risk")) or nh3_n > 0.5:
        hazards.append({
            "id": "ammonia_toxicity",
            "label": "氨毒性(NH3)",
            "present": True,
            "evidence": "Free ammonia risk present.",
            "base_level": "HIGH",
        })
    if float(site.get("nh4_n_conc_mgL") or 0) > 0:
        hazards.append({
            "id": "nitrogen_loading",
            "label": "氮负荷",
            "present": True,
            "evidence": f"Ammonium-N {site.get('nh4_n_conc_mgL')} mg/L present.",
            "base_level": "MODERATE",
        })
    if _rate_bool_like(site.get("calcium_chloride_use")) or _rate_bool_like(site.get("salinity")):
        hazards.append({
            "id": "salt_load",
            "label": "盐负荷",
            "present": True,
            "evidence": "Calcium/ammonium salt load present.",
            "base_level": "MODERATE",
        })
    if sensitive_ecology:
        hazards.append({
            "id": "soil_ecology_disruption",
            "label": "土壤生态扰动",
            "present": True,
            "evidence": "Sensitive ecological receptors flagged at the trial site.",
            "base_level": "CRITICAL",
        })
    if _rate_bool_like(site.get("arg_concern")):
        hazards.append({
            "id": "antibiotic_resistance_mobilization",
            "label": "抗性基因风险",
            "present": True,
            "evidence": "ARG concern flagged for the released community.",
            "base_level": "HIGH",
        })
    if _rate_bool_like(site.get("odour_exposure")):
        hazards.append({
            "id": "odour",
            "label": "气味",
            "present": True,
            "evidence": "Ammonia odour exposure near receptors.",
            "base_level": "MODERATE",
        })
    if _rate_bool_like(site.get("confined_space")):
        hazards.append({
            "id": "confined_space_exposure",
            "label": "密闭空间暴露",
            "present": True,
            "evidence": "Confined-space entry/operations flagged.",
            "base_level": "HIGH",
        })
    return hazards


EXPOSURE_PATHWAYS = [
    "inhalation_of_aerosols",
    "dermal_contact",
    "ingestion_of_contaminated_water",
    "groundwater_migration",
    "surface_water_runoff",
    "soil_exposure_at_release_point",
    "equipment_personnel_contact",
    "downwind_ammonia_plume",
    "sewage_wastewater_transport",
    "food_chain_accumulation",
]


def exposure_pathways(site: dict[str, Any]) -> list[dict[str, Any]]:
    """Score the plausible exposure pathways for the site profile."""
    out: list[dict[str, Any]] = []
    groundwater = _rate_bool_like(site.get("groundwater_injection"))
    aerosol = _rate_bool_like(site.get("aerosol_potential"))
    nh3 = float(site.get("nh3_n_mgL") or 0) > 0.5
    release = str(site.get("release_type") or "contained").lower()

    def add(key: str, present: bool, intensity: str) -> None:
        out.append({"pathway": key, "present": present, "intensity": intensity if present else "none"})

    add("inhalation_of_aerosols", aerosol, "moderate" if aerosol else "none")
    add("groundwater_migration", groundwater or release == "injection", "critical" if groundwater else "none")
    add("downwind_ammonia_plume", nh3, "moderate" if nh3 else "none")
    add("surface_water_runoff", release != "contained", "moderate" if release != "contained" else "none")
    add("dermal_contact", True, "low")
    add("soil_exposure_at_release_point", release != "contained", "moderate" if release != "contained" else "none")
    add("equipment_personnel_contact", True, "low")
    add("ingestion_of_contaminated_water", groundwater, "moderate" if groundwater else "none")
    return out


# ------------------------------------------------------------------------- #
# Monitoring thresholds & alarms
# ------------------------------------------------------------------------- #


def monitoring_plan(site: dict[str, Any], overrides: dict[str, Any] | None = None) -> dict[str, Any]:
    """Build a monitoring threshold + alarm-rule set.

    Applies verified regulatory limits when available (via site.regulatory),
    otherwise uses the engineered default bands (always flagged as defaults).
    Returns per-parameter: low/high thresholds, alarm on exceed, warning band.
    """
    overrides = overrides or {}
    reg = site.get("regulatory") or {}
    params: dict[str, Any] = {}
    for param, default in MONITORING_THRESHOLDS.items():
        row = dict(default)
        # regulatory override by exact key when a verified limit exists
        limit = reg.get(param)
        if isinstance(limit, (int, float)) and "max" in row:
            row["max"] = float(limit)
            row["source"] = "regulatory"
        else:
            row["source"] = "default"
        if param in overrides:
            row.update(overrides[param])
        params[param] = row
    return {"parameters": params, "note": "Default bands are engineering placeholders until verified regulatory limits are applied."}


def alarm_rules(monitoring: dict[str, Any], measurements: dict[str, Any]) -> list[dict[str, Any]]:
    """Evaluate measurements against monitoring thresholds; emit alarm rules.

    Returns a list of alarm states: {parameter, value, threshold, level,
    triggered}. A triggered alarm must escalate to stop conditions.
    """
    alarms: list[dict[str, Any]] = []
    params = monitoring.get("parameters", {})
    for param, spec in params.items():
        if param not in measurements:
            continue
        value = ensure_finite(measurements[param], f"measurement.{param}")
        triggered = False
        level = "ok"
        msg: list[str] = []
        if "max" in spec and value > spec["max"]:
            triggered = True
            level = "alarm"
            msg.append(f"exceeds max {spec['max']}")
        if "min" in spec and value < spec["min"]:
            triggered = True
            level = "alarm"
            msg.append(f"below min {spec['min']}")
        warn = spec.get("warning")
        if not triggered and warn is not None:
            if isinstance(warn, float) and warn < 1.0:
                # warning is a fraction of the max (e.g. 0.8 = 80% of max)
                band = spec.get("max")
                if band and value > band * warn:
                    level = "warning"
                    msg.append(f"in warning band (> {warn:.0%} of max {band})")
            else:
                # warning is an absolute margin below the max (e.g. max-5.0)
                band = spec.get("max")
                if band and value > band - float(warn):
                    level = "warning"
                    msg.append(f"in warning band (within {warn:g} of max {band})")
        alarms.append({
            "parameter": param,
            "value": value,
            "threshold": {k: spec.get(k) for k in ("min", "max", "warning")},
            "level": level,
            "triggered": triggered,
            "message": "; ".join(msg) or "within limits",
            "source": spec.get("source", "default"),
        })
    # A measured parameter with no configured threshold must ESCALATE rather
    # than pass silently: an unmapped reading is a monitoring gap, not a pass.
    known = set(params)
    for param, value in measurements.items():
        if param in known:
            continue
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            continue
        alarms.append({
            "parameter": param,
            "value": float(value),
            "threshold": {"min": None, "max": None, "warning": None},
            "level": "no-threshold",
            "triggered": True,
            "message": f"no configured threshold for measured parameter '{param}'",
            "source": "unknown",
        })
    return alarms


def any_alarm(alarms: list[dict[str, Any]]) -> bool:
    return any(a["triggered"] for a in alarms)


# ------------------------------------------------------------------------- #
# Emergency response
# ------------------------------------------------------------------------- #

EMERGENCY_ACTIONS: dict[str, list[str]] = {
    "ammonia_leak": [
        "STOP feed/injection; isolate the source valve or vessel.",
        "Evacuate downwind personnel; ventilate the area.",
        "Use respiratory protection (NH3 breakthrough cartridge or SCBA) for entry.",
        "Contain liquid; neutralize with dilute acid under supervision; collect as waste.",
        "Notify the site safety officer and activate the emergency plan.",
    ],
    "live_strain_release": [
        "STOP operations; contain the spill area with absorbent.",
        "Decontaminate with 70% ethanol or 1% hypochlorite; collect contaminated material as biohazard waste.",
        "Restrict entry; report to biosafety officer per site rules.",
    ],
    "wastewater_overflow": [
        "STOP discharge; block the outlet; divert to containment basin.",
        "Sample the affected water; assess NH4-N/NH3 against verified limits.",
        "Notify the environmental officer; file the incident report.",
    ],
    "personnel_exposure": [
        "Remove contaminated clothing; rinse affected skin/eyes for 15 minutes.",
        "Report to occupational health; document exposure (agent, route, duration).",
        "For ammonia inhalation: move to fresh air; seek medical attention if symptomatic.",
    ],
    "groundwater_concern": [
        "STOP groundwater-involved operations immediately.",
        "Down-gradient monitoring wells sampled; compare against verified limits.",
        "Notify the competent environmental authority per the permit.",
    ],
    "general": [
        "Activate the site emergency response plan; contact the designated officer.",
        "Preserve evidence (samples, logs) for incident review.",
    ],
}


def emergency_actions(site: dict[str, Any], triggered_alarms: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    """Build an emergency-response checklist tailored to the site triggers."""
    triggered_alarms = triggered_alarms or []
    selected: list[str] = []
    if any("ammoni" in a["parameter"] or "nh3" in a["parameter"] for a in triggered_alarms):
        selected.append("ammonia_leak")
    if _rate_bool_like(site.get("live_release_risk")):
        selected.append("live_strain_release")
    if any("load" in a["parameter"] or "nh4" in a["parameter"] for a in triggered_alarms) or _rate_bool_like(site.get("discharge_flag")):
        selected.append("wastewater_overflow")
    if _rate_bool_like(site.get("groundwater_injection")):
        selected.append("groundwater_concern")
    selected.append("personnel_exposure")
    selected.append("general")

    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for key in selected:
        if key in seen:
            continue
        seen.add(key)
        out.append({"scenario": key, "actions": EMERGENCY_ACTIONS[key]})
    return out
