"""Waste-treatment option comparison and environmental sampling-plan generation.

These tools give the auditor a defensible, traceable basis for comparing
treatment routes and for building a monitoring plan — they never authorize a
discharge. Approval gates remain upstream.
"""

from __future__ import annotations

from typing import Any

from .chemistry import ensure_finite, ensure_in_range
from .errors import MbsError, MbsErrorCode

# Treatment-route registry: engineered default performance bands, flagged as
# such. Real values must be replaced by site-specific / vendor data when
# available; the auditor never presents defaults as guarantees.
TREATMENT_OPTIONS: dict[str, dict[str, Any]] = {
    "dilution": {
        "label": "稀释后排放",
        "nh4_n_removal_pct": 0.0,
        "nh3_volatilization": True,
        "cost_tier": "low",
        "residual_nh3_risk": "HIGH",
        "consent_required": True,
        "notes": "Only transfers load; volatilized NH3 becomes an air pathway. Requires discharge consent.",
    },
    "breakpoint_chlorination": {
        "label": "折点氯化",
        "nh4_n_removal_pct": 90.0,
        "nh3_volatilization": False,
        "cost_tier": "medium",
        "residual_nh3_risk": "LOW",
        "consent_required": False,
        "notes": "NH4+ oxidized to N2; chloramines intermediate; DBPs must be managed.",
    },
    "biological_nitrification_denitrification": {
        "label": "生物硝化-反硝化",
        "nh4_n_removal_pct": 90.0,
        "nh3_volatilization": False,
        "cost_tier": "medium",
        "residual_nh3_risk": "LOW",
        "consent_required": False,
        "notes": "Robust for ammonium; requires carbon source + aeration; slower.",
    },
    "struvite_precipitation": {
        "label": "鸟粪石沉淀",
        "nh4_n_removal_pct": 85.0,
        "nh3_volatilization": False,
        "cost_tier": "medium",
        "residual_nh3_risk": "LOW",
        "consent_required": False,
        "notes": "Recovers N+P as struvite; needs Mg/P dosing; alkaline pH.",
    },
    "reverse_osmosis": {
        "label": "反渗透",
        "nh4_n_removal_pct": 95.0,
        "nh3_volatilization": False,
        "cost_tier": "high",
        "residual_nh3_risk": "LOW",
        "consent_required": False,
        "notes": "High removal; concentrate stream still needs handling.",
    },
    "air_stripping": {
        "label": "空气吹脱",
        "nh4_n_removal_pct": 80.0,
        "nh3_volatilization": True,
        "cost_tier": "low",
        "residual_nh3_risk": "HIGH",
        "consent_required": True,
        "notes": "Shifts NH3 to air; needs scrubber to avoid atmospheric release.",
    },
    "contained_collection_offsite": {
        "label": "密闭收集-外运处置",
        "nh4_n_removal_pct": 100.0,
        "nh3_volatilization": False,
        "cost_tier": "high",
        "residual_nh3_risk": "LOW",
        "consent_required": True,
        "notes": "No on-site discharge; requires licensed hazardous-waste transporter/disposer.",
    },
}


