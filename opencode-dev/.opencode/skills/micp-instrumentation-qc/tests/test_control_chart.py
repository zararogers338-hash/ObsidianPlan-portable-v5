"""Unit tests for control_chart module."""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
import pytest
from control_chart import check_measurements, _consecutive_same_side, _monotonic_run


def _m(value, mid="m", sid="s1", ts="2026-08-01T10:00:00", qc=None):
    m = {"measurement_id": mid, "instrument_id": "pH-1", "sample_id": sid,
         "value": value, "unit": "pH", "timestamp": ts}
    if qc:
        m["qc"] = qc
    return m


def test_all_pass():
    measurements = [_m(7.0 + 0.05 * i, mid=f"m{i}") for i in range(5)]
    res = check_measurements({"measurements": measurements, "instruments": [
        {"instrument_id": "pH-1", "measurement_range": [0, 14], "saturation_threshold": 14.1}]})
    assert res["pass_count"] == 5
    assert res["out_of_control_count"] == 0
    assert res["pass_rate"] == 1.0


def test_out_of_control_detected():
    # Explicit QC criteria (mean=7.0, sd=0.1): 7.9 is an 9-sigma outlier.
    qc = {"mean": 7.0, "sd": 0.1}
    measurements = [_m(7.0, mid="m0", qc=qc), _m(7.1, mid="m1", qc=qc), _m(7.9, mid="m2", qc=qc),
                    _m(7.0, mid="m3", qc=qc), _m(7.05, mid="m4", qc=qc), _m(7.1, mid="m5", qc=qc)]
    res = check_measurements({"measurements": measurements, "instruments": [
        {"instrument_id": "pH-1", "measurement_range": [0, 14], "saturation_threshold": 14.1}]})
    flags = [f["flag"] for f in res["flags"]]
    assert "OUT_OF_CONTROL" in flags


def test_over_range_detected():
    measurements = [_m(15.0, mid="m0"), _m(7.0, mid="m1")]
    res = check_measurements({"measurements": measurements, "instruments": [
        {"instrument_id": "pH-1", "measurement_range": [0, 14], "saturation_threshold": 14.1}]})
    flags = [f["flag"] for f in res["flags"]]
    assert "OVER_RANGE" in flags


def test_saturation_detected():
    measurements = [_m(14.2, mid="m0"), _m(7.0, mid="m1")]
    res = check_measurements({"measurements": measurements, "instruments": [
        {"instrument_id": "pH-1", "measurement_range": [0, 14], "saturation_threshold": 14.0}]})
    flags = [f["flag"] for f in res["flags"]]
    assert "SATURATION" in flags


def test_drift_seven_same_side():
    values = [8.0, 8.1, 8.2, 8.3, 8.4, 8.5, 8.6]
    assert _consecutive_same_side(values, 7.0) is True
    values_ok = [7.0, 7.1, 7.0, 7.2, 7.0, 7.1, 7.0]
    assert _consecutive_same_side(values_ok, 7.0) is False


def test_drift_monotonic():
    values = [7.0, 7.2, 7.4, 7.6, 7.8, 8.0]
    assert _monotonic_run(values, run_len=6) is True


def test_timestamp_misalignment():
    measurements = [_m(7.0, mid="m0", ts="2026-08-01T11:00:00"),
                    _m(7.0, mid="m1", ts="2026-08-01T10:00:00")]
    res = check_measurements({"measurements": measurements})
    flags = [f["flag"] for f in res["flags"]]
    assert "TIMESTAMP_MISALIGNMENT" in flags


def test_rejects_no_measurements():
    with pytest.raises(ValueError):
        check_measurements({"measurements": []})


def test_rejects_non_finite_value():
    with pytest.raises(ValueError):
        check_measurements({"measurements": [_m(float("nan"))]})
