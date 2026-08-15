"""Adversarial review tests: the six failure modes a decision gate must resist.

These mirror the bootstrap adversarial review as repeatable regression tests:
  1. evidence stripped → must NOT pass
  2. over-conservatism → a complete, approvable project must pass
  3. mission success criteria ignored → failure threshold must block
  4. blocking item missed → BLOCKING red-team finding must block
  5. scientific support mistaken for engineering deploy → cost failure must block
  6. human approval bypassed → missing approval must produce HUMAN_APPROVAL_REQUIRED
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from conftest import make_base_payload, approval, experiment, strength_met, reproducibility, scaleup_plan, ammonia
from odg.service import evaluate
from odg.models import OutputStatus

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def bootstrap():
    """The complete simulated MICP deployment project."""
    return json.loads((ROOT / "examples" / "example-bootstrap.json").read_text(encoding="utf-8"))


def _ev(p):
    res = evaluate(p)
    return res.status, res.envelope["decision"], [b["rule"] for b in res.envelope["blocking_items"]], res.envelope


def test_bootstrap_project_reaches_deployable(bootstrap):
    status, decision, blockers, env = _ev(bootstrap)
    assert status == OutputStatus.SUCCESS
    assert decision == "PASS"
    assert env["proposed_state"] == "DEPLOYABLE"
    assert blockers == []


def test_attack1_evidence_stripped_blocks(bootstrap):
    p = dict(bootstrap)
    p["evidence_cards"] = []
    p["synthesis"] = None
    status, decision, blockers, _ = _ev(p)
    assert decision != "PASS"


def test_attack2_removing_hypothesis_still_passes(bootstrap):
    p = dict(bootstrap)
    p.pop("hypothesis_cards", None)
    status, decision, blockers, _ = _ev(p)
    assert decision == "PASS"


def test_attack3_failure_threshold_blocks(bootstrap):
    p = dict(bootstrap)
    p["failure_thresholds_triggered"] = ["氨排放>1500 mg/m3"]
    status, decision, blockers, _ = _ev(p)
    assert decision != "PASS"
    assert "B13" in blockers


def test_attack4_blocking_red_team_blocks(bootstrap):
    p = dict(bootstrap)
    p["red_team_report"] = {"status": "failed", "findings": [
        {"id": "RT-B", "severity": "BLOCKING", "title": "致命", "description": "x", "resolution": "unresolved"}]}
    status, decision, blockers, _ = _ev(p)
    assert decision != "PASS"
    assert "B1" in blockers


def test_attack5_cost_failure_blocks(bootstrap):
    p = dict(bootstrap)
    p["lca"] = {"status": "open", "findings": [
        {"id": "LCA-B", "severity": "high", "status": "open", "description": "单位成本超预算3倍"}]}
    status, decision, blockers, _ = _ev(p)
    assert decision != "PASS"
    assert status != OutputStatus.SUCCESS


def test_attack6_approval_revoked_requires_human(bootstrap):
    p = dict(bootstrap)
    p["human_approval_state"] = {"granted": False, "scope": "DEPLOYABLE", "revision": None, "granted_at": None}
    status, decision, blockers, env = _ev(p)
    assert status == OutputStatus.HUMAN_APPROVAL_REQUIRED
    assert "B10" in blockers
    assert env["required_human_approvals"][0]["status"] == "missing"


def test_attack6b_stale_approval_requires_human(bootstrap):
    p = dict(bootstrap)
    p["human_approval_state"] = {"granted": True, "scope": "VALIDATED", "revision": 42, "granted_at": "2026-08-05T00:00:00Z"}
    status, decision, blockers, env = _ev(p)
    # wrong scope: approval covers VALIDATED, not DEPLOYABLE
    assert status == OutputStatus.HUMAN_APPROVAL_REQUIRED
    assert "B10" in blockers
