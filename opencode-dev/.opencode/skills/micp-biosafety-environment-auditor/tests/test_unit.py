"""Unit tests for the individual tool modules (pure, no CLI)."""

from __future__ import annotations

import math

import pytest

from tools.mbs.chemistry import (
    nh3_concentration,
    nh3_fraction,
    pka_ammonium,
    urea_to_nitrogen_balance,
    ureolysis_ammonium,
    waste_loading,
)
from tools.mbs.errors import MbsError
from tools.mbs.risk import alarm_rules, monitoring_plan, residual_risk, risk_level, risk_matrix
from tools.mbs.strain import classify_biosafety, verify_strain_identity
from tools.mbs.treatment import compare_treatment_options, permit_status, sampling_plan


# ------------------------------------------------------------------------- #
# chemistry
# ------------------------------------------------------------------------- #
class TestChemistry:
    def test_pka_correlation(self) -> None:
        # At 25C the NH4+ pKa is ~9.25.
        assert abs(pka_ammonium(25.0) - 9.25) < 0.05

    def test_nh3_fraction_monotonic(self) -> None:
        f7 = nh3_fraction(7.0, 20.0)
        f8 = nh3_fraction(8.0, 20.0)
        f9 = nh3_fraction(9.0, 20.0)
        assert f7 < f8 < f9

    def test_nh3_fraction_temperature(self) -> None:
        f20 = nh3_fraction(9.0, 20.0)
        f35 = nh3_fraction(9.0, 35.0)
        assert f35 > f20  # hotter => more free NH3

    def test_nh3_never_negative_or_over_total(self) -> None:
        for ph in (0.0, 7.0, 14.0):
            res = nh3_concentration(100.0, ph, 20.0)
            assert 0.0 <= res["nh3_n_mgL"] <= 100.0 + 1e-9
            assert abs(res["nh3_n_mgL"] + res["nh4_n_mgL"] - 100.0) < 1e-9

    def test_ureolysis_stoichiometry(self) -> None:
        res = ureolysis_ammonium(60.0, 1.0)
        assert abs(res["nh4_mM"] - 120.0) < 1e-6  # 2x
        assert abs(res["nh4_n_mgL"] - 120.0 * 14.007) < 1e-6

    def test_balance_rejects_nan(self) -> None:
        with pytest.raises(MbsError) as e:
            urea_to_nitrogen_balance(urea_input_g=float("nan"))
        assert e.value.code.code == "MBS-E302"

    def test_balance_negative_urea(self) -> None:
        with pytest.raises(MbsError):
            urea_to_nitrogen_balance(urea_input_g=-5.0)

    def test_waste_loading_zero(self) -> None:
        res = waste_loading(waste_volume_l=0.0, nh4_n_conc_mgL=0.0)
        assert res["total_n_load_g"] == 0.0

    def test_waste_loading_nh3(self) -> None:
        res = waste_loading(waste_volume_l=100.0, nh4_n_conc_mgL=100.0, pH=9.0, temperature_c=30.0)
        assert res["nh3_n_load_g"] > 0
        assert res["nh3_n_load_g"] < res["nh4_n_load_g"]


# ------------------------------------------------------------------------- #
# strain
# ------------------------------------------------------------------------- #
class TestStrain:
    def test_verified_strain(self) -> None:
        s = {"name": "Sporosarcina pasteurii", "culture_collection_id": "ATCC 11859"}
        identity = verify_strain_identity(s)
        assert identity["verified"] is True
        assert identity["common_micp_hint"] is not None

    def test_unverified_strain_raises(self) -> None:
        with pytest.raises(MbsError) as e:
            verify_strain_identity({"name": ""})
        assert e.value.code.code == "MBS-E203"

    def test_unknown_strain_not_defaulted_safe(self) -> None:
        cls = classify_biosafety({"name": "某个未鉴定细菌"})
        assert cls["needs_regulatory_confirmation"] is True
        assert cls["classification_confidence"] in ("provisional", "none")

    def test_pathogenic_marker_not_defaulted(self) -> None:
        cls = classify_biosafety({"name": "Bacillus anthracis strain X", "culture_collection_id": "ACC-1"})
        assert cls["biosafety_level"] != "BSL-1"  # never default safe

    def test_invalid_claimed_risk_group(self) -> None:
        with pytest.raises(MbsError):
            classify_biosafety({"name": "A", "culture_collection_id": "B"}, claimed_risk_group="RG-9")


