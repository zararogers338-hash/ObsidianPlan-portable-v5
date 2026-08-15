"""Failure-mode and adversarial tests (spec §九, §十二: conflict, missing,
boundary, malicious inputs must be covered and must genuinely run).
"""

from __future__ import annotations

import json

import pytest

from conftest import cli_call


# ---------------------------------------------------------------------
# input contract violations
# ---------------------------------------------------------------------

def test_missing_required_fields_returns_blocked(cli):
    from conftest import BASE
    import subprocess, sys
    from pathlib import Path
    bad = dict(BASE)
    del bad["timestamp"]
    bad["action"] = "state.get"
    p = subprocess.run(
        [sys.executable, str(Path(__file__).resolve().parent.parent / "tools" / "state_manager.py"),
         "--store", cli],
        input=json.dumps(bad), capture_output=True, text=True)
    out = json.loads(p.stdout)
    assert out["status"] == "BLOCKED"
    assert out["errors"][0]["code"] == "OSM-E101"
    assert "timestamp" in str(out["errors"][0]["detail"])


def test_unknown_action_rejected(cli):
    from conftest import BASE
    import subprocess, sys
    from pathlib import Path
    bad = dict(BASE)
    bad["action"] = "bogus.action"
    p = subprocess.run(
        [sys.executable, str(Path(__file__).resolve().parent.parent / "tools" / "state_manager.py"),
         "--store", cli],
        input=json.dumps(bad), capture_output=True, text=True)
    out = json.loads(p.stdout)
    assert out["errors"][0]["code"] == "OSM-E101"
    assert "bogus.action" in out["errors"][0]["message"]


def test_invalid_state_name(cli):
    out = cli_call(cli, "state.transition", expect_ok=False, extra={"to_state": "WARP"})
    assert out["status"] == "BLOCKED"
    assert out["errors"][0]["code"] == "OSM-E101"


def test_contract_version_2_rejected(cli):
    out = cli_call(cli, "state.get", expect_ok=False, extra={"contract_version": "2.0"})
    assert out["errors"][0]["code"] == "OSM-E801"


def test_project_id_path_traversal_rejected(cli):
    out = cli_call(cli, "state.get", expect_ok=False,
                   overrides={"project_id": "../../etc"})
    # schema pattern rejects it (OSM-E101); defense-in-depth in store also present
    assert out["errors"][0]["code"] == "OSM-E101"


def test_missing_project_stream_blocked_with_actionable_details(cli):
    out = cli_call(cli, "state.get", expect_ok=False,
                   overrides={"project_id": "does-not-exist"})
    assert out["status"] == "BLOCKED"
    err = out["errors"][0]
    assert err["code"] == "OSM-E304"
    assert "how_to_fix" in err["detail"]


def test_project_init_twice_rejected(cli):
    cli_call(cli, "project.init", extra={"title": "once"})
    out = cli_call(cli, "project.init", expect_ok=False, extra={"title": "twice"})
    assert out["errors"][0]["code"] == "OSM-E101"
    assert "once-only" in out["errors"][0]["message"]


def test_duplicate_hypothesis_rejected(cli):
    cli_call(cli, "project.init", extra={"title": "dh"})
    cli_call(cli, "hypothesis.record", extra={"hypothesis": {"id": "h1", "statement": "s"}})
    out = cli_call(cli, "hypothesis.record", expect_ok=False,
                   extra={"hypothesis": {"id": "h1", "statement": "dup"}})
    assert out["errors"][0]["code"] == "OSM-E101"


def test_retract_unknown_evidence(cli):
    cli_call(cli, "project.init", extra={"title": "re"})
    out = cli_call(cli, "evidence.retract", expect_ok=False, extra={"ref": "nope"})
    assert out["errors"][0]["code"] == "OSM-E201"


# ---------------------------------------------------------------------
# guards
# ---------------------------------------------------------------------

def test_review_verdict_required_before_validated(cli):
    cli_call(cli, "project.init", extra={"title": "rv"})
    cli_call(cli, "state.transition", extra={"to_state": "SCOPED", "actor": {"role": "controller"}})
    cli_call(cli, "state.transition", extra={"to_state": "EVIDENCE_GATHERING", "actor": {"role": "controller"}})
    cli_call(cli, "evidence.attach", extra={"evidence": {"ref": "e1"}})
    cli_call(cli, "state.transition", extra={"to_state": "HYPOTHESIS_BUILDING", "actor": {"role": "skill"}})
    cli_call(cli, "hypothesis.record", extra={"hypothesis": {"id": "h1", "statement": "s"}})
    cli_call(cli, "state.transition", extra={"to_state": "DESIGNING", "actor": {"role": "skill"}})
    cli_call(cli, "task.checkpoint", extra={"task_id": "d", "completed_work": [{"step": "s"}]})
    cli_call(cli, "state.transition", extra={"to_state": "AWAITING_DATA", "actor": {"role": "controller"}})
    cli_call(cli, "evidence.attach", extra={"evidence": {"ref": "e2"}})
    cli_call(cli, "state.transition", extra={"to_state": "ANALYZING", "actor": {"role": "controller"}})
    cli_call(cli, "task.checkpoint", extra={"task_id": "a", "completed_work": [{"step": "f"}]})
    cli_call(cli, "state.transition", extra={"to_state": "UNDER_REVIEW", "actor": {"role": "controller"}})
    # No review yet -> GUARD_UNSATISFIED
    out = cli_call(cli, "state.transition", expect_ok=False, extra={
        "to_state": "VALIDATED", "actor": {"role": "human"},
        "human_approval_state": {"granted": True, "approver": "pi"}})
    assert out["errors"][0]["code"] == "OSM-E306"


