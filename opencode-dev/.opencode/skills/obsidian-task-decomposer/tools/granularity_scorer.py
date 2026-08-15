#!/usr/bin/env python3
"""granularity_scorer.py — score task granularity to prevent both scheduling
explosion (tasks too fine) and unverifiable blobs (tasks too coarse).

Model (project-custom heuristic, method justified by PMBOK WBS practice and
planning-fallacy literature — see references/sources.md S5/S8):

Each node gets sub-scores in [0, 1] across dimensions; total = weighted sum * 100.
  - definition_of_done completeness (verifiable artifact + quantitative criterion)
  - single-owner assignability (exactly one primary skill)
  - effort within bounds [MIN_EFFORT, MAX_EFFORT] hours (defaults 0.5 .. 40)
  - context footprint within bound (est_context_tokens <= MAX_CONTEXT)
  - failure semantics present (failure_modes + retry_policy)

Verdicts: TOO_FINE / OK / TOO_COARSE / UNDER_SPECIFIED, plus concrete `issues`
and `suggestions`. Under-specified nodes can never be OK regardless of size:
a node without a verifiable definition-of-done is unverifiable by construction.

stdin: {"nodes": [ <task node objects> ], "config": {optional overrides}}
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from _common import ToolError, as_dict, as_list, as_number, as_str, run_tool

DEFAULTS = {
    "min_effort_hours": 0.5,     # below this a task is scheduling noise
    "max_effort_hours": 40.0,    # above this a task cannot be verified in one step
    "max_context_tokens": 120000,
    "weights": {
        "definition_of_done": 0.35,
        "single_owner": 0.15,
        "effort_bounds": 0.25,
        "context_bounds": 0.10,
        "failure_semantics": 0.15,
    },
}

VERIFIABLE_MARKERS = ("artifact", "criterion", "metric", "threshold", "acceptance")


def _score_dod(node: dict, issues: list[str], suggestions: list[str]) -> float:
    dod = node.get("definition_of_done")
    if not isinstance(dod, dict):
        issues.append("definition_of_done missing or not an object")
        suggestions.append("add definition_of_done with `artifact` and `acceptance_criteria`")
        return 0.0
    score = 0.0
    artifact = dod.get("artifact")
    if isinstance(artifact, str) and artifact.strip():
        score += 0.4
    else:
        issues.append("definition_of_done.artifact missing: no tangible output declared")
        suggestions.append("name the concrete artifact (file, dataset, report, decision record)")
    criteria = dod.get("acceptance_criteria")
    if isinstance(criteria, list) and criteria:
        quantitative = sum(
            1 for c in criteria
            if isinstance(c, dict) and isinstance(c.get("metric"), str)
            and ("threshold" in c or "comparator" in c or "target" in c)
        )
        if quantitative:
            score += 0.4 + 0.2 * min(1.0, quantitative / max(1, len(criteria)))
        else:
            score += 0.2
            issues.append("acceptance_criteria exist but none are quantitative (metric+threshold)")
            suggestions.append("add at least one measurable criterion, e.g. "
                               "{metric: 'uniformity_cv', comparator: '<=', threshold: 0.3}")
    else:
        issues.append("definition_of_done.acceptance_criteria missing or empty")
        suggestions.append("add acceptance_criteria so reviewers can verify completion")
    return min(1.0, score)


def _score_owner(node: dict, issues: list[str], suggestions: list[str]) -> float:
    primary = node.get("primary_skill")
    collab = node.get("collaborator_skill")
    if not isinstance(primary, str) or not primary.strip():
        issues.append("primary_skill missing: node has no accountable owner")
        suggestions.append("assign exactly one primary_skill")
        return 0.0
    if isinstance(collab, list):
        if len(collab) > 1:
            issues.append(f"{len(collab)} collaborator skills; contract allows at most 1")
            suggestions.append("split the node or demote extra collaborators to inputs")
            return 0.5
    return 1.0


def _score_effort(node: dict, cfg: dict, issues: list[str], suggestions: list[str]) -> tuple[float, str | None]:
    effort = node.get("est_effort_hours")
    if effort is None:
        issues.append("est_effort_hours missing: effort bounds cannot be checked")
        suggestions.append("estimate effort in hours (use budget_estimator for reference classes)")
        return 0.3, None
    e = as_number(effort, "est_effort_hours", min_v=0.0, max_v=10000.0)
    lo, hi = cfg["min_effort_hours"], cfg["max_effort_hours"]
    if e < lo:
        return 0.2, "TOO_FINE"
    if e > hi:
        issues.append(f"est_effort_hours {e} exceeds max {hi}: too large to verify in one step")
        suggestions.append("split into sub-tasks each <= max_effort_hours")
        return 0.2, "TOO_COARSE"
    # gentle preference for the middle of the range
    center_distance = abs(e - (lo + hi) / 2) / ((hi - lo) / 2)
    return 1.0 - 0.3 * center_distance, None


def _score_context(node: dict, cfg: dict, issues: list[str], suggestions: list[str]) -> float:
    ctx = node.get("est_context_tokens")
    if ctx is None:
        return 0.7  # unknown footprint: warn-level, not fatal
    c = as_number(ctx, "est_context_tokens", min_v=0.0, max_v=10_000_000)
    if c > cfg["max_context_tokens"]:
        issues.append(f"est_context_tokens {int(c)} exceeds {cfg['max_context_tokens']}: "
                      "one executor cannot hold this task's context")
        suggestions.append("split by sub-question or add an upstream summarization task")
        return 0.1
    return 1.0


def _score_failure_semantics(node: dict, issues: list[str], suggestions: list[str]) -> float:
    score = 0.0
    fm = node.get("failure_modes")
    if isinstance(fm, list) and fm and all(isinstance(x, str) and x.strip() for x in fm):
        score += 0.5
    else:
        issues.append("failure_modes missing: no declared way this task can fail")
        suggestions.append("list plausible failure modes (drives retry and replan decisions)")
    rp = node.get("retry_policy")
    if isinstance(rp, dict) and isinstance(rp.get("max_attempts"), int) and rp["max_attempts"] >= 0:
        score += 0.5
    else:
        issues.append("retry_policy.max_attempts missing")
        suggestions.append("add retry_policy {max_attempts, backoff, escalation}")
    return score


def score_node(node: dict, cfg: dict) -> dict:
    issues: list[str] = []
    suggestions: list[str] = []
    nid = node.get("id", "<unknown>")
    if not isinstance(node.get("id"), str) or not node.get("id"):
        issues.append("id missing")

    s_dod = _score_dod(node, issues, suggestions)
    s_owner = _score_owner(node, issues, suggestions)
    s_effort, size_verdict = _score_effort(node, cfg, issues, suggestions)
    s_ctx = _score_context(node, cfg, issues, suggestions)
    s_fail = _score_failure_semantics(node, issues, suggestions)

    w = cfg["weights"]
    total = 100.0 * (w["definition_of_done"] * s_dod
                     + w["single_owner"] * s_owner
                     + w["effort_bounds"] * s_effort
                     + w["context_bounds"] * s_ctx
                     + w["failure_semantics"] * s_fail)
    total = round(total, 1)

    if size_verdict == "TOO_FINE":
        verdict = "TOO_FINE"
        suggestions.append("merge into a sibling task or fold into its successor as a step")
    elif size_verdict == "TOO_COARSE":
        verdict = "TOO_COARSE"
    elif s_dod < 0.4 or s_owner < 1.0:
        verdict = "UNDER_SPECIFIED"
    elif total >= cfg.get("ok_threshold", 70.0):
        verdict = "OK"
    else:
        verdict = "UNDER_SPECIFIED"

    return {
        "id": nid,
        "score": total,
        "verdict": verdict,
        "subscores": {
            "definition_of_done": round(s_dod, 3),
            "single_owner": round(s_owner, 3),
            "effort_bounds": round(s_effort, 3),
            "context_bounds": round(s_ctx, 3),
            "failure_semantics": round(s_fail, 3),
        },
        "issues": issues,
        "suggestions": suggestions,
    }


def main(payload):
    doc = as_dict(payload, "$")
    nodes = as_list(doc.get("nodes"), "$.nodes", min_len=1, max_len=500)
    cfg = dict(DEFAULTS)
    cfg["weights"] = dict(DEFAULTS["weights"])
    user_cfg = doc.get("config")
    if user_cfg is not None:
        uc = as_dict(user_cfg, "$.config")
        for k in ("min_effort_hours", "max_effort_hours", "max_context_tokens", "ok_threshold"):
            if k in uc:
                cfg[k] = as_number(uc[k], f"$.config.{k}", min_v=0.0)
        if "weights" in uc:
            w = as_dict(uc["weights"], "$.config.weights")
            merged = dict(DEFAULTS["weights"])
            for k, v in w.items():
                if k in merged:
                    merged[k] = as_number(v, f"$.config.weights.{k}", min_v=0.0, max_v=1.0)
            total_w = sum(merged.values())
            if abs(total_w - 1.0) > 1e-6:
                raise ToolError("E_CONFIG", f"granularity weights must sum to 1.0, got {total_w}",
                                details={"weights": merged})
            cfg["weights"] = merged
    if cfg["min_effort_hours"] >= cfg["max_effort_hours"]:
        raise ToolError("E_CONFIG", "min_effort_hours must be < max_effort_hours")

    results = [score_node(as_dict(n, f"$.nodes[{i}]"), cfg) for i, n in enumerate(nodes)]
    counts: dict[str, int] = {}
    for r in results:
        counts[r["verdict"]] = counts.get(r["verdict"], 0) + 1
    return {
        "nodes": results,
        "summary": {
            "total": len(results),
            "verdicts": counts,
            "ok_ratio": round(counts.get("OK", 0) / len(results), 4),
            "mean_score": round(sum(r["score"] for r in results) / len(results), 1),
        },
    }


if __name__ == "__main__":
    run_tool("granularity_scorer", main)