# ------------------------------------------------------------------------- #
# risk
# ------------------------------------------------------------------------- #
class TestRisk:
    def test_risk_matrix_cells(self) -> None:
        assert risk_level("ALMOST_CERTAIN", "SEVERE") == "CRITICAL"
        assert risk_level("RARE", "NEGLIGIBLE") == "LOW"
        assert risk_level("LIKELY", "MAJOR") == "CRITICAL"

    def test_risk_matrix_artifact(self) -> None:
        m = risk_matrix()
        assert len(m["matrix"]) == 5 and len(m["matrix"][0]) == 5

    def test_residual_reduces(self) -> None:
        # HIGH never drops below MODERATE (red-team fix: HIGH floor added).
        assert residual_risk("HIGH", "high") == "MODERATE"
        assert residual_risk("HIGH", "none") == "HIGH"
        assert residual_risk("HIGH", "moderate") == "MODERATE"
        # Conservative floor: CRITICAL never drops below MODERATE.
        assert residual_risk("CRITICAL", "high") == "MODERATE"
        # LOW is only reachable from MODERATE-with-high-controls or below.
        assert residual_risk("MODERATE", "high") == "LOW"

    def test_alarm_trigger(self) -> None:
        mon = monitoring_plan({"pH": 8.0})
        alarms = alarm_rules(mon, {"nh3_n_mgL": 2.0})
        nh3 = [a for a in alarms if a["parameter"] == "nh3_n_mgL"][0]
        assert nh3["triggered"] is True

    def test_alarm_ok(self) -> None:
        mon = monitoring_plan({"pH": 8.0})
        alarms = alarm_rules(mon, {"nh3_n_mgL": 0.1, "ph": 7.0})
        assert all(not a["triggered"] for a in alarms)

    def test_alarm_warning_absolute_margin(self) -> None:
        # temperature_c warning=5.0 is an absolute margin below max=50.
        mon = monitoring_plan({"pH": 8.0})
        alarms = alarm_rules(mon, {"temperature_c": 46.0})
        temp = [a for a in alarms if a["parameter"] == "temperature_c"][0]
        assert temp["triggered"] is False
        assert temp["level"] == "warning"

    def test_alarm_warning_fraction(self) -> None:
        # nh3_n_mgL warning=0.8 is 80% of max=0.5? No: warning=0.8>=1 so absolute;
        # use ammonia_n_mgL warning=0.8 = 80% of max=5.0.
        mon = monitoring_plan({"pH": 8.0})
        alarms = alarm_rules(mon, {"ammonia_n_mgL": 4.5})
        amm = [a for a in alarms if a["parameter"] == "ammonia_n_mgL"][0]
        assert amm["triggered"] is False
        assert amm["level"] == "warning"


# ------------------------------------------------------------------------- #
# treatment / sampling / permit
# ------------------------------------------------------------------------- #
class TestTreatment:
    def test_compare_ranked(self) -> None:
        res = compare_treatment_options(total_n_load_g=10.0, volume_l=100.0)
        assert res["ranked"][0]["composite_score"] >= res["ranked"][-1]["composite_score"]

    def test_high_residual_blocked(self) -> None:
        res = compare_treatment_options(total_n_load_g=10.0, volume_l=100.0,
                                        available_options=["dilution"])
        assert res["recommendation_blocked"] is True
        assert "HIGH" in res["reason"]

    def test_unknown_option(self) -> None:
        with pytest.raises(MbsError):
            compare_treatment_options(total_n_load_g=1.0, volume_l=1.0,
                                      available_options=["magic"])

    def test_sampling_plan(self) -> None:
        plan = sampling_plan({"groundwater_injection": True, "site_sensitive_ecology": True,
                              "release_type": "injection", "waste_stream_volume_l": 100})
        matrices = {s["matrix"] for s in plan["sampling_stations"]}
        assert "groundwater_down_gradient" in matrices
        assert plan["needs_authority_confirmation"] is True

    def test_permit_missing_gates(self) -> None:
        res = permit_status(permits=[], requested_actions=["groundwater_injection"])
        assert res["all_approved"] is False
        assert res["verdict"] == "HUMAN_APPROVAL_REQUIRED"

    def test_permit_granted(self) -> None:
        res = permit_status(
            permits=[{"action": "groundwater_injection", "granted": True}],
            requested_actions=["groundwater_injection"],
        )
        assert res["all_approved"] is True
        assert res["verdict"] == "APPROVED"
