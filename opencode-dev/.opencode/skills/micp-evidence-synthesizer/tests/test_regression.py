"""Regression tests: known-good behaviors that must not break across refactors
(e.g. unit normalization, pooling guards, epistemic label discipline, the four
bootstrap scenarios from SKILL.md §自举测试).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

from mes import (  # noqa: E402
    effect_compute, evidence_map, evidence_validate, grade_assess,
    heterogeneity_compute, meta_analyze, result_check_overgeneralization,
    sensitivity_run, unit_map,
)
from mes.service import MesService  # noqa: E402

from conftest import make_base_input, make_card  # noqa: E402


@pytest.fixture(scope="module")
def service():
    return MesService(skill_root=str(ROOT))


class TestUnitNormalizationRegression:
    def test_kpa_to_mpa(self):
        assert unit_map.convert(1000, "kPa", "MPa") == pytest.approx(1.0)

    def test_mpa_to_kpa_preserves_original(self):
        q = unit_map.normalize(2.0, "MPa", target_unit="kPa")
        assert q.value == 2.0
        assert q.unit == "MPa"
        assert q.normalized_value == pytest.approx(2000.0)


class TestEffectRegression:
    def test_two_arms_positive_treatment(self):
        arms = [{"name": "MICP", "n": 8, "mean": 4.0, "sd": 0.5, "unit": "MPa"},
                {"name": "control", "n": 8, "mean": 0.5, "sd": 0.2, "unit": "MPa"}]
        eff = effect_compute.compute_effect("r1", arms)
        assert eff is not None
        assert eff.effect_size > 1.0


class TestMetaRegression:
    def test_identical_effects_zero_i2(self):
        effects = [
            {"ref_id": "a", "effect_size": 2.5, "variance": 0.3},
            {"ref_id": "b", "effect_size": 2.5, "variance": 0.4},
        ]
        res = meta_analyze.meta_analyze(effects, model="random_effects")
        assert res.i2 == pytest.approx(0.0, abs=1e-6)
        assert res.pooled_effect == pytest.approx(2.5, abs=0.05)


class TestSensitivityRegression:
    def test_remove_high_bias_changes_pool(self, service):
        """Removing a high-bias outlier must move the pooled effect
        (measured directly on the sensitivity tool with controlled effects,
        so the test does not depend on whether the 3-card pool is admissible)."""
        effects = [
            {"ref_id": "a", "effect_size": 2.0, "variance": 0.4},
            {"ref_id": "b", "effect_size": 2.2, "variance": 0.5},
            {"ref_id": "outlier", "effect_size": 8.0, "variance": 0.6},
        ]
        res = sensitivity_run.run_sensitivity(effects, model="random_effects",
                                              remove_one="outlier")
        assert res["runs"]
        loo = [r for r in res["runs"] if r["name"].startswith("leave-one-out")]
        assert loo, "leave-one-out runs missing"
        deltas = [r["delta"] for r in loo if r["delta"] is not None]
        assert any(abs(d) > 0.01 for d in deltas), "LOO should move the pooled effect"

        high = [r for r in res["runs"] if r["name"] == "exclude-high-bias:outlier"]
        assert high, "explicit high-bias exclusion run missing"
        assert high[0]["pooled_effect"] is not None


class TestEvidenceMatrixRegression:
    def test_matrix_has_all_rows(self, service):
        cards = [
            make_card(ref_id="doi:10.1000/a", study_id="a"),
            make_card(ref_id="doi:10.1000/b", study_id="b"),
        ]
        out = service.handle(make_base_input(evidence_cards=cards))
        assert len(out["synthesis"]["evidence_matrix"]) == 2
        assert {r["ref_id"] for r in out["synthesis"]["evidence_matrix"]} == {"doi:10.1000/a", "doi:10.1000/b"}


class TestEpistemicDisciplineRegression:
    def test_no_observed_without_source(self, service):
        """OBSERVED claims must carry a source; synthesized conclusions never
        upgrade card claims to OBSERVED."""
        a = make_card(ref_id="doi:10.1000/a", study_id="a",
                      claims=[{"statement": "x", "label": "OBSERVED"}])
        out = service.handle(make_base_input(evidence_cards=[a]))
        for f in out["findings"]:
            if f["label"] == "OBSERVED":
                assert f.get("source"), "OBSERVED finding missing source"

    def test_grade_never_overclaims(self, service):
        cards = [make_card(ref_id="doi:10.1000/a", study_id="a", study_type="review"),
                 make_card(ref_id="doi:10.1000/b", study_id="b", study_type="case_series")]
        out = service.handle(make_base_input(evidence_cards=cards))
        assert out["synthesis"]["grade"]["certainty"] in ("low", "very_low")
