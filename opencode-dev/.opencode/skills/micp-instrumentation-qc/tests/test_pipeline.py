"""Unit tests for qc_pipeline module (orchestration + hard gates)."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
import pytest
from qc_pipeline import build_qc_report, run


def _qc_input(**kw):
    base = {
        "instruments": [{"instrument_id": "pH-1", "kind": "pH", "model": "Mettler S220",
                         "measurement_range": [0, 14], "saturation_threshold": 14.0}],
        "calibrations": [{"calibration_id": "cal-1", "instrument_id": "pH-1", "method": "linear",
                          "status": "passed",
                          "standards": [{"concentration": 4.0, "response": -170.0},
                                        {"concentration": 7.0, "response": 0.0},
                                        {"concentration": 10.0, "response": 177.0}]}],
        "measurements": [{"measurement_id": "m0", "instrument_id": "pH-1", "sample_id": "s1",
                          "value": 7.02, "unit": "pH", "timestamp": "2026-08-01T10:00:00"}],
        "samples": [{"sample_id": "s1", "collection_time": "2026-08-01T09:00:00"}],
    }
    base.update(kw)
    return base


def test_full_report_passes():
    r = build_qc_report(_qc_input(), "qc_report")
    assert r["overall_passed"] is True
    assert r["calibration"]["r2"] > 0.999
    assert r["control"]["pass_count"] == 1
    assert r["sample_chain"]["duplicate_ids"] == []
    assert r["retest_items"] == []
    assert r["analysis_restrictions"] == []


def test_mixed_units_blocked():
    qc = _qc_input()
    qc["calibrations"][0]["standards"][0]["unit"] = "M"
    qc["calibrations"][0]["standards"][1]["unit"] = "mM"
    r = build_qc_report(qc, "qc_report")
    codes = [e["code"] for e in r["errors"]]
    assert "MICQ-E1003" in codes
    assert r["overall_passed"] is False


def test_unresolvable_data_ref_blocked():
    qc = _qc_input()
    qc["data_refs"] = ["/nonexistent/file.csv"]
    r = build_qc_report(qc, "qc_report")
    codes = [e["code"] for e in r["errors"]]
    assert "MICQ-E1002" in codes


def test_bad_calibration_fails_report():
    qc = _qc_input()
    qc["calibrations"][0]["standards"] = [{"concentration": 1.0, "response": 2.0}]
    r = build_qc_report(qc, "qc_report")
    assert r["overall_passed"] is False
    assert r["calibration"]["status"] == "failed"


def test_duplicate_sample_ids_block():
    qc = _qc_input()
    qc["samples"] = [{"sample_id": "s1", "collection_time": "2026-08-01T09:00:00"},
                     {"sample_id": "s1", "collection_time": "2026-08-01T09:00:00"}]
    r = build_qc_report(qc, "qc_report")
    assert r["overall_passed"] is False
    assert "duplicate sample IDs" in "; ".join(r["analysis_restrictions"])


def test_out_of_control_blocks():
    qc = _qc_input()
    qc["measurements"].append({"measurement_id": "m1", "instrument_id": "pH-1", "sample_id": "s1",
                               "value": 13.9, "unit": "pH", "timestamp": "2026-08-01T10:01:00",
                               "qc": {"mean": 7.0, "sd": 0.1}})
    r = build_qc_report(qc, "qc_report")
    assert r["overall_passed"] is False
    assert r["retest_items"] == ["s1"]


def test_plan_format_no_measurements_ok():
    r = build_qc_report({"instruments": [{"instrument_id": "pH-1", "kind": "pH", "model": "x"}]}, "qc_plan")
    assert r["report_type"] == "qc_plan"
