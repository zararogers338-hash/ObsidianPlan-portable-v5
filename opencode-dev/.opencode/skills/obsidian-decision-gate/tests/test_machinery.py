"""State-machine, blocking-rule, approval, expiry and comparison tests.

These cover the machinery the 12 scenarios exercise implicitly, in isolation:
  - whitelist legality + grade-gap (no illegal jumps)
  - the 13 blocking rules, each triggered and resolved
  - human-approval gate (granted / stale / missing)
  - review-expiry / supersession
  - decision-drift comparison
"""

from __future__ import annotations

import pytest

from conftest import (
    ammonia,
    approval,
    experiment,
    make_base_payload,
    reproducibility,
    scaleup_plan,
    strength_met,
)

from odg.models import ResearchState, Decision, OutputStatus
from odg.rules import RuleTable, evaluate_blockers
from odg.mission import check_mission
from odg.expiry import check_expiry, parse_ts
from odg.compare import compare_decisions
from odg.service import evaluate
from odg.validate import validate_input, validate_output, validate_memo


# --- whitelist legality -------------------------------------------------------
def test_whitelist_no_illegal_jumps():
    rt = RuleTable.load()
    illegal = [
        ("OPEN", "DEPLOYABLE"),
        ("OPEN", "PILOT_READY"),
        ("OPEN", "VALIDATED"),
        ("SUPPORTED", "DEPLOYABLE"),
        ("EVIDENCE_GATHERING", "PILOT_READY"),
        ("REJECTED", "SUPPORTED"),  # reopen may not skip straight to support
        ("DEPLOYABLE", "VALIDATED"),  # irreversible
        ("EXPIRED", "DEPLOYABLE"),
    ]
    for f, t in illegal:
        assert not rt.is_edge_legal(ResearchState(f), ResearchState(t)), f"{f}→{t} must be illegal"
    legal = [
        ("OPEN", "EVIDENCE_GATHERING"),
        ("EVIDENCE_GATHERING", "SUPPORTED"),
        ("SUPPORTED", "VALIDATED"),
        ("VALIDATED", "PILOT_READY"),
        ("PILOT_READY", "DEPLOYABLE"),
        ("VALIDATED", "REJECTED"),
        ("DEPLOYABLE", "EXPIRED"),
    ]
    for f, t in legal:
        assert rt.is_edge_legal(ResearchState(f), ResearchState(t)), f"{f}→{t} must be legal"


def test_grade_gap_matches_maturity():
    rt = RuleTable.load()
    from odg.rules import grade_gap
    assert grade_gap(rt, ResearchState.OPEN, ResearchState.DEPLOYABLE) == 5
    assert grade_gap(rt, ResearchState.VALIDATED, ResearchState.DEPLOYABLE) == 2
    assert grade_gap(rt, ResearchState.DEPLOYABLE, ResearchState.SUSPENDED) == 0


# --- the 13 blocking rules ----------------------------------------------------
def _payload_with(cards_ok=True, **overrides):
    p = make_base_payload(current_state="EVIDENCE_GATHERING", proposed_state="SUPPORTED")
    if overrides:
        p.update(overrides)
    return p


def test_b1_red_team_blocking():
    p = _payload_with(red_team_report={"status": "failed", "findings": [
        {"id": "r", "severity": "BLOCKING", "title": "t", "description": "d", "resolution": "unresolved"}]})
    b = evaluate_blockers(p, RuleTable.load(), ResearchState.EVIDENCE_GATHERING, ResearchState.SUPPORTED)
    assert any(x.rule == "B1" for x in b)


def test_b1_resolved_red_team_not_blocking():
    p = _payload_with(red_team_report={"status": "passed", "findings": [
        {"id": "r", "severity": "BLOCKING", "title": "t", "description": "d", "resolution": "resolved"}]})
    b = evaluate_blockers(p, RuleTable.load(), ResearchState.EVIDENCE_GATHERING, ResearchState.SUPPORTED)
    assert not any(x.rule == "B1" for x in b)


def test_b2_unverifiable_evidence():
    p = _payload_with(evidence_cards=[{"ref_id": "R", "source": "x", "label": "REPORTED", "verifiable": False}])
    b = evaluate_blockers(p, RuleTable.load(), ResearchState.EVIDENCE_GATHERING, ResearchState.SUPPORTED)
    assert any(x.rule == "B2" for x in b)


def test_b3_irreproducible():
    p = _payload_with(reproducibility=reproducibility(reproducible=False))
    b = evaluate_blockers(p, RuleTable.load(), ResearchState.EVIDENCE_GATHERING, ResearchState.SUPPORTED)
    assert any(x.rule == "B3" for x in b)


