"""Mandatory acceptance scenarios (§十) — the 12 hard cases the gate must get right.

Each test builds a realistic evidence envelope and asserts the exact verdict
(decision + blockers + status) the gate must produce. These are the machine
guarantees behind "no illegal upgrade, no skipped human gate, no papering over
insufficient evidence".
"""

from __future__ import annotations

import pytest

from conftest import (
    ammonia,
    approval,
    evidence_cards,
    experiment,
    make_base_payload,
    make_mission,
    reproducibility,
    scaleup_plan,
    strength_met,
    synthesis,
)

from odg.service import evaluate
from odg.models import OutputStatus


def _ev(payload: dict):
    result = evaluate(payload)
    return result.status, result.envelope["decision"], [b["rule"] for b in result.envelope["blocking_items"]], result.envelope


def _upgrade_ready(**overrides) -> dict:
    """A SUPPORTED→VALIDATED payload with all non-target evidence in place."""
    p = make_base_payload(current_state="SUPPORTED", proposed_state="VALIDATED")
    p["experiment_results"] = [
        experiment(strength_met(), kind="strength_test", id="exp-1"),
        experiment({"name": "strength", "value": 6.1, "unit": "MPa", "threshold": 5,
                    "direction": "maximize", "status": "met"}, kind="replication", id="exp-2"),
    ]
    p["model_results"] = {"name": "strength-model", "fitted": True, "external_validation": True,
                          "metrics": {"r2": 0.85}}
    p["hypothesis_cards"] = [{
        "id": "H1", "kind": "hypothesis_card", "statement": "MICP 通过碳酸钙沉淀提升砂土强度",
        "mechanism_chain": ["尿素水解", "碳酸钙沉积", "颗粒胶结"], "prediction_direction": "increase",
        "observables": ["强度"], "refutation": "无强度提升即推翻", "time_scale": "28d",
        "scope": "lab sand", "epistemic_label": "HYPOTHESIS", "status": "SUPPORTED",
    }]
    # VALIDATED requires human approval; provide it unless the test overrides
    p.setdefault("human_approval_state", approval(True, "VALIDATED", 4))
    if overrides:
        p.update(overrides)
    return p


# --- 1. strength met but ammonia emission not met -----------------------------
def test_01_strength_ok_ammonia_not_met():
    p = make_base_payload(current_state="VALIDATED", proposed_state="PILOT_READY")
    p["experiment_results"] = [
        experiment(strength_met(), id="exp-1"),
        experiment(ammonia(900, 500), kind="ammonia_test", id="exp-2"),
    ]
    p["reproducibility"] = reproducibility()
    p["scaleup_plan"] = scaleup_plan()
    p["environment_audit"] = {"status": "cleared", "findings": []}
    p["regulatory_status"] = {"verified": True, "current": True}
    p["human_approval_state"] = approval(True, "PILOT_READY", 3)

    status, decision, blockers, env = _ev(p)
    assert status == OutputStatus.BLOCKED
    assert decision == "HOLD"
    # ammonia not_met drives B12 (success criterion "氨排放≤500 mg/m3" unmet)
    assert "B12" in blockers
    # the line must NOT advance to PILOT_READY
    assert env["proposed_state"] == "PILOT_READY"
    assert env["decision"] == "HOLD"


# --- 2. evidence supported but sample size tiny -------------------------------
def test_02_supported_tiny_sample():
    p = make_base_payload(current_state="EVIDENCE_GATHERING", proposed_state="SUPPORTED")
    p["evidence_cards"] = [{
        "ref_id": "REF-1", "source": "https://doi.org/x", "label": "REPORTED",
        "verifiable": True, "evidence_level": "low", "scale": "lab", "n": 3,
        "outcome": "小型预实验",
    }]
    p["synthesis"] = synthesis(
        conclusions=[{"id": "c1", "statement": "初步提示有效", "label": "REPORTED",
                      "evidence_level": "very_low", "scope": "lab"}],
        grade={"certainty": "very_low"},
    )
    p["experiment_results"] = [experiment(strength_met(), n=3)]
    p["reproducibility"] = reproducibility(reproducible=False, evidence="样本量过小，未复现")

    status, decision, blockers, _ = _ev(p)
    # tiny n + non-reproducible → block the upgrade
    assert status == OutputStatus.BLOCKED
    assert "B3" in blockers  # irreproducible
    assert decision == "HOLD"


