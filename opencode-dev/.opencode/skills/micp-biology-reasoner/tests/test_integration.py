"""Integration tests: drive the real CLI (stdin JSON -> stdout JSON)."""

from __future__ import annotations

import math

import pytest


class TestCompareAction:
    def test_same_od_diff_activity(self, base, invoke_cli):
        payload = dict(base)
        payload["action"] = "compare"
        payload["request"] = "compare two batches"
        payload["culture"] = {"od600": 1.2, "urease_activity": 5.0, "urease_activity_unit": "U/mL"}
        payload["baseline"] = {"culture": {"od600": 1.2, "urease_activity": 8.0, "urease_activity_unit": "U/mL"}}
        out = invoke_cli(payload)
        assert out["status"] == "SUCCESS"
        assert out["skill"] == "micp-biology-reasoner"
        assert out["validation"]["output_schema"] == "passed"
        assert out["validation"]["self_check"] == "passed"
        labels = {f["label"] for f in out["findings"]}
        assert "CALCULATED" in labels and "INFERRED" in labels
        assert out["errors"] == []

    def test_compare_activity_missing_unit_blocked(self, base, invoke_cli):
        payload = dict(base)
        payload["action"] = "compare"
        payload["culture"] = {"od600": 1.2, "urease_activity": 5.0}
        payload["baseline"] = {"culture": {"od600": 1.2, "urease_activity": 8.0, "urease_activity_unit": "U/mL"}}
        out = invoke_cli(payload)
        assert out["status"] == "FAILED"
        assert out["errors"][0]["code"] == "MBR-E203"

    def test_compare_missing_baseline_blocked(self, base, invoke_cli):
        payload = dict(base)
        payload["action"] = "compare"
        payload["culture"] = {"od600": 1.0}
        out = invoke_cli(payload)
        assert out["status"] == "FAILED"
        assert out["errors"][0]["code"] == "MBR-E102"


class TestAssessAction:
    def test_salinity_pasteurii(self, base, invoke_cli):
        payload = dict(base)
        payload["action"] = "assess"
        payload["culture"] = {"name": "Sporosarcina pasteurii"}
        payload["conditions"] = {"salinity": 35.0}
        out = invoke_cli(payload)
        assert out["status"] == "SUCCESS"
        labels = {f["label"] for f in out["findings"]}
        assert "REPORTED" in labels

    def test_salinity_unknown_strain_insufficient(self, base, invoke_cli):
        payload = dict(base)
        payload["action"] = "assess"
        payload["culture"] = {"name": "Bacillus sp. NBS-7"}
        payload["conditions"] = {"salinity": 60.0}
        out = invoke_cli(payload)
        assert out["status"] == "SUCCESS"
        labels = {f["label"] for f in out["findings"]}
        assert "HYPOTHESIS" in labels and "RECOMMENDATION" in labels

    def test_treatment_strategy(self, base, invoke_cli):
        payload = dict(base)
        payload["action"] = "assess"
        payload["treatment"] = "biostimulation"
        payload["context"] = {"soil_organic_carbon": 0.2}
        out = invoke_cli(payload)
        assert out["status"] == "SUCCESS"
        assert any("indigenous" in f["statement"] for f in out["findings"])

    def test_assess_neither_blocked(self, base, invoke_cli):
        payload = dict(base)
        payload["action"] = "assess"
        out = invoke_cli(payload)
        assert out["status"] == "FAILED"
        assert out["errors"][0]["code"] == "MBR-E102"


class TestConvertAction:
    def test_activity_normalization(self, base, invoke_cli):
        payload = dict(base)
        payload["action"] = "convert"
        payload["culture"] = {"urease_activity": 120.0, "urease_activity_unit": "mmol/L/h"}
        payload["metric_query"] = {"kind": "activity_normalization"}
        out = invoke_cli(payload)
        assert out["status"] == "SUCCESS"
        assert any("2 U/mL" in f["statement"] for f in out["findings"])  # 120/60

    def test_specific_activity(self, base, invoke_cli):
        payload = dict(base)
        payload["action"] = "convert"
        payload["culture"] = {"urease_activity": 5.0, "urease_activity_unit": "U/mL"}
        payload["metric_query"] = {
            "kind": "activity_normalization",
            "denominator": {"value": 1.25, "kind": "od600"},
        }
        out = invoke_cli(payload)
        assert out["status"] == "SUCCESS"
        assert any("4 U/mL/OD600" in f["statement"] for f in out["findings"])

    def test_cell_concentration_without_calibration(self, base, invoke_cli):
        payload = dict(base)
        payload["action"] = "convert"
        payload["culture"] = {"od600": 1.0}
        payload["metric_query"] = {"kind": "cell_concentration"}
        out = invoke_cli(payload)
        assert out["status"] == "FAILED"
        assert out["errors"][0]["code"] == "MBR-E203"


class TestEvaluateAction:
    def test_retention_rate(self, base, invoke_cli):
        payload = dict(base)
        payload["action"] = "evaluate"
        payload["metric_query"] = {"kind": "retention_rate"}
        t = [0.0, 1.0, 2.0, 4.0]
        payload["attachments"] = {"retention": {
            "time_points_h": t,
            "retained_fraction": [math.exp(-0.3 * ti) for ti in t],
        }}
        out = invoke_cli(payload)
        assert out["status"] == "SUCCESS"
        note = out["artifacts"][0]["note"]
        assert note["k_per_h"] == pytest.approx(0.3, rel=0.05)

    def test_sensitivity(self, base, invoke_cli):
        payload = dict(base)
        payload["action"] = "evaluate"
        payload["metric_query"] = {
            "kind": "sensitivity",
            "sensitivity": {"parameter": "k", "base_value": 0.5, "range_pct": 10.0},
        }
        out = invoke_cli(payload)
        assert out["status"] == "SUCCESS"
        assert any("elasticity" in f["statement"].lower() for f in out["findings"])

    def test_mass_balance(self, base, invoke_cli):
        payload = dict(base)
        payload["action"] = "evaluate"
        payload["metric_query"] = {"kind": "urease_mass_balance", "urea_consumed_mM": 50.0}
        out = invoke_cli(payload)
        assert out["status"] == "SUCCESS"
        assert any("100 mM NH4+" in f["statement"] for f in out["findings"])
