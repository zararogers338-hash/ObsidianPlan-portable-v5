"""Mechanistic reasoning primitives for MICP biology.

Pure functions that encode the domain rules the skill must enforce (spec §四),
so the same logic is used by the CLI, the tests, and the evals. No I/O here;
all functions return plain dicts that the CLI stamps into the output envelope.
"""

from __future__ import annotations

import math
from typing import Any

from ._common import ensure_finite, require_activity_unit
from .errors import MbrError, MbrErrorCode
from .units import activity_to_u_per_ml


def compare_batches(batch_a: dict[str, Any], batch_b: dict[str, Any]) -> dict[str, Any]:
    """Compare two culture batches for identical OD600 but differing activity.

    Rules enforced:
      - OD600 is biomass proxy, never activity (MBR-E204 if compared as activity).
      - Activity comparison requires units on both sides; units normalized to
        U/mL when convertible; otherwise PARTIAL + explicit uncertainty.
    """
    od_a = batch_a.get("od600")
    od_b = batch_b.get("od600")
    act_a = batch_a.get("urease_activity")
    act_b = batch_b.get("urease_activity")
    unit_a = batch_a.get("urease_activity_unit")
    unit_b = batch_b.get("urease_activity_unit")

    # OD600 comparison is legitimate ONLY as biomass equality; never activity.
    biomass_identical = _approx_equal(od_a, od_b)

    # Activity: if either activity present, both units are mandatory.
    if act_a is not None or act_b is not None:
        require_activity_unit(unit_a if act_a is not None else unit_b)
        require_activity_unit(unit_b if act_b is not None else unit_a)
        ua = activity_to_u_per_ml(float(act_a), unit_a)["u_per_ml"]
        ub = activity_to_u_per_ml(float(act_b), unit_b)["u_per_ml"]
        activity_ratio = ua / ub if ub != 0 else math.inf
    else:
        ua = ub = None
        activity_ratio = None

    same_od = biomass_identical
    if same_od and act_a is not None and act_b is not None:
        conclusion = (
            "Same OD600 but different urease activity: biomass is comparable, "
            "activity is not. Consistent with non-constitutive urease (Whiffin "
            "2004; Lapierre & Huber 2024) — do not infer activity from OD600."
            if not _approx_equal(ua, ub)
            else "Same OD600 and comparable activity: batches are interchangeable at this scale."
        )
    elif same_od and (act_a is None or act_b is None):
        conclusion = (
            "OD600 identical but activity data incomplete for at least one batch; "
            "biomass comparable, activity incomparable without measured values."
        )
    else:
        conclusion = "Batches differ in OD600; biomass not comparable without normalization."

    findings = [
        {
            "label": "CALCULATED" if (ua is not None and ub is not None) else "INFERRED",
            "statement": f"Batch A OD600={od_a}, activity={ua if ua is not None else act_a} U/mL-equiv; "
                         f"Batch B OD600={od_b}, activity={ub if ub is not None else act_b} U/mL-equiv.",
        },
        {
            "label": "INFERRED",
            "statement": conclusion,
            "source": "micp-biology-reasoner domain rules; Whiffin 2004; Lapierre & Huber 2024",
        },
    ]
    return {
        "same_od600": same_od,
        "activity_ratio_a_over_b": activity_ratio,
        "activity_identical": _approx_equal(ua, ub) if (ua is not None and ub is not None) else None,
        "conclusion": conclusion,
        "findings": findings,
    }


def assess_treatment_strategy(treatment: str, *, context: dict[str, Any] | None = None) -> dict[str, Any]:
    """Evaluate pure-culture vs biostimulation vs mixed community for spatial
    uniformity and community dynamics. Evidence-grade REFUTABLE conclusions only."""
    ctx = context or {}
    soil_organic = ctx.get("soil_organic_carbon")
    findings: list[dict[str, str]] = []

    if treatment == "bioaugmentation":
        findings.append({
            "label": "INFERRED",
            "statement": (
                "Bioaugmentation injects large volumes of exogenous pure culture; "
                "distribution homogeneity depends on retention/filtration and may "
                "be spatially non-uniform; introduced cells face competition and "
                "predation (Graddy 2021: augmented S. pasteurii declined below "
                "detection after 9 treatments)."
            ),
            "source": "Graddy et al. 2021 (ES&T); Riley & colleagues (native-community convergence)",
        })
        findings.append({
            "label": "RECOMMENDATION",
            "statement": "If pure-culture uniformity is the goal, require attachment/retention data; request micp-porous-media-transport for spatial modeling.",
        })
    elif treatment == "biostimulation":
        findings.append({
            "label": "INFERRED",
            "statement": (
                "Biostimulation enriches indigenous ureolytic community (e.g. "
                "Firmicutes, Sporosarcina+Lysinibacillus) via urea + carbon "
                "source; spatial distribution follows the native community's "
                "distribution and can be more uniform, but requires sufficient "
                "organic carbon (low yeast extract => poor stimulation)."
            ),
            "source": "Graddy et al. 2021; Dhami et al. 2017; Babaeizad et al. 2025",
        })
        if soil_organic is not None and isinstance(soil_organic, (int, float)) and float(soil_organic) < 0.5:
            findings.append({
                "label": "RECOMMENDATION",
                "statement": "Low organic carbon site: biostimulation likely under-powered; consider augmentation with repeated nutrient injections (Dhami 2017).",
            })
    elif treatment in ("indigenous", "mixed_community"):
        findings.append({
            "label": "INFERRED",
            "statement": (
                "Indigenous/mixed community: native taxa persist but are slower "
                "and rates are community-dependent; convergence with augmentation "
                "observed over repeated treatments."
            ),
            "source": "Graddy et al. 2021",
        })
    else:
        findings.append({
            "label": "INFERRED",
            "statement": f"Treatment '{treatment}' has no built-in domain model here; request focused assessment.",
        })

    return {"treatment": treatment, "findings": findings}