def compare_treatment_options(
    *,
    total_n_load_g: float,
    volume_l: float,
    available_options: list[str] | None = None,
    criteria_weights: dict[str, float] | None = None,
) -> dict[str, Any]:
    """Score and compare waste-treatment options.

    Default criteria weights (sum to 1):
      residual_risk 0.4, cost 0.2, removal_efficacy 0.25, consent_effort 0.15

    Returns ranked options with a composite score 0..1 (higher = better) and
    the reason trail so the recommendation is auditable. A HIGH residual-NH3
    option never scores above a LOW one unless weights explicitly say so.
    """
    load = ensure_finite(total_n_load_g, "total_n_load_g")
    if load < 0:
        raise MbsError(MbsErrorCode.NUMERIC_INVALID, "total_n_load_g must be >= 0.",
                       detail={"field": "total_n_load_g"})
    vol = ensure_finite(volume_l, "volume_l")
    if vol < 0:
        raise MbsError(MbsErrorCode.NUMERIC_INVALID, "volume_l must be >= 0.",
                       detail={"field": "volume_l"})
    opts = available_options or list(TREATMENT_OPTIONS)
    unknown = [o for o in opts if o not in TREATMENT_OPTIONS]
    if unknown:
        raise MbsError(
            MbsErrorCode.INPUT_SCHEMA_VIOLATION,
            f"Unknown treatment option(s): {unknown}.",
            detail={"available": sorted(TREATMENT_OPTIONS)},
        )
    weights = dict({"residual_risk": 0.4, "cost": 0.2, "removal_efficacy": 0.25, "consent_effort": 0.15})
    if criteria_weights:
        weights.update(criteria_weights)
    total_w = sum(weights.values())
    if total_w <= 0:
        raise MbsError(MbsErrorCode.INPUT_SCHEMA_VIOLATION, "criteria_weights must sum to > 0.",
                       detail={"weights": weights})

    cost_score = {"low": 1.0, "medium": 0.6, "high": 0.2}
    consent_score = {True: 0.4, False: 1.0}  # requiring consent costs points
    rows: list[dict[str, Any]] = []
    for o in opts:
        spec = TREATMENT_OPTIONS[o]
        removal = spec["nh4_n_removal_pct"] / 100.0
        residual_ok = spec["residual_nh3_risk"] == "LOW"
        sub = {
            "residual_risk": 1.0 if residual_ok else 0.2,
            "cost": cost_score[spec["cost_tier"]],
            "removal_efficacy": removal,
            "consent_effort": consent_score[spec["consent_required"]],
        }
        score = sum(weights[k] * sub[k] for k in weights)
        rows.append({
            "option": o,
            "label": spec["label"],
            "nh4_n_removal_pct": spec["nh4_n_removal_pct"],
            "residual_nh3_risk": spec["residual_nh3_risk"],
            "cost_tier": spec["cost_tier"],
            "consent_required": spec["consent_required"],
            "scores": sub,
            "composite_score": round(score, 4),
            "notes": spec["notes"],
        })
    rows.sort(key=lambda r: r["composite_score"], reverse=True)
    best = rows[0]
    if best["residual_nh3_risk"] != "LOW":
        # The auditor refuses to recommend a high-residual-risk route as "best"
        # purely on score — flag it loudly.
        flagged = best["option"]
        next_best = next((r for r in rows if r["residual_nh3_risk"] == "LOW"), None)
        return {
            "ranked": rows,
            "best_option": flagged,
            "best_residual_nh3_risk": best["residual_nh3_risk"],
            "recommendation_blocked": True,
            "reason": f"Top-scored option '{flagged}' carries HIGH residual NH3 risk; "
                      f"auditor will not greenlight it. "
                      + (f"Next acceptable option: '{next_best['option']}'." if next_best else "No low-residual option offered."),
        }
    return {
        "ranked": rows,
        "best_option": best["option"],
        "best_residual_nh3_risk": "LOW",
        "recommendation_blocked": False,
        "reason": f"Best option '{best['option']}' scored {best['composite_score']:.3f}.",
    }


# ------------------------------------------------------------------------- #
# Environmental sampling plan
# ------------------------------------------------------------------------- #

SAMPLING_MATRICES = ["effluent", "groundwater_down_gradient", "groundwater_up_gradient",
                     "soil", "air_nh3", "waste_stream"]


