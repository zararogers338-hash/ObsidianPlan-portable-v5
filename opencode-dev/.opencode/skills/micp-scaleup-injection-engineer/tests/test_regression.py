"""Regression tests for micp-scaleup-injection-engineer.

Verifies determinism, cross-action consistency and balance invariants that
must not regress.
"""

from __future__ import annotations

from conftest import make_payload, run

from msi import scenario as scen_mod
from msi.material import material_balance
from msi.service import ScaleUpService


class TestDeterminism:
    def test_identical_input_identical_output(self):
        p = make_payload()
        a = run(p)
        b = run(p)
        assert a["material_balance"]["caco3_required_kg"] == b["material_balance"]["caco3_required_kg"]
        assert a["material_balance"]["nh4_n_conc_mg_L"] == b["material_balance"]["nh4_n_conc_mg_L"]
        assert a["summary"] == b["summary"]

    def test_scaleup_consistent_with_subactions(self):
        """The full scaleup plan's material balance must match material_balance
        action and its pressure constraints must match boundary_check action."""
        p = make_payload()
        full = run(p)
        # material_balance action
        pm = make_payload()
        pm["action"] = "material_balance"
        mb = run(pm)
        assert (full["material_balance"]["caco3_required_kg"]
                == mb["material_balance"]["caco3_required_kg"])
        assert (full["material_balance"]["urea_mol"] == mb["material_balance"]["urea_mol"])
        # boundary_check action
        pb = make_payload()
        pb["action"] = "boundary_check"
        bc = run(pb)
        assert (full["pressure_constraints"]["verdict"] == bc["pressure_constraints"]["verdict"])

    def test_schedule_rounds_positive(self):
        p = make_payload()
        p["action"] = "injection_schedule"
        out = run(p)
        sched = out["injection_schedule"]
        assert sched["rounds"] >= 1
        assert sched["sequence"][0] in ("bacteria", "cementation")


class TestBalanceInvariants:
    def test_nh4_is_twice_urea(self):
        s = scen_mod.normalize_scenario(make_payload())
        mb = material_balance(s)
        # Environmental NH4-N is counted from injected urea (conservative):
        # 2 mol NH4-N per mol urea.
        assert abs(mb.nh4_n_mol - 2.0 * mb.urea_mol) < 1e-6

    def test_urea_ca_equal_stoichiometry(self):
        s = scen_mod.normalize_scenario(make_payload())
        mb = material_balance(s)
        assert abs(mb.urea_mol - mb.ca_mol) < 1e-6

    def test_cementation_volume_reasonable(self):
        s = scen_mod.normalize_scenario(make_payload())
        mb = material_balance(s)
        # urea_mol / 0.5 M = volume; must be finite and positive
        assert mb.cementation_volume_m3 > 0
        assert mb.cementation_volume_m3 < 1000.0


class TestOutputContract:
    def test_required_fields_present(self):
        out = run(make_payload())
        for f in ("status", "summary", "findings", "assumptions", "evidence_used",
                  "uncertainty", "risks", "artifacts", "requested_next_skills",
                  "validation", "provenance", "errors"):
            assert f in out, f"missing {f}"
        # §八 domain fields
        for f in ("scale_level", "site_assumptions", "similarity_matrix",
                  "non_scalable_factors", "injection_layout", "injection_schedule",
                  "material_balance", "pressure_constraints", "monitoring_plan",
                  "stop_conditions", "fallback_plan", "environmental_requirements"):
            assert f in out, f"missing domain field {f}"

    def test_epistemic_labels_valid(self):
        out = run(make_payload())
        for f in ("findings", "assumptions", "risks"):
            for item in out.get(f, []):
                assert item["label"] in (
                    "OBSERVED", "REPORTED", "CALCULATED", "INFERRED", "HYPOTHESIS",
                    "RECOMMENDATION")

    def test_service_never_raises(self):
        svc = ScaleUpService()
        for action in ("scaleup", "similarity", "material_balance", "boundary_check",
                       "pressure_risk", "injection_layout", "injection_schedule",
                       "monitoring_plan", "clogging_risk", "stage_gate", "validate",
                       "generate_tables", "tracer"):
            p = make_payload()
            p["action"] = action
            if action == "tracer":
                p["tracer"] = {"time_s": [0, 1, 2], "conc": [0, 1, 0.5], "injected_conc": 1.0}
            out = svc.handle(p)
            assert out["status"] in (
                "SUCCESS", "PARTIAL", "BLOCKED", "FAILED", "NEED_ADDITIONAL_SKILL",
                "HUMAN_APPROVAL_REQUIRED")
            assert isinstance(out["summary"], str)
