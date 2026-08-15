"""Unit tests for individual obsidian-red-team tool modules."""

from __future__ import annotations

from balance import parse_formula, species_mass, main as balance_main
from citation import verify_one, _extract_doi
from blocking_rules import _blocking_rule, _state_recommendation
from errors import OrtErrorCode
from models import Severity, BlockingRuleId
from units import dims, compatible, QUANTITY_DIMS, TRAPS
from severity import _score
from retest import _audit_fix


# --- balance / formula parsing --------------------------------------------

class TestFormulaParsing:
    def test_simple_formula(self):
        assert parse_formula("CaCO3") == {"Ca": 1, "C": 1, "O": 3}

    def test_parenthesized(self):
        assert parse_formula("CO(NH2)2") == {"C": 1, "O": 1, "N": 2, "H": 4}

    def test_coefficient(self):
        assert parse_formula("2NH3") == {"N": 2, "H": 6}

    def test_coefficient_parenthesized(self):
        assert parse_formula("3CaCO3") == {"Ca": 3, "C": 3, "O": 9}

    def test_urea_balance_closes_with_water(self):
        r = balance_main({"reactions": [{
            "name": "urea",
            "reactants": [{"species": "CO(NH2)2", "amount_mol": 1.0},
                          {"species": "H2O", "amount_mol": 1.0}],
            "products": [{"species": "NH3", "amount_mol": 2.0},
                         {"species": "CO2", "amount_mol": 1.0}],
        }]})
        assert r["reactions"][0]["closed"] is True

    def test_unbalanced_detected(self):
        r = balance_main({"reactions": [{
            "name": "bad",
            "reactants": [{"species": "CO(NH2)2", "amount_mol": 1.0}],
            "products": [{"species": "NH3", "amount_mol": 2.0}],
        }]})
        assert r["reactions"][0]["closed"] is False
        assert r["summary"]["blocking_violation"] is True

    def test_flow_balance(self):
        r = balance_main({"reactions": [{
            "name": "x",
            "reactants": [{"species": "H2O", "amount_mol": 1.0}],
            "products": [{"species": "H2O", "amount_mol": 1.0}],
        }], "flows": [{
            "id": "f1", "species": "NH4", "inflow": 100.0, "outflow": 50.0, "accumulation": 0.0,
        }]})
        assert len(r["flow_findings"]) == 1


# --- citation verifier ------------------------------------------------------

class TestCitation:
    def test_doi_extraction(self):
        assert _extract_doi("doi:10.1038/s41598-018-19895-y") == "10.1038/s41598-018-19895-y"
        assert _extract_doi("https://doi.org/10.1016/j.ecoleng.2008.12.029") == \
            "10.1016/j.ecoleng.2008.12.029"
        assert _extract_doi("not-a-doi") is None

    def test_malformed_doi_rejected(self):
        r = verify_one({"ref_id": "r1", "locator": "doi:10.x-invalid"})
        assert r["verdict"] == "REJECTED"

    def test_fabricated_locator_suspected(self):
        r = verify_one({"ref_id": "r1", "locator": "this-paper-does-not-exist"})
        assert r["verdict"] == "SUSPECTED"

    def test_valid_doi_unverified_offline(self):
        r = verify_one({"ref_id": "r1", "locator": "doi:10.1038/s41598-018-19895-y", "year": 2018})
        assert r["verdict"] == "UNVERIFIED"
        assert r["verification_required"] is True

    def test_year_out_of_range(self):
        r = verify_one({"ref_id": "r1", "locator": "doi:10.1000/xyz", "year": 3026})
        assert r["verdict"] == "SUSPECTED"


# --- units / dimension ------------------------------------------------------

class TestUnits:
    def test_parse_dimensions(self):
        assert dims("MPa") == (1, -1, -2, 0, 0, 0)
        assert dims("m/s") == (0, 1, -1, 0, 0, 0)
        assert dims("mg/L") == (1, -3, 0, 0, 0, 0)
        assert dims("mol/L") == (0, -3, 0, 1, 0, 0)

    def test_compatibility(self):
        assert compatible("MPa", "kPa")
        assert not compatible("MPa", "m/s")
        assert not compatible("OD600", "umol/min/ml")

    def test_od600_not_urease(self):
        from units import main as units_main
        r = units_main({"measurements": [
            {"id": "m1", "value": 1.5, "unit": "OD600", "quantity": "urease_activity"},
        ]})
        assert r["findings"][0]["severity"] == "CRITICAL"

    def test_quantity_trap_table_consistent(self):
        for q1, q2, _ in TRAPS:
            assert q1 in QUANTITY_DIMS
            assert q2 in QUANTITY_DIMS


# --- severity ---------------------------------------------------------------

class TestSeverity:
    def test_fatal_safety_certain_is_blocking(self):
        r = _score({"id": "i1", "impact": 4, "affected_domain": "safety",
                    "certainty": "observed", "consequence_probability": "certain"})
        assert r["severity"] == "BLOCKING"

    def test_cosmetic_hypothesis_is_info(self):
        r = _score({"id": "i2", "impact": 1, "affected_domain": "science",
                    "certainty": "hypothesis", "consequence_probability": "possible"})
        assert r["severity"] == "INFO"

    def test_override_blocking(self):
        r = _score({"id": "i3", "impact": 1, "overrides": "BLOCKING"})
        assert r["severity"] == "BLOCKING"


