"""Unit tests: pure functions in the tool package (no CLI)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

from micp_bio.errors import MbrError, MbrErrorCode  # noqa: E402
from micp_bio.units import (  # noqa: E402
    activity_to_u_per_ml,
    cell_concentration_from_od,
    specific_urease_activity,
)
from micp_bio.analysis import (  # noqa: E402
    analyze_contradictory_data,
    compare_batches,
    salinity_assessment,
    urease_yield_urea_to_ammonia,
)
from micp_bio.kinetics import fit_first_order_decay, fit_logistic_growth, sensitivity_elasticity  # noqa: E402


# --------------------------------------------------------------------------
# units
# --------------------------------------------------------------------------

class TestActivityToUPerMl:
    def test_identity(self):
        r = activity_to_u_per_ml(5.0, "U/mL")
        assert r["u_per_ml"] == 5.0
        assert r["converted"] is False

    def test_mm_urea_per_min_equiv(self):
        # 1 mM urea/min == 1 U/mL
        r = activity_to_u_per_ml(3.0, "mM urea/min")
        assert r["u_per_ml"] == pytest.approx(3.0)
        assert r["converted"] is True

    def test_mmol_per_h(self):
        # 1 mmol/L/h == 1/60 U/mL
        r = activity_to_u_per_ml(60.0, "mmol/L/h")
        assert r["u_per_ml"] == pytest.approx(1.0)

    def test_missing_unit_raises_203(self):
        with pytest.raises(MbrError) as e:
            activity_to_u_per_ml(5.0, None)
        assert e.value.code == MbrErrorCode.UNIT_INCONSISTENT

    def test_od_as_unit_raises_204(self):
        with pytest.raises(MbrError) as e:
            activity_to_u_per_ml(5.0, "OD600")
        assert e.value.code == MbrErrorCode.OD_NOT_ACTIVITY

    def test_unsupported_unit_raises_203(self):
        with pytest.raises(MbrError) as e:
            activity_to_u_per_ml(5.0, "furlongs/fortnight")
        assert e.value.code == MbrErrorCode.UNIT_INCONSISTENT

    def test_nan_rejected_302(self):
        with pytest.raises(MbrError) as e:
            activity_to_u_per_ml(float("nan"), "U/mL")
        assert e.value.code == MbrErrorCode.NUMERIC_INVALID


class TestSpecificActivity:
    def test_od_denominator(self):
        r = specific_urease_activity(5.0, "U/mL", 1.25, "od600")
        assert r["specific"] == pytest.approx(4.0)  # 5 / 1.25
        assert r["unit"] == "U/mL/OD600"

    def test_cdw_denominator_1000x(self):
        # A U/mL ÷ (g/L CDW) = 1000·A/g CDW
        r = specific_urease_activity(5.0, "U/mL", 2.0, "cdw_g_per_l")
        assert r["specific"] == pytest.approx(2500.0)  # 5*1000/2

    def test_zero_denominator_302(self):
        with pytest.raises(MbrError) as e:
            specific_urease_activity(5.0, "U/mL", 0.0, "od600")
        assert e.value.code == MbrErrorCode.NUMERIC_INVALID


class TestCellConcentration:
    def test_requires_calibration(self):
        with pytest.raises(MbrError) as e:
            cell_concentration_from_od(1.0)
        assert e.value.code == MbrErrorCode.UNIT_INCONSISTENT

    def test_calibrated(self):
        r = cell_concentration_from_od(1.0, calibration={"slope": 1e8, "intercept": 0})
        assert r["cfu_per_ml"] == pytest.approx(1e8)

    def test_negative_od_302(self):
        with pytest.raises(MbrError) as e:
            cell_concentration_from_od(-0.5, calibration={"slope": 1e8})
        assert e.value.code == MbrErrorCode.NUMERIC_INVALID


# --------------------------------------------------------------------------
# analysis
# --------------------------------------------------------------------------

class TestCompareBatches:
    def test_same_od_diff_activity(self):
        r = compare_batches(
            {"od600": 1.2, "urease_activity": 5.0, "urease_activity_unit": "U/mL"},
            {"od600": 1.2, "urease_activity": 8.0, "urease_activity_unit": "U/mL"},
        )
        assert r["same_od600"] is True
        assert r["activity_identical"] is False
        assert r["activity_ratio_a_over_b"] == pytest.approx(5.0 / 8.0)
        assert "non-constitutive" in r["conclusion"]

    def test_same_od_same_activity(self):
        r = compare_batches(
            {"od600": 0.8, "urease_activity": 3.0, "urease_activity_unit": "U/mL"},
            {"od600": 0.8, "urease_activity": 3.0, "urease_activity_unit": "U/mL"},
        )
        assert r["activity_identical"] is True

    def test_activity_missing_unit(self):
        with pytest.raises(MbrError) as e:
            compare_batches(
                {"od600": 1.0, "urease_activity": 5.0},
                {"od600": 1.0, "urease_activity": 6.0, "urease_activity_unit": "U/mL"},
            )
        assert e.value.code == MbrErrorCode.UNIT_INCONSISTENT


class TestAnalyzeContradictory:
    def test_flags_od_claiming_activity(self):
        r = analyze_contradictory_data([
            {"metric": "od600", "value": 1.2, "unit": "", "claim": "high activity"},
        ])
        assert any("conflates biomass with activity" in f["statement"] for f in r["findings"])

    def test_flags_od_claiming_activity_chinese(self):
        # 自举测试 4 发现的缺口：中文"酶活"声称也必须被识别
        r = analyze_contradictory_data([
            {"metric": "od600", "value": 1.5, "unit": "", "claim": "OD600 高所以酶活高"},
            {"metric": "od600", "value": 1.0, "unit": "", "claim": "OD600 低"},
        ])
        assert any("conflates biomass with activity" in f["statement"] for f in r["findings"])

    def test_flags_activity_without_unit(self):
        r = analyze_contradictory_data([
            {"metric": "urease_activity", "value": 8.0, "unit": None},
        ])
        assert any("lacks a unit" in f["statement"] for f in r["findings"])

    def test_clean_records(self):
        r = analyze_contradictory_data([
            {"metric": "od600", "value": 1.2, "unit": "", "claim": "biomass 1.2"},
            {"metric": "urease_activity", "value": 8.0, "unit": "U/mL", "claim": "activity 8 U/mL"},
        ])
        assert r["metrics_seen"] == ["od600", "urease_activity"]
        assert any("No metric-conflation" in f["statement"] for f in r["findings"])


class TestSalinityAssessment:
    def test_observed_only_with_data(self):
        r = salinity_assessment("S. pasteurii", salinity=35.0, observed_evidence=True)
        assert r["evidence_label"] == "OBSERVED"

    def test_reported_for_pasteurii(self):
        r = salinity_assessment("Sporosarcina pasteurii", salinity=35.0)
        assert r["evidence_label"] == "REPORTED"
        assert r["insufficient_evidence"] is False

    def test_hypothesis_for_unknown(self):
        r = salinity_assessment("Bacillus sp. X", salinity=60.0)
        assert r["evidence_label"] == "HYPOTHESIS"
        assert r["insufficient_evidence"] is True

    def test_missing_salinity_raises(self):
        with pytest.raises(MbrError) as e:
            salinity_assessment("X", salinity=None)
        assert e.value.code == MbrErrorCode.INPUT_SCHEMA_VIOLATION


class TestMassBalance:
    def test_1_2_stoichiometry(self):
        r = urease_yield_urea_to_ammonia(100.0)
        assert r["ammonium_produced_mM"] == 200.0

    def test_negative_urea(self):
        with pytest.raises(MbrError) as e:
            urease_yield_urea_to_ammonia(-1.0)
        assert e.value.code == MbrErrorCode.NUMERIC_INVALID


# --------------------------------------------------------------------------
# kinetics
# --------------------------------------------------------------------------

class TestFirstOrderDecay:
    def test_exact_fit(self):
        import math

        t = [0.0, 1.0, 2.0, 4.0]
        k = 0.5
        y = [1.0 * math.exp(-k * ti) for ti in t]
        r = fit_first_order_decay(t, y, y_name="value")
        assert r["k_per_h"] == pytest.approx(k, rel=0.05)
        assert r["halflife_h"] == pytest.approx(math.log(2.0) / k, rel=0.05)
        assert r["r2"] > 0.99

    def test_needs_two_points(self):
        with pytest.raises(MbrError) as e:
            fit_first_order_decay([0.0], [1.0], y_name="value")
        assert e.value.code == MbrErrorCode.INPUT_SCHEMA_VIOLATION

    def test_unpaired(self):
        with pytest.raises(MbrError) as e:
            fit_first_order_decay([0.0, 1.0, 2.0], [1.0, 0.5], y_name="value")
        assert e.value.code == MbrErrorCode.INPUT_SCHEMA_VIOLATION

    def test_negative_value_302(self):
        with pytest.raises(MbrError) as e:
            fit_first_order_decay([0.0, 1.0], [1.0, -0.2], y_name="value")
        assert e.value.code == MbrErrorCode.NUMERIC_INVALID


class TestLogisticGrowth:
    def test_exact_fit(self):
        import math

        t = [0.0, 1.0, 2.0, 3.0, 5.0, 8.0]
        K, r, N0 = 3.0, 0.8, 0.1
        n = [K / (1 + (K / N0 - 1) * math.exp(-r * ti)) for ti in t]
        res = fit_logistic_growth(t, n)
        assert res["K"] == pytest.approx(K, rel=0.05)
        assert res["r_per_h"] == pytest.approx(r, rel=0.05)
        assert res["doubling_h"] == pytest.approx(math.log(2.0) / r, rel=0.05)


class TestSensitivityElasticity:
    def test_linear_model_elasticity_one(self):
        res = sensitivity_elasticity(lambda p: 2.0 * p, parameter=5.0, delta_pct=10.0)
        assert res["elasticity"] == pytest.approx(1.0, abs=1e-6)

    def test_power_model(self):
        # f = p^2  => elasticity 2
        res = sensitivity_elasticity(lambda p: p**2, parameter=3.0, delta_pct=5.0)
        assert res["elasticity"] == pytest.approx(2.0, abs=1e-4)

    def test_zero_param_rejected(self):
        with pytest.raises(MbrError) as e:
            sensitivity_elasticity(lambda p: p, parameter=0.0, delta_pct=5.0)
        assert e.value.code == MbrErrorCode.NUMERIC_INVALID
