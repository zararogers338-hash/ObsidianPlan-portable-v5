"""Integration tests: exercise the real CLI over a temp store. These are the
tests the controller would run, and they assert schema-valid output every
time (output.schema.json is enforced inside the service).
"""

from __future__ import annotations

import json

import pytest

from conftest import cli_call, BASE


def evd(ref: str, **kw) -> dict:
    return {"ref": ref, "summary": f"evidence {ref}", **kw}


def grant(cli, scope: str, approver: str = "pi") -> int:
    """Record an on-chain APPROVAL_GRANTED event for the given scope and return
    the new head revision (which the approving transition must reference)."""
    cli_call(cli, "approval.grant", extra={"approver": approver, "scope": scope})
    return cli_call(cli, "state.get")["artifacts"][0]["note"]["head_revision"]


def approve_for(cli, scope: str, approver: str = "pi") -> dict:
    """Grant on-chain approval for a scope and return the matching
    human_approval_state the approving transition must carry."""
    rev = grant(cli, scope, approver)
    return {"granted": True, "approver": approver, "revision": rev}


def test_full_forward_lifecycle_to_validated(cli):
    cli_call(cli, "project.init", extra={"title": "LCA lifecycle"})
    for tgt in ("SCOPED", "EVIDENCE_GATHERING"):
        cli_call(cli, "state.transition", extra={"to_state": tgt, "actor": {"role": "controller"}})
    cli_call(cli, "evidence.attach", extra={"evidence": evd("e1", sha256="a" * 64)})
    cli_call(cli, "state.transition", extra={"to_state": "HYPOTHESIS_BUILDING", "actor": {"role": "skill"}})
    cli_call(cli, "hypothesis.record", extra={"hypothesis": {"id": "h1", "statement": "urease drives MICP"}})
    cli_call(cli, "state.transition", extra={"to_state": "DESIGNING", "actor": {"role": "skill"}})
    cli_call(cli, "task.checkpoint", extra={
        "task_id": "design-1",
        "completed_work": [{"step": "protocol"}],
        "pending_work": [{"step": "run"}],
    })
    cli_call(cli, "state.transition", extra={"to_state": "AWAITING_DATA", "actor": {"role": "controller"}})
    cli_call(cli, "evidence.attach", extra={"evidence": evd("e2", sha256="b" * 64)})
    cli_call(cli, "state.transition", extra={"to_state": "ANALYZING", "actor": {"role": "controller"}})
    cli_call(cli, "task.checkpoint", extra={
        "task_id": "analysis-1",
        "completed_work": [{"step": "regression"}],
    })
    cli_call(cli, "state.transition", extra={"to_state": "UNDER_REVIEW", "actor": {"role": "controller"}})
    cli_call(cli, "review.complete", extra={"verdict": "pass", "reviewer": "red-team"})
    # Approval must be RECORDED on-chain (approval.grant) before the transition
    # — a self-declared human_approval_state is not sufficient (trust boundary).
    approval = approve_for(cli, "VALIDATED")
    out = cli_call(cli, "state.transition", extra={
        "to_state": "VALIDATED",
        "actor": {"role": "human", "id": "pi"},
        "human_approval_state": approval,
    })
    assert out["state"] == "VALIDATED"
    assert out["validation"]["rebuild_matches_snapshot"] is True
    assert out["validation"]["self_check"] == "passed"


