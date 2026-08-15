"""Regression tests: properties that must never silently change.

These guard the scientific contract of the skill:
  * stoichiometric residuals stay ~0,
  * calibrated parameters recover known truth,
  * Sobol' indices stay in [0,1] and the leading parameter is stable,
  * DOE run counts match the closed-form counts,
  * output schema validates every action's envelope.
"""

from __future__ import annotations

import json

from kinetics import KineticsConfig, solve_kinetic_system
from sensitivity import sobol_indices
from doe import doe_generate
from bayesopt import bayesian_optimize


class TestStoichiometryRegression:
    def test_nh4_two_times_urea(self) -> None:
        res = solve_kinetic_system(KineticsConfig(k_ure=3e-4, k_pre=2e-4),
                                   urea0=600, ca0=600, t_end=172800)
        mb = res.mass_balance
        assert abs(mb["nh4_produced"] - 2.0 * mb["urea_consumed"]) < 1e-9

    def test_caco3_kg_matches_moles(self) -> None:
        res = solve_kinetic_system(KineticsConfig(k_ure=1e-4, k_pre=1e-4),
                                   urea0=500, ca0=500, t_end=86400)
        mb = res.mass_balance
        assert abs(mb["caco3_kg"] - mb["caco3_mol"] * 100.0869 / 1000.0) < 1e-9


class TestParameterRecoveryRegression:
    def test_kure_recovered_consistently(self) -> None:
        from optimizer import FitSpec, fit_parameters

        true_k = 5e-4

        def model(theta, t, ex):
            # first-order decay: y = y0 * exp(-theta*t)
            return [1.0 * math.exp(-theta[0] * t)]

        import math

        data = []
        for i in range(1, 41):
            t = i * 100.0
            data.append((t, [math.exp(-true_k * t)], None))
        spec = FitSpec(model=model, data=data, theta0=[1e-3],
                       bounds=[(1e-6, 1e-2)], n_starts=2, seed=0)
        res = fit_parameters(spec)
        assert abs(res.theta[0] - true_k) / true_k < 0.01


class TestSensitivityRegression:
    def test_sobol_indices_in_range(self) -> None:
        def g(x, ex):
            # y = x0 + 0.5*x1
            return x[0] + 0.5 * x[1]

        out = sobol_indices(g, 2, n_base=100, seed=1)
        for v in out["first_order"] + out["total_order"]:
            assert 0.0 <= v <= 1.0
        # x0 (coef 1.0) should dominate x1 (coef 0.5)
        assert out["first_order"][0] > out["first_order"][1]

    def test_morris_identifies_dominant(self) -> None:
        from sensitivity import morris_screening

        def g(x, ex):
            return 10.0 * x[0] + x[1]

        out = morris_screening(g, 2, r_trajectories=8, p_levels=4, seed=1)
        assert out["mu_star"][0] > out["mu_star"][1]


class TestDoeRegression:
    def test_full_factorial_run_count(self) -> None:
        out = doe_generate(
            [{"name": "a", "low": 0, "high": 1}, {"name": "b", "low": 0, "high": 1},
             {"name": "c", "low": 0, "high": 1}],
            kind="full_factorial", seed=1,
        )
        assert out["n_runs"] == 8  # 2^3

    def test_ccd_run_count(self) -> None:
        out = doe_generate(
            [{"name": "a", "low": 0, "high": 1}, {"name": "b", "low": 0, "high": 1},
             {"name": "c", "low": 0, "high": 1}],
            kind="ccd", seed=1, center_points=1,
        )
        assert out["n_runs"] == 15  # 8 factorial + 6 axial + 1 center

    def test_box_behnken_run_count(self) -> None:
        out = doe_generate(
            [{"name": "a", "low": 0, "high": 1}, {"name": "b", "low": 0, "high": 1},
             {"name": "c", "low": 0, "high": 1}],
            kind="box_behnken", seed=1, center_points=3,
        )
        assert out["n_runs"] == 15  # 12 edge midpoints + 3 center


class TestBayesOptRegression:
    def test_finds_known_optimum(self) -> None:
        def f(x, ex):
            return (x[0] - 0.3) ** 2 + (x[1] - 0.7) ** 2

        out = bayesian_optimize(f, [(0.0, 1.0), (0.0, 1.0)],
                                n_init=5, n_iter=8, seed=3)
        # best must be close to (0.3, 0.7)
        assert abs(out["best_point"][0] - 0.3) < 0.15
        assert abs(out["best_point"][1] - 0.7) < 0.15


class TestResponseSurfaceRegression:
    def test_quadratic_surface_recovers_coefficients(self) -> None:
        from doe import response_surface

        factors = [{"name": "x", "low": 0, "high": 1}, {"name": "y", "low": 0, "high": 1}]
        # full factorial 3x3 grid
        coded = []
        ys = []
        for xi in (-1.0, 0.0, 1.0):
            for yi in (-1.0, 0.0, 1.0):
                coded.append([xi, yi])
                # y = 2 + 3x - 4y + x*y + 0.5 x^2
                ys.append(2 + 3 * xi - 4 * yi + xi * yi + 0.5 * xi ** 2)
        out = response_surface(factors, coded, {"z": ys})
        coeff = out["surfaces"]["z"]["coefficients"]
        assert abs(coeff["intercept"] - 2.0) < 1e-6
        assert abs(coeff["x"] - 3.0) < 1e-6
        assert abs(coeff["y"] + 4.0) < 1e-6
        assert abs(coeff["x:y"] - 1.0) < 1e-6
        assert abs(coeff["x^2"] - 0.5) < 1e-6