def test_b4_missing_control():
    p = _payload_with(experiment_results=[experiment(strength_met(), has_control=False)])
    b = evaluate_blockers(p, RuleTable.load(), ResearchState.EVIDENCE_GATHERING, ResearchState.SUPPORTED)
    assert any(x.rule == "B4" for x in b)


def test_b5_mass_balance_failure():
    e = experiment(strength_met())
    e["mass_balance"] = {"closure_error_percent": 12.0, "tolerance_percent": 5.0, "closed": False}
    p = _payload_with(experiment_results=[e])
    b = evaluate_blockers(p, RuleTable.load(), ResearchState.EVIDENCE_GATHERING, ResearchState.SUPPORTED)
    assert any(x.rule == "B5" for x in b)


def test_b6_model_without_external_validation():
    p = _payload_with(model_results={"name": "m", "fitted": True, "external_validation": False})
    b = evaluate_blockers(p, RuleTable.load(), ResearchState.SUPPORTED, ResearchState.VALIDATED)
    assert any(x.rule == "B6" for x in b)


def test_b6_model_does_not_gate_supported():
    # external validation only required at VALIDATED+; SUPPORTED is fine without
    p = _payload_with(model_results={"name": "m", "fitted": True, "external_validation": False})
    b = evaluate_blockers(p, RuleTable.load(), ResearchState.EVIDENCE_GATHERING, ResearchState.SUPPORTED)
    assert not any(x.rule == "B6" for x in b)


def test_b7_scale_ladder_gap():
    p = _payload_with(experiment_results=[experiment(strength_met(), scale="lab")])
    b = evaluate_blockers(p, RuleTable.load(), ResearchState.VALIDATED, ResearchState.DEPLOYABLE)
    assert any(x.rule == "B7" for x in b)


def test_b7_staged_scaleup_passes():
    p = _payload_with(experiment_results=[
        experiment(strength_met(), scale="lab"),
        experiment(strength_met(), scale="pilot"),
    ])
    b = evaluate_blockers(p, RuleTable.load(), ResearchState.VALIDATED, ResearchState.DEPLOYABLE)
    assert not any(x.rule == "B7" for x in b)


def test_b8_env_risk_open():
    p = _payload_with(environment_audit={"status": "open", "findings": [
        {"id": "e", "severity": "high", "status": "open", "description": "氨扩散"}]})
    b = evaluate_blockers(p, RuleTable.load(), ResearchState.VALIDATED, ResearchState.PILOT_READY)
    assert any(x.rule == "B8" for x in b)


def test_b9_regulatory_unverified():
    p = _payload_with(regulatory_status={"verified": False, "current": False})
    b = evaluate_blockers(p, RuleTable.load(), ResearchState.SUPPORTED, ResearchState.VALIDATED)
    assert any(x.rule == "B9" for x in b)


def test_b10_approval_missing():
    p = _payload_with(human_approval_state=approval(False, "VALIDATED", 1))
    b = evaluate_blockers(p, RuleTable.load(), ResearchState.SUPPORTED, ResearchState.VALIDATED)
    assert any(x.rule == "B10" for x in b)


def test_b10_approval_granted_passes():
    p = _payload_with(human_approval_state=approval(True, "VALIDATED", 1))
    b = evaluate_blockers(p, RuleTable.load(), ResearchState.SUPPORTED, ResearchState.VALIDATED)
    assert not any(x.rule == "B10" for x in b)


def test_b10_approval_wrong_scope_blocks():
    p = _payload_with(human_approval_state=approval(True, "DEPLOYABLE", 1))
    b = evaluate_blockers(p, RuleTable.load(), ResearchState.SUPPORTED, ResearchState.VALIDATED)
    assert any(x.rule == "B10" for x in b)


def test_b11_no_monitoring_shutdown():
    p = _payload_with(scaleup_plan={"stages": [{"scale": "pilot", "objective": "o", "duration": "1mo"}],
                                    "monitoring_plan": "", "shutdown_conditions": [], "rollback_plan": ""})
    b = evaluate_blockers(p, RuleTable.load(), ResearchState.VALIDATED, ResearchState.PILOT_READY)
    assert any(x.rule == "B11" for x in b)


def test_b12_success_criteria_not_met():
    p = _payload_with(_criteria_not_met=[{"criterion": "强度≥5MPa", "why": "current 3 < target 5"}])
    b = evaluate_blockers(p, RuleTable.load(), ResearchState.EVIDENCE_GATHERING, ResearchState.SUPPORTED)
    assert any(x.rule == "B12" for x in b)


def test_b13_failure_threshold_triggered():
    p = _payload_with(failure_thresholds_triggered=["强度<1MPa"])
    b = evaluate_blockers(p, RuleTable.load(), ResearchState.EVIDENCE_GATHERING, ResearchState.SUPPORTED)
    assert any(x.rule == "B13" for x in b)


