"""Unit tests for the micp tools (no subprocess; direct imports)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

from micp import clogging, dimensionless, scenario, units  # noqa: E402
from micp.errors import OpError, OpErrorCode  # noqa: E402
from micp.solver import SolverConfig, kozeny_carman, rate_ure, solve_transport  # noqa: E402


# ---------------------------------------------------------------------------
# units / quantity
# ---------------------------------------------------------------------------

class TestUnits:
    def test_parse_bare_number_is_dimensionless(self):
        q = units.parse_quantity(3.5)
        assert q.unit == "-"
        assert q.to_si() == 3.5

    def test_parse_quantity_with_unit(self):
        q = units.parse_quantity({"value": 10, "unit": "cm"})
        assert q.to_si() == pytest.approx(0.1)

    def test_unknown_unit_raises_opm_e203(self):
        with pytest.raises(OpError) as ei:
            units.parse_quantity({"value": 1, "unit": "furlong"})
        assert ei.value.code == OpErrorCode.UNIT_PARSE_ERROR

    def test_non_finite_raises_opm_e301(self):
        with pytest.raises(OpError) as ei:
            units.check_finite("x", float("nan"))
        assert ei.value.code == OpErrorCode.CONTEXT_CORRUPT

    def test_validate_parameter_range(self):
        with pytest.raises(OpError) as ei:
            units.validate_parameter("porosity", {"value": 1.5, "unit": "-"})
        assert ei.value.code == OpErrorCode.RANGE_OUT_OF_BOUNDS

    def test_validate_parameter_wrong_unit_family(self):
        with pytest.raises(OpError) as ei:
            units.validate_parameter("velocity", {"value": 1, "unit": "m2/s"})
        assert ei.value.code == OpErrorCode.UNIT_INCONSISTENT

    def test_safe_project_id_rejects_path_traversal(self):
        with pytest.raises(OpError):
            units.safe_project_id("../etc/passwd")


# ---------------------------------------------------------------------------
# dimensionless
# ---------------------------------------------------------------------------

class TestDimensionless:
    def test_pe_da_classification(self):
        nums = dimensionless.dimensionless_numbers(
            velocity=1e-3, length=0.1, dispersion=1e-5,
            reaction_rate=1e-2, c0=1.0)
        assert nums["transport_regime"] == "advection_dominated"  # Pe=10
        assert nums["reaction_regime"] == "reaction_dominated"    # Da=100

    def test_dispersion_dominated(self):
        nums = dimensionless.dimensionless_numbers(
            velocity=1e-3, length=0.1, dispersion=1.0,
            reaction_rate=1e-6, c0=1.0)
        assert nums["transport_regime"] == "dispersion_dominated"  # Pe=1e-4

    def test_reaction_limited(self):
        nums = dimensionless.dimensionless_numbers(
            velocity=1e-3, length=0.1, dispersion=1e-5,
            reaction_rate=1e-8, c0=1.0)
        assert nums["reaction_regime"] == "reaction_limited"  # Da=1e-4

    def test_zero_velocity_handled(self):
        nums = dimensionless.dimensionless_numbers(
            velocity=0.0, length=0.1, dispersion=1e-5,
            reaction_rate=1e-6, c0=1.0)
        assert nums["da"] is None  # inf -> None


# ---------------------------------------------------------------------------
# solver
# ---------------------------------------------------------------------------

def _cfg(**overrides) -> SolverConfig:
    defaults = dict(
        length=0.1, nx=32, porosity0=0.4, velocity=2.8e-5, dispersion=2.8e-7,
        k_ure=2e-3, k_pre=1e-3, k_half=0.5, c_ca_in=0.5, c_urea_in=0.5,
        k_perm0=1e-11, c_biomass=1.0, t_end=3600,
    )
    defaults.update(overrides)
    return SolverConfig(**defaults)


class TestSolver:
    def test_runs_and_commits_state(self):
        r = solve_transport(_cfg())
        prof = r.profiles[-1]
        assert r.converged
        assert len(prof.urea) == 32
        # inlet holds influent, interior reacted, outlet low
        assert prof.urea[0] == pytest.approx(0.5, abs=1e-6)
        assert prof.urea[-1] < 0.5
        assert prof.ca[-1] <= prof.ca[0]

    def test_kozeny_carman_monotonic(self):
        k1 = kozeny_carman(0.30, 0.40, 1e-11)
        k2 = kozeny_carman(0.20, 0.40, 1e-11)
        assert k2 < k1
        assert k1 < 1e-11  # porosity drop reduces K

    def test_mm_rate_form(self):
        r = rate_ure(0.5, 2e-3, 0.5, 1.0)
        assert 0 < r <= 2e-3  # k*B*U/(K+U) <= k*B
        assert rate_ure(0.0, 2e-3, 0.5, 1.0) == 0.0

    def test_high_rate_clogs_inlet(self):
        r = solve_transport(_cfg(
            k_ure=0.1, k_pre=0.05, k_half=10.0,
            c_urea_in=500.0, c_ca_in=500.0, c_biomass=10.0, t_end=72000,
        ))
        assert r.clogged
        assert r.reason == "clogged"
        assert r.summary["final_porosity_min"] < 0.02

    def test_conservation_small_residual(self):
        r = solve_transport(_cfg())
        mb = r.mass_balance
        urea_in = mb["urea_in_total"]
        out = urea_in - mb["urea_consumed"] - mb["urea_remaining"] - mb["urea_out_approx"]
        assert abs(out) / max(abs(urea_in), 1e-12) < 0.05

    def test_stoichiometry_exact(self):
        r = solve_transport(_cfg())
        mb = r.mass_balance
        assert abs(mb["nh_produced"] - 2.0 * mb["urea_consumed"]) < 1e-9 * max(mb["urea_consumed"], 1.0)

    def test_deterministic(self):
        a = solve_transport(_cfg())
        b = solve_transport(_cfg())
        assert a.mass_balance == b.mass_balance

    def test_invalid_nx(self):
        with pytest.raises(OpError):
            solve_transport(_cfg(nx=4))


# ---------------------------------------------------------------------------
# clogging
# ---------------------------------------------------------------------------

class TestClogging:
    def test_porosity_rule(self):
        c = clogging.ClogCriteria(porosity_min=0.02)
        v = c.evaluate([0.4, 0.015, 0.3], [1e-11, 1e-13, 1e-11], 1e-11)
        assert v["clogged"]
        assert v["rule_hit"] == "porosity"

    def test_permeability_rule(self):
        c = clogging.ClogCriteria(permeability_ratio=1e-2)
        v = c.evaluate([0.4, 0.35, 0.3], [1e-11, 1e-14, 1e-11], 1e-11)
        assert v["clogged"]
        assert v["rule_hit"] == "permeability"

    def test_no_clog(self):
        c = clogging.ClogCriteria()
        v = c.evaluate([0.4, 0.35], [1e-11, 1e-11], 1e-11)
        assert not v["clogged"]

    def test_near_zero_porosity_warns(self):
        c = clogging.ClogCriteria()
        v = c.evaluate([0.04, 0.4], [1e-12, 1e-11], 1e-11)
        assert v["warnings"]

    def test_bad_criteria(self):
        with pytest.raises(OpError):
            clogging.ClogCriteria(porosity_min=0.0)


# ---------------------------------------------------------------------------
# scenario normalization
# ---------------------------------------------------------------------------

class TestScenario:
    def test_normalize_smoke(self):
        norm = scenario.normalize_scenario({
            "geometry": {"length": {"value": 0.1, "unit": "m"}, "nx": 32},
            "porosity": {"value": 0.4, "unit": "-"},
            "permeability": {"value": 1e-11, "unit": "m2"},
            "flow": {"mode": "flux", "velocity": {"value": 2.8e-5, "unit": "m/s"}},
            "species": {"c_urea_in": {"value": 0.5, "unit": "mol/m3"},
                        "c_ca_in": {"value": 0.5, "unit": "mol/m3"}},
        })
        assert norm.porosity == pytest.approx(0.4)
        assert norm.geometry["length_m"] == pytest.approx(0.1)
        assert norm.flow_mode == "flux"

    def test_missing_porosity_blocked(self):
        with pytest.raises(OpError) as ei:
            scenario.normalize_scenario({
                "geometry": {"length": {"value": 0.1, "unit": "m"}, "nx": 32},
                "permeability": {"value": 1e-11, "unit": "m2"},
                "flow": {"mode": "flux", "velocity": {"value": 2.8e-5, "unit": "m/s"}},
            })
        assert ei.value.code == OpErrorCode.MISSING_REQUIRED_FIELD
        fields = {m["field"] for m in ei.value.detail["missing_fields"]}
        assert "porosity" in fields

    def test_missing_flow_blocked(self):
        with pytest.raises(OpError) as ei:
            scenario.normalize_scenario({
                "geometry": {"length": {"value": 0.1, "unit": "m"}, "nx": 32},
                "porosity": {"value": 0.4, "unit": "-"},
                "permeability": {"value": 1e-11, "unit": "m2"},
            })
        assert ei.value.code == OpErrorCode.MISSING_REQUIRED_FIELD

    def test_head_mode_requires_pressure(self):
        with pytest.raises(OpError):
            scenario.normalize_scenario({
                "geometry": {"length": {"value": 0.1, "unit": "m"}, "nx": 32},
                "porosity": {"value": 0.4, "unit": "-"},
                "permeability": {"value": 1e-11, "unit": "m2"},
                "flow": {"mode": "head"},
            })
