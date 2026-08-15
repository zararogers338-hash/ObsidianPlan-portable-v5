"""Regression tests: guard previously-fixed bugs so they never return."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

from micp.solver import SolverConfig, solve_transport  # noqa: E402

from conftest import SMOKE_SCENARIO, cli_call  # noqa: E402


def _cfg(**overrides) -> SolverConfig:
    defaults = dict(
        length=0.1, nx=32, porosity0=0.4, velocity=2.8e-5, dispersion=2.8e-7,
        k_ure=2e-3, k_pre=1e-3, k_half=0.5, c_ca_in=0.5, c_urea_in=0.5,
        k_perm0=1e-11, c_biomass=1.0, t_end=3600,
    )
    defaults.update(overrides)
    return SolverConfig(**defaults)


class TestRegression:
    def test_state_commits_each_step(self):
        """REGRESSION: concentrations used to stay at initial values (mass
        never moved). Now interior urea must fall and NH4+ must rise."""
        r = solve_transport(_cfg())
        prof = r.profiles[-1]
        assert prof.urea[-1] < prof.urea[0] - 1e-6
        assert prof.nh[-1] > 0

    def test_no_placeholder_state(self):
        """REGRESSION: the solver must not depend on a module-level previous-M
        placeholder (hidden global state)."""
        import micp.solver as s
        assert not hasattr(s, "_M_PREV")
        # and the mass-balance residual must be bounded on the smoke case
        r = solve_transport(_cfg())
        mb = r.mass_balance
        rel = abs(mb["urea_mass_balance_residual"]) / max(mb["urea_in_total"], 1e-12)
        assert rel < 0.05

    def test_dispersive_inflow_accounted(self):
        """REGRESSION: only advective inflow used to be counted, so urea
        consumption exceeded injection (mass created). The dispersive Fickian
        inflow at the Dirichlet inlet is now part of mass_urea_in."""
        r = solve_transport(_cfg())
        mb = r.mass_balance
        assert mb["urea_consumed"] <= mb["urea_in_total"] * 1.02  # within 2%

    def test_clogging_threshold_respected(self):
        r = solve_transport(_cfg(k_ure=0.1, k_pre=0.05, k_half=10.0,
                                 c_urea_in=500.0, c_ca_in=500.0, c_biomass=10.0,
                                 t_end=72000))
        assert r.summary["final_porosity_min"] < 0.02

    def test_output_schema_selfcheck_utility(self, base, smoke_scenario):
        """REGRESSION: selfcheck subcommand must accept a valid output file."""
        import subprocess
        import tempfile

        from conftest import SMOKE_PARAMS

        p_analyze = dict(base)
        p_analyze["action"] = "analyze"
        p_analyze["scenario"] = smoke_scenario
        p_analyze.update(SMOKE_PARAMS)
        out = cli_call(p_analyze)
        cli_path = Path(__file__).resolve().parent.parent / "tools" / "transport.py"
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            json.dump(out, f)
            path = f.name
        proc = subprocess.run([sys.executable, str(cli_path), "selfcheck", path],
                              capture_output=True, text=True)
        assert proc.returncode == 0, proc.stderr
        assert "OK" in proc.stdout
