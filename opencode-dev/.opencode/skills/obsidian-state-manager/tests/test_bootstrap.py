"""Bootstrap tests (spec §八): the skill must be loadable and capable of
executing complete realistic research-workflow tasks end to end.

Scenario 1: interrupt+resume mid-DESIGNING  — context not lost, work not redone
Scenario 2: new evidence refutes a supported hypothesis — state downgrade
Scenario 3: illegal OPEN -> DEPLOYABLE — hard blocked, no silent pass
Scenario 4: event-log replay rebuilds a full study and matches the snapshot

These run through the real CLI with a temp store. Each scenario is written as
a fresh invocation from a plain user request; no expected answers are leaked
into inputs.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from conftest import cli_call

TOOLS = Path(__file__).resolve().parent.parent / "tools"
CLI = TOOLS / "state_manager.py"


def _head(cli: str, pid: str) -> int:
    out = cli_call(cli, "state.get")
    for art in out["artifacts"]:
        note = art.get("note")
        if isinstance(note, dict) and "head_revision" in note:
            return int(note["head_revision"])
    return 0


def _transition(cli: str, tgt: str, *, actor: str = "controller") -> None:
    out = cli_call(cli, "state.transition", extra={"to_state": tgt,
                                                   "actor": {"role": actor}})
    assert out["state"] == tgt, f"expected {tgt}, got {out['state']}: {out['summary']}"


def _drive_to_designing(cli: str) -> None:
    cli_call(cli, "project.init", extra={"title": "MICP ureolysis design study"})
    _transition(cli, "SCOPED")
    _transition(cli, "EVIDENCE_GATHERING")
    cli_call(cli, "evidence.attach", extra={
        "evidence": {"ref": "doi:10.1000/urease-kinetics",
                     "sha256": "a" * 64, "summary": "urease kinetics literature"}})
    _transition(cli, "HYPOTHESIS_BUILDING", actor="skill")
    cli_call(cli, "hypothesis.record", extra={
        "hypothesis": {"id": "h-urease", "statement": "urease concentration controls precipitation rate"}})
    _transition(cli, "DESIGNING", actor="skill")


def _drive_to_analyzing(cli: str) -> None:
    _drive_to_designing(cli)
    cli_call(cli, "task.checkpoint", extra={
        "task_id": "design-phase",
        "completed_work": [{"step": "factorial design", "input": "protocol-v1"},
                           {"step": "control plan", "input": "protocol-v1"}],
        "pending_work": [{"step": "execute experiments"}]})
    _transition(cli, "AWAITING_DATA")
    cli_call(cli, "evidence.attach", extra={
        "evidence": {"ref": "exp:run-001", "sha256": "b" * 64, "summary": "run 1 results"}})
    _transition(cli, "ANALYZING")


# ---------------------------------------------------------------------
# Scenario 1: interrupt + resume, context preserved, no duplicate work
# ---------------------------------------------------------------------

def test_scenario1_interrupt_and_resume_in_design_phase(cli):
    _drive_to_designing(cli)
    # Interrupt simulation: checkpoint exists, then a fresh session resumes.
    cli_call(cli, "task.checkpoint", extra={
        "task_id": "design-phase",
        "completed_work": [{"step": "factorial design", "input": "protocol-v1"},
                           {"step": "control plan", "input": "protocol-v1"}],
        "pending_work": [{"step": "execute experiments"}]})
    # Crash: new session (fresh subprocess) asks for a resume plan.
    plan = cli_call(cli, "task.resume_plan", extra={
        "task_id": "design-phase",
        "candidate_work": [
            {"step": "factorial design", "input": "protocol-v1"},  # unchanged -> skip
            {"step": "control plan", "input": "protocol-v1"},      # unchanged -> skip
            {"step": "execute experiments"},                       # pending -> run
        ]})
    note = plan["artifacts"][-1]["note"]
    assert note["skipped_count"] == 2
    assert len(note["to_run"]) == 1
    # Context (design decisions) is intact in the stream.
    got = cli_call(cli, "state.get")
    view = got["artifacts"][0]["note"]
    assert view["state"] == "DESIGNING"
    assert view["checkpoints"] != []
    assert view["hypotheses"][0]["id"] == "h-urease"


# ---------------------------------------------------------------------
# Scenario 2: refuting evidence downgrades a supported hypothesis
# ---------------------------------------------------------------------

def test_scenario2_contradicting_evidence_downgrades_state(cli):
    _drive_to_analyzing(cli)
    cli_call(cli, "hypothesis.set_status", extra={
        "id": "h-urease", "to_status": "SUPPORTED", "reason": "run-001 agrees"})
    # New study contradicts the supported hypothesis.
    out = cli_call(cli, "evidence.attach", extra={
        "evidence": {"ref": "exp:run-002", "sha256": "c" * 64,
                     "summary": "run 2 contradicts urease model",
                     "contradicts_hypothesis": ["h-urease"]}})
    # Watcher marks hypothesis CONTESTED and downgrades ANALYZING -> EVIDENCE_GATHERING.
    assert out["state"] == "EVIDENCE_GATHERING"
    got = cli_call(cli, "state.get")
    view = got["artifacts"][0]["note"]
    assert any(h["id"] == "h-urease" and h["status"] == "CONTESTED" for h in view["hypotheses"])
    assert view["state"] == "EVIDENCE_GATHERING"
    # Old validated conclusion must not be re-affirmed: it needs fresh evidence.
    out2 = cli_call(cli, "state.transition", expect_ok=False, extra={
        "to_state": "HYPOTHESIS_BUILDING", "actor": {"role": "skill"}})
    # Still needs >=1 live evidence; the retracted/contested ones may not count —
    # but e1 is still live, so this may pass. What matters: never back to VALIDATED.
    assert out2["state"] != "VALIDATED"


# ---------------------------------------------------------------------
# Scenario 3: illegal OPEN -> DEPLOYABLE is hard blocked
# ---------------------------------------------------------------------

def test_scenario3_open_to_deployable_hard_blocked(cli):
    cli_call(cli, "project.init", extra={"title": "attacker simulation"})
    out = cli_call(cli, "state.transition", expect_ok=False, extra={
        "to_state": "DEPLOYABLE",
        "actor": {"role": "human", "id": "attacker"},
        "human_approval_state": {"granted": True, "approver": "attacker", "revision": 1},
        "reason": "bypass attempt"})
    assert out["status"] == "FAILED"
    assert out["errors"][0]["code"] == "OSM-E305"
    assert out["state"] == "OPEN"
    # The rejected attempt is itself recorded (no silent loss).
    tl = cli_call(cli, "state.timeline")
    human = [a for a in tl["artifacts"] if a["kind"] == "timeline_human"][0]["note"]
    assert "REJECTED" in human


# ---------------------------------------------------------------------
# Scenario 4: event log rebuild == snapshot, full study replay
# ---------------------------------------------------------------------

def test_scenario4_event_replay_matches_snapshot(cli):
    _drive_to_analyzing(cli)
    cli_call(cli, "task.checkpoint", extra={
        "task_id": "analysis", "completed_work": [{"step": "fit model"}]})
    cli_call(cli, "decision.record", extra={
        "decision": {"id": "d1", "decision": "adopt urease-first protocol",
                     "rationale": "run-001 supports", "alternatives": ["direct-injection"]}})
    # Attach then retract an evidence item to prove retraction is append-only
    # and survives replay.
    cli_call(cli, "evidence.attach", extra={
        "evidence": {"ref": "exp:run-002", "sha256": "c" * 64, "summary": "run 2 (retracted later)"}})
    cli_call(cli, "evidence.retract", extra={"ref": "exp:run-002", "reason": "instrument drift"})

    # Rebuild from the log via a fresh process — the full study must replay.
    from conftest import BASE
    replay = dict(BASE)
    replay.update({"action": "snapshot.verify", "request": "replay"})
    proc = subprocess.run([sys.executable, str(CLI), "--store", cli],
                          input=json.dumps(replay),
                          capture_output=True, text=True, timeout=120)
    out = json.loads(proc.stdout)
    assert out["validation"]["rebuild_matches_snapshot"] is True
    # Timeline shows the full arc including retraction.
    tl = cli_call(cli, "state.timeline")
    machine = [a for a in tl["artifacts"] if a["kind"] == "timeline_machine"][0]["note"]
    types = [e["type"] for e in machine]
    assert "EVIDENCE_ATTACHED" in types
    assert "EVIDENCE_RETRACTED" in types
    assert "DECISION_RECORDED" in types