# --- blocking rules ---------------------------------------------------------

class TestBlockingRules:
    def test_fabricated_citation(self):
        assert _blocking_rule({"citation_verdict": "REJECTED"}) == BlockingRuleId.FABRICATED_CITATION.value

    def test_ammonia_exceedance(self):
        assert _blocking_rule({"ammonia_concentration": 12, "recommends_deployment": True}) == \
            BlockingRuleId.AMMONIA_EXCEEDANCE.value
        assert _blocking_rule({"ammonia_concentration": 0.2, "recommends_deployment": True}) is None

    def test_open_blocker_escalation(self):
        assert _blocking_rule({"open_blockers": 1, "claims_upgrade": True}) == \
            BlockingRuleId.OPEN_BLOCKER_ESCALATION.value
        assert _blocking_rule({"open_blockers": 1}) is None

    def test_mass_balance(self):
        assert _blocking_rule({"mass_balance_closed": False}) == BlockingRuleId.MASS_BALANCE_VIOLATION.value

    def test_pseudo_replication_carries_key(self):
        assert _blocking_rule({"pseudo_replication": True,
                               "pseudo_replication_carries_significance": True}) == \
            BlockingRuleId.PSEUDOREPLICATION_CARRIES_KEY.value

    def test_regulation_unverified(self):
        assert _blocking_rule({"recommends_deployment": True, "regulations_unverified": True}) == \
            BlockingRuleId.REGULATION_UNVERIFIED.value

    def test_engineering_blocker(self):
        assert _blocking_rule({"recommends_deployment": True, "permeability_degraded": True}) == \
            BlockingRuleId.ENGINEERING_BLOCKER_RELEASE.value

    def test_state_escalation(self):
        assert _blocking_rule({"state_escalation_illegal": True}) == BlockingRuleId.STATE_ESCALATION.value

    def test_permission_boundary(self):
        assert _blocking_rule({"long_term_write_without_approval": True}) == \
            BlockingRuleId.PERMISSION_BOUNDARY.value

    def test_epistemic_escalation_deploy(self):
        assert _blocking_rule({"epistemic_escalation": True, "recommends_deployment": True}) == \
            BlockingRuleId.EPISTEMIC_ESCALATION_DEPLOY.value

    def test_state_recommendation_review_fail(self):
        r = _state_recommendation("DEPLOYABLE", 2)
        assert r["recommendation"] == "REVIEW_FAIL"
        r2 = _state_recommendation("REVIEW", 1)
        assert r2["recommendation"] == "HOLD"
        r3 = _state_recommendation("VALIDATED", 0)
        assert r3["recommendation"] == "APPROVE"


# --- retest verifier --------------------------------------------------------

class TestRetest:
    def test_executable_and_verifiable_passes(self):
        r = _audit_fix({"finding_id": "f1", "fix": "重跑 cli.py stats 并补充效应量",
                        "acceptance": "效应量 d>=0.5 且 CI 不含 0", "verify_by": "pytest"})
        assert r["verdict"] == "PASS"

    def test_vague_fix_fails(self):
        r = _audit_fix({"finding_id": "f2", "fix": "考虑改进", "acceptance": "更好", "verify_by": ""})
        assert r["verdict"] == "FAIL"


# --- escalation checker -----------------------------------------------------

class TestEscalation:
    def test_skip_gate_blocked(self):
        from escalation import _audit_escalation
        r = _audit_escalation({"target_id": "T1", "from": "SUPPORTED", "to": "DEPLOYABLE",
                               "review_verdict": "pass", "red_team_verdict": "pass",
                               "approval": "granted", "open_blockers": 0})
        assert r["legal"] is False
        codes = [i["code"] for i in r["issues"]]
        assert "ESC_SKIP_GATE" in codes

    def test_open_blocker_blocks(self):
        from escalation import _audit_escalation
        r = _audit_escalation({"target_id": "T1", "from": "VALIDATED", "to": "PILOT_READY",
                               "review_verdict": "pass", "red_team_verdict": "pass",
                               "approval": "granted", "open_blockers": 2})
        assert r["legal"] is False
        assert "ESC_OPEN_BLOCKER" in [i["code"] for i in r["issues"]]


# --- permission checker -----------------------------------------------------

class TestPermissions:
    def test_long_term_write_without_approval(self):
        from permissions import _audit_action
        r = _audit_action({"actor": "skill:x", "action": "memory.promote",
                           "target_tier": "verified_knowledge", "approval": "missing",
                           "writes": ["audit/x.json"]})
        assert r["legal"] is False
        assert r["findings"][0]["severity"] == "BLOCKING"

    def test_write_outside_scope(self):
        from permissions import _audit_action
        r = _audit_action({"actor": "skill:x", "action": "write", "writes": ["/etc/hosts"]})
        assert r["legal"] is False
        assert r["findings"][0]["code"] == "PERM_WRITE_OUTSIDE"


# --- models -----------------------------------------------------------------

class TestModels:
    def test_severity_order(self):
        assert Severity.BLOCKING.value == "BLOCKING"
        from models import SEVERITY_ORDER
        assert SEVERITY_ORDER[Severity.BLOCKING] == 4
        assert SEVERITY_ORDER[Severity.INFO] == 0
