"""Unit tests for calibration module."""

import math

import pytest

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
from calibration import compute, linear_regression, lod_loq, predict_uncertainty


def test_linear_regression_perfect_fit():
    xs = [1.0, 2.0, 3.0, 4.0, 5.0]
    ys = [2.0 * x + 1.0 for x in xs]
    fit = linear_regression(xs, ys)
    assert math.isclose(fit["slope"], 2.0, rel_tol=1e-9)
    assert math.isclose(fit["intercept"], 1.0, rel_tol=1e-9)
    assert fit["r2"] == 1.0


def test_lod_loq():
    lod, loq = lod_loq(2.0, 0.5)
    assert math.isclose(lod, 3.3 * 0.5 / 2.0)
    assert math.isclose(loq, 10.0 * 0.5 / 2.0)


def test_predict_uncertainty_positive():
    xs = [1.0, 2.0, 3.0, 4.0, 5.0]
    ys = [2.0 * x + 1.0 for x in xs]
    fit = linear_regression(xs, ys)
    u = predict_uncertainty(fit, xs, ys, 2.5, k=2.0)
    assert u["expanded_uncertainty"] >= 0
    assert math.isclose(u["x"], 0.75)  # (2.5 - intercept)/slope = (2.5-1)/2


def test_compute_perfect():
    data = {
        "calibration_id": "cal-1",
        "instrument_id": "pH-1",
        "method": "linear",
        "status": "passed",
        "standards": [
            {"concentration": 1.0, "response": 2.0},
            {"concentration": 2.0, "response": 4.0},
            {"concentration": 3.0, "response": 6.0},
        ],
    }
    res = compute(data)
    assert res["slope"] == pytest.approx(2.0)
    assert res["intercept"] == pytest.approx(0.0)
    assert res["r2"] == 1.0
    assert res["lod"] >= 0
    assert res["loq"] >= 0
    assert len(res["residuals"]) == 3


def test_compute_rejects_single_standard():
    data = {
        "calibration_id": "cal-2",
        "instrument_id": "pH-1",
        "method": "linear",
        "status": "passed",
        "standards": [{"concentration": 1.0, "response": 2.0}],
    }
    with pytest.raises(ValueError):
        compute(data)


def test_compute_rejects_unsupported_method():
    data = {
        "calibration_id": "cal-3",
        "instrument_id": "pH-1",
        "method": "quadratic",
        "status": "passed",
        "standards": [
            {"concentration": 1.0, "response": 2.0},
            {"concentration": 2.0, "response": 4.0},
        ],
    }
    with pytest.raises(ValueError):
        compute(data)


def test_compute_rejects_non_finite():
    data = {
        "calibration_id": "cal-4",
        "instrument_id": "pH-1",
        "method": "linear",
        "status": "passed",
        "standards": [
            {"concentration": 1.0, "response": float("nan")},
            {"concentration": 2.0, "response": 4.0},
        ],
    }
    with pytest.raises(ValueError):
        compute(data)


def test_compute_rejects_negative_concentration():
    data = {
        "calibration_id": "cal-5",
        "instrument_id": "pH-1",
        "method": "linear",
        "status": "passed",
        "standards": [
            {"concentration": -1.0, "response": 2.0},
            {"concentration": 2.0, "response": 4.0},
        ],
    }
    with pytest.raises(ValueError):
        compute(data)


def test_compute_collinear_standards():
    data = {
        "calibration_id": "cal-6",
        "instrument_id": "pH-1",
        "method": "linear",
        "status": "passed",
        "standards": [
            {"concentration": 1.0, "response": 2.0},
            {"concentration": 1.0, "response": 4.0},
        ],
    }
    with pytest.raises(ValueError):
        compute(data)
