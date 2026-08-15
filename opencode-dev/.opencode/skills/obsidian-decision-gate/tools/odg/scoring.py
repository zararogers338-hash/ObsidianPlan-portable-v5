"""Evidence-maturity scorer and multi-criteria decision analysis.

Scores the 12 decision dimensions from the evidence context (0..1, higher is
better; RESIDUAL_RISK is inverse — 1 means negligible residual risk). Scoring
is deterministic and derived from the input envelope: identical inputs always
produce identical scores, so the gate result is reproducible.

The gate uses MINIMUM-DIMENSION floors, not a weighted total: one dimension
below its floor blocks the upgrade no matter how high the others score.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from .models import ALL_DIMENSIONS, DecisionDimension as D, ResearchState
from .rules import RuleTable, grade_gap


def _clamp(v: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, float(v)))


def _avg(values: list[float], default: float = 0.0) -> float:
    if not values:
        return default
    return sum(values) / len(values)


def _norm(value: float, lo: float, hi: float) -> float:
    """Map [lo,hi] onto [0,1]."""
    if hi == lo:
        return 0.5
    return _clamp((float(value) - lo) / (hi - lo))


@dataclass
class DimensionScore:
    dimension: str
    score: float
    basis: str

    def to_dict(self) -> dict:
        return {"dimension": self.dimension, "score": round(self.score, 3), "basis": self.basis}


def _evidence_level_rank(level: str | None) -> float:
    return {
        "high": 1.0,
        "moderate": 0.7,
        "low": 0.45,
        "very_low": 0.25,
        "insufficient": 0.1,
        None: 0.3,
    }.get(level, 0.3)


def score_scientific_validity(payload: dict[str, Any]) -> DimensionScore:
    parts: list[float] = []
    basis: list[str] = []

    synth = payload.get("synthesis")
    if synth:
        for c in synth.get("conclusions", []) or []:
            parts.append(_evidence_level_rank(c.get("evidence_level")))
            basis.append(f"conclusion {c.get('id', '?')} evidence_level={c.get('evidence_level')}")
        grade = (synth.get("grade") or {}).get("certainty")
        if grade:
            parts.append({"high": 1.0, "moderate": 0.7, "low": 0.45, "very_low": 0.2}.get(grade, 0.4))
            basis.append(f"GRADE certainty={grade}")

    # Hypothesis status: REFUTED crushes validity; SUPPORTED adds.
    hyp = payload.get("hypothesis_cards", []) or []
    if any(h.get("status") == "REFUTED" for h in hyp):
        parts.append(0.0)
        basis.append("main hypothesis REFUTED")
    elif any(h.get("status") == "CONTESTED" for h in hyp):
        parts.append(0.2)
        basis.append("hypothesis CONTESTED")
    elif any(h.get("status") == "SUPPORTED" for h in hyp):
        parts.append(0.75)
        basis.append("hypothesis SUPPORTED")

    # Model fit quality contributes when fitted.
    model = payload.get("model_results")
    if model:
        m = model.get("metrics") or {}
        if model.get("fitted"):
            parts.append(_clamp(float(m.get("validation_score", m.get("r2", 0.7)))))
            basis.append(f"model {model.get('name', '?')} fitted")
        if model.get("external_validation"):
            parts.append(1.0)
            basis.append("model externally validated")

    score = _avg(parts, 0.2)
    if not basis:
        basis.append("no synthesis/hypothesis/model inputs")
    return DimensionScore(D.SCIENTIFIC_VALIDITY.value, score, "; ".join(basis))


def score_evidence_quality(payload: dict[str, Any]) -> DimensionScore:
    cards = payload.get("evidence_cards", []) or []
    parts: list[float] = []
    basis: list[str] = []

    for c in cards:
        if c.get("retracted"):
            continue
        if not c.get("verifiable"):
            parts.append(0.1)
            basis.append(f"{c.get('ref_id', '?')} unverifiable")
            continue
        parts.append(0.7)
        basis.append(f"{c.get('ref_id', '?')} verifiable")
        lvl = c.get("evidence_level")
        if lvl:
            parts.append(_evidence_level_rank(lvl))

    # synthesis certainty as an overall quality indicator
    synth = payload.get("synthesis")
    if synth:
        g = (synth.get("grade") or {}).get("certainty")
        if g:
            parts.append({"high": 0.9, "moderate": 0.7, "low": 0.5, "very_low": 0.3}.get(g, 0.5))

    if not cards and not synth:
        return DimensionScore(D.EVIDENCE_QUALITY.value, 0.1, "no evidence cards or synthesis")
    return DimensionScore(D.EVIDENCE_QUALITY.value, _avg(parts, 0.2), "; ".join(basis) or "evidence cards present")


def score_reproducibility(payload: dict[str, Any]) -> DimensionScore:
    rep = payload.get("reproducibility") or {}
    basis: list[str] = []
    parts: list[float] = []
    if rep:
        if rep.get("data_archived"):
            parts.append(0.8)
            basis.append("data archived")
        if rep.get("code_archived"):
            parts.append(0.8)
            basis.append("code archived")
        if rep.get("versioned"):
            parts.append(0.8)
            basis.append("versioned")
        if rep.get("reproducible") is True:
            parts.append(1.0)
            basis.append("reproduced")
        elif rep.get("reproducible") is False:
            parts.append(0.0)
            basis.append("NOT reproducible")
    # independent repeated runs from experiments
    exps = payload.get("experiment_results", []) or []
    repeats = [e for e in exps if e.get("n") and e.get("n", 0) >= 3]
    if repeats:
        parts.append(0.6)
        basis.append(f"{len(repeats)} experiment(s) with n>=3")
    if not parts:
        return DimensionScore(D.REPRODUCIBILITY.value, 0.15, "no reproducibility evidence")
    return DimensionScore(D.REPRODUCIBILITY.value, _avg(parts), "; ".join(basis))


def score_engineering_feasibility(payload: dict[str, Any]) -> DimensionScore:
    parts: list[float] = []
    basis: list[str] = []
    for e in payload.get("experiment_results", []) or []:
        for o in e.get("outcomes", []) or []:
            t = o.get("threshold")
            v = o.get("value")
            st = o.get("status")
            if st == "met":
                parts.append(1.0)
                basis.append(f"{e.get('id', '?')}.{o.get('name')} met")
            elif st == "not_met":
                parts.append(0.0)
                basis.append(f"{e.get('id', '?')}.{o.get('name')} not_met")
            elif t is not None and v is not None:
                direction = o.get("direction", "maximize")
                ok = (v >= t) if direction == "maximize" else (v <= t) if direction == "minimize" else abs(v - t) <= 0.05 * abs(t)
                parts.append(1.0 if ok else 0.2)
                basis.append(f"{e.get('id', '?')}.{o.get('name')} vs threshold {t}")

    scaleup = payload.get("scaleup_plan")
    if scaleup:
        stages = scaleup.get("stages", []) or []
        if stages:
            parts.append(0.6 + 0.1 * min(4, len(stages)))
            basis.append(f"scale-up plan with {len(stages)} stage(s)")

    if not parts:
        return DimensionScore(D.ENGINEERING_FEASIBILITY.value, 0.2, "no engineering outcomes reported")
    return DimensionScore(D.ENGINEERING_FEASIBILITY.value, _avg(parts), "; ".join(basis))


def score_scale_readiness(payload: dict[str, Any]) -> DimensionScore:
    ladder: list[str] = []
    for c in payload.get("evidence_cards", []) or []:
        if c.get("scale"):
            ladder.append(c["scale"])
    for e in payload.get("experiment_results", []) or []:
        if e.get("scale"):
            ladder.append(e["scale"])
    for st in (payload.get("scaleup_plan") or {}).get("stages", []) or []:
        if st.get("scale"):
            ladder.append(st["scale"])
    ladder = list(dict.fromkeys(ladder))

    basis = [f"observed scales: {', '.join(ladder) or 'none'}"]
    if not ladder:
        return DimensionScore(D.SCALE_READINESS.value, 0.1, "no scale evidence")
    score = 0.2
    if "lab" in ladder:
        score = max(score, 0.3)
    if "bench" in ladder:
        score = max(score, 0.5)
    if "pilot" in ladder:
        score = max(score, 0.7)
    if "field" in ladder:
        score = max(score, 0.9)
    score = min(score + 0.1 * (len(ladder) - 1), 1.0)
    return DimensionScore(D.SCALE_READINESS.value, score, "; ".join(basis))


def score_environmental(payload: dict[str, Any]) -> DimensionScore:
    env = payload.get("environment_audit") or {}
    basis: list[str] = []
    if not env:
        return DimensionScore(D.ENVIRONMENTAL_ACCEPTABILITY.value, 0.2, "no environment audit")
    status = env.get("status")
    if status == "cleared":
        score = 0.9
    elif status == "conditional":
        score = 0.55
    elif status in ("open", "expired"):
        score = 0.1
    else:  # not_run
        score = 0.2
    basis.append(f"audit status={status}")
    findings = env.get("findings", []) or []
    if any(f.get("severity") == "high" and f.get("status") not in ("closed", "waived") for f in findings):
        score = min(score, 0.1)
        basis.append("open high-severity finding")
    return DimensionScore(D.ENVIRONMENTAL_ACCEPTABILITY.value, score, "; ".join(basis))


def score_biosafety(payload: dict[str, Any]) -> DimensionScore:
    env = payload.get("environment_audit") or {}
    # biosafety reads ammonia/emission outcomes + audit findings
    parts: list[float] = []
    basis: list[str] = []
    for e in payload.get("experiment_results", []) or []:
        for o in e.get("outcomes", []) or []:
            name = o.get("name", "").lower()
            if "ammonia" in name or "nh3" in name or "氨" in name or "emission" in name:
                st = o.get("status")
                if st == "met":
                    parts.append(1.0)
                    basis.append(f"{o.get('name')} emission met")
                elif st == "not_met":
                    parts.append(0.0)
                    basis.append(f"{o.get('name')} emission not_met")
    if env:
        open_high = [f for f in env.get("findings", []) or []
                     if f.get("severity") == "high" and f.get("status") not in ("closed", "waived")]
        if open_high:
            parts.append(0.15)
            basis.append(f"environment audit has {len(open_high)} open high finding(s)")
        elif env.get("status") == "cleared":
            parts.append(0.9)
            basis.append("environment audit cleared (no open high findings)")
        elif env.get("status") == "conditional":
            parts.append(0.55)
            basis.append("environment audit conditional")
    if not parts:
        return DimensionScore(D.BIOSAFETY.value, 0.3, "no biosafety-specific evidence")
    return DimensionScore(D.BIOSAFETY.value, _avg(parts), "; ".join(basis))


def score_regulatory(payload: dict[str, Any]) -> DimensionScore:
    reg = payload.get("regulatory_status") or {}
    if not reg:
        return DimensionScore(D.REGULATORY_STATUS.value, 0.2, "no regulatory status reported")
    parts: list[float] = []
    basis: list[str] = []
    if reg.get("verified"):
        parts.append(0.8)
        basis.append("verified")
    else:
        parts.append(0.1)
        basis.append("not verified")
    if reg.get("current"):
        parts.append(0.9)
        basis.append("current")
    else:
        parts.append(0.1)
        basis.append("expired/stale")
    ps = reg.get("permit_status")
    if ps == "granted":
        parts.append(0.9)
        basis.append("permit granted")
    elif ps == "not_required":
        parts.append(0.8)
        basis.append("permit not required")
    elif ps in ("pending", "unknown"):
        parts.append(0.4)
        basis.append(f"permit {ps}")
    elif ps == "denied":
        parts.append(0.0)
        basis.append("permit denied")
    return DimensionScore(D.REGULATORY_STATUS.value, _avg(parts), "; ".join(basis))


def score_economic(payload: dict[str, Any]) -> DimensionScore:
    lca = payload.get("lca") or {}
    basis: list[str] = []
    if not lca:
        return DimensionScore(D.ECONOMIC_VIABILITY.value, 0.25, "no LCA/techno-economic data")
    status = lca.get("status")
    if status == "cleared":
        score = 0.85
    elif status == "conditional":
        score = 0.5
    elif status in ("open", "expired", "not_run"):
        score = 0.2
    else:
        score = 0.25
    basis.append(f"LCA status={status}")
    findings = lca.get("findings", []) or []
    for f in findings:
        desc = (f.get("description", "")).lower()
        if any(w in desc for w in ("cost", "经济", "成本", "unit cost", "unacceptable")):
            if f.get("severity") == "high" and f.get("status") not in ("closed", "waived"):
                score = min(score, 0.15)
                basis.append(f"high-cost finding open: {f.get('description')}")
    return DimensionScore(D.ECONOMIC_VIABILITY.value, score, "; ".join(basis))


def score_monitorability(payload: dict[str, Any]) -> DimensionScore:
    sp = payload.get("scaleup_plan") or {}
    parts: list[float] = []
    basis: list[str] = []
    if sp.get("monitoring_plan"):
        parts.append(0.9)
        basis.append("monitoring plan present")
    else:
        parts.append(0.1)
        basis.append("no monitoring plan")
    if sp.get("shutdown_conditions"):
        parts.append(0.9)
        basis.append("shutdown conditions present")
    else:
        parts.append(0.1)
        basis.append("no shutdown conditions")
    if not parts:
        return DimensionScore(D.MONITORABILITY.value, 0.2, "no scale-up plan")
    return DimensionScore(D.MONITORABILITY.value, _avg(parts), "; ".join(basis))


def score_reversibility(payload: dict[str, Any]) -> DimensionScore:
    sp = payload.get("scaleup_plan") or {}
    basis: list[str] = []
    parts: list[float] = []
    if sp.get("rollback_plan"):
        parts.append(0.9)
        basis.append("rollback plan present")
    else:
        parts.append(0.2)
        basis.append("no rollback plan")
    # field injection is harder to reverse than lab work
    scales = [e.get("scale") for e in payload.get("experiment_results", []) or []]
    if "field" in scales:
        parts.append(0.3)
        basis.append("field-scale (lower reversibility)")
    elif "pilot" in scales:
        parts.append(0.6)
        basis.append("pilot-scale")
    if not parts:
        return DimensionScore(D.REVERSIBILITY.value, 0.4, "no scale-up plan")
    return DimensionScore(D.REVERSIBILITY.value, _avg(parts), "; ".join(basis))


def score_residual_risk(payload: dict[str, Any]) -> DimensionScore:
    """Inverse dimension: returns the 'goodness' (1 = negligible residual risk)."""
    basis: list[str] = []
    penalties: list[float] = []
    # open medium/low env findings
    env = payload.get("environment_audit") or {}
    for f in env.get("findings", []) or []:
        if f.get("status") not in ("closed", "waived"):
            penalties.append(0.2 if f.get("severity") == "high" else 0.08)
            basis.append(f"env finding open: {f.get('id', '?')}")
    # residual uncertainty statements
    ru = payload.get("residual_uncertainty") or []
    if isinstance(ru, list):
        for u in ru:
            impact = u.get("impact") if isinstance(u, dict) else None
            if impact == "high":
                penalties.append(0.25)
                basis.append("high-impact residual uncertainty")
            elif impact == "medium":
                penalties.append(0.12)
                basis.append("medium-impact residual uncertainty")
    # unresolved red-team non-blocking findings add risk
    rt = payload.get("red_team_report") or {}
    for f in rt.get("findings", []) or []:
        if f.get("severity") in ("HIGH", "MEDIUM") and f.get("resolution") not in ("resolved", "accepted_risk"):
            penalties.append(0.15 if f.get("severity") == "HIGH" else 0.08)
            basis.append(f"red-team {f.get('severity')} unresolved: {f.get('id', '?')}")
    score = 1.0 - min(sum(penalties), 1.0)
    if not penalties:
        basis.append("no open residual-risk signals")
    return DimensionScore(D.RESIDUAL_RISK.value, score, "; ".join(basis))


_SCORERS: dict[str, Any] = {
    D.SCIENTIFIC_VALIDITY.value: score_scientific_validity,
    D.EVIDENCE_QUALITY.value: score_evidence_quality,
    D.REPRODUCIBILITY.value: score_reproducibility,
    D.ENGINEERING_FEASIBILITY.value: score_engineering_feasibility,
    D.SCALE_READINESS.value: score_scale_readiness,
    D.ENVIRONMENTAL_ACCEPTABILITY.value: score_environmental,
    D.BIOSAFETY.value: score_biosafety,
    D.REGULATORY_STATUS.value: score_regulatory,
    D.ECONOMIC_VIABILITY.value: score_economic,
    D.MONITORABILITY.value: score_monitorability,
    D.REVERSIBILITY.value: score_reversibility,
    D.RESIDUAL_RISK.value: score_residual_risk,
}


def score_dimensions(payload: dict[str, Any]) -> dict[str, DimensionScore]:
    result: dict[str, DimensionScore] = {}
    for dim in ALL_DIMENSIONS:
        result[dim.value] = _SCORERS[dim.value](payload)
    # honor explicit overrides (audit-grade determinism escape hatch)
    over = payload.get("dimension_overrides") or {}
    for dim, value in over.items():
        if dim in result and isinstance(value, (int, float)):
            score = result[dim]
            result[dim] = DimensionScore(dim, _clamp(float(value)), score.basis + f" [overridden={value}]")
    return result


def below_floor_map(scores: dict[str, float], floor_map: dict[str, float]) -> list[str]:
    return sorted(dim for dim, floor in floor_map.items() if scores.get(dim, 0.0) < floor)


def mcda_analysis(
    payload: dict[str, Any],
    table: RuleTable,
    target: ResearchState,
) -> dict[str, Any]:
    """Multi-criteria decision analysis: weighted composite + per-dimension floors.

    Returns a dict with weights, composite score, floors, and below-floor list.
    Gate PASS requires every floor cleared (minimum-dimension rule).
    """
    scores = {d: s.score for d, s in score_dimensions(payload).items()}
    target_grade = table.grade(target)
    floors = table.floor_map(target_grade)

    weights: dict[str, float] = {}
    overrides = (payload.get("dimension_overrides") or {})
    declared = overrides.get("weights") if isinstance(overrides.get("weights"), dict) else {}
    for dim in ALL_DIMENSIONS:
        weights[dim.value] = float(declared.get(dim.value, 1.0))
    wsum = sum(weights.values()) or 1.0
    weights = {k: v / wsum for k, v in weights.items()}

    composite = sum(scores[d] * weights[d] for d in scores)
    below = below_floor_map(scores, floors)
    return {
        "weights": {k: round(v, 4) for k, v in weights.items()},
        "scores": {k: round(v, 3) for k, v in scores.items()},
        "floors": {k: round(v, 3) for k, v in floors.items()},
        "composite": round(composite, 3),
        "below_floor": below,
        "passed": len(below) == 0,
    }


def risk_benefit_matrix(payload: dict[str, Any], scores: dict[str, float]) -> dict[str, Any]:
    """Risk-benefit assessment. benefit = mean of positive dimensions;
    residual_risk = inverse of RESIDUAL_RISK score."""
    positive = [
        scores.get(d, 0.0)
        for d in (D.SCIENTIFIC_VALIDITY.value, D.ENGINEERING_FEASIBILITY.value,
                  D.ENVIRONMENTAL_ACCEPTABILITY.value, D.ECONOMIC_VIABILITY.value)
    ]
    benefit = _avg(positive, 0.0)
    residual_risk = 1.0 - scores.get(D.RESIDUAL_RISK.value, 0.5)
    net_positive = benefit >= 0.5 and residual_risk <= 0.5
    if benefit >= 0.6 and residual_risk <= 0.3:
        assessment = "benefit clearly outweighs residual risk"
    elif net_positive:
        assessment = "benefit moderately outweighs residual risk"
    elif benefit >= 0.5:
        assessment = "benefit present but residual risk elevated; conditional release warranted"
    else:
        assessment = "benefit insufficient relative to residual risk"
    return {
        "net_positive": net_positive,
        "benefit": f"mean positive-dimension benefit {benefit:.2f}",
        "risk": f"residual risk {residual_risk:.2f} (inverse of RESIDUAL_RISK)",
        "residual_risk_score": round(residual_risk, 3),
        "benefit_score": round(benefit, 3),
        "assessment": assessment,
    }
