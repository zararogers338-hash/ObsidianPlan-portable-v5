"""Decision Memo generator.

Turns a completed gate evaluation into the formal, schema-validated Decision
Memo (schemas/decision-memo.schema.json). Memos are versioned documents the
controller can file next to the state stream for audit.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from .mission import MissionCheck
from .rules import BlockingItem


def _ts(now: datetime | None = None) -> str:
    return (now or datetime.now(timezone.utc)).astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def generate_memo(
    *,
    task_id: str,
    project_id: str,
    title: str,
    current_state: str,
    proposed_state: str | None,
    decision: str,
    decision_summary: str,
    gate_results: dict[str, Any],
    blocking_items: list[BlockingItem],
    mission_check: MissionCheck,
    supporting_evidence: list[dict],
    opposing_evidence: list[dict],
    residual_uncertainty: list[dict],
    risk_benefit: dict[str, Any],
    required_human_approvals: list[dict],
    conditional_release_terms: list[dict],
    monitoring_requirements: list[dict],
    failure_conditions: list[dict],
    next_actions: list[dict],
    review_expiry: str | None,
    reviewer: str = "obsidian-decision-gate",
    approved_by: str | None = None,
    now: datetime | None = None,
    memo_seq: int = 1,
) -> dict[str, Any]:
    memo: dict[str, Any] = {
        "memo_id": f"odg-{task_id}-{memo_seq:04d}",
        "created_at": _ts(now),
        "task_id": task_id,
        "project_id": project_id,
        "title": title,
        "current_state": current_state,
        "proposed_state": proposed_state,
        "decision": decision,
        "decision_summary": decision_summary,
        "gate_results": gate_results,
        "blocking_items": [b.to_dict() for b in blocking_items],
        "criteria_met": mission_check.criteria_met,
        "criteria_not_met": mission_check.criteria_not_met,
        "supporting_evidence": supporting_evidence,
        "opposing_evidence": opposing_evidence,
        "residual_uncertainty": residual_uncertainty,
        "risk_benefit": risk_benefit,
        "required_human_approvals": required_human_approvals,
        "conditional_release_terms": conditional_release_terms,
        "monitoring_requirements": monitoring_requirements,
        "failure_conditions": failure_conditions,
        "next_actions": next_actions,
        "review_expiry": review_expiry,
        "reviewer": reviewer,
        "approved_by": approved_by,
        "provenance": {
            "skill": "obsidian-decision-gate",
            "generated_by": reviewer,
            "contract_version": "1.0",
        },
    }
    return memo
