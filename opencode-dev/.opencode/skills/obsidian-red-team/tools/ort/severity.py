"""Severity scorer (风险严重度评分器).

Deterministically scores a candidate issue into
INFO / MINOR / MAJOR / CRITICAL / BLOCKING using a transparent feature vector
(no hidden "feels critical" logic):

  base impact      1=cosmetic 2=local 3=core 4=fatal
  affected_domain  deployment/safety/finance/legal = +1 boost
  reproducibility impact adds +1 when it breaks reproducibility
  certainty of the defect: observed/reported/hypothesis
  consequence_probability: certain/likely/possible

The scorer returns the chosen level plus the exact rules that fired, so the
decision is auditable.

Input shape (`issues`):
  [
    {
      "id": "...",
      "impact": 1|2|3|4,
      "affected_domain": "science|deployment|safety|finance|legal|reproducibility",
      "certainty": "observed|reported|hypothesis",
      "consequence_probability": "certain|likely|possible",
      "overrides": "BLOCKING" | null
    }
  ]
"""

from __future__ import annotations

from typing import Any

from common import ToolError, emit_progress
from errors import OrtErrorCode, OrtError

LEVEL_ORDER = ["INFO", "MINOR", "MAJOR", "CRITICAL", "BLOCKING"]  # score 1..5

IMPACT_LABEL = {1: "cosmetic", 2: "local", 3: "core", 4: "fatal"}
DOMAIN_BOOST = {"deployment", "safety", "finance", "legal"}


def _score(issue: dict[str, Any]) -> dict[str, Any]:
    i_id = str(issue.get("id", "?"))
    overrides = issue.get("overrides")
    if overrides == "BLOCKING":
        return {
            "id": i_id,
            "severity": "BLOCKING",
            "rules": ["override:BLOCKING"],
        }

    impact = int(issue.get("impact", 2))
    domain = str(issue.get("affected_domain", "science"))
    certainty = str(issue.get("certainty", "reported"))
    prob = str(issue.get("consequence_probability", "likely"))

    score = impact  # 1..4
    reasons: list[str] = [f"impact={impact} ({IMPACT_LABEL.get(impact, '?')})"]
    if domain in DOMAIN_BOOST:
        score += 1
        reasons.append(f"domain_boost:{domain}")
    if domain == "reproducibility":
        score += 1
        reasons.append("domain_boost:reproducibility")

    # certainty dampens (hypothesis attacks are weaker than observed defects)
    if certainty == "hypothesis":
        score -= 1
        reasons.append("certainty_hypothesis:-1")
    elif certainty == "reported":
        reasons.append("certainty_reported:0")
    else:  # observed
        reasons.append("certainty_observed:0")

    if prob == "certain":
        reasons.append("prob_certain:0")
    elif prob == "possible":
        score -= 1
        reasons.append("prob_possible:-1")
    else:
        reasons.append("prob_likely:0")

    score = max(1, min(5, score))
    level = LEVEL_ORDER[score - 1]  # 1→INFO ... 5→BLOCKING
    reasons.append(f"mapped:{level}")
    return {"id": i_id, "severity": level, "rules": reasons, "score": score}


def main(payload: dict[str, Any]) -> dict[str, Any]:
    emit_progress("severity: scoring issues")
    issues = payload.get("issues")
    if not issues:
        raise OrtError(OrtErrorCode.INPUT_SCHEMA_VIOLATION,
                       "severity: issues array is required",
                       detail={"how_to_fix": "attach the candidate issues with impact/domain/certainty"})
    results = [_score(i) for i in issues]
    counts = {lvl: sum(1 for r in results if r["severity"] == lvl) for lvl in LEVEL_ORDER}
    return {
        "issues": results,
        "summary": {"total": len(results), "counts": counts},
    }


if __name__ == "__main__":
    from common import read_stdin_envelope, run_tool
    run_tool("severity", lambda: main(read_stdin_envelope()))
