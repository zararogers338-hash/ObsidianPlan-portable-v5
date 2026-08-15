"""Unit tests for the pure domain layer: transition table, hashing, rollback
guards, watcher, recovery, diff. No I/O beyond in-memory fixtures.
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

from osm.errors import OsmError, OsmErrorCode  # noqa: E402
from osm.models import ActorRole, EventType, HypothesisStatus, ResearchState  # noqa: E402
from osm.rollback import check_rollback, diff_snapshots  # noqa: E402
from osm.store import GENESIS_HASH, EventStore, Projection, apply_event, event_hash  # noqa: E402
from osm.transition import (  # noqa: E402
    TRANSITION_TABLE,
    check_transition,
    get_rule,
    legal_targets,
)
from osm.watcher import scan  # noqa: E402

S = ResearchState


def empty_projection() -> Projection:
    return Projection(project_id="unit")


def proj_in(state: S, **kw) -> Projection:
    p = empty_projection()
    p.state = state
    p.revision = kw.get("revision", 1)
    p.head_hash = kw.get("head_hash", GENESIS_HASH)
    return p


def attach(proj: Projection, ref: str, *, review_by: str | None = None,
           retracted: bool = False) -> Projection:
    proj.evidence.append({"ref": ref, "sha256": "a" * 64, "retracted": retracted,
                          "tier": "unreviewed_draft", "review_by": review_by,
                          "attached_revision": proj.revision + 1})
    proj.revision += 1
    return proj


# ---------------------------------------------------------------------
# transition table integrity
# ---------------------------------------------------------------------

def test_table_has_no_duplicate_edges():
    edges = [(r.source, r.target) for r in TRANSITION_TABLE]
    assert len(edges) == len(set(edges)), "duplicate transition edge in table"


def test_eleven_states_all_present():
    expected = {S.OPEN, S.SCOPED, S.EVIDENCE_GATHERING, S.HYPOTHESIS_BUILDING,
                S.DESIGNING, S.AWAITING_DATA, S.ANALYZING, S.UNDER_REVIEW,
                S.VALIDATED, S.REJECTED, S.DEPLOYABLE}
    states = {r.source for r in TRANSITION_TABLE} | {r.target for r in TRANSITION_TABLE}
    assert states == expected


def test_legal_targets_from_open():
    assert legal_targets(S.OPEN) == [S.SCOPED]


def test_irreversible_edge_exists_only_for_deployable():
    for r in TRANSITION_TABLE:
        if r.irreversible:
            assert r.target is S.DEPLOYABLE


# ---------------------------------------------------------------------
# hard-block illegal transitions (acceptance §九.2)
# ---------------------------------------------------------------------

@pytest.mark.parametrize("src,tgt", [
    (S.OPEN, S.DEPLOYABLE),
    (S.OPEN, S.VALIDATED),
    (S.OPEN, S.UNDER_REVIEW),
    (S.OPEN, S.REJECTED),
    (S.SCOPED, S.DEPLOYABLE),
    (S.SCOPED, S.HYPOTHESIS_BUILDING),
    (S.DESIGNING, S.VALIDATED),
    (S.VALIDATED, S.DEPLOYABLE),  # valid edge but fails role guard (skill)
    (S.REJECTED, S.DEPLOYABLE),
])
def test_illegal_transitions_hard_blocked(src, tgt):
    rule = get_rule(src, tgt)
    if rule is None:
        with pytest.raises(OsmError) as ei:
            check_transition(src, tgt, projection=empty_projection().guard_view(),
                             approval=None, actor_role=ActorRole.CONTROLLER,
                             stream_revision=1)
        assert ei.value.code is OsmErrorCode.TRANSITION_REJECTED
    else:
        # Edge exists but requires human-only / approval; a controller must fail.
        with pytest.raises(OsmError) as ei:
            check_transition(src, tgt, projection=empty_projection().guard_view(),
                             approval=None, actor_role=ActorRole.CONTROLLER,
                             stream_revision=1)
        assert ei.value.code in (OsmErrorCode.TRANSITION_REJECTED,
                                 OsmErrorCode.GUARD_UNSATISFIED,
                                 OsmErrorCode.APPROVAL_REQUIRED,
                                 OsmErrorCode.PERMISSION_DENIED)


# ---------------------------------------------------------------------
# guard semantics
# ---------------------------------------------------------------------

def test_evidence_guard_blocks_then_allows():
    p = proj_in(S.EVIDENCE_GATHERING)
    with pytest.raises(OsmError) as ei:
        check_transition(S.EVIDENCE_GATHERING, S.HYPOTHESIS_BUILDING,
                         projection=p.guard_view(), approval=None,
                         actor_role=ActorRole.SKILL, stream_revision=p.revision)
    assert ei.value.code is OsmErrorCode.GUARD_UNSATISFIED
    assert any(f["guard"] == "requires_evidence" for f in ei.value.detail["failures"])

    attach(p, "e1")
    check_transition(S.EVIDENCE_GATHERING, S.HYPOTHESIS_BUILDING,
                     projection=p.guard_view(), approval=None,
                     actor_role=ActorRole.SKILL, stream_revision=p.revision)


def test_hypothesis_guard():
    p = proj_in(S.HYPOTHESIS_BUILDING)
    with pytest.raises(OsmError):
        check_transition(S.HYPOTHESIS_BUILDING, S.DESIGNING,
                         projection=p.guard_view(), approval=None,
                         actor_role=ActorRole.SKILL, stream_revision=p.revision)
    p.hypotheses.append({"id": "h1", "status": HypothesisStatus.PROPOSED.value})
    check_transition(S.HYPOTHESIS_BUILDING, S.DESIGNING,
                     projection=p.guard_view(), approval=None,
                     actor_role=ActorRole.SKILL, stream_revision=p.revision)


def test_contested_blocks_design():
    p = proj_in(S.HYPOTHESIS_BUILDING)
    p.hypotheses.append({"id": "h1", "status": HypothesisStatus.CONTESTED.value})
    with pytest.raises(OsmError) as ei:
        check_transition(S.HYPOTHESIS_BUILDING, S.DESIGNING,
                         projection=p.guard_view(), approval=None,
                         actor_role=ActorRole.SKILL, stream_revision=p.revision)
    assert ei.value.code is OsmErrorCode.GUARD_UNSATISFIED
    assert any(f["guard"] == "forbidden_if_contested" for f in ei.value.detail["failures"])


def test_approval_revision_staleness():
    # With an on-chain approval at revision 5, a request claiming approval at
    # revision 4 (older than the grant) must be rejected as stale.
    p = proj_in(S.UNDER_REVIEW, revision=5)
    p.reviews.append({"verdict": "pass", "revision": 4})
    p.approvals.append({"approver": "human", "scope": "VALIDATED", "revision": 5})
    with pytest.raises(OsmError) as ei:
        check_transition(S.UNDER_REVIEW, S.VALIDATED,
                         projection=p.guard_view(),
                         approval={"granted": True, "approver": "human",
                                   "revision": 4},  # older than the grant
                         actor_role=ActorRole.HUMAN, stream_revision=5)
    assert ei.value.code is OsmErrorCode.APPROVAL_STALE


def test_approval_requires_onchain_record():
    # A self-declared approval with NO recorded APPROVAL_GRANTED event must be
    # rejected (trust boundary) even when every other guard passes.
    p = proj_in(S.UNDER_REVIEW, revision=3)
    p.reviews.append({"verdict": "pass", "revision": 2})
    with pytest.raises(OsmError) as ei:
        check_transition(S.UNDER_REVIEW, S.VALIDATED,
                         projection=p.guard_view(),
                         approval={"granted": True, "approver": "h", "revision": 3},
                         actor_role=ActorRole.HUMAN, stream_revision=3)
    assert ei.value.code is OsmErrorCode.APPROVAL_REQUIRED


def test_review_and_approval_needed_for_validated():
    p = proj_in(S.UNDER_REVIEW, revision=3)
    # No review AND no approval -> combined GUARD_UNSATISFIED (review reported first).
    with pytest.raises(OsmError) as ei:
        check_transition(S.UNDER_REVIEW, S.VALIDATED,
                         projection=p.guard_view(), approval=None,
                         actor_role=ActorRole.HUMAN, stream_revision=3)
    assert ei.value.code is OsmErrorCode.GUARD_UNSATISFIED
    # Review present, approval missing -> APPROVAL_REQUIRED (trust boundary).
    p.reviews.append({"verdict": "pass", "revision": 2})
    with pytest.raises(OsmError) as ei:
        check_transition(S.UNDER_REVIEW, S.VALIDATED,
                         projection=p.guard_view(), approval=None,
                         actor_role=ActorRole.HUMAN, stream_revision=3)
    assert ei.value.code is OsmErrorCode.APPROVAL_REQUIRED
    # Both present -> passes.
    p.approvals.append({"approver": "h", "scope": "VALIDATED", "revision": 3})
    check_transition(S.UNDER_REVIEW, S.VALIDATED,
                     projection=p.guard_view(),
                     approval={"granted": True, "approver": "h", "revision": 3},
                     actor_role=ActorRole.HUMAN, stream_revision=3)


def test_role_denied_for_human_only():
    p = proj_in(S.VALIDATED)
    p.reviews.append({"verdict": "pass"})
    p.approvals.append({"approver": "h", "scope": "DEPLOYABLE", "revision": p.revision})
    with pytest.raises(OsmError) as ei:
        check_transition(S.VALIDATED, S.DEPLOYABLE,
                         projection=p.guard_view(),
                         approval={"granted": True, "approver": "h",
                                   "revision": p.revision},
                         actor_role=ActorRole.SKILL, stream_revision=p.revision)
    assert ei.value.code is OsmErrorCode.PERMISSION_DENIED


# ---------------------------------------------------------------------
# event hashing / chain integrity
# ---------------------------------------------------------------------

def test_event_hash_deterministic_and_sensitive():
    p1 = {"revision": 1, "type": "X", "recorded_at": "t", "actor": "a",
          "payload": {"b": 2, "a": 1}, "prev_hash": GENESIS_HASH}
    p2 = {"revision": 1, "type": "X", "recorded_at": "t", "actor": "a",
          "payload": {"a": 1, "b": 2}, "prev_hash": GENESIS_HASH}
    assert event_hash(GENESIS_HASH, p1) == event_hash(GENESIS_HASH, p2)
    p3 = {**p1, "payload": {"a": 1, "b": 3}}
    assert event_hash(GENESIS_HASH, p1) != event_hash(GENESIS_HASH, p3)


def test_store_verify_detects_tampering(tmp_path):
    store = EventStore(tmp_path)
    store.append("p", EventType.PROJECT_INITIALIZED, {"title": "t"}, actor="a")
    log = store.log_path("p")
    lines = log.read_text(encoding="utf-8").splitlines()
    # Corrupt payload: flip a field inside the JSON.
    import json as _json
    rec = _json.loads(lines[0])
    rec["payload"]["title"] = "HACKED"
    log.write_text(_json.dumps(rec, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
    with pytest.raises(OsmError) as ei:
        store.read_events("p")
    assert ei.value.code is OsmErrorCode.EVENT_LOG_CORRUPT


def test_revision_gap_detected(tmp_path):
    store = EventStore(tmp_path)
    store.append("p", EventType.PROJECT_INITIALIZED, {"title": "t"}, actor="a")
    log = store.log_path("p")
    lines = log.read_text(encoding="utf-8").splitlines()
    import json as _json
    rec = _json.loads(lines[0])
    rec["revision"] = 7
    log.write_text(_json.dumps(rec, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
    with pytest.raises(OsmError) as ei:
        store.read_events("p")
    assert ei.value.code is OsmErrorCode.EVENT_LOG_CORRUPT


def test_append_requires_init_first(tmp_path):
    store = EventStore(tmp_path)
    with pytest.raises(OsmError) as ei:
        store.append("fresh", EventType.EVIDENCE_ATTACHED, {}, actor="a")
    assert ei.value.code is OsmErrorCode.PROJECT_NOT_FOUND


def test_projection_rebuild_matches(tmp_path):
    store = EventStore(tmp_path)
    store.append("p", EventType.PROJECT_INITIALIZED, {"title": "t"}, actor="a")
    store.append("p", EventType.EVIDENCE_ATTACHED,
                 {"ref": "e1", "sha256": "a" * 64, "tier": "unreviewed_draft"}, actor="a")
    proj = store.rebuild("p")
    assert proj.revision == 2
    assert len(proj.evidence) == 1
    assert proj.evidence[0]["ref"] == "e1"


# ---------------------------------------------------------------------
# rollback
# ---------------------------------------------------------------------

def test_rollback_deparable_irreversible():
    p = proj_in(S.DEPLOYABLE)
    with pytest.raises(OsmError) as ei:
        check_rollback(p, S.VALIDATED)
    assert ei.value.code is OsmErrorCode.IRREVERSIBLE_TRANSITION


def test_rollback_backward_only():
    p = proj_in(S.DESIGNING)
    check_rollback(p, S.EVIDENCE_GATHERING)  # backward ok
    with pytest.raises(OsmError):
        check_rollback(p, S.AWAITING_DATA)  # forward — use transition instead


def test_rollback_same_state_rejected():
    p = proj_in(S.ANALYZING)
    with pytest.raises(OsmError):
        check_rollback(p, S.ANALYZING)


def test_diff_snapshots():
    old = {"a": 1, "b": {"x": 1, "y": 2}, "c": [1, 2]}
    new = {"a": 1, "b": {"x": 1, "y": 3}, "d": "added"}
    diff = diff_snapshots(old, new)
    # b.y changed; c was a 2-element list and is fully removed (2 removed paths);
    # d added. Assert the *kind* counts we care about.
    assert diff["counts"]["added"] == 1
    assert diff["counts"]["changed"] == 1
    assert any(c["path"] == "b.y" for c in diff["changed"])


# ---------------------------------------------------------------------
# watcher
# ---------------------------------------------------------------------

def test_watcher_flags_stale_evidence_and_downgrades_validated():
    p = proj_in(S.VALIDATED)
    now = datetime(2026, 8, 6, tzinfo=timezone.utc)
    attach(p, "e-old", review_by="2026-01-01T00:00:00Z")
    report = scan(p, now=now)
    assert len(report["stale_evidence"]) == 1
    assert any(pr["kind"] == "staleness_downgrade" for pr in report["proposals"])
    d = [pr for pr in report["proposals"] if pr["kind"] == "staleness_downgrade"][0]
    assert d["to_state"] == S.UNDER_REVIEW.value


def test_watcher_contested_downgrades_designing():
    p = proj_in(S.DESIGNING)
    p.hypotheses.append({"id": "h1", "status": HypothesisStatus.CONTESTED.value})
    report = scan(p)
    assert any(pr["kind"] == "contradiction_downgrade" for pr in report["proposals"])
    d = [pr for pr in report["proposals"] if pr["kind"] == "contradiction_downgrade"][0]
    assert d["to_state"] == S.HYPOTHESIS_BUILDING.value


def test_watcher_clean():
    p = proj_in(S.ANALYZING)
    attach(p, "e-fresh", review_by="2099-01-01T00:00:00Z")
    report = scan(p)
    assert report["stale_evidence"] == []
    assert report["proposals"] == []


# ---------------------------------------------------------------------
# apply_event fold coverage
# ---------------------------------------------------------------------

def test_apply_event_covers_all_projection_types(tmp_path):
    store = EventStore(tmp_path)
    store.append("p", EventType.PROJECT_INITIALIZED, {"title": "t"}, actor="a")
    store.append("p", EventType.EVIDENCE_ATTACHED, {"ref": "e1"}, actor="a")
    store.append("p", EventType.HYPOTHESIS_RECORDED, {"id": "h1", "statement": "s"}, actor="a")
    store.append("p", EventType.HYPOTHESIS_STATUS_CHANGED, {"id": "h1", "to_status": "SUPPORTED"}, actor="a")
    store.append("p", EventType.DECISION_RECORDED, {"id": "d1", "decision": "go"}, actor="a")
    store.append("p", EventType.TASK_CHECKPOINT, {"task_id": "t1", "state": "OPEN"}, actor="a")
    store.append("p", EventType.MEMORY_PROMOTED, {"ref": "e1", "to_tier": "verified_knowledge"}, actor="a")
    store.append("p", EventType.REVIEW_COMPLETED, {"verdict": "pass"}, actor="a")
    store.append("p", EventType.APPROVAL_GRANTED, {"approver": "h"}, actor="a")
    store.append("p", EventType.STATE_TRANSITIONED, {"to_state": "SCOPED"}, actor="a")
    store.append("p", EventType.EVIDENCE_RETRACTED, {"ref": "e1"}, actor="a")
    proj = store.rebuild("p")
    assert proj.state is S.SCOPED
    assert proj.evidence[0]["retracted"] is True
    assert proj.hypotheses[0]["status"] == "SUPPORTED"
    assert proj.decisions[0]["decision"] == "go"
    assert len(proj.memory["verified_knowledge"]) == 1
    assert proj.reviews[0]["verdict"] == "pass"
