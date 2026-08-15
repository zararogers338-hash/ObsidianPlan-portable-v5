"""Integration tests: full audit pipeline for a complete MICP plan.

These exercise the self-check (bootstrap) workflow: a realistic sand-column
plan and a realistic field plan, asserting every section of the task brief §七
is present and internally consistent.
"""

from __future__ import annotations

from tests.conftest import audit_payload, invoke


class TestBootstrapSections:
    def test_bootstrap_sand_column_has_all_sections(self, invoke_cli) -> None:
        """A complete sand-column audit must populate every brief §七 section."""
        payload = audit_payload()
        payload["site"]["release_type"] = "sand_column"
        out = invoke_cli(payload)
        assert out["status"] == "SUCCESS"
        # Every mandatory section present and typed.
        assert isinstance(out["hazards"], list)
        assert isinstance(out["exposure_pathways"], list)
        assert isinstance(out["nitrogen_balance"], dict)
        assert isinstance(out["waste_streams"], list)
        assert isinstance(out["regulatory_context"], dict)
        assert isinstance(out["monitoring_requirements"], dict)
        assert isinstance(out["control_measures"], list)
        assert isinstance(out["residual_risk"], list)
        assert isinstance(out["approval_requirements"], list)
        assert isinstance(out["stop_conditions"], list)
        assert isinstance(out["emergency_actions"], list)
        assert isinstance(out["evidence_used"], list)
        assert isinstance(out["uncertainty"], list)
        assert isinstance(out["artifacts"], list)
        assert isinstance(out["validation"], dict)
        assert isinstance(out["provenance"], dict)
        assert isinstance(out["errors"], list)
        assert isinstance(out["requested_next_skills"], list)
        # Nitrogen balance closed and populated.
        nb = out["nitrogen_balance"]
        assert nb["mass_balance_closed"] is True
        assert nb["urea_input_g"] == 120.0
        assert nb["theoretical_total_n_g"] > 0
        # validation all passed.
        assert out["validation"] == {"input_schema": "passed", "output_schema": "passed", "self_check": "passed"}

    def test_bootstrap_field_plan_blocks_and_lists_stops(self, invoke_cli) -> None:
        """A field injection plan must gate, list hazards, stops and emergencies."""
        payload = audit_payload()
        payload["site"].update({
            "release_type": "injection",
            "groundwater_injection": True,
            "waste_treatment_capacity": False,
            "site_sensitive_ecology": True,
            "confined_space": True,
            "aerosol_potential": True,
            "strain": {"name": "未鉴定菌株"},
        })
        payload["plan"]["waste"]["discharge_to_environment"] = True
        payload["plan"]["measurements"] = {"nh3_n_mgL": 3.0, "ph": 9.5}
        out = invoke_cli(payload)
        assert out["status"] == "HUMAN_APPROVAL_REQUIRED"
        codes = [g["code"] for g in out["approval_requirements"]]
        assert "GROUNDWATER_INJECTION" in codes
        assert "MONITORING_EXCEEDED" in codes
        assert "UNVERIFIED_STRAIN" in codes
        # stop conditions include an exceedance stop.
        assert any("超限" in s["condition"] for s in out["stop_conditions"])
        # emergency actions present.
        assert len(out["emergency_actions"]) >= 1
        # requested_next_skills suggests transport for injection.
        skills = [r["skill"] for r in out["requested_next_skills"]]
        assert "micp-porous-media-transport" in skills

    def test_biosafety_classification_of_sporosarcina(self, invoke_cli) -> None:
        """S. pasteurii is not in the 2023 CN pathogen list (verified finding):
        classification is provisional BSL-1 via institutional biosafety committee,
        not an official OBSERVED safety verdict."""
        payload = audit_payload(action="strain_verify")
        payload["strain"] = {"name": "Sporosarcina pasteurii", "culture_collection_id": "ATCC 11859"}
        out = invoke_cli(payload)
        assert out["status"] == "SUCCESS"
        cls = [a["note"] for a in out["artifacts"] if a["kind"] == "strain_biosafety"][0]
        assert cls["biosafety_level"] == "BSL-1"
        # provisional until the institutional committee + site list confirm it
        assert cls["needs_regulatory_confirmation"] is True
        assert cls["classification_confidence"] == "provisional"

    def test_nitrogen_balance_section_matches_mass_balance_tool(self, invoke_cli) -> None:
        """The audit's nitrogen_balance must equal the standalone mass_balance result."""
        audit_payload_in = audit_payload()
        audit_out = invoke_cli(audit_payload_in)
        mb_in = {"contract_version": "1.0", "task_id": "t", "project_id": "p",
                 "request": "balance", "action": "mass_balance",
                 "skill_version": "1.0.0", "timestamp": "2026-08-07T00:00:00Z",
                 "nitrogen": audit_payload_in["plan"]["nitrogen"]}
        mb_out = invoke_cli(mb_in)
        a = audit_out["nitrogen_balance"]
        b = mb_out["nitrogen_balance"]
        assert abs(a["theoretical_total_n_g"] - b["theoretical_total_n_g"]) < 1e-9
        assert a["mass_balance_closed"] == b["mass_balance_closed"]