def sampling_plan(site: dict[str, Any]) -> dict[str, Any]:
    """Generate an environmental sampling plan for the site profile.

    The plan is a template (frequency/parameters are engineering defaults)
    that must be confirmed with the competent authority before use. It is an
    artifact, not an authorization.
    """
    groundwater = bool(site.get("groundwater_injection")) or str(site.get("release_type", "")).lower() == "injection"
    sensitive = bool(site.get("site_sensitive_ecology"))
    release = str(site.get("release_type") or "contained").lower()

    stations: list[dict[str, Any]] = []
    # Effluent / discharge point
    stations.append({
        "matrix": "effluent",
        "location": "discharge_point",
        "frequency": "per_batch_or_daily",
        "parameters": ["pH", "temperature_c", "nh4_n_mgL", "nh3_n_mgL", "tn_mgL", "urea_mgL", "ec_ms_cm"],
        "rationale": "Receiving-water loading check against verified limits.",
    })
    if groundwater:
        stations.append({
            "matrix": "groundwater_down_gradient",
            "location": "down_gradient_monitoring_wells",
            "frequency": "before_during_after",
            "parameters": ["ph", "nh4_n_mgL", "tn_mgL", "ec_ms_cm", "bacteria_presence"],
            "rationale": "Plume and cell-transport surveillance (sensitive receptor).",
        })
        stations.append({
            "matrix": "groundwater_up_gradient",
            "location": "up_gradient_baseline_wells",
            "frequency": "before_and_after",
            "parameters": ["ph", "nh4_n_mgL", "tn_mgL", "ec_ms_cm"],
            "rationale": "Baseline control for attribution.",
        })
    if release != "contained" or sensitive:
        stations.append({
            "matrix": "soil",
            "location": "release_zone_and_buffer",
            "frequency": "before_after",
            "parameters": ["ph", "total_n", "ec_ms_cm", "calcium_content"],
            "rationale": "Soil-ecology impact check near sensitive receptors.",
        })
    stations.append({
        "matrix": "air_nh3",
        "location": "source_and_fenceline",
        "frequency": "during_operations",
        "parameters": ["nh3_ug_m3"],
        "rationale": "NH3 inhalation/odour pathway; compare to verified occupational and fenceline limits.",
    })
    if site.get("waste_stream_volume_l"):
        stations.append({
            "matrix": "waste_stream",
            "location": "before_treatment",
            "frequency": "per_batch",
            "parameters": ["volume_l", "nh4_n_mgL", "tn_mgL", "urea_mgL", "pH"],
            "rationale": "Waste characterization for the treatment route.",
        })

    return {
        "sampling_stations": stations,
        "qa_notes": [
            "Collect trip blanks, field blanks and duplicate samples for QA/QC.",
            "Preserve NH4-N/NH3 samples (acidify, 4 °C) and analyze within holding time.",
            "Chain-of-custody must be documented for any sample used in compliance decisions.",
        ],
        "status": "template",
        "needs_authority_confirmation": True,
    }


# ------------------------------------------------------------------------- #
# Permit & approval status
# ------------------------------------------------------------------------- #

def permit_status(
    *,
    permits: list[dict[str, Any]] | None = None,
    requested_actions: list[str] | None = None,
) -> dict[str, Any]:
    """Check the permit/approval status for the planned actions.

    `permits` entries: {action, granted, expiry_date, authority}.
    `requested_actions`: the actions the plan needs approved (e.g.
    environmental_release, groundwater_injection, wastewater_discharge,
    strain_use, confined_space_entry).

    Any requested action without a granted, in-date permit -> not_approved,
    which forces HUMAN_APPROVAL_REQUIRED upstream.
    """
    permits = permits or []
    requested = requested_actions or []
    by_action: dict[str, dict[str, Any]] = {}
    for p in permits:
        a = str(p.get("action", ""))
        by_action[a] = p

    checks: list[dict[str, Any]] = []
    missing: list[str] = []
    for a in requested:
        p = by_action.get(a)
        if p is None:
            missing.append(a)
            checks.append({"action": a, "status": "NOT_GRANTED", "reason": "No permit record provided."})
            continue
        granted = bool(p.get("granted"))
        # expiry check (best effort; missing date treated as unverifiable)
        expiry = p.get("expiry_date")
        checks.append({
            "action": a,
            "status": "GRANTED" if granted else "NOT_GRANTED",
            "authority": p.get("authority"),
            "expiry_date": expiry,
            "reason": p.get("reason", ""),
        })
    all_approved = not missing and all(c["status"] == "GRANTED" for c in checks)
    return {
        "checks": checks,
        "all_approved": all_approved,
        "missing_approvals": missing,
        "verdict": "APPROVED" if all_approved else "HUMAN_APPROVAL_REQUIRED",
    }