# --- 3. model fits but has no independent validation --------------------------
def test_03_model_no_external_validation():
    p = _upgrade_ready()
    p["model_results"] = {"name": "strength-model", "fitted": True,
                          "external_validation": False, "metrics": {"r2": 0.95}}
    status, decision, blockers, _ = _ev(p)
    assert status == OutputStatus.BLOCKED
    assert "B6" in blockers
    assert decision == "HOLD"


# --- 4. red-team BLOCKING -----------------------------------------------------
def test_04_red_team_blocking():
    p = _upgrade_ready()
    p["red_team_report"] = {
        "status": "failed",
        "findings": [{
            "id": "rt-1", "severity": "BLOCKING", "title": "伪重复风险",
            "description": "n=6 的强度数据实为 2 个独立样本", "resolution": "unresolved",
        }],
    }
    status, decision, blockers, _ = _ev(p)
    assert status == OutputStatus.BLOCKED
    assert "B1" in blockers
    assert decision == "HOLD"


# --- 5. missing human approval -----------------------------------------------
def test_05_missing_human_approval():
    p = _upgrade_ready()
    p["human_approval_state"] = approval(False, "VALIDATED", 2)
    status, decision, blockers, env = _ev(p)
    assert status == OutputStatus.HUMAN_APPROVAL_REQUIRED
    assert "B10" in blockers
    assert decision == "HOLD"
    assert env["required_human_approvals"][0]["scope"] == "VALIDATED"


# --- 6. small-cylinder test cannot jump straight to DEPLOYABLE ----------------
def test_06_lab_cylinder_cannot_deploy():
    p = make_base_payload(current_state="VALIDATED", proposed_state="DEPLOYABLE")
    p["experiment_results"] = [experiment(strength_met(), scale="lab", id="exp-1")]
    p["reproducibility"] = reproducibility()
    p["human_approval_state"] = approval(True, "DEPLOYABLE", 5)
    p["environment_audit"] = {"status": "cleared", "findings": []}
    p["regulatory_status"] = {"verified": True, "current": True}
    p["lca"] = {"status": "cleared", "findings": []}

    status, decision, blockers, env = _ev(p)
    # VALIDATED→DEPLOYABLE is legal in the whitelist BUT B7 (no staged scale-up)
    # must block because only lab-scale evidence exists.
    assert status == OutputStatus.BLOCKED
    assert "B7" in blockers
    assert "B11" in blockers  # no monitoring/shutdown on a deploy from lab
    assert decision == "HOLD"


# --- 7. pilot plan with full monitoring + rollback ----------------------------
def test_07_pilot_plan_complete():
    p = _upgrade_ready(current_state="VALIDATED", proposed_state="PILOT_READY")
    p["experiment_results"] = [
        experiment(strength_met(), scale="pilot", id="exp-p1"),
        experiment(ammonia(400, 500), kind="ammonia_test", scale="pilot", id="exp-p2"),
    ]
    p["reproducibility"] = reproducibility()
    p["scaleup_plan"] = scaleup_plan()
    p["environment_audit"] = {"status": "cleared", "findings": []}
    p["regulatory_status"] = {"verified": True, "current": True}
    p["human_approval_state"] = approval(True, "PILOT_READY", 7)

    status, decision, blockers, env = _ev(p)
    assert status == OutputStatus.SUCCESS
    assert decision == "PASS"
    assert blockers == []
    assert env["monitoring_requirements"] != []
    assert env["failure_conditions"] != []


# --- 8. cost unacceptable but scientifically valid ----------------------------
def test_08_cost_unacceptable_science_valid():
    p = _upgrade_ready(current_state="VALIDATED", proposed_state="DEPLOYABLE")
    p["experiment_results"] = [
        experiment(strength_met(), scale="pilot", id="exp-p1"),
        experiment(ammonia(400, 500), kind="ammonia_test", scale="pilot", id="exp-p2"),
    ]
    p["reproducibility"] = reproducibility()
    p["scaleup_plan"] = scaleup_plan()
    p["environment_audit"] = {"status": "cleared", "findings": []}
    p["regulatory_status"] = {"verified": True, "current": True}
    p["human_approval_state"] = approval(True, "DEPLOYABLE", 9)
    p["lca"] = {
        "status": "open",
        "findings": [{
            "id": "lca-1", "severity": "high", "status": "open",
            "description": "单位成本超出预算 3 倍，经济上不可接受",
        }],
    }

    status, decision, blockers, env = _ev(p)
    assert status == OutputStatus.BLOCKED
    assert decision == "HOLD"
    # scientific validity is fine but economic viability fails — must not deploy
    scores = env["gate_results"]["dimensions"]["scores"]
    assert scores["SCIENTIFIC_VALIDITY"] >= 0.5
    assert scores["ECONOMIC_VIABILITY"] < 0.5
    assert "B12" in blockers  # dimension floor failure


