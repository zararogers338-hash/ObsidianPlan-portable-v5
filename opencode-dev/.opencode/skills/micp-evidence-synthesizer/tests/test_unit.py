"""Unit tests: schema validation, unit mapping, effect computation,
meta-analysis, heterogeneity, conflict matrix, grade, over-generalization.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

from mes import (  # noqa: E402
    effect_compute, evidence_map, evidence_validate, grade_assess,
    heterogeneity_compute, jsonschema as _js, meta_analyze,
    result_check_overgeneralization, sensitivity_run, unit_map,
)

from conftest import load_schema, make_card, make_base_input  # noqa: E402


# --------------------------------------------------------------------------
# schema validation
# --------------------------------------------------------------------------

class TestSchema:
    def test_input_schema_accepts_valid(self):
        schema = load_schema("input.schema.json")
        assert _js.is_valid(make_base_input(), schema)

    def test_input_schema_rejects_missing_pico(self):
        schema = load_schema("input.schema.json")
        payload = make_base_input()
        del payload["pico"]
        assert not _js.is_valid(payload, schema)

    def test_input_schema_rejects_missing_cards(self):
        schema = load_schema("input.schema.json")
        payload = make_base_input()
        del payload["evidence_cards"]
        assert not _js.is_valid(payload, schema)

    def test_output_schema_accepts_full_envelope(self):
        schema = load_schema("output.schema.json")
        # minimal envelope with every required top-level key
        env = {
            "contract_version": "1.0", "skill": "micp-evidence-synthesizer",
            "skill_version": "1.0.0", "status": "BLOCKED", "summary": "s",
            "action": None, "project_id": None, "task_id": None,
            "findings": [], "assumptions": [], "evidence_used": [],
            "uncertainty": [], "risks": [], "artifacts": [],
            "requested_next_skills": [],
            "validation": {"input_schema": "failed", "output_schema": "pending",
                           "self_check": "not_run"},
            "provenance": {"started_at": None, "completed_at": None,
                           "skill_version": "1.0.0", "tool_versions": {},
                           "input_digest": None},
            "errors": [{"code": "OES-E101", "message": "m", "detail": {}, "retryable": False}],
        }
        assert _js.is_valid(env, schema)

    def test_jsonschema_pattern_and_minimum(self):
        schema = {"type": "object", "required": ["code"],
                  "properties": {"code": {"type": "string", "pattern": "^OES-E\\d{3}$"}}}
        assert not _js.is_valid({"code": "OES-X1"}, schema)
        schema2 = {"type": "object", "properties": {"n": {"type": "number", "minimum": 0}}}
        assert not _js.is_valid({"n": -1}, schema2)


# --------------------------------------------------------------------------
# unit mapping
# --------------------------------------------------------------------------

class TestUnitMap:
    def test_pa_family(self):
        q = unit_map.normalize(1.0, "MPa")
        assert q.normalized_value == pytest.approx(1e6)
        assert q.normalized_unit == "Pa"

    def test_preserves_raw(self):
        q = unit_map.normalize(2.5, "MPa")
        assert q.value == 2.5
        assert q.unit == "MPa"

    def test_temperature_offset(self):
        assert unit_map.convert(0, "C", "K") == pytest.approx(273.15)
        assert unit_map.convert(273.15, "K", "C") == pytest.approx(0)

    def test_density(self):
        assert unit_map.convert(1.0, "g/cm3", "kg/m3") == pytest.approx(1000.0)

    def test_unknown_unit_not_silently_converted(self):
        q = unit_map.normalize(10, "blorb")
        assert q.normalized_value is None
        assert q.normalized_unit is None

    def test_incomparable_units(self):
        assert not unit_map.comparable_unit("MPa", "%")
        assert unit_map.comparable_unit("kPa", "MPa")

    def test_nonfinite_raises(self):
        import pytest as pt
        with pt.raises(Exception):
            unit_map.normalize(float("nan"), "MPa")


# --------------------------------------------------------------------------
# evidence validation
# --------------------------------------------------------------------------

class TestEvidenceValidate:
    def test_valid_card_passes(self):
        res = evidence_validate.validate_cards([make_card()])
        assert res["ok"] is True

    def test_missing_ref_id_detected(self):
        card = make_card()
        del card["ref_id"]
        res = evidence_validate.validate_cards([card])
        assert res["ok"] is False
        assert any("ref_id" in p for p in res["problems"])

    def test_duplicate_ref_id_detected(self):
        a = make_card(ref_id="doi:10.1000/dup")
        b = make_card(ref_id="doi:10.1000/dup")
        res = evidence_validate.validate_cards([a, b])
        assert not res["ok"]
        assert any("duplicate ref_id" in p for p in res["problems"])

    def test_nonfinite_value_detected(self):
        card = make_card()
        card["outcome"]["value"] = float("nan")
        res = evidence_validate.validate_cards([card])
        assert not res["ok"]

    def test_empty_cards_raises(self):
        import pytest as pt
        from mes.errors import MesError
        with pt.raises(MesError):
            evidence_validate.validate_cards([])


# --------------------------------------------------------------------------
# effect computation
# --------------------------------------------------------------------------

class TestEffectCompute:
    def test_hedges_g_sign(self):
        arms = [{"name": "MICP", "n": 6, "mean": 3.2, "sd": 0.4, "unit": "MPa"},
                {"name": "control", "n": 6, "mean": 0.4, "sd": 0.1, "unit": "MPa"}]
        eff = effect_compute.compute_effect("c1", arms)
        assert eff is not None
        assert eff.effect_size > 0  # treatment better

    def test_single_arm_not_poolable(self):
        arms = [{"name": "MICP", "n": 6, "mean": 3.2, "sd": 0.4, "unit": "MPa"}]
        assert effect_compute.compute_effect("c1", arms) is None

    def test_incomparable_units_not_poolable(self):
        arms = [{"name": "A", "n": 6, "mean": 3.2, "sd": 0.4, "unit": "MPa"},
                {"name": "B", "n": 6, "mean": 40, "sd": 5, "unit": "%"}]
        assert effect_compute.compute_effect("c1", arms) is None

    def test_negative_sd_rejected(self):
        arms = [{"name": "A", "n": 6, "mean": 3.2, "sd": -0.4, "unit": "MPa"},
                {"name": "B", "n": 6, "mean": 0.4, "sd": 0.1, "unit": "MPa"}]
        import pytest as pt
        from mes.errors import MesError
        with pt.raises(MesError):
            effect_compute.compute_effect("c1", arms)


# --------------------------------------------------------------------------
# meta-analysis
# --------------------------------------------------------------------------

class TestMetaAnalyze:
    def _effects(self):
        return [
            {"ref_id": "a", "effect_size": 2.0, "variance": 0.4},
            {"ref_id": "b", "effect_size": 3.0, "variance": 0.6},
            {"ref_id": "c", "effect_size": 2.5, "variance": 0.5},
        ]

    def test_fixed_effect_pools(self):
        res = meta_analyze.meta_analyze(self._effects(), model="fixed_effect")
        assert res.pooled_effect is not None
        assert res.ci95[0] < res.pooled_effect < res.ci95[1]

    def test_random_effects_computes_tau2(self):
        res = meta_analyze.meta_analyze(self._effects(), model="random_effects")
        assert res.between_study_variance_tau2 is not None
        assert res.i2 is not None

    def test_requires_two_studies(self):
        import pytest as pt
        from mes.errors import MesError
        with pt.raises(MesError):
            meta_analyze.meta_analyze(self._effects()[:1], model="fixed_effect")

    def test_can_pool_ceiling(self):
        ok, reason = meta_analyze.can_pool(self._effects(), min_studies=2, i2_ceiling=75)
        assert ok is True
        # identical effects -> zero I2
        ident = [{"ref_id": "a", "effect_size": 2.0, "variance": 0.4},
                 {"ref_id": "b", "effect_size": 2.0, "variance": 0.5}]
        ok2, _ = meta_analyze.can_pool(ident, min_studies=2, i2_ceiling=75)
        assert ok2 is True


# --------------------------------------------------------------------------
# heterogeneity
# --------------------------------------------------------------------------

class TestHeterogeneity:
    def test_scale_divergence_detected(self):
        cards = [
            make_card(ref_id="doi:1", study_id="a",
                      context={"scale": "column"}),
            make_card(ref_id="doi:2", study_id="b",
                      context={"scale": "field"}),
        ]
        het = heterogeneity_compute.classify_heterogeneity(cards, meta=None)
        scale_type = next(t for t in het["types"] if t["type"] == "scale")
        assert scale_type["present"] is True

    def test_method_divergence_detected(self):
        cards = [
            make_card(ref_id="doi:1", study_id="a",
                      measurement={"method": "UCS", "endpoint_timing": "7 d"}),
            make_card(ref_id="doi:2", study_id="b",
                      measurement={"method": "split tensile", "endpoint_timing": "28 d"}),
        ]
        het = heterogeneity_compute.classify_heterogeneity(cards, meta=None)
        m = next(t for t in het["types"] if t["type"] == "methodological")
        assert m["present"] is True

    def test_comparability_statuses(self):
        # identical cards -> comparable
        comp = heterogeneity_compute.check_comparability([make_card(), make_card()])
        assert comp["status"] in ("comparable", "conditional")
        # unit mismatch -> incomparable
        cards = [
            make_card(ref_id="doi:1", study_id="a",
                      outcome={"name": "UCS", "value": 3.2, "unit": "MPa"}),
            make_card(ref_id="doi:2", study_id="b",
                      outcome={"name": "UCS", "value": 40, "unit": "%"}),
        ]
        comp2 = heterogeneity_compute.check_comparability(cards)
        assert comp2["status"] == "incomparable"


# --------------------------------------------------------------------------
# evidence + conflict matrix
# --------------------------------------------------------------------------

class TestEvidenceMap:
    def test_matrix_rows(self):
        cards = [make_card(ref_id="doi:1", study_id="a"),
                 make_card(ref_id="doi:2", study_id="b")]
        m = evidence_map.build_evidence_matrix(cards, pico_unit="MPa")
        assert len(m) == 2
        assert all(r["ref_id"] for r in m)

    def test_normalization_applied(self):
        card = make_card(ref_id="doi:1", outcome={"name": "UCS", "value": 3.2, "unit": "MPa"})
        m = evidence_map.build_evidence_matrix([card], pico_unit="kPa")
        assert m[0]["normalized_value"] == pytest.approx(3200.0)

    def test_conflict_detected_on_magnitude(self):
        a = make_card(ref_id="doi:1", study_id="a",
                      outcome={"name": "UCS", "value": 3.2, "unit": "MPa", "direction": "higher_is_better"})
        b = make_card(ref_id="doi:2", study_id="b",
                      outcome={"name": "UCS", "value": 0.4, "unit": "MPa", "direction": "higher_is_better"})
        conflicts = evidence_map.build_conflict_matrix([a, b])
        assert any(c["type"] == "magnitude" for c in conflicts)

    def test_conflict_direction_semantics(self):
        a = make_card(ref_id="doi:1", study_id="a",
                      outcome={"name": "UCS", "value": 3.2, "unit": "MPa", "direction": "higher_is_better"})
        b = make_card(ref_id="doi:2", study_id="b",
                      outcome={"name": "UCS", "value": 3.2, "unit": "MPa", "direction": "lower_is_better"})
        conflicts = evidence_map.build_conflict_matrix([a, b])
        assert any(c["type"] == "direction" for c in conflicts)


# --------------------------------------------------------------------------
# sensitivity
# --------------------------------------------------------------------------

class TestSensitivity:
    def test_leave_one_out(self):
        effects = [
            {"ref_id": "a", "effect_size": 2.0, "variance": 0.4},
            {"ref_id": "b", "effect_size": 3.0, "variance": 0.6},
            {"ref_id": "c", "effect_size": 2.5, "variance": 0.5},
        ]
        res = sensitivity_run.run_sensitivity(effects, model="random_effects")
        assert len(res["runs"]) >= 2
        assert all(r["pooled_effect"] is not None for r in res["runs"])


# --------------------------------------------------------------------------
# grade
# --------------------------------------------------------------------------

class TestGrade:
    def test_lab_experiments_start_high(self):
        cards = [make_card(ref_id="doi:1", study_id="a"),
                 make_card(ref_id="doi:2", study_id="b")]
        g = grade_assess.assess_grade(cards)
        assert g["certainty"] in ("high", "moderate", "low", "very_low")

    def test_high_rob_downgrades(self):
        cards = [make_card(ref_id="doi:1", study_id="a", risk_of_bias={"overall": "critical"}),
                 make_card(ref_id="doi:2", study_id="b", risk_of_bias={"overall": "critical"})]
        g = grade_assess.assess_grade(cards)
        assert g["certainty"] in ("low", "very_low")

    def test_review_study_baseline_low(self):
        cards = [make_card(ref_id="doi:1", study_id="a", study_type="review")]
        g = grade_assess.assess_grade(cards)
        assert g["certainty"] in ("low", "very_low")


# --------------------------------------------------------------------------
# over-generalization
# --------------------------------------------------------------------------

class TestOvergeneralization:
    def test_missing_counterexample_fails(self):
        conclusions = [{
            "id": "C01", "statement": "MICP increases UCS",
            "label": "INFERRED", "evidence_level": "moderate",
            "scope": "Ottawa sand", "counterexample": "", "open_questions": [],
        }]
        res = result_check_overgeneralization.check_conclusions(conclusions, ["doi:1"])
        assert res["passed"] is False

    def test_label_inflation_detected(self):
        conclusions = [{
            "id": "C01", "statement": "MICP is proven to increase UCS in all sands",
            "label": "HYPOTHESIS", "evidence_level": "low",
            "scope": "sands", "counterexample": "clayey soil", "open_questions": [],
        }]
        res = result_check_overgeneralization.check_conclusions(conclusions, ["doi:1"])
        assert res["passed"] is False
        assert any(c["name"].endswith("universal_claim") or c["name"].endswith("label_inflated")
                   for c in res["checks"])

    def test_well_scoped_conclusion_passes(self):
        conclusions = [{
            "id": "C01",
            "statement": "MICP treatment raised UCS for Ottawa sand under the reported protocol",
            "label": "INFERRED", "evidence_level": "moderate",
            "scope": "Ottawa sand, D50=0.4mm, 7d curing",
            "counterexample": "coarse gravel or fine silt may respond differently",
            "open_questions": ["strain transfer to field scale"],
        }]
        res = result_check_overgeneralization.check_conclusions(conclusions, ["doi:1"])
        assert res["passed"] is True


if __name__ == "__main__":  # pragma: no cover
    import pytest as _pt
    raise SystemExit(_pt.main([__file__]))