def test_deployable_human_only_and_irreversible(cli):
    """Drive to VALIDATED then attempt DEPLOYABLE as a controller/skill (denied),
    then as human with approval (allowed), then attempt rollback (denied)."""
    cli_call(cli, "project.init", extra={"title": "deploy"})
    cli_call(cli, "state.transition", extra={"to_state": "SCOPED", "actor": {"role": "controller"}})
    cli_call(cli, "state.transition", extra={"to_state": "EVIDENCE_GATHERING", "actor": {"role": "controller"}})
    cli_call(cli, "evidence.attach", extra={"evidence": evd("e1", sha256="a" * 64)})
    cli_call(cli, "state.transition", extra={"to_state": "HYPOTHESIS_BUILDING", "actor": {"role": "skill"}})
    cli_call(cli, "hypothesis.record", extra={"hypothesis": {"id": "h1", "statement": "x"}})
    cli_call(cli, "state.transition", extra={"to_state": "DESIGNING", "actor": {"role": "skill"}})
    cli_call(cli, "task.checkpoint", extra={"task_id": "d", "completed_work": [{"step": "s"}]})
    cli_call(cli, "state.transition", extra={"to_state": "AWAITING_DATA", "actor": {"role": "controller"}})
    cli_call(cli, "evidence.attach", extra={"evidence": evd("e2", sha256="b" * 64)})
    cli_call(cli, "state.transition", extra={"to_state": "ANALYZING", "actor": {"role": "controller"}})
    cli_call(cli, "task.checkpoint", extra={"task_id": "a", "completed_work": [{"step": "fit"}]})
    cli_call(cli, "state.transition", extra={"to_state": "UNDER_REVIEW", "actor": {"role": "controller"}})
    cli_call(cli, "review.complete", extra={"verdict": "pass"})
    # On-chain approvals: one for VALIDATED (promotion), one for DEPLOYABLE.
    approval_validated = approve_for(cli, "VALIDATED")
    cli_call(cli, "state.transition", extra={
        "to_state": "VALIDATED", "actor": {"role": "human"},
        "human_approval_state": approval_validated})
    # controller attempts deployable -> denied by role (human-only edge)
    out = cli_call(cli, "state.transition", expect_ok=False, extra={
        "to_state": "DEPLOYABLE", "actor": {"role": "controller"},
        "human_approval_state": approval_validated})
    assert out["status"] == "FAILED"
    assert out["errors"][0]["code"] == "OSM-E501"
    # skill spoofing human + forged approval -> denied by trust boundary
    # (no on-chain APPROVAL_GRANTED for DEPLOYABLE scope was ever recorded)
    out = cli_call(cli, "state.transition", expect_ok=False, extra={
        "to_state": "DEPLOYABLE", "actor": {"role": "human", "id": "spoofed-skill"},
        "human_approval_state": {"granted": True, "approver": "spoofed-skill",
                                 "revision": approval_validated["revision"] + 1}})
    assert out["errors"][0]["code"] == "OSM-E502"
    # legitimate: grant DEPLOYABLE approval on-chain, human drives transition
    approval_deployable = approve_for(cli, "DEPLOYABLE")
    out = cli_call(cli, "state.transition", extra={
        "to_state": "DEPLOYABLE", "actor": {"role": "human"},
        "human_approval_state": approval_deployable})
    assert out["state"] == "DEPLOYABLE"
    # rollback of DEPLOYABLE -> irreversible
    out = cli_call(cli, "state.rollback", expect_ok=False, extra={
        "to_state": "VALIDATED",
        "human_approval_state": approval_deployable})
    assert out["errors"][0]["code"] == "OSM-E307"


def test_contradiction_auto_downgrade(cli):
    cli_call(cli, "project.init", extra={"title": "contradiction"})
    cli_call(cli, "state.transition", extra={"to_state": "SCOPED", "actor": {"role": "controller"}})
    cli_call(cli, "state.transition", extra={"to_state": "EVIDENCE_GATHERING", "actor": {"role": "controller"}})
    cli_call(cli, "evidence.attach", extra={"evidence": evd("e1")})
    cli_call(cli, "state.transition", extra={"to_state": "HYPOTHESIS_BUILDING", "actor": {"role": "skill"}})
    cli_call(cli, "hypothesis.record", extra={"hypothesis": {"id": "h1", "statement": "hypo"}})
    cli_call(cli, "state.transition", extra={"to_state": "DESIGNING", "actor": {"role": "skill"}})
    cli_call(cli, "task.checkpoint", extra={"task_id": "d", "completed_work": [{"step": "s"}]})
    cli_call(cli, "state.transition", extra={"to_state": "AWAITING_DATA", "actor": {"role": "controller"}})
    out = cli_call(cli, "evidence.attach", extra={
        "evidence": evd("contra", contradicts_hypothesis=["h1"]),
    })
    assert out["state"] == "DESIGNING"
    assert any("downgrade" in f["statement"].lower() for f in out["findings"])
    # auto-downgrade off: attach another contradiction but stay put
    out2 = cli_call(cli, "evidence.attach", extra={
        "evidence": evd("contra2", contradicts_hypothesis=["h1"]),
        "auto_downgrade": False,
    })
    assert out2["state"] == "DESIGNING"
    assert not any("downgrade" in f["statement"].lower() for f in out2["findings"])


def test_dry_run_appends_nothing(cli):
    cli_call(cli, "project.init", extra={"title": "dry"})
    before = cli_call(cli, "state.get")
    rev_before = before["artifacts"][0]["note"]["head_revision"]
    out = cli_call(cli, "state.transition", extra={
        "to_state": "SCOPED", "dry_run": True, "actor": {"role": "controller"}})
    assert out["state"] == "SCOPED"  # simulated projection
    assert out["provenance"]["events_appended"][0]["revision"] == "dry-run"
    after = cli_call(cli, "state.get")
    assert after["artifacts"][0]["note"]["head_revision"] == rev_before


def test_expected_revision_race_detected(cli):
    cli_call(cli, "project.init", extra={"title": "race"})
    out = cli_call(cli, "state.transition", expect_ok=False, extra={
        "to_state": "SCOPED", "actor": {"role": "controller"}, "expected_revision": 99})
    assert out["errors"][0]["code"] == "OSM-E104"


