"""Integration tests — drive the real CLI end to end."""

from __future__ import annotations

import json

from conftest import SMOKE_PARAMS, SMOKE_SCENARIO, cli_call


def _payload(base, action, **extra):
    p = dict(base)
    p["action"] = action
    p.update(extra)
    return p


def _analyze_payload(base, scenario, **extra):
    p = _payload(base, "analyze", scenario=scenario, **SMOKE_PARAMS)
    p.update(extra)
    return p


class TestAnalyze:
    def test_smoke_analyze_success(self, base, smoke_scenario):
        out = cli_call(_analyze_payload(base, smoke_scenario))
        assert out["status"] == "SUCCESS"
        assert out["skill"] == "micp-porous-media-transport"
        assert out["validation"]["self_check"] == "passed"
        kinds = {a["kind"] for a in out["artifacts"]}
        assert {"mass_balance", "profile", "dimensionless", "clogging_verdict"} <= kinds

    def test_conservation_checks_pass(self, base, smoke_scenario):
        out = cli_call(_analyze_payload(base, smoke_scenario))
        checks = {c["name"]: c["passed"] for c in out["validation"]["checks"]}
        assert checks["urea_mass_balance"] is True
        assert checks["ammonium_stoichiometry"] is True
        assert checks["caco3_mass_consistency"] is True

    def test_epistemic_labels_present(self, base, smoke_scenario):
        out = cli_call(_analyze_payload(base, smoke_scenario))
        assert all(f["label"] in ("OBSERVED", "REPORTED", "CALCULATED", "INFERRED",
                                  "HYPOTHESIS", "RECOMMENDATION") for f in out["findings"])
        assert out["provenance"]["host"]  # host recorded

    def test_high_rate_clogs(self, base):
        clog_scenario = {
            "geometry": {"length": {"value": 0.1, "unit": "m"}, "nx": 32},
            "porosity": {"value": 0.38, "unit": "-"},
            "permeability": {"value": 1e-11, "unit": "m2"},
            "flow": {"mode": "flux", "velocity": {"value": 2.8e-5, "unit": "m/s"}},
            "species": {"c_urea_in": {"value": 500, "unit": "mol/m3"},
                        "c_ca_in": {"value": 500, "unit": "mol/m3"},
                        "c_biomass": {"value": 10, "unit": "kg/m3"}},
        }
        out = cli_call(_analyze_payload(base, clog_scenario,
                                        k_ure=0.1, k_pre=0.05, k_half=10, t_end=72000))
        clog = next(a["note"] for a in out["artifacts"] if a["kind"] == "clogging_verdict")
        assert clog["clogged"] is True
        assert clog["rule_hit"] == "porosity"
        assert out["state"]["clogged"] is True

    def test_head_boundary_runs(self, base):
        head_scenario = {
            "geometry": {"length": {"value": 0.1, "unit": "m"}, "nx": 32},
            "porosity": {"value": 0.40, "unit": "-"},
            "permeability": {"value": 1e-11, "unit": "m2"},
            "flow": {"mode": "head", "p_in": {"value": 3000, "unit": "Pa"},
                     "p_out": {"value": 0, "unit": "Pa"}},
            "species": {"c_urea_in": {"value": 500, "unit": "mol/m3"},
                        "c_ca_in": {"value": 500, "unit": "mol/m3"},
                        "c_biomass": {"value": 10, "unit": "kg/m3"}},
        }
        out = cli_call(_analyze_payload(base, head_scenario,
                                        k_ure=0.1, k_pre=0.05, k_half=10, t_end=36000))
        assert out["status"] == "SUCCESS"
        # head BC must couple clogging to flow; still deterministic
        assert out["provenance"]["skill_version"] == "1.0.0"

    def test_flux_vs_head_differ(self, base):
        """The two BCs must produce measurably different precipitation mass."""
        flux = {
            "geometry": {"length": {"value": 0.1, "unit": "m"}, "nx": 32},
            "porosity": {"value": 0.40, "unit": "-"},
            "permeability": {"value": 1e-11, "unit": "m2"},
            "flow": {"mode": "flux", "velocity": {"value": 2.8e-5, "unit": "m/s"}},
            "species": {"c_urea_in": {"value": 500, "unit": "mol/m3"},
                        "c_ca_in": {"value": 500, "unit": "mol/m3"},
                        "c_biomass": {"value": 10, "unit": "kg/m3"}},
        }
        head = dict(flux)
        head["flow"] = {"mode": "head", "p_in": {"value": 3000, "unit": "Pa"},
                        "p_out": {"value": 0, "unit": "Pa"}}
        a = cli_call(_analyze_payload(base, flux, k_ure=0.1, k_pre=0.05, k_half=10, t_end=36000))
        b = cli_call(_analyze_payload(base, head, k_ure=0.1, k_pre=0.05, k_half=10, t_end=36000))
        ka = next(a["note"] for a in a["artifacts"] if a["kind"] == "mass_balance")
        kb = next(a["note"] for a in b["artifacts"] if a["kind"] == "mass_balance")
        assert ka["caco3_kg_precipitated"] != kb["caco3_kg_precipitated"]


class TestDimensionless:
    def test_dimensionless_action(self, base, smoke_scenario):
        out = cli_call(_payload(base, "dimensionless", scenario=smoke_scenario,
                                **SMOKE_PARAMS))
        note = next(a["note"] for a in out["artifacts"] if a["kind"] == "dimensionless")
        assert note["pe"] is not None
        assert note["da"] is not None
        assert note["transport_regime"] in ("advection_dominated", "dispersion_dominated")
        assert note["reaction_regime"] in ("reaction_dominated", "reaction_limited")


class TestValidate:
    def test_validate_action(self, base, smoke_scenario):
        out = cli_call(_payload(base, "validate", scenario=smoke_scenario))
        assert out["status"] == "SUCCESS"
        assert out["validation"]["input_schema"] == "passed"


class TestCloggingAction:
    def test_clogging_action(self, base):
        out = cli_call(_payload(base, "clogging",
                                profiles={"porosity": [0.4, 0.015, 0.3],
                                          "permeability": [1e-11, 1e-13, 1e-11],
                                          "permeability0": 1e-11}))
        clog = next(a["note"] for a in out["artifacts"] if a["kind"] == "clogging_verdict")
        assert clog["clogged"] is True


class TestDeterminism:
    def test_same_input_same_output(self, base, smoke_scenario):
        a = cli_call(_analyze_payload(base, smoke_scenario))
        b = cli_call(_analyze_payload(base, smoke_scenario))
        def core(out):
            return (out["summary"], out.get("state"),
                    next(a["note"] for a in out["artifacts"] if a["kind"] == "mass_balance"))
        assert core(a) == core(b)
