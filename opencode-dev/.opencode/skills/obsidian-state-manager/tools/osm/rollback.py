"""Rollback: compensating transitions + snapshot diffing (tool 4 of spec §五).

Two capabilities live here:
  1. state.rollback — move the stream from state A back to an earlier state B
     by appending a DOWNGRADE_TRIGGERED event (never by rewriting history).
  2. state.diff — compare two snapshots (or a snapshot vs live rebuild) and
     report what changed, for auditing and for "what did approval X actually
     approve" questions.
"""

from __future__ import annotations

from typing import Any

from .errors import OsmError, OsmErrorCode
from .models import ResearchState
from .store import Projection

# Order used to decide whether a rollback moves "backwards". DEPLOYABLE and
# REJECTED are sinks: DEPLOYABLE cannot be rolled back at all (irreversible
# publication), REJECTED reopens only via the transition table's approval path.
_STATE_ORDER: list[ResearchState] = [
    ResearchState.OPEN,
    ResearchState.SCOPED,
    ResearchState.EVIDENCE_GATHERING,
    ResearchState.HYPOTHESIS_BUILDING,
    ResearchState.DESIGNING,
    ResearchState.AWAITING_DATA,
    ResearchState.ANALYZING,
    ResearchState.UNDER_REVIEW,
    ResearchState.VALIDATED,
    ResearchState.DEPLOYABLE,
]


def check_rollback(proj: Projection, target: ResearchState) -> None:
    """Validate a rollback request against the current projection."""
    current = proj.state
    if current is ResearchState.DEPLOYABLE:
        raise OsmError(
            OsmErrorCode.IRREVERSIBLE_TRANSITION,
            "DEPLOYABLE is an irreversible, human-approved publication state and cannot "
            "be rolled back. If deployment was premature, open a new project stream that "
            "supersedes this one and link it in the decision record.",
            detail={"current": current.value, "requested_target": target.value},
        )
    if current is target:
        raise OsmError(
            OsmErrorCode.INPUT_SCHEMA_VIOLATION,
            f"Rollback target equals current state ({current.value}); nothing to do.",
        )
    if current not in _STATE_ORDER or target not in _STATE_ORDER:
        raise OsmError(
            OsmErrorCode.TRANSITION_REJECTED,
            f"Rollback {current.value} → {target.value} is not on the linear research axis; "
            "use an explicit legal transition instead (e.g., REJECTED → OPEN with approval).",
            detail={"current": current.value, "target": target.value},
        )
    if _STATE_ORDER.index(target) >= _STATE_ORDER.index(current):
        raise OsmError(
            OsmErrorCode.TRANSITION_REJECTED,
            f"Rollback must move backwards; {current.value} → {target.value} moves forwards. "
            "Use state.transition for forward moves.",
            detail={"current": current.value, "target": target.value},
        )


def _flatten(value: Any, prefix: str = "") -> dict[str, str]:
    """Flatten nested dict/list into 'a.b[0].c' -> repr(value) for diffing."""
    out: dict[str, str] = {}
    if isinstance(value, dict):
        for k, v in sorted(value.items()):
            out.update(_flatten(v, f"{prefix}.{k}" if prefix else str(k)))
    elif isinstance(value, list):
        for i, v in enumerate(value):
            out.update(_flatten(v, f"{prefix}[{i}]"))
    else:
        out[prefix] = repr(value)
    return out


def diff_snapshots(old: dict[str, Any], new: dict[str, Any]) -> dict[str, Any]:
    """Structural diff between two snapshot dicts (added/removed/changed paths)."""
    fo, fn = _flatten(old), _flatten(new)
    added = sorted(k for k in fn if k not in fo)
    removed = sorted(k for k in fo if k not in fn)
    changed = sorted(k for k in fo if k in fn and fo[k] != fn[k])
    return {
        "added": [{"path": k, "value": fn[k]} for k in added],
        "removed": [{"path": k, "value": fo[k]} for k in removed],
        "changed": [{"path": k, "from": fo[k], "to": fn[k]} for k in changed],
        "counts": {"added": len(added), "removed": len(removed), "changed": len(changed)},
    }