def analyze_contradictory_data(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Given a set of biological measurement records, detect whether the claims
    conflate distinct metrics (OD600 vs activity vs viability vs CDW)."""
    if not isinstance(records, list) or len(records) == 0:
        raise MbrError(MbrErrorCode.INPUT_SCHEMA_VIOLATION, "analyze_contradictory_data requires a non-empty records list.")
    issues: list[dict[str, str]] = []
    metrics_seen: set[str] = set()
    for i, r in enumerate(records):
        if not isinstance(r, dict):
            issues.append({"label": "INFERRED", "statement": f"record[{i}] is not an object; skipped."})
            continue
        metric = str(r.get("metric", "")).strip().lower()
        metrics_seen.add(metric)
        unit = r.get("unit")
        if metric == "od600" and any(
            w in str(r.get("claim", "")).lower() for w in ("activity", "酶活", "活性", "比活")
        ):
            issues.append({
                "label": "INFERRED",
                "statement": f"record[{i}] claims activity from OD600 measurement; this conflates biomass with activity (MBR-E204). "
                             "OD600 is a biomass proxy — higher OD600 does NOT imply higher urease activity (non-constitutive urease).",
            })
        if metric in ("urease_activity", "activity") and (unit is None or str(unit).strip() == ""):
            issues.append({
                "label": "INFERRED",
                "statement": f"record[{i}] activity lacks a unit; incomparable (MBR-E203).",
            })
    findings = issues if issues else [
        {"label": "INFERRED", "statement": "No metric-conflation detected in the provided records."}
    ]
    return {"metrics_seen": sorted(metrics_seen), "findings": findings}


def salinity_assessment(
    strain: str,
    *,
    salinity: float | None,
    observed_evidence: bool = False,
) -> dict[str, Any]:
    """Assess strain fitness at high salinity with explicit evidence grading.

    Without measured data, high-salt fitness may only be REPORTED/INFERRED,
    never OBSERVED; with direct data it becomes OBSERVED. If no data at all,
    flags evidence insufficiency (spec §八.2).
    """
    if salinity is None:
        raise MbrError(
            MbrErrorCode.INPUT_SCHEMA_VIOLATION,
            "salinity_assessment requires a salinity value (g/L NaCl-equivalent).",
            detail={"field": "salinity"},
        )
    s = ensure_finite(salinity, "salinity")
    if s < 0:
        raise MbrError(MbrErrorCode.NUMERIC_INVALID, "salinity cannot be negative.", detail={"salinity": s})
    # Seawater reference ~35 g/L; "high" threshold heuristic.
    high = s >= 35.0

    if observed_evidence:
        label, statement = "OBSERVED", (
            f"Direct measurements indicate the strain maintains activity at {s} g/L "
            "salinity within the tested range."
        )
    elif strain.lower() in ("sporosarcina pasteurii", "sporosarcina pasteurii (atcc 11859)", "s. pasteurii"):
        label, statement = "REPORTED", (
            f"Literature reports S. pasteurii precipitates CaCO3 efficiently at "
            f"{s} g/L (seawater-level) salinity (Mortensen 2011; high-salt study), "
            "but specific growth/urease activity at this salinity must be verified "
            "against primary data before OBSERVED."
        )
    else:
        label, statement = "HYPOTHESIS", (
            f"High-salt fitness of '{strain}' at {s} g/L is unverified for this strain; "
            "no direct or strain-specific evidence. Requires growth + urease activity "
            "measurements at this salinity."
        )
    return {
        "salinity_g_per_l": s,
        "high_salt": high,
        "evidence_label": label,
        "statement": statement,
        "insufficient_evidence": not observed_evidence and strain.lower() not in ("sporosarcina pasteurii", "s. pasteurii", "sporosarcina pasteurii (atcc 11859)"),
    }


def _approx_equal(a: Any, b: Any, tol: float = 1e-9) -> bool:
    if a is None or b is None:
        return False
    try:
        return abs(float(a) - float(b)) <= tol * max(1.0, abs(float(a)), abs(float(b)))
    except (TypeError, ValueError):
        return False


def urease_yield_urea_to_ammonia(urea_consumed_mM: float) -> dict[str, Any]:
    """Mass-balance bookkeeping: 1 mol urea -> 2 mol NH4+ (spec §七)."""
    u = ensure_finite(urea_consumed_mM, "urea_consumed_mM")
    if u < 0:
        raise MbrError(MbrErrorCode.NUMERIC_INVALID, "urea_consumed_mM cannot be negative.", detail={"urea_mM": u})
    return {
        "urea_consumed_mM": u,
        "ammonium_produced_mM": 2.0 * u,
        "stoichiometry": "CO(NH2)2 + 2H2O -> 2NH3 + H2CO3; 1 urea : 2 NH4+",
    }