# --- mission comparator -------------------------------------------------------
def test_mission_strength_met_ammonia_not():
    p = make_base_payload()
    p["experiment_results"] = [
        experiment(strength_met(), id="e1"),
        experiment(ammonia(900, 500), kind="ammonia", id="e2"),
    ]
    mc = check_mission(p)
    assert "强度≥5MPa" in mc.criteria_met
    assert any(n["criterion"].startswith("氨排放") for n in mc.criteria_not_met)


def test_mission_failure_threshold_triggered():
    p = make_base_payload()
    p["experiment_results"] = [experiment(
        {"name": "strength", "value": 0.5, "unit": "MPa", "threshold": 5,
         "direction": "maximize", "status": "not_met"})]
    p["failure_thresholds_triggered"] = ["强度<1MPa"]
    mc = check_mission(p)
    assert mc.failure_thresholds_triggered


# --- expiry -------------------------------------------------------------------
def test_expiry_regulatory_past():
    p = make_base_payload()
    p["regulatory_status"] = {"verified": True, "current": True,
                              "expires_at": "2026-01-01T00:00:00Z"}
    e = check_expiry(p, now=parse_ts("2026-08-07T00:00:00Z"))
    assert e.expired
    assert any(t["type"] == "regulatory_expired" for t in e.triggers)


def test_expiry_review_horizon():
    p = make_base_payload()
    p["review_expiry"] = "2026-01-01T00:00:00Z"
    e = check_expiry(p, now=parse_ts("2026-08-07T00:00:00Z"))
    assert e.expired
    assert any(t["type"] == "review_horizon_passed" for t in e.triggers)


def test_expiry_hypothesis_refuted():
    p = make_base_payload()
    p["hypothesis_cards"] = [{
        "id": "H1", "kind": "hypothesis_card", "statement": "MICP 提升砂土强度",
        "mechanism_chain": ["a"], "prediction_direction": "increase", "observables": ["s"],
        "refutation": "r", "time_scale": "28d", "scope": "lab", "epistemic_label": "HYPOTHESIS",
        "status": "REFUTED"}]
    e = check_expiry(p, now=parse_ts("2026-08-07T00:00:00Z"))
    assert e.expired
    assert any(t["type"] == "hypothesis_refuted" for t in e.triggers)


def test_expiry_clear():
    p = make_base_payload()
    e = check_expiry(p, now=parse_ts("2026-08-07T00:00:00Z"))
    assert not e.expired


# --- comparison ---------------------------------------------------------------
def test_compare_flags_decision_reversal():
    p = make_base_payload()
    p["history"] = [{
        "recorded_at": "2026-07-01T00:00:00Z", "decision": "PASS",
        "current_state": "SUPPORTED", "proposed_state": "VALIDATED",
        "gate_results": {"dimensions": {"scores": {}}}, "blocking_items": [],
    }]
    res = compare_decisions(p, RuleTable.load(), current={
        "decision": "HOLD", "current_state": "SUPPORTED", "proposed_state": "VALIDATED",
        "blocking_items": [{"rule": "B6"}],
        "gate_results": {"dimensions": {"scores": {}}},
    }, now="2026-08-07T00:00:00Z")
    assert res["compared"]
    assert res["deltas"]


def test_compare_no_history():
    p = make_base_payload()
    res = compare_decisions(p, RuleTable.load(), current={"decision": "PASS", "current_state": "OPEN"},
                            now="2026-08-07T00:00:00Z")
    assert not res["compared"]


# --- schema validation --------------------------------------------------------
def test_input_schema_rejects_unknown_field():
    p = make_base_payload()
    p["bogus_field"] = True
    with pytest.raises(Exception):
        validate_input(p)


def test_output_schema_validates_full_evaluation():
    res = evaluate(make_base_payload())
    env = res.envelope
    validate_output(env)  # must not raise
    assert env["validation"]["output_schema"] == "passed"


def test_decision_memo_schema():
    res = evaluate(make_base_payload(current_state="VALIDATED", proposed_state="PILOT_READY",
                                     human_approval_state=approval(True, "PILOT_READY", 7)))
    env = res.envelope
    validate_memo(env["decision_memo"])


# --- decision consistency self-check ------------------------------------------
def test_no_pass_with_blockers():
    # a payload that triggers a blocker must never produce PASS
    p = make_base_payload(current_state="SUPPORTED", proposed_state="VALIDATED",
                          red_team_report={"status": "failed", "findings": [
                              {"id": "r", "severity": "BLOCKING", "title": "t", "description": "d",
                               "resolution": "unresolved"}]})
    res = evaluate(p)
    assert res.envelope["decision"] != "PASS"
    assert res.envelope["validation"]["checks"][0]["ok"]
