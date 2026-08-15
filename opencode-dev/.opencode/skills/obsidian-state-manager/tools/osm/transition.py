"""Lifecycle transition table and guard evaluation.

The table is data, not code: each row declares the legal edge, the guard
requirements, the roles allowed to drive it, whether it is irreversible,
and what happens on failure. Guards are evaluated against a *projection*
(the rebuilt stream state) plus the command payload — this module is pure
and performs no I/O.

Guard vocabulary (all must hold for the transition to be legal):
  requires_evidence:     int   — ≥ N attached, non-retracted evidence refs
  requires_hypothesis:   str|None — a hypothesis in this status must exist
  requires_approval:     bool  — payload.human_approval.granted must be True
                                 AND approval.revision must equal the stream's
                                 current revision (else OSM-E503)
  requires_checkpoint:   bool  — a TASK_CHECKPOINT for the current state must
                                 exist (used so recovery never loses work)
  requires_review:       bool  — a REVIEW_COMPLETED with verdict must exist
  forbidden_if_contested: bool — block while any hypothesis is CONTESTED

Irreversibility: edges marked irreversible=True can never be the *target*
of a rollback (e.g., DEPLOYABLE publication); attempting to undo them is
OSM-E307. Rollback itself is modeled as a new compensating transition, not
history rewriting — the event log is never mutated.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .errors import OsmError, OsmErrorCode
from .models import ActorRole, HypothesisStatus, ResearchState

S = ResearchState


@dataclass(frozen=True)
class Guard:
    requires_evidence: int = 0
    requires_hypothesis: HypothesisStatus | None = None
    requires_approval: bool = False
    requires_checkpoint: bool = False
    requires_review: bool = False
    forbidden_if_contested: bool = False


@dataclass(frozen=True)
class TransitionRule:
    source: ResearchState
    target: ResearchState
    guard: Guard
    allowed_roles: frozenset[ActorRole]
    irreversible: bool = False
    on_failure_fallback: ResearchState | None = None
    note: str = ""


R = ActorRole
H = HypothesisStatus

_SKILL_OR_CONTROLLER = frozenset({R.CONTROLLER, R.SKILL})
_ANY_WORKER = frozenset({R.CONTROLLER, R.SKILL, R.HUMAN})
_HUMAN_ONLY = frozenset({R.HUMAN})
_HUMAN_OR_CONTROLLER = frozenset({R.HUMAN, R.CONTROLLER})


TRANSITION_TABLE: tuple[TransitionRule, ...] = (
    # --- forward path -------------------------------------------------
    TransitionRule(
        S.OPEN, S.SCOPED, Guard(),
        _SKILL_OR_CONTROLLER,
        note="Mission/scope locked (typically by obsidian-mission-lock output).",
    ),
    TransitionRule(
        S.SCOPED, S.EVIDENCE_GATHERING, Guard(),
        _SKILL_OR_CONTROLLER,
        note="Scouting/extraction skills dispatched.",
    ),
    TransitionRule(
        S.EVIDENCE_GATHERING, S.HYPOTHESIS_BUILDING,
        Guard(requires_evidence=1),
        _SKILL_OR_CONTROLLER,
        on_failure_fallback=S.EVIDENCE_GATHERING,
        note="Need at least one non-retracted evidence item before hypothesizing.",
    ),
    TransitionRule(
        S.HYPOTHESIS_BUILDING, S.DESIGNING,
        Guard(requires_hypothesis=H.PROPOSED, forbidden_if_contested=True),
        _SKILL_OR_CONTROLLER,
        on_failure_fallback=S.EVIDENCE_GATHERING,
        note="A live hypothesis exists and none are contested.",
    ),
    TransitionRule(
        S.DESIGNING, S.AWAITING_DATA,
        Guard(requires_checkpoint=True),
        _SKILL_OR_CONTROLLER,
        on_failure_fallback=S.DESIGNING,
        note="Design must be checkpointed so an interrupted run resumes instead of restarting.",
    ),
    TransitionRule(
        S.AWAITING_DATA, S.ANALYZING,
        Guard(requires_evidence=1),
        _SKILL_OR_CONTROLLER,
        on_failure_fallback=S.AWAITING_DATA,
        note="New data arrived (registered as evidence).",
    ),
    TransitionRule(
        S.ANALYZING, S.UNDER_REVIEW,
        Guard(requires_checkpoint=True, forbidden_if_contested=True),
        _SKILL_OR_CONTROLLER,
        on_failure_fallback=S.ANALYZING,
        note="Analysis checkpointed; unresolved contradictions block review submission.",
    ),
    TransitionRule(
        S.UNDER_REVIEW, S.VALIDATED,
        Guard(requires_review=True, requires_approval=True),
        _HUMAN_OR_CONTROLLER,
        on_failure_fallback=S.ANALYZING,
        note="Review passed AND human approved promotion to validated knowledge.",
    ),
    TransitionRule(
        S.UNDER_REVIEW, S.REJECTED,
        Guard(requires_review=True),
        _HUMAN_OR_CONTROLLER,
        note="Review concluded the line of inquiry is unsound. Terminal-ish; reopen allowed.",
    ),
    TransitionRule(
        S.VALIDATED, S.DEPLOYABLE,
        Guard(requires_approval=True, requires_review=True),
        _HUMAN_ONLY,
        irreversible=True,
        note="Field/deployment release. Human-only, irreversible, approval-gated.",
    ),

    # --- backward / corrective paths ----------------------------------
    TransitionRule(
        S.HYPOTHESIS_BUILDING, S.EVIDENCE_GATHERING, Guard(),
        _ANY_WORKER,
        note="Need more evidence before hypotheses can stand.",
    ),
    TransitionRule(
        S.DESIGNING, S.HYPOTHESIS_BUILDING, Guard(),
        _ANY_WORKER,
        note="Design exposed an untested assumption; back to hypothesizing.",
    ),
    TransitionRule(
        S.AWAITING_DATA, S.DESIGNING, Guard(),
        _ANY_WORKER,
        note="Protocol revised while waiting (e.g., instrumentation QC failed).",
    ),
    TransitionRule(
        S.ANALYZING, S.AWAITING_DATA, Guard(),
        _ANY_WORKER,
        note="Analysis shows data gaps; wait for more.",
    ),
    TransitionRule(
        S.ANALYZING, S.EVIDENCE_GATHERING, Guard(),
        _ANY_WORKER,
        note="Contradiction forced re-scoping of the evidence base (watcher downgrade).",
    ),
    TransitionRule(
        S.UNDER_REVIEW, S.ANALYZING, Guard(),
        _ANY_WORKER,
        note="Reviewer requested rework.",
    ),

    # --- contradiction / supersession downgrades (spec §四.6) ---------
    TransitionRule(
        S.VALIDATED, S.UNDER_REVIEW,
        Guard(),
        _ANY_WORKER,
        note="New contradictory evidence or expired review horizon forces re-review.",
    ),

    # --- reopen --------------------------------------------------------
    TransitionRule(
        S.REJECTED, S.OPEN,
        Guard(requires_approval=True),
        _HUMAN_OR_CONTROLLER,
        note="Reopen a rejected line only with explicit human approval.",
    ),
)

# Engine lookup: (source, target) -> rule. The table is the single source of
# truth; this index is derived, never edited by hand. A duplicate edge is a
# build error, not a silent dedupe — the table must be unambiguous.
_RULE_INDEX: dict[tuple[ResearchState, ResearchState], TransitionRule] = {}
for _rule in TRANSITION_TABLE:
    _key = (_rule.source, _rule.target)
    if _key in _RULE_INDEX:
        raise RuntimeError(
            f"Duplicate transition edge {_key[0].value} -> {_key[1].value} in TRANSITION_TABLE"
        )
    _RULE_INDEX[_key] = _rule


def legal_targets(source: ResearchState) -> list[ResearchState]:
    """All states reachable from `source` in one legal edge."""
    return sorted(
        (t for (s, t) in _RULE_INDEX if s is source),
        key=lambda st: st.value,
    )


def get_rule(source: ResearchState, target: ResearchState) -> TransitionRule | None:
    return _RULE_INDEX.get((source, target))


def evaluate_guard(
    rule: TransitionRule,
    *,
    projection: dict[str, Any],
    approval: dict[str, Any] | None,
    actor_role: ActorRole,
    stream_revision: int,
) -> None:
    """Raise OsmError if the transition is not currently permitted.

    `projection` is the rebuilt stream state with keys:
      evidence: list[{ref, sha256, retracted, attached_revision}]
      hypotheses: list[{id, status}]
      checkpoints: list[{state, task_id, revision}]
      reviews: list[{verdict, revision}]
    """
    if actor_role not in rule.allowed_roles:
        raise OsmError(
            OsmErrorCode.PERMISSION_DENIED,
            f"Role '{actor_role.value}' may not drive {rule.source.value} → "
            f"{rule.target.value}; allowed: {sorted(r.value for r in rule.allowed_roles)}.",
            detail={
                "source": rule.source.value,
                "target": rule.target.value,
                "actor_role": actor_role.value,
                "allowed_roles": sorted(r.value for r in rule.allowed_roles),
            },
        )

    g = rule.guard
    failures: list[dict[str, str]] = []

    live_evidence = [e for e in projection.get("evidence", []) if not e.get("retracted")]
    if len(live_evidence) < g.requires_evidence:
        failures.append({
            "guard": "requires_evidence",
            "why": f"needs ≥{g.requires_evidence} non-retracted evidence item(s), has {len(live_evidence)}",
            "how_to_fix": "Attach evidence via evidence.attach (with sha256 + tier) before retrying.",
        })

    if g.requires_hypothesis is not None:
        wanted = g.requires_hypothesis
        if not any(h.get("status") == wanted.value for h in projection.get("hypotheses", [])):
            failures.append({
                "guard": "requires_hypothesis",
                "why": f"no hypothesis in status {wanted.value}",
                "how_to_fix": "Record a hypothesis via hypothesis.record.",
            })

    if g.forbidden_if_contested:
        contested = [h for h in projection.get("hypotheses", []) if h.get("status") == H.CONTESTED.value]
        if contested:
            failures.append({
                "guard": "forbidden_if_contested",
                "why": f"{len(contested)} hypothesis(es) are CONTESTED "
                       f"({', '.join(h.get('id', '?') for h in contested)})",
                "how_to_fix": "Resolve the contradiction (retract/refute or attach reconciling evidence), "
                              "or the watcher will downgrade state automatically.",
            })

    if g.requires_checkpoint:
        if not any(c.get("state") == rule.source.value for c in projection.get("checkpoints", [])):
            failures.append({
                "guard": "requires_checkpoint",
                "why": f"no TASK_CHECKPOINT recorded while in {rule.source.value}",
                "how_to_fix": "Emit task.checkpoint describing completed work before leaving the state.",
            })

    if g.requires_review:
        if not any(r.get("verdict") in ("pass", "fail") for r in projection.get("reviews", [])):
            failures.append({
                "guard": "requires_review",
                "why": "no completed review with a verdict",
                "how_to_fix": "Record review.request, then review.complete with verdict pass/fail.",
            })

    if g.requires_approval:
        # TRUST BOUNDARY: approval must have been RECORDED as an
        # APPROVAL_GRANTED event in the stream BEFORE the current head, not
        # merely self-declared in the payload. A caller who writes
        # human_approval_state.granted=true without an on-chain approval event
        # is forging the approval gate (adversarial-review finding, fixed).
        #
        # Approval failures are raised with their precise code (E502/E503) only
        # when every OTHER guard already passes; if another guard also fails we
        # report the combined GUARD_UNSATISFIED so the caller fixes the whole
        # precondition set at once.
        recorded = projection.get("approvals", [])
        valid_approval = None
        for ap in recorded:
            ap_rev = ap.get("revision")
            scope = str(ap.get("scope") or "unspecified")
            if ap_rev is not None and ap_rev <= stream_revision and \
               (scope == "all" or scope == rule.target.value):
                valid_approval = ap
                break

        approval_errors: list[tuple[OsmErrorCode, str, dict]] = []
        if valid_approval is None:
            approval_errors.append((
                OsmErrorCode.APPROVAL_REQUIRED,
                f"{rule.source.value} → {rule.target.value} requires a RECORDED APPROVAL_GRANTED "
                "event (scope covering this transition) at or before the current head revision.",
                {
                    "source": rule.source.value,
                    "target": rule.target.value,
                    "how_to_fix": "Emit action=approval.grant (records an APPROVAL_GRANTED event in the "
                                  "log) for the exact target state, then retry.",
                    "recorded_approvals": [
                        {"revision": a.get("revision"), "scope": a.get("scope")} for a in recorded
                    ],
                },
            ))
        elif approval is None or not approval.get("granted"):
            approval_errors.append((
                OsmErrorCode.APPROVAL_REQUIRED,
                f"Caller must re-affirm approval for {rule.source.value} → {rule.target.value}; "
                "the recorded APPROVAL_GRANTED event exists but the request does not carry a "
                "granted approval reference.",
                {"source": rule.source.value, "target": rule.target.value},
            ))
        else:
            claimed = approval.get("revision")
            if claimed is not None and claimed < valid_approval["revision"]:
                approval_errors.append((
                    OsmErrorCode.APPROVAL_STALE,
                    f"Request claims approval at revision {claimed} but the recorded APPROVAL_GRANTED "
                    f"is at revision {valid_approval['revision']}; the approval cannot predate the "
                    "grant event.",
                    {"claimed": claimed, "recorded": valid_approval["revision"]},
                ))

        if approval_errors and not failures:
            code, msg, det = approval_errors[0]
            raise OsmError(code, msg, detail=det)

    if failures:
        raise OsmError(
            OsmErrorCode.GUARD_UNSATISFIED,
            f"Guard unmet for {rule.source.value} → {rule.target.value}: "
            + "; ".join(f["why"] for f in failures),
            detail={
                "source": rule.source.value,
                "target": rule.target.value,
                "failures": failures,
                "fallback": rule.on_failure_fallback.value if rule.on_failure_fallback else None,
            },
        )


def check_transition(
    source: ResearchState,
    target: ResearchState,
    *,
    projection: dict[str, Any],
    approval: dict[str, Any] | None,
    actor_role: ActorRole,
    stream_revision: int,
) -> TransitionRule:
    """Full legality check. Returns the rule on success; raises otherwise.

    Hard block (OSM-E305) when no edge exists at all — this is the
    machine-enforced guarantee behind acceptance gate §九.2.
    """
    rule = get_rule(source, target)
    if rule is None:
        raise OsmError(
            OsmErrorCode.TRANSITION_REJECTED,
            f"Illegal transition {source.value} → {target.value}. "
            f"Legal targets from {source.value}: "
            f"{[t.value for t in legal_targets(source)] or 'none (terminal)'}.",
            detail={
                "source": source.value,
                "target": target.value,
                "legal_targets": [t.value for t in legal_targets(source)],
            },
        )
    evaluate_guard(
        rule,
        projection=projection,
        approval=approval,
        actor_role=actor_role,
        stream_revision=stream_revision,
    )
    return rule
