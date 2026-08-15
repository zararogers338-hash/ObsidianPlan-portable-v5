"""Unit tests for micp-scaleup-injection-engineer core modules."""

from __future__ import annotations

import math

import pytest

from conftest import make_payload, run

from msi import scenario as scen_mod
from msi.errors import OpError, OpErrorCode
from msi.material import material_balance
from msi.models import M_CaCO3, M_N
from msi.pressure import boundary_check
from msi.similarity import build_similarity
from msi.units import parse_quantity, validate_parameter


class TestUnits:
    def test_parse_quantity_bare_number(self):
        assert parse_quantity(5.0).value == 5.0
        assert parse_quantity(5.0).unit == "-"

    def test_parse_quantity_object(self):
        q = parse_quantity({"value": 500, "unit": "mol/m3"})
        assert q.to_si() == 500.0

    def test_parse_quantity_molar_to_si(self):
        assert parse_quantity({"value": 0.5, "unit": "M"}).to_si() == 500.0

    def test_parse_quantity_mm_to_si(self):
        assert parse_quantity({"value": 50, "unit": "mm"}).to_si() == 0.05

    def test_parse_quantity_bad_unit_raises(self):
        with pytest.raises(OpError) as ei:
            parse_quantity({"value": 1, "unit": "furlong"})
        assert ei.value.code == OpErrorCode.UNIT_PARSE_ERROR

    def test_validate_parameter_range(self):
        with pytest.raises(OpError) as ei:
            validate_parameter("concentration", {"value": 1e9, "unit": "mol/m3"})
        assert ei.value.code == OpErrorCode.RANGE_OUT_OF_BOUNDS


class TestScenario:
    def test_normalize_requires_scale_level(self):
        p = make_payload()
        del p["target"]
        out = run(p)
        assert out["status"] == "BLOCKED"

    def test_normalize_site_requires_permeability(self):
        p = make_payload()
        p["target"]["scale_level"] = "site"
        p["site"]["layers"][0].pop("permeability")
        out = run(p)
        assert out["status"] == "BLOCKED"
        assert any(e["code"] == "MSI-E102" for e in out["errors"])
        names = [m["field"] for e in out["errors"]
                 for m in e.get("detail", {}).get("missing_fields", [])]
        assert any("permeability" in n for n in names)

    def test_pilot_allows_no_site_permeability(self):
        p = make_payload()
        p["site"] = {"layers": [{"name": "A", "thickness": {"value": 1.0, "unit": "m"},
                                 "porosity": 0.4}]}
        out = run(p)
        # pilot/metre scale does not gate on site permeability
        assert out["status"] in ("SUCCESS", "PARTIAL")

    def test_effective_porosity_thickness_weighted(self):
        s = scen_mod.normalize_scenario(make_payload())
        assert s.effective_porosity is not None
        assert abs(s.effective_porosity - 0.4) < 1e-9


class TestMaterialBalance:
    def test_stoichiometry(self):
        p = make_payload()
        s = scen_mod.normalize_scenario(p)
        mb = material_balance(s)
        # Environmental NH4-N is counted from INJECTED urea: 2 mol NH4-N per
        # mol urea (urea = caco3/eff). At eff=0.5, NH4/CaCO3 = 4.
        assert abs(mb.nh4_n_mol - 2.0 * mb.urea_mol) < 1e-6
        assert abs(mb.nh4_n_mol - 2.0 * mb.caco3_mol / 0.5) < 1e-6
        # urea = CaCO3 mol / conversion
        assert abs(mb.urea_mol - mb.caco3_mol / 0.5) < 1e-6

    def test_caco3_mass_from_content(self):
        p = make_payload()
        s = scen_mod.normalize_scenario(p)
        mb = material_balance(s)
        assert abs(mb.caco3_required_kg - 60.0 * 0.05) < 1e-9

    def test_nh4_conc_mgL(self):
        p = make_payload()
        s = scen_mod.normalize_scenario(p)
        mb = material_balance(s)
        # 60 mol urea (injected) -> 120 mol NH4-N in 0.02 m3 pore volume
        expected_mgL = (mb.nh4_n_mol / mb.pore_volume_m3) * M_N * 1e3
        assert abs(mb.nh4_n_conc_mg_L - expected_mgL) < 1e-6
        # conservative: exceeds the precipitate-tied amount
        assert mb.nh4_n_mol > mb.caco3_mol * 2.0

    def test_missing_volume_blocked(self):
        p = make_payload()
        del p["target"]["geometry"]["volume"]
        out = run(p)
        assert out["status"] in ("BLOCKED", "PARTIAL")


class TestBoundaryCheck:
    def test_constant_flux(self):
        p = make_payload()
        s = scen_mod.normalize_scenario(p)
        bc = boundary_check(s)
        assert bc.flow_mode == "constant_flux"
        assert bc.pressure_drop_pa is not None

    def test_high_flow_exceeds(self):
        p = make_payload()
        p["lab"]["recipe"]["flow_rate"] = {"value": 0.05, "unit": "m3/s"}
        s = scen_mod.normalize_scenario(p)
        bc = boundary_check(s)
        assert bc.verdict == "EXCEEDS"

    def test_constant_head_notes(self):
        p = make_payload()
        p["lab"]["recipe"]["flow_mode"] = "constant_head"
        s = scen_mod.normalize_scenario(p)
        bc = boundary_check(s)
        assert any("constant-head" in n for n in bc.notes)


class TestSimilarity:
    def test_non_scalable_factors(self):
        s = scen_mod.normalize_scenario(make_payload())
        sim = build_similarity(s)
        assert len(sim["non_scalable_factors"]) >= 5
        factors = {f["factor"] for f in sim["non_scalable_factors"]}
        assert "cementation concentration" in factors
        assert "uniformity" in factors

    def test_concentration_conserved_row(self):
        s = scen_mod.normalize_scenario(make_payload())
        sim = build_similarity(s)
        row = next(r for r in sim["rows"] if r["parameter"] == "urea concentration")
        assert row["scalable"] is False
        assert "CONSERVED" in row["scaling_rule"]


class TestContract:
    def test_contract_v2_blocked(self):
        p = make_payload()
        p["contract_version"] = "2.0"
        out = run(p)
        assert out["status"] == "BLOCKED"
        assert any(e["code"] == "MSI-E801" for e in out["errors"])

    def test_unknown_action_blocked(self):
        p = make_payload()
        p["action"] = "not.a.real.action"
        out = run(p)
        assert out["status"] == "BLOCKED"
        assert any(e["code"] == "MSI-E103" for e in out["errors"])

    def test_missing_required_field_blocked(self):
        p = make_payload()
        del p["timestamp"]
        out = run(p)
        assert out["status"] == "BLOCKED"
        assert any(e["code"] == "MSI-E101" for e in out["errors"])

    def test_output_schema_selfcheck(self):
        p = make_payload()
        out = run(p)
        assert out["validation"]["self_check"] == "passed"
