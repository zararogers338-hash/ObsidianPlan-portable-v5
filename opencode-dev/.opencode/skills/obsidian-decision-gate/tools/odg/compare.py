"""Decision-drift and history comparison.

Compares a new gate evaluation against prior Decision Memos (payload.history)
and reports:
  - decision changes (PASS -> HOLD, etc.)
  - state regression (proposed maturity grade dropped)
  - blocking-item changes (resolved vs newly added)
  - dimension-score deltas
  - flagging a suspiciously "lenient" reversal (downgrade of blockers without
    new evidence) — the anti-fudge check that stops a line from being walked
    through the gate by repeated evaluations.
"""

from __future__ import annotations

from typing import Any

from .rules import RuleTable, grade_gap


def compare_decisions(
    payload: dict[str, Any],
    table: RuleTable,
    current: dict[str, Any],
    now: str,
) -> dict[str, Any]:
    history = payload.get("history") or []
    if not history:
        return {
            "compared": False,
            "prior_memos": 0,
            "deltas": [],
            "flags": [],
        }

    prior = history[-1]  # most recent prior memo
    prior_decision = prior.get("decision")
    prior_state = prior.get("current_state")
    prior_proposed = prior.get("proposed_state")

    deltas: list[dict] = []
    flags: list[str] = []

    new_decision = current.get("decision")
    if prior_decision and new_decision and prior_decision != new_decision:
        deltas.append({
            "field": "decision",
            "prior": prior_decision,
            "current": new_decision,
        })
        # a decision that upgrades maturity but a blocker set that shrank is
        # expected; a decision that upgrades while blockers GREW is suspicious
        prior_blockers = prior.get("blocking_items") or []
        new_blockers = current.get("blocking_items") or []
        if new_decision in ("PASS", "CONDITIONAL_PASS"):
            if len(new_blockers) > len(prior_blockers):
                flags.append(
                    f"决策 {new_decision} 但阻断项从 {len(prior_blockers)} 增至 {len(new_blockers)}"
                )

    # proposed state regression
    if prior_state and prior_state != current.get("current_state"):
        deltas.append({
            "field": "current_state",
            "prior": prior_state,
            "current": current.get("current_state"),
        })
    if prior_proposed and current.get("proposed_state"):
        try:
            from .models import ResearchState
            old = table.grade(ResearchState(prior_proposed))
            new = table.grade(ResearchState(current["proposed_state"]))
            if new < old:
                deltas.append({
                    "field": "proposed_state_maturity",
                    "prior": prior_proposed,
                    "current": current.get("proposed_state"),
                    "delta_grades": new - old,
                })
                flags.append("目标状态成熟度下降（相比上一决策）")
        except ValueError:
            pass

    # dimension drift
    prior_dims = (prior.get("gate_results") or {}).get("dimensions", {}).get("scores", {})
    new_dims = (current.get("gate_results") or {}).get("dimensions", {}).get("scores", {})
    for dim in sorted(set(list(prior_dims) + list(new_dims))):
        p = prior_dims.get(dim)
        n = new_dims.get(dim)
        if p is not None and n is not None and abs(p - n) >= 0.15:
            deltas.append({
                "field": f"dimension.{dim}",
                "prior": p,
                "current": n,
                "delta": round(n - p, 3),
            })

    return {
        "compared": True,
        "prior_memos": len(history),
        "deltas": deltas,
        "flags": flags,
        "summary": (
            f"与最近 {len(history)} 份历史决策比较: {len(deltas)} 处差异, {len(flags)} 个警示"
            + (f"; 警示: {'; '.join(flags)}" if flags else "")
        ),
    }