def test_dry_run_also_enforces_expected_revision(cli):
    """Regression: dry_run must not bypass the optimistic-concurrency guard
    (CONFIRMED finding from adversarial review). A stale-view dry-run must
    fail exactly like a real write would."""
    cli_call(cli, "project.init", extra={"title": "race-dry"})
    out = cli_call(cli, "state.transition", expect_ok=False, extra={
        "to_state": "SCOPED", "actor": {"role": "controller"},
        "expected_revision": 99, "dry_run": True})
    assert out["errors"][0]["code"] == "OSM-E104"
    # And the store must be untouched: still in OPEN.
    assert out["provenance"]["events_appended"] == []
    got = cli_call(cli, "state.get")
    assert got["state"] == "OPEN"


def test_approval_stale_rejected(cli):
    cli_call(cli, "project.init", extra={"title": "stale"})
    cli_call(cli, "state.transition", extra={"to_state": "SCOPED", "actor": {"role": "controller"}})
    out = cli_call(cli, "state.transition", expect_ok=False, extra={
        "to_state": "SCOPED", "actor": {"role": "controller"},
        "human_approval_state": {"granted": True, "approver": "h", "revision": 1}})
    # This is an illegal transition anyway (already SCOPED); the point is it's
    # rejected and not treated as success.
    assert out["errors"][0]["code"] == "OSM-E305"


def test_rollback_requires_onchain_approval(cli):
    cli_call(cli, "project.init", extra={"title": "rb"})
    cli_call(cli, "state.transition", extra={"to_state": "SCOPED", "actor": {"role": "controller"}})
    cli_call(cli, "state.transition", extra={"to_state": "EVIDENCE_GATHERING", "actor": {"role": "controller"}})
    # No recorded approval -> rollback must demand one (trust boundary).
    out = cli_call(cli, "state.rollback", expect_ok=False, extra={
        "to_state": "SCOPED", "actor": {"role": "human"},
        "human_approval_state": {"granted": True, "approver": "pi", "revision": 4}})
    assert out["status"] == "HUMAN_APPROVAL_REQUIRED"
    assert out["errors"][0]["code"] == "OSM-E502"
    # With an on-chain approval covering the scope, rollback proceeds.
    approval = approve_for(cli, "SCOPED")
    out2 = cli_call(cli, "state.rollback", extra={
        "to_state": "SCOPED", "actor": {"role": "human"},
        "human_approval_state": approval})
    assert out2["state"] == "SCOPED"


def test_resume_plan_skips_unchanged_work(cli):
    cli_call(cli, "project.init", extra={"title": "resume"})
    cli_call(cli, "task.checkpoint", extra={
        "task_id": "t1", "completed_work": [{"step": "compile data", "input": "a.csv"}],
        "pending_work": [{"step": "fit model"}],
    })
    out = cli_call(cli, "task.resume_plan", extra={
        "task_id": "t1",
        "candidate_work": [
            {"step": "compile data", "input": "a.csv"},   # unchanged -> skip
            {"step": "compile data", "input": "b.csv"},   # changed  -> run
            {"step": "fit model"},                         # pending  -> run
        ],
    })
    plan = out["artifacts"][-1]["note"]
    assert plan["skipped_count"] == 1
    assert len(plan["to_run"]) == 2
    assert len(plan["already_done"]) == 1


def test_evidence_retract_is_append_only(cli):
    cli_call(cli, "project.init", extra={"title": "retract"})
    cli_call(cli, "evidence.attach", extra={"evidence": evd("e1")})
    cli_call(cli, "evidence.retract", extra={"ref": "e1", "reason": "bad data"})
    out = cli_call(cli, "state.get")
    view = out["artifacts"][0]["note"]
    assert view["evidence_count"] == 0
    assert view["evidence_retracted_count"] == 1


def test_output_is_schema_valid_even_on_failure(cli):
    # Missing project stream -> BLOCKED, still schema-valid output.
    out = cli_call(cli, "state.get", expect_ok=False)
    assert out["status"] == "BLOCKED"
    assert out["errors"][0]["code"] == "OSM-E304"
    # Output envelope fields present
    for key in ("contract_version", "skill", "status", "summary", "findings",
                "validation", "provenance", "errors"):
        assert key in out


def test_timeline_human_and_machine(cli):
    cli_call(cli, "project.init", extra={"title": "tl"})
    cli_call(cli, "state.transition", extra={"to_state": "SCOPED", "actor": {"role": "controller"}})
    out = cli_call(cli, "state.timeline")
    kinds = {a["kind"] for a in out["artifacts"]}
    assert {"timeline_human", "timeline_machine"} <= kinds
    human = [a for a in out["artifacts"] if a["kind"] == "timeline_human"][0]["note"]
    assert "SCOPED" in human
    machine = [a for a in out["artifacts"] if a["kind"] == "timeline_machine"][0]["note"]
    assert len(machine) >= 2


def test_snapshot_verify_and_diff(cli):
    cli_call(cli, "project.init", extra={"title": "sv"})
    cli_call(cli, "evidence.attach", extra={"evidence": evd("e1")})
    out = cli_call(cli, "snapshot.verify")
    assert out["validation"]["rebuild_matches_snapshot"] is True
    diff = cli_call(cli, "state.diff")
    assert diff["validation"]["rebuild_matches_snapshot"] is True
