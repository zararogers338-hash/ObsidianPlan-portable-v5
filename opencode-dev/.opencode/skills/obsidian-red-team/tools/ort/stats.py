"""Statistical-structure checker (统计结构检查器).

Attacks the statistical reporting of a claim/analysis, offline and
deterministically:

  - p-value-only reporting (no effect size, no CI) → finding
  - selective reporting (significant results reported, nulls hidden)
  - tiny-effect-with-significance (p < alpha but |d| < 0.2) → finding
  - overfitting signals (many predictors, few independent samples)
  - model-assumption violations (independence, normality, equal variance)
  - missing n / missing uncertainty in the reported statistics

The checker does NOT re-run the author's analysis; it audits the *reporting
structure* and flags what is missing or misused.
"""

from __future__ import annotations

import math
from typing import Any

from common import ToolError, emit_progress
from errors import OrtErrorCode, OrtError

# Cohen's d magnitude thresholds (common conventions)
D_SMALL = 0.2
D_MEDIUM = 0.5
D_LARGE = 0.8


def _audit(analysis: dict[str, Any]) -> dict[str, Any]:
    a_id = str(analysis.get("id", "?"))
    findings: list[dict] = []

    p_value = analysis.get("p_value")
    effect_size = analysis.get("effect_size")
    effect_type = str(analysis.get("effect_type", "cohens_d"))
    ci = analysis.get("ci")
    n_independent = analysis.get("n_independent")
    n_rows = analysis.get("n_rows")
    predictors = analysis.get("n_predictors")
    hypotheses = analysis.get("n_hypotheses_tested")
    reported_results = analysis.get("n_results_reported")
    significance_level = float(analysis.get("significance_level", 0.05))
    conclusion = str(analysis.get("conclusion", ""))

    # 1) p-only reporting
    if p_value is not None and effect_size is None and ci is None:
        findings.append({
            "id": a_id, "severity": "CRITICAL", "dimension": "statistical_analysis",
            "message": "p-value-only reporting: no effect size or confidence interval",
            "code": "STAT_P_ONLY",
        })

    # 2) significant-but-tiny effect
    if p_value is not None and effect_size is not None:
        try:
            pv = float(p_value)
            es = float(effect_size)
            if pv < significance_level and effect_type in ("cohens_d", "hedges_g"):
                if abs(es) < D_SMALL:
                    findings.append({
                        "id": a_id, "severity": "CRITICAL", "dimension": "statistical_analysis",
                        "message": f"p={pv} < {significance_level} but |d|={abs(es):.3f} < 0.2: "
                                   "statistically significant yet engineering-negligible; "
                                   "concluding 'meaningful' is an effect-size trap",
                        "code": "STAT_TINY_EFFECT",
                    })
        except (TypeError, ValueError):
            pass

    # 3) selective reporting
    if hypotheses is not None and reported_results is not None:
        if reported_results < hypotheses:
            findings.append({
                "id": a_id, "severity": "MAJOR", "dimension": "statistical_analysis",
                "message": f"selective reporting: {reported_results}/{hypotheses} results reported",
                "code": "STAT_SELECTIVE",
            })

    # 4) overfitting
    if predictors is not None and n_independent is not None:
        if n_independent <= predictors * 10:
            findings.append({
                "id": a_id, "severity": "MAJOR", "dimension": "statistical_analysis",
                "message": f"overfitting risk: {predictors} predictors vs {n_independent} independent "
                           "samples (rule of thumb ≥ 10:1)",
                "code": "STAT_OVERFIT",
            })

    # 5) model assumptions
    assumptions = analysis.get("assumptions_checked") or []
    for needed in ("independence", "normality", "equal_variance"):
        if needed not in assumptions and analysis.get("assumption_check_required", True):
            findings.append({
                "id": a_id, "severity": "MINOR", "dimension": "statistical_analysis",
                "message": f"model assumption {needed!r} not reported as checked",
                "code": f"STAT_ASSUMPTION_{needed.upper()}",
            })

    # 6) missing n / missing uncertainty
    if n_independent is None:
        findings.append({
            "id": a_id, "severity": "MAJOR", "dimension": "statistical_analysis",
            "message": "independent sample size n not reported",
            "code": "STAT_NO_N",
        })
    if n_independent is not None and n_rows is not None and n_rows > n_independent:
        findings.append({
            "id": a_id, "severity": "CRITICAL", "dimension": "statistical_analysis",
            "message": f"{n_rows} rows treated as {n_independent} independent samples: "
                       "pseudo-replication risk in the statistical unit",
            "code": "STAT_PSEUDO_UNIT",
        })

    # conclusion escalation: conclusion wording claims causality on correlation
    if conclusion and any(k in conclusion for k in ("causes", "proves", "demonstrates")):
        findings.append({
            "id": a_id, "severity": "MAJOR", "dimension": "epistemic_escalation",
            "message": f"conclusion wording {conclusion!r} overstates support (causal claim on "
                       "correlational/observational evidence)",
            "code": "STAT_CAUSAL_WORDING",
        })

    return {"analysis_id": a_id, "findings": findings}


def main(payload: dict[str, Any]) -> dict[str, Any]:
    emit_progress("stats: auditing statistical reporting structure")
    analyses = payload.get("analyses")
    if not analyses:
        raise OrtError(OrtErrorCode.INPUT_SCHEMA_VIOLATION,
                       "stats: analyses array is required",
                       detail={"how_to_fix": "attach the statistical claims to audit (p/effect/ci/n)"})
    results = [_audit(a) for a in analyses]
    all_findings = [f for r in results for f in r["findings"]]
    critical = [f for f in all_findings if f["severity"] in ("CRITICAL", "BLOCKING")]
    return {
        "analyses": results,
        "summary": {
            "analyses_checked": len(analyses),
            "findings": len(all_findings),
            "critical": len(critical),
            "codes": sorted({f["code"] for f in all_findings}),
        },
    }


if __name__ == "__main__":
    from common import read_stdin_envelope, run_tool
    run_tool("stats", lambda: main(read_stdin_envelope()))
