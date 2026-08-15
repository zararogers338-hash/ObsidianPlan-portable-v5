"""Unit tests for the numerical cores: kinetics, ODE, sensitivity, DOE,
Bayesian optimization, multi-objective, UQ, checks, model-spec, reporting."""

from __future__ import annotations

import json
import math

import pytest

from kinetics import (
    KineticsConfig,
    permeability_ratio,
    porosity_from_calcite,
    precipitation_rate,
    solve_kinetic_system,
    ureolysis_rate,
)
from checks import check_conservation, check_grid_step_sensitivity, check_numerical_stability
from modelspec import validate_model_spec
from errors import MmoError, MmoErrorCode


class TestKinetics:
    def test_ureolysis_zero_at_zero(self) -> None:
        cfg = KineticsConfig()
        assert ureolysis_rate(0.0, cfg) == 0.0

    def test_ureolysis_michaelis_menten(self) -> None:
        cfg = KineticsConfig(k_ure=1e-4, c_biomass=1.0, k_half=305.0)
        r = ureolysis_rate(305.0, cfg)
        assert r == pytest.approx(0.5 * 1e-4)  # U/(K+U) = 1/2 at U=K

    def test_first_order_is_linear_in_urea(self) -> None:
        cfg = KineticsConfig(k_ure=2e-4, ureolysis="first_order")
        assert ureolysis_rate(10, cfg) == pytest.approx(2e-3)
        assert ureolysis_rate(5, cfg) == pytest.approx(1e-3)

    def test_precipitation_limiting_reactant(self) -> None:
        cfg = KineticsConfig(k_pre=3e-4)
        assert precipitation_rate(10, 5, cfg) == pytest.approx(1.5e-3)
        assert precipitation_rate(5, 10, cfg) == pytest.approx(1.5e-3)

    def test_solver_conserves_urea(self) -> None:
        res = solve_kinetic_system(KineticsConfig(k_ure=1e-4, k_pre=1e-4),
                                   urea0=500, ca0=500, t_end=86400)
        mb = res.mass_balance
        assert abs(mb["urea_mass_balance_residual"]) < 1e-6
        assert abs(mb["urea_to_nh4_residual"]) < 1e-9

    def test_solver_deterministic(self) -> None:
        cfg = KineticsConfig(k_ure=1e-4, k_pre=1e-4)
        a = solve_kinetic_system(cfg, urea0=500, ca0=500, t_end=86400)
        b = solve_kinetic_system(cfg, urea0=500, ca0=500, t_end=86400)
        assert a.calcite_kg == b.calcite_kg

    def test_porosity_from_calcite(self) -> None:
        assert porosity_from_calcite(0.4, 0.0) == pytest.approx(0.4)
        assert porosity_from_calcite(0.4, 2711.0) < 0.4
        assert porosity_from_calcite(0.4, 1e9) == 1e-6  # clamped

    def test_permeability_kozeny_carman(self) -> None:
        cfg = KineticsConfig(porosity_permeability="kozeny_carman")
        assert permeability_ratio(0.4, 0.4, cfg) == pytest.approx(1.0)
        r = permeability_ratio(0.2, 0.4, cfg)
        assert 0 < r < 1

    def test_permeability_verma_pruess_below_crit(self) -> None:
        cfg = KineticsConfig(porosity_permeability="verma_pruess", phi_crit=0.108)
        assert permeability_ratio(0.05, 0.4, cfg) == 0.0


