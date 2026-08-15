"""GRADE-style certainty rating (5 domains), per SKILL.md §能力要求-7 and the
output.schema `grade` def. Mirrors GRADE guidance for evidence-based
conclusions, adapted for engineering/lab MICP evidence:

  baseline: randomized_trial / direct lab measurement  -> high
            quasi_experiment / field_experiment        -> moderate
            cohort / case_series / modeling            -> low
            review / other                             -> low
  downgrade domains: risk_of_bias, inconsistency, indirectness, imprecision
  upgrade domain:    dose_response_gradient
"""

from __future__ import annotations

from typing import Optional

from .meta_analyze import MetaResult

_STUDY_BASELINE = {
    "randomized_trial": "high",
    "lab_experiment": "high",
    "field_experiment": "moderate",
    "quasi_experiment": "moderate",
    "cohort": "low",
    "case_series": "low",
    "modeling": "low",
    "review": "low",
    "other": "low",
}

_DOMAIN_ORDER = ("risk_of_bias", "inconsistency", "indirectness", "imprecision", "dose_response_gradient")


def assess_grade(cards: list[dict], meta: Optional[MetaResult] = None) -> dict:
    """Assess certainty for the synthesized conclusion set.

    Returns the output.schema `grade` object: {certainty, domains}.
    """
    if not cards:
        return {"certainty": "very_low", "domains": [
            {"domain": "risk_of_bias", "rating": "no_evidence", "reason": "no evidence cards"}]}

    # ---- baseline from dominant study type ----
    study_types = [c.get("study_type") for c in cards]
    from collections import Counter
    dominant = Counter(study_types).most_common(1)[0][0] if study_types else "other"
    certainty = _STUDY_BASELINE.get(dominant, "low")

    domains: list[dict] = []

    # ---- risk_of_bias ----
    robs = [c.get("risk_of_bias", {}).get("overall", "unclear")
            for c in cards if isinstance(c.get("risk_of_bias"), dict)]
    high_robs = [r for r in robs if r in ("high", "critical")]
    critical = [r for r in robs if r == "critical"]
    unclear = [r for r in robs if r == "unclear"]
    if critical:
        # GRADE: critical risk of bias in >0 studies -> typically very serious
        # (downgrade by 2 when it affects most studies)
        if len(critical) / len(robs) >= 0.5:
            domains.append({"domain": "risk_of_bias", "rating": "very_serious",
                            "reason": f"{len(critical)}/{len(robs)} cards rated critical risk of bias"})
        else:
            domains.append({"domain": "risk_of_bias", "rating": "serious",
                            "reason": f"{len(critical)}/{len(robs)} cards rated critical risk of bias"})
    elif high_robs:
        domains.append({"domain": "risk_of_bias", "rating": "serious",
                        "reason": f"{len(high_robs)}/{len(robs) or 1} cards rated high/critical risk of bias"})
    elif unclear and len(robs) and len(unclear) / len(robs) > 0.5:
        domains.append({"domain": "risk_of_bias", "rating": "serious",
                        "reason": f"{len(unclear)}/{len(robs)} cards have unclear risk of bias"})
    else:
        domains.append({"domain": "risk_of_bias", "rating": "not_serious",
                        "reason": "risk of bias across cards is low/moderate"})

    # ---- inconsistency (I2) ----
    if meta is not None and meta.i2 is not None:
        if meta.i2 >= 75:
            domains.append({"domain": "inconsistency", "rating": "serious",
                            "reason": f"I2={meta.i2:.1f}% — considerable unexplained inconsistency"})
        elif meta.i2 >= 50:
            domains.append({"domain": "inconsistency", "rating": "moderate",
                            "reason": f"I2={meta.i2:.1f}% — substantial inconsistency"})
        else:
            domains.append({"domain": "inconsistency", "rating": "not_serious",
                            "reason": f"I2={meta.i2:.1f}% — consistent effects"})
    else:
        domains.append({"domain": "inconsistency", "rating": "not_serious",
                        "reason": "pooling not performed; narrative synthesis"})

    # ---- indirectness ----
    # if multiple MICP layers are mixed, the population/outcome link is indirect
    layers = {c.get("layer") for c in cards}
    if len(layers) > 1:
        domains.append({"domain": "indirectness", "rating": "serious",
                        "reason": f"evidence spans multiple layers {sorted(layers)} — indirect for any single layer"})
    else:
        domains.append({"domain": "indirectness", "rating": "not_serious",
                        "reason": f"evidence is single-layer ({layers or {'engineering_performance'}})"})

    # ---- imprecision ----
    if meta is not None and meta.ci95:
        width = (meta.ci95[1] - meta.ci95[0]) if meta.ci95[1] is not None and meta.ci95[0] is not None else None
        if width is not None and meta.pooled_effect is not None and meta.pooled_effect != 0:
            if width > abs(meta.pooled_effect):
                domains.append({"domain": "imprecision", "rating": "serious",
                                "reason": f"95% CI width {width:.3f} exceeds the effect magnitude — very imprecise"})
            else:
                domains.append({"domain": "imprecision", "rating": "not_serious",
                                "reason": f"95% CI width {width:.3f} acceptable"})
        else:
            domains.append({"domain": "imprecision", "rating": "not_serious",
                            "reason": "CI not meaningful for this pool"})
    else:
        domains.append({"domain": "imprecision", "rating": "not_serious",
                        "reason": "narrative synthesis; imprecision assessed qualitatively in conclusions"})

    # ---- dose-response gradient (upgrade only) ----
    n_cards = len(cards)
    if n_cards >= 3:
        # crude proxy: >=3 distinct concentration values reported across cards
        concentrations = set()
        for c in cards:
            conc = c.get("treatment", {}).get("cementation_solution_concentration", {}).get("value")
            if conc is not None:
                concentrations.add(conc)
        if len(concentrations) >= 3:
            domains.append({"domain": "dose_response_gradient", "rating": "present",
                            "reason": f"{len(concentrations)} distinct concentrations observed across cards"})
        else:
            domains.append({"domain": "dose_response_gradient", "rating": "absent",
                            "reason": "insufficient concentration spread for a gradient claim"})
    else:
        domains.append({"domain": "dose_response_gradient", "rating": "absent",
                        "reason": "fewer than 3 cards — gradient not assessable"})

    # ---- combine ----
    downgrades = sum(1 for d in domains
                     if d["rating"] in ("serious", "very_serious") and d["domain"] != "dose_response_gradient")
    very_serious = [d["domain"] for d in domains if d["rating"] == "very_serious" and d["domain"] != "dose_response_gradient"]
    serious_domains = [d["domain"] for d in domains if d["rating"] in ("serious", "very_serious") and d["domain"] != "dose_response_gradient"]
    upgrade = any(d["domain"] == "dose_response_gradient" and d["rating"] == "present" for d in domains)

    level_order = ["high", "moderate", "low", "very_low"]
    idx = level_order.index(certainty)
    if very_serious:
        idx = min(idx + 2, 3)  # very serious -> downgrade 2
    elif downgrades == 1:
        idx = min(idx + 1, 3)
    elif downgrades >= 2:
        idx = min(idx + 2, 3)
    if upgrade:
        idx = max(idx - 1, 0)
    certainty = level_order[idx]

    if serious_domains:
        domains.append({"domain": "summary", "rating": certainty,
                        "reason": f"downgraded for: {', '.join(serious_domains)}"})

    return {"certainty": certainty, "domains": domains}
