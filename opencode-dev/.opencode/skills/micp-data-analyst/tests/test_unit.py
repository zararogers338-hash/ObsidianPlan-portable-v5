"""Unit tests for individual statistics and QC functions.

These test tool behavior directly (statistics math, outlier policies,
pseudo-replication detection, units) through the real CLI — not just that the
pipeline composes.
"""

from __future__ import annotations


from conftest import run_tool


def test_descriptive_matches_known_values() -> None:
    env = run_tool("stats", {"op": "descriptive", "values": [1, 2, 3, 4, 5]})
    d = env["result"]["descriptive"]
    assert d["n"] == 5
    assert d["mean"] == 3.0
    assert d["sd"] == 1.581139  # sample sd (ddof=1): sqrt(2.5)
    assert d["median"] == 3.0
    assert d["min"] == 1.0 and d["max"] == 5.0


def test_t_ci_known_value() -> None:
    # For [10,11,12,13,14]: mean=12, sd=1.581, se=0.707, t(0.975,4)=2.776,
    # half-width ~1.96 → 95% CI ≈ [10.04, 13.96]
    env = run_tool("stats", {"op": "ci", "values": [10, 11, 12, 13, 14]})
    ci = env["result"]["ci"]
    assert abs(ci["mean"] - 12.0) < 1e-6
    assert 10.0 < ci["ci_lower"] < 10.1
    assert 13.9 < ci["ci_upper"] < 14.0
    assert ci["ci_lower"] < ci["ci_upper"]


def test_cohens_d_sign_and_magnitude() -> None:
    env = run_tool("stats", {"op": "cohens_d", "a": [10, 11, 12, 13, 14],
                             "b": [5, 6, 7, 8, 9]})
    es = env["result"]["effect_size"]
    assert es["cohens_d"] > 0  # a > b
    assert es["magnitude"] == "large"
    assert es["ci_lower_95"] < es["ci_upper_95"]


def test_power_monotonic_in_n() -> None:
    small = run_tool("stats", {"op": "power", "n": 3, "d": 0.8})
    big = run_tool("stats", {"op": "power", "n": 30, "d": 0.8})
    assert big["result"]["power"]["power"] > small["result"]["power"]["power"]


def test_normality_n_below_8_is_not_certified() -> None:
    env = run_tool("stats", {"op": "normality", "values": [1, 2, 3, 4, 5, 6]})
    n = env["result"]["normality"]
    assert n["testable"] is False
    assert n["verdict"] == "insufficient_data"
    assert n["normal"] is None


def test_normality_screen_on_uniform_data() -> None:
    env = run_tool("stats", {"op": "normality", "values": list(range(1, 21))})
    n = env["result"]["normality"]
    assert n["testable"] is True
    # uniform data: significant departure or at least a runnable screen
    assert n["p_value"] is not None


def test_outlier_policies_flag_extreme_value() -> None:
    env = run_tool("stats", {"op": "outliers",
                             "values": [1.0, 1.1, 1.2, 1.3, 1.4, 1.5, 20.0]})
    o = env["result"]["outliers"]
    assert o["n_iqr_outliers"] >= 1
    assert 6 in o["flags_iqr_indices"]


def test_sensitivity_spread_positive() -> None:
    env = run_tool("stats", {"op": "sensitivity",
                             "values": [1.0, 1.1, 1.2, 1.3, 1.4, 1.5, 20.0],
                             "strategies": ["keep", "winsorize_1p5iqr", "trim_5pct"]})
    s = env["result"]["sensitivity"]
    assert set(s["estimates"]) >= {"keep", "winsorize_1p5iqr", "trim_5pct"}
    assert s["spread"] >= 0


def test_regression_slope_and_r2() -> None:
    x = [1.0, 2.0, 3.0, 4.0, 5.0]
    y = [2.0, 4.0, 6.0, 8.0, 10.0]
    env = run_tool("stats", {"op": "regression", "x": x, "y": y})
    r = env["result"]["regression"]
    assert abs(r["slope"] - 2.0) < 1e-6
    assert abs(r["r2"] - 1.0) < 1e-6
    # perfect fit → p ≈ 0 (or a finite tiny value, never 1.0)
    assert r["p_value"] is not None
    assert r["p_value"] < 1e-3


def test_anova_detects_group_difference() -> None:
    env = run_tool("stats", {"op": "anova",
                             "groups": [[1.0, 1.1, 1.2], [3.0, 3.1, 3.2]]})
    a = env["result"]["anova"]
    assert a["p_value"] < 0.05
    assert a["eta_squared"] > 0.5


def test_uniformity_uniform_vs_nonuniform() -> None:
    u = run_tool("stats", {"op": "uniformity", "values": [1.0, 1.01, 1.02, 1.03]})
    assert u["result"]["uniformity"]["recommendation"] == "uniform"
    nu = run_tool("stats", {"op": "uniformity", "values": [1.0, 10.0, 100.0]})
    assert nu["result"]["uniformity"]["recommendation"] == "non_uniform"


def test_repro_hash_deterministic() -> None:
    frames = {"a": [1, 2, 3], "b": {"x": 1.0}}
    h1 = run_tool("stats", {"op": "repro_hash", "frames": frames})
    h2 = run_tool("stats", {"op": "repro_hash", "frames": frames})
    assert h1["result"]["reproducibility"]["sha256"] == \
        h2["result"]["reproducibility"]["sha256"]