class TestModelSpecValidation:
    def test_complete_spec_valid(self) -> None:
        spec = {
            "purpose": "EXPLANATION",
            "state_variables": ["urea"],
            "parameters": [{"name": "k", "role": "fixed", "unit": "1/s"}],
            "equations": "dU/dt = -kU",
            "initial_conditions": {"urea0": 1},
            "observations": ["urea"],
            "error_model": "additive_gaussian",
            "space_scale": "lab_column",
            "time_scale": "days",
        }
        out = validate_model_spec(spec)
        assert out["purpose"] == "EXPLANATION"

    def test_missing_purpose_blocked(self) -> None:
        spec = {
            "state_variables": ["urea"],
            "parameters": [{"name": "k", "role": "fixed", "unit": "1/s"}],
            "equations": "dU/dt = -kU",
            "initial_conditions": {"urea0": 1},
            "observations": ["urea"],
            "error_model": "additive_gaussian",
            "space_scale": "lab_column",
            "time_scale": "days",
        }
        with pytest.raises(MmoError) as ei:
            validate_model_spec(spec)
        assert ei.value.ecode == MmoErrorCode.MISSING_REQUIRED_FIELD

    def test_spatial_requires_boundary(self) -> None:
        spec = {
            "purpose": "PREDICTION",
            "model_kind": "reactive_transport",
            "state_variables": ["urea"],
            "parameters": [{"name": "k", "role": "fixed", "unit": "1/s"}],
            "equations": {"kind": "reactive_transport"},
            "initial_conditions": {"urea0": 1},
            "observations": ["urea"],
            "error_model": "additive_gaussian",
            "space_scale": "lab_column",
            "time_scale": "days",
        }
        with pytest.raises(MmoError) as ei:
            validate_model_spec(spec)
        assert "boundary_conditions" in {m["field"] for m in ei.value.details["missing_fields"]}

    def test_bad_purpose_rejected(self) -> None:
        spec = {
            "purpose": "GUESSING",
            "state_variables": ["urea"],
            "parameters": [],
            "equations": "x",
            "initial_conditions": {},
            "observations": [],
            "error_model": "x",
            "space_scale": "x",
            "time_scale": "x",
        }
        with pytest.raises(MmoError) as ei:
            validate_model_spec(spec)
        assert ei.value.ecode == MmoErrorCode.INVALID_MODEL_SPEC


class TestChecks:
    def test_conservation_ok(self) -> None:
        mb = {
            "urea_in_total": 100, "urea_consumed": 60, "urea_remaining": 40, "urea_out_approx": 0,
            "ca_in_total": 100, "ca_consumed": 60, "ca_remaining": 40, "ca_out_approx": 0,
            "nh4_produced": 120, "carbonate_produced": 60,
            "caco3_mol": 60, "caco3_kg": 60 * 100.0869 / 1000.0,
        }
        res = check_conservation(mb)
        assert res["ok"] is True

    def test_conservation_fails(self) -> None:
        mb = {
            "urea_in_total": 100, "urea_consumed": 10, "urea_remaining": 10, "urea_out_approx": 0,
            "ca_in_total": 100, "ca_consumed": 10, "ca_remaining": 90, "ca_out_approx": 0,
            "nh4_produced": 20, "carbonate_produced": 10,
            "caco3_mol": 10, "caco3_kg": 1.0,
        }
        res = check_conservation(mb)
        assert res["ok"] is False

    def test_numerical_stability_rejects_nan(self) -> None:
        res = check_numerical_stability({"porosity": [0.4, float("nan")], "urea": [1, 2]})
        assert res["ok"] is False

    def test_grid_sensitivity(self) -> None:
        def run(cfg):
            return cfg.get("nx", 32) * 1.0

        out = check_grid_step_sensitivity(run, {"nx": 32, "dt": 1.0})
        # nx=32 vs nx=128 drift = 4x -> must fail
        assert out["ok"] is False


class TestReporting:
    def test_kinetics_html(self) -> None:
        from reporting import kinetics_time_series_html

        html = kinetics_time_series_html({
            "times": [0, 1, 2], "urea": [5, 4, 3], "ca": [5, 4, 3],
            "nh4": [0, 2, 4], "calcite_kg": [0, 0.1, 0.2], "phi": [0.4, 0.39, 0.38],
        })
        assert "<svg" in html and "</svg>" in html

    def test_pareto_html(self) -> None:
        from reporting import pareto_front_html

        html = pareto_front_html(
            [{"x": [1], "objectives": [0.0, 1.0]}, {"x": [2], "objectives": [1.0, 0.0]}],
            ["obj1", "obj2"],
        )
        assert "<svg" in html
