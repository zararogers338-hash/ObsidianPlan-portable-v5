"""Regression tests for red-team-confirmed vulnerabilities.

Each test locks in a fix so the defect cannot silently reappear:
  RT1  zero-total-N balance force-closed (critical)
  RT2  pathogenic strain with accession returns SUCCESS (critical)
  RT3  unverified category record escapes the regulatory gate (high)
  RT4  computed NH3 speciation orphaned (high)
  RT5  residual risk HIGH->LOW downplaying (high)
  RT6  monitoring nh4_n_mgL with no threshold escapes G7 (high)
  RT7  residual_paths double-counts NH3 potential (high)
  RT8  field-injection plan downgraded to contained by absent flags (high)
  RT9  user-supplied nh3_potential_g silently ignored (medium)
"""

from __future__ import annotations

from tests.conftest import audit_payload, invoke


class TestRedTeamRegressions:
    # RT1: zero urea input but non-zero measured path must NOT close.
    def test_rt1_zero_urea_nonzero_path_not_closed(self, invoke_cli) -> None:
        payload = audit_payload(
            action="mass_balance",
            nitrogen={"urea_input_g": 0.0, "liquid_residual_g": 100.0},
        )
        out = invoke_cli(payload)
        assert out["status"] == "FAILED"
        assert out["errors"][0]["code"] == "MBS-E301"

    # RT2: pathogenic genus with a claimed accession must never reach SUCCESS.
    def test_rt2_pathogenic_strain_with_accession_gated(self, invoke_cli) -> None:
        payload = audit_payload()
        payload["site"]["strain"] = {"name": "Bacillus anthracis", "culture_collection_id": "ATCC 14578"}
        payload["site"]["pathogen_list_ref"] = "国卫科教发〔2023〕24号"
        out = invoke_cli(payload)
        assert out["status"] == "HUMAN_APPROVAL_REQUIRED"
        codes = [g["code"] for g in out["approval_requirements"]]
        assert "PATHOGENIC_STRAIN_UNCERTIFIED" in codes
        hazard_ids = [h["id"] for h in out["hazards"]]
        assert "strain_pathogenicity" in hazard_ids

    # RT2b: provisional BSL-1 without a site list ref is gated.
    def test_rt2b_unconfirmed_strain_gated(self, invoke_cli) -> None:
        payload = audit_payload()
        payload["site"].pop("pathogen_list_ref", None)
        out = invoke_cli(payload)
        assert out["status"] == "HUMAN_APPROVAL_REQUIRED"
        codes = [g["code"] for g in out["approval_requirements"]]
        assert "STRAIN_BIOSAFETY_UNCONFIRMED" in codes

    # RT3: a site that declares discharge gets REGULATORY_UNVERIFIED because
    # the water category carries unverified limit records.
    def test_rt3_discharge_site_regulatory_gap(self, invoke_cli) -> None:
        payload = audit_payload()
        payload["site"]["pathogen_list_ref"] = "国卫科教发〔2023〕24号"
        payload["plan"]["waste"]["discharge_to_environment"] = True
        out = invoke_cli(payload)
        assert out["status"] == "HUMAN_APPROVAL_REQUIRED"
        codes = [g["code"] for g in out["approval_requirements"]]
        assert "REGULATORY_UNVERIFIED" in codes

    # RT4: high NH4-N at alkaline pH raises ammonia_toxicity from computed
    # speciation even when the caller omitted site.nh3_risk.
    def test_rt4_computed_nh3_raises_hazard(self, invoke_cli) -> None:
        payload = audit_payload()
        payload["site"]["pathogen_list_ref"] = "国卫科教发〔2023〕24号"
        payload["plan"]["nitrogen"]["nh4_n_conc_mgL"] = 50.0
        payload["plan"]["nitrogen"]["pH"] = 9.5
        payload["plan"]["nitrogen"]["temperature_c"] = 25.0
        payload["site"].pop("nh3_risk", None)
        out = invoke_cli(payload)
        hazard_ids = [h["id"] for h in out["hazards"]]
        assert "ammonia_toxicity" in hazard_ids

    # RT5: HIGH hazard residual never drops below MODERATE.
    def test_rt5_high_hazard_residual_floor(self) -> None:
        from tools.mbs.risk import residual_risk
        assert residual_risk("HIGH", "high") == "MODERATE"
        assert residual_risk("HIGH", "moderate") == "MODERATE"

    # RT6: nh4_n_mgL measurement has a threshold and triggers G7.
    def test_rt6_nh4_monitoring_exceedance_gates(self, invoke_cli) -> None:
        payload = audit_payload()
        payload["site"]["pathogen_list_ref"] = "国卫科教发〔2023〕24号"
        payload["plan"]["measurements"] = {"nh4_n_mgL": 9999.0}
        out = invoke_cli(payload)
        assert out["status"] == "HUMAN_APPROVAL_REQUIRED"
        codes = [g["code"] for g in out["approval_requirements"]]
        assert "MONITORING_EXCEEDED" in codes

    # RT7: residual_paths must not double-count NH3 potential as a sink.
    def test_rt7_residual_paths_no_double_count(self, invoke_cli) -> None:
        payload = audit_payload(
            action="mass_balance",
            nitrogen={"urea_input_g": 100.0, "liquid_residual_g": 46.64},
        )
        out = invoke_cli(payload)
        nb = out["nitrogen_balance"]
        rp = nb["residual_paths"]
        assert "nh3_potential_g" not in rp  # speciation potential not a sink
        # accounted == liquid only, not double-counted.
        assert abs(nb["accounted_g"] - 46.64) < 1e-6

    # RT8: plan-level discharge/injection inferred even with contained flags.
    def test_rt8_plan_discharge_not_downgraded(self, invoke_cli) -> None:
        payload = audit_payload()
        payload["site"]["pathogen_list_ref"] = "国卫科教发〔2023〕24号"
        payload["site"]["release_type"] = "contained"  # absent/misleading flag
        payload["plan"]["waste"]["discharge_to_environment"] = True
        out = invoke_cli(payload)
        assert out["status"] == "HUMAN_APPROVAL_REQUIRED"
        codes = [g["code"] for g in out["approval_requirements"]]
        assert "HIGH_N_DISCHARGE" in codes or "REGULATORY_UNVERIFIED" in codes

    # RT9: user-supplied nh3_potential_g that disagrees with stoichiometry is
    # rejected, never silently dropped.
    def test_rt9_user_nh3_potential_conflict_rejected(self, invoke_cli) -> None:
        payload = audit_payload(
            action="mass_balance",
            nitrogen={"urea_input_g": 100.0, "nh3_potential_g": 999.0},
        )
        out = invoke_cli(payload)
        assert out["status"] == "FAILED"
        assert out["errors"][0]["code"] == "MBS-E301"