def test_contested_hypothesis_blocks_under_review(cli):
    cli_call(cli, "project.init", extra={"title": "cb"})
    cli_call(cli, "state.transition", extra={"to_state": "SCOPED", "actor": {"role": "controller"}})
    cli_call(cli, "state.transition", extra={"to_state": "EVIDENCE_GATHERING", "actor": {"role": "controller"}})
    cli_call(cli, "evidence.attach", extra={"evidence": {"ref": "e1"}})
    cli_call(cli, "state.transition", extra={"to_state": "HYPOTHESIS_BUILDING", "actor": {"role": "skill"}})
    cli_call(cli, "hypothesis.record", extra={"hypothesis": {"id": "h1", "statement": "s"}})
    cli_call(cli, "state.transition", extra={"to_state": "DESIGNING", "actor": {"role": "skill"}})
    cli_call(cli, "task.checkpoint", extra={"task_id": "d", "completed_work": [{"step": "s"}]})
    cli_call(cli, "state.transition", extra={"to_state": "AWAITING_DATA", "actor": {"role": "controller"}})
    cli_call(cli, "evidence.attach", extra={"evidence": {"ref": "e2"}})
    cli_call(cli, "state.transition", extra={"to_state": "ANALYZING", "actor": {"role": "controller"}})
    # Contradict now (auto_downgrade defaults True -> ANALYZING -> EVIDENCE_GATHERING)
    out = cli_call(cli, "evidence.attach", extra={
        "evidence": {"ref": "contra", "contradicts_hypothesis": ["h1"]}})
    assert out["state"] == "EVIDENCE_GATHERING"


# ---------------------------------------------------------------------
# adversarial / malicious inputs
# ---------------------------------------------------------------------

def test_non_json_stdin_returns_blocked_envelope(cli):
    import subprocess, sys
    from pathlib import Path
    p = subprocess.run(
        [sys.executable, str(Path(__file__).resolve().parent.parent / "tools" / "state_manager.py"),
         "--store", cli],
        input="not json at all", capture_output=True, text=True)
    assert p.returncode == 0
    out = json.loads(p.stdout)
    assert out["status"] == "BLOCKED"
    assert out["errors"][0]["code"] == "OSM-E101"


def test_array_stdin_rejected(cli):
    import subprocess, sys
    from pathlib import Path
    p = subprocess.run(
        [sys.executable, str(Path(__file__).resolve().parent.parent / "tools" / "state_manager.py"),
         "--store", cli],
        input="[1,2,3]", capture_output=True, text=True)
    assert p.returncode == 0
    assert json.loads(p.stdout)["status"] == "BLOCKED"


def test_huge_payload_does_not_crash(cli):
    import subprocess, sys
    from pathlib import Path
    from conftest import BASE, cli_call as cc
    cc(cli, "project.init", extra={"title": "big"})
    big = dict(BASE)
    big["action"] = "state.get"
    big["constraints"] = ["x" * 100000] * 200
    p = subprocess.run(
        [sys.executable, str(Path(__file__).resolve().parent.parent / "tools" / "state_manager.py"),
         "--store", cli],
        input=json.dumps(big), capture_output=True, text=True, timeout=120)
    assert p.returncode == 0
    assert json.loads(p.stdout)["status"] == "SUCCESS"


def test_unknown_enum_in_actor_role_rejected(cli):
    out = cli_call(cli, "state.get", expect_ok=False,
                   extra={"actor": {"role": "root"}})
    assert out["errors"][0]["code"] == "OSM-E101"


def test_duplicate_event_type_in_apply_is_idempotent():
    """Replaying the same log twice must produce the same projection (idempotent
    rebuild is the basis of recovery consistency)."""
    import sys, tempfile
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
    from osm.store import EventStore
    from osm.models import EventType
    td = tempfile.mkdtemp(prefix="osm_replay_")
    store = EventStore(td)
    store.append("p", EventType.PROJECT_INITIALIZED, {"title": "t"}, actor="a")
    store.append("p", EventType.EVIDENCE_ATTACHED, {"ref": "e1"}, actor="a")
    p1 = store.rebuild("p")
    p2 = store.rebuild("p")
    assert p1.to_snapshot() == p2.to_snapshot()
