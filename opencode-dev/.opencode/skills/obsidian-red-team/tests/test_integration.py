"""Integration tests: the review pipeline and per-tool CLI over real stdin."""

from __future__ import annotations

from conftest import run_cli


# --- review pipeline --------------------------------------------------------

class TestReviewPipeline:
    def test_blocked_case_blocks_escalation(self, review_blocked_payload):
        out = run_cli("review", review_blocked_payload)
        assert out["ok"] is True
        r = out["result"]
        assert r["status"] == "BLOCKED"
        assert r["state_recommendation"]["recommendation"] == "REVIEW_FAIL"
        assert len(r["blocking_findings"]) >= 1
        assert r["validation"]["self_audit_pass"] is True

    def test_blocking_findings_are_subset_of_findings(self, review_blocked_payload):
        out = run_cli("review", review_blocked_payload)
        r = out["result"]
        finding_ids = {f["finding_id"] for f in r["findings"]}
        for b in r["blocking_findings"]:
            assert b["finding_id"] in finding_ids
            assert b["severity"] == "BLOCKING"
            assert b["blocks_state_upgrade"] is True

    def test_clean_case_approves(self, review_clean_payload):
        out = run_cli("review", review_clean_payload)
        r = out["result"]
        assert r["status"] == "SUCCESS"
        assert r["state_recommendation"]["recommendation"] == "APPROVE"
        assert r["blocking_findings"] == []

    def test_output_passes_check_self(self, review_blocked_payload):
        out = run_cli("review", review_blocked_payload)
        r = out["result"]
        check = run_cli("check-self", r)
        assert check["result"]["valid"] is True

    def test_review_deterministic(self, review_blocked_payload):
        a = run_cli("review", review_blocked_payload)
        b = run_cli("review", review_blocked_payload)
        assert a["result"]["findings"] == b["result"]["findings"]
        assert a["result"]["state_recommendation"] == b["result"]["state_recommendation"]

    def test_missing_targets_blocks(self, review_clean_payload):
        payload = dict(review_clean_payload)
        payload.pop("targets", None)  # absent key → ORT-E102 (no auditable target)
        out = run_cli("review", payload)
        assert out["ok"] is False
        assert out["error"]["code"] == "ORT-E102"


# --- per-tool CLI over stdin ------------------------------------------------

class TestToolCLI:
    def test_citation_cli(self):
        out = run_cli("citation", {"citations": [
            {"ref_id": "r1", "locator": "doi:10.1038/s41598-018-19895-y", "year": 2018},
        ]})
        assert out["ok"] is True
        assert out["result"]["results"][0]["verdict"] == "UNVERIFIED"

    def test_units_cli(self):
        out = run_cli("units", {"measurements": [
            {"id": "m1", "value": 1.5, "unit": "OD600", "quantity": "urease_activity"},
        ]})
        assert out["ok"] is True
        assert out["result"]["findings"][0]["severity"] == "CRITICAL"

    def test_balance_cli(self):
        out = run_cli("balance", {"reactions": [{
            "name": "urea",
            "reactants": [{"species": "CO(NH2)2", "amount_mol": 1.0},
                          {"species": "H2O", "amount_mol": 1.0}],
            "products": [{"species": "NH3", "amount_mol": 2.0},
                         {"species": "CO2", "amount_mol": 1.0}],
        }]})
        assert out["result"]["reactions"][0]["closed"] is True

    def test_pseudo_cli(self):
        out = run_cli("pseudo", {"samples": [
            {"id": "A1", "pos": "top"}, {"id": "A1", "pos": "mid"}, {"id": "A2", "pos": "top"},
        ], "data_columns": [
            {"name": "id", "role": "id"}, {"name": "pos", "role": "position"},
        ]})
        assert out["result"]["detected"] is True
        assert out["result"]["effective_n"] == 2

    def test_blocking_cli(self):
        out = run_cli("blocking", {"findings": [
            {"id": "f1", "ammonia_concentration": 12, "recommends_deployment": True},
            {"id": "f2", "pseudo_replication": True,
             "pseudo_replication_carries_significance": True},
        ], "state_gate": "DEPLOYABLE"})
        r = out["result"]
        assert r["blocking_count"] == 2
        assert r["state_recommendation"]["recommendation"] == "REVIEW_FAIL"
        assert set(r["rules_fired"]) == {"BLOCK-2", "BLOCK-5"}

    def test_escalation_cli(self):
        out = run_cli("escalation", {"escalations": [
            {"target_id": "T1", "from": "SUPPORTED", "to": "DEPLOYABLE",
             "review_verdict": "pass", "red_team_verdict": "fail",
             "approval": "granted", "open_blockers": 0},
        ]})
        assert out["result"]["escalations"][0]["legal"] is False

    def test_permissions_cli(self):
        out = run_cli("permissions", {"actions": [
            {"actor": "skill:micp-data-analyst", "action": "memory.promote",
             "target_tier": "verified_knowledge", "approval": "missing", "writes": ["audit/x.json"]},
        ]})
        assert out["result"]["summary"]["blocking"] == 1

    def test_retest_cli(self):
        out = run_cli("retest", {"required_fixes": [
            {"finding_id": "f1", "fix": "重跑 cli.py stats 并补充效应量",
             "acceptance": "效应量 d>=0.5 且 CI 不含 0", "verify_by": "pytest"},
        ]})
        assert out["result"]["fixes"][0]["verdict"] == "PASS"

    def test_validate_cli_rejects_bad_input(self):
        out = run_cli("review", {})  # empty payload fails input validation
        assert out["ok"] is False
        assert out["error"]["code"] == "ORT-E101"

    def test_check_self_detects_invariant_violation(self):
        # A malformed output with BLOCKING but SUCCESS status must fail check-self.
        bad = {
            "status": "SUCCESS",
            "blocking_findings": [{"finding_id": "b1"}],
            "findings": [{"finding_id": "b1"}],
            "state_recommendation": {"recommendation": "APPROVE", "blocking_count": 1},
        }
        out = run_cli("check-self", bad)
        assert out["result"]["valid"] is False