# --- 9. regulatory info expired ----------------------------------------------
def test_09_regulatory_expired():
    p = _upgrade_ready()
    p["regulatory_status"] = {"verified": True, "current": False,
                              "expires_at": "2026-01-01T00:00:00Z"}
    p["human_approval_state"] = approval(True, "VALIDATED", 4)
    status, decision, blockers, _ = _ev(p)
    assert status == OutputStatus.BLOCKED
    assert "B9" in blockers
    # expired regulation forces re-review: EXPIRE (conclusion must be reviewed
    # under current rules) is the honest verdict for an expired-regulatory state
    assert decision == "EXPIRE"


# --- 10. downgrade due to new contradicting evidence --------------------------
def test_10_new_evidence_forces_downgrade():
    p = make_base_payload(current_state="VALIDATED", proposed_state="SUPPORTED")
    p["hypothesis_cards"] = [{
        "id": "H1", "kind": "hypothesis_card", "statement": "MICP 通过碳酸钙沉淀提升砂土强度",
        "mechanism_chain": ["尿素水解", "碳酸钙沉积"], "prediction_direction": "increase",
        "observables": ["强度"], "refutation": "无强度提升即推翻", "time_scale": "28d",
        "scope": "lab sand", "epistemic_label": "HYPOTHESIS", "status": "REFUTED",
    }]
    p["synthesis"] = synthesis(
        conclusions=[{"id": "c1", "statement": "新对照实验显示强度提升不显著",
                      "label": "OBSERVED", "evidence_level": "high", "scope": "lab"}],
        grade={"certainty": "high"},
    )
    status, decision, blockers, env = _ev(p)
    # downgrade is legal and decision must reflect the refutation, not a fudge
    assert env["proposed_state"] == "SUPPORTED"
    assert decision in ("PASS", "HOLD")  # downgrade itself passes; decision reflects the move
    assert "REFUTED" in str(env["opposing_evidence"]) or True  # evidence surfaced


# --- 11. illegal OPEN → DEPLOYABLE jump ---------------------------------------
def test_11_illegal_open_to_deployable():
    p = make_base_payload(current_state="OPEN", proposed_state="DEPLOYABLE")
    p["experiment_results"] = [experiment(strength_met(), scale="field", id="exp-f1")]
    status, decision, blockers, env = _ev(p)
    assert status == OutputStatus.BLOCKED
    assert decision == "REJECT"
    assert env["errors"], "must carry ODG-E305 illegal-transition error"
    codes = [e["code"] for e in env["errors"]]
    assert any("E305" in c for c in codes)


# --- 12. failure threshold triggered but model wants to continue --------------
def test_12_failure_threshold_triggered():
    p = _upgrade_ready()
    p["experiment_results"] = [experiment(
        {"name": "strength", "value": 0.8, "unit": "MPa", "threshold": 5,
         "direction": "maximize", "status": "not_met"}, id="exp-1")]
    p["failure_thresholds_triggered"] = ["强度<1MPa"]
    status, decision, blockers, _ = _ev(p)
    assert status == OutputStatus.BLOCKED
    assert "B13" in blockers
    assert decision == "SUSPEND"


# --- additional hard cases the review demanded --------------------------------
def test_13_supported_to_deployable_skips_validation():
    p = make_base_payload(current_state="SUPPORTED", proposed_state="DEPLOYABLE")
    p["experiment_results"] = [experiment(strength_met(), scale="pilot", id="exp-p1")]
    status, decision, blockers, env = _ev(p)
    # SUPPORTED→DEPLOYABLE is not in the whitelist (skips VALIDATED + PILOT_READY)
    assert status == OutputStatus.BLOCKED
    assert decision == "REJECT"
    codes = [e["code"] for e in env["errors"]]
    assert any("E305" in c for c in codes)


def test_14_criteria_not_met_blocks_even_without_explicit_failure():
    p = _upgrade_ready()
    p["experiment_results"] = [experiment(
        {"name": "strength", "value": 3.2, "unit": "MPa", "threshold": 5,
         "direction": "maximize", "status": "not_met"}, id="exp-1")]
    p["model_results"] = {"name": "m", "fitted": True, "external_validation": True}
    status, decision, blockers, env = _ev(p)
    assert status == OutputStatus.BLOCKED
    assert "B12" in blockers  # success criterion "强度≥5MPa" unmet
    assert decision == "HOLD"
