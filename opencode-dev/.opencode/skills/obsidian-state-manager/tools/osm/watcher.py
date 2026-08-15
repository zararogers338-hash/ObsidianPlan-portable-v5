"""Staleness & contradiction watcher (tool 5 of spec §五).

Pure analysis over a projection + "now". Two detectors:
  1. Expiry: evidence items and validated conclusions whose review_by date has
     passed -> STALENESS_FLAGGED candidates; if the stream is VALIDATED and any
     supporting evidence expired, propose downgrade to UNDER_REVIEW.
  2. Contradiction: a hypothesis marked CONTESTED (by evidence.attach with
   contradicts=[...] or hypothesis.set_status) while the stream is at or past
     DESIGNING -> propose downgrade to HYPOTHESIS_BUILDING's predecessor state
     per the transition table's corrective edges.

The watcher never mutates the stream; it returns *proposals*. The service
layer decides whether to apply them (auto-downgrade) or report them.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from .models import HypothesisStatus, ResearchState
from .store import Projection

# States from which a contested hypothesis forces a downgrade, and to where.
_CONTESTED_DOWNGRADE: dict[ResearchState, ResearchState] = {
    ResearchState.DESIGNING: ResearchState.HYPOTHESIS_BUILDING,
    ResearchState.AWAITING_DATA: ResearchState.DESIGNING,
    ResearchState.ANALYZING: ResearchState.EVIDENCE_GATHERING,
    ResearchState.UNDER_REVIEW: ResearchState.ANALYZING,
    ResearchState.VALIDATED: ResearchState.UNDER_REVIEW,
}


def _parse_iso(ts: str) -> datetime | None:
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None


def scan(proj: Projection, *, now: datetime | None = None) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    stale_evidence: list[dict[str, Any]] = []
    for e in proj.evidence:
        if e.get("retracted"):
            continue
        review_by = e.get("review_by")
        if not review_by:
            continue
        due = _parse_iso(str(review_by))
        if due and due < now:
            stale_evidence.append({
                "ref": e["ref"],
                "review_by": review_by,
                "attached_revision": e.get("attached_revision"),
            })

    contested = [h for h in proj.hypotheses if h.get("status") == HypothesisStatus.CONTESTED.value]

    proposals: list[dict[str, Any]] = []
    if contested and proj.state in _CONTESTED_DOWNGRADE:
        proposals.append({
            "kind": "contradiction_downgrade",
            "from_state": proj.state.value,
            "to_state": _CONTESTED_DOWNGRADE[proj.state].value,
            "reason": f"{len(contested)} contested hypothesis(es): "
                      + ", ".join(h.get("id", "?") for h in contested),
            "contested_ids": [h.get("id") for h in contested],
        })
    elif stale_evidence and proj.state in (ResearchState.VALIDATED, ResearchState.UNDER_REVIEW):
        proposals.append({
            "kind": "staleness_downgrade",
            "from_state": proj.state.value,
            "to_state": ResearchState.UNDER_REVIEW.value,
            "reason": f"{len(stale_evidence)} evidence item(s) past review_by horizon",
            "stale_refs": [s["ref"] for s in stale_evidence],
        })

    return {
        "now": now.isoformat().replace("+00:00", "Z"),
        "state": proj.state.value,
        "stale_evidence": stale_evidence,
        "contested_hypotheses": [h.get("id") for h in contested],
        "proposals": proposals,
    }
