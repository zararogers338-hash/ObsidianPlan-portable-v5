"""Unit tests for micp-hypothesis-forge: deterministic core logic."""

from __future__ import annotations

from tools.mhfx import models as M


class TestEpistemicLabels:
    def test_all_six_labels_legal(self):
        assert M.EPISTEMIC_LABELS == (
            "OBSERVED", "REPORTED", "CALCULATED", "INFERRED",
            "HYPOTHESIS", "RECOMMENDATION",
        )

    def test_validate_label_accepts_legal(self):
        for label in M.EPISTEMIC_LABELS:
            M.validate_label(label)  # must not raise

    def test_validate_label_rejects_unknown(self):
        from tools.mhfx.errors import MhfxError, MhfxErrorCode
        try:
            M.validate_label("FACT")
        except MhfxError as exc:
            assert exc.code is MhfxErrorCode.EPISTEMIC_MISLABEL
        else:
            raise AssertionError("expected MhfxError")


class TestFalsifiability:
    def test_falsifiable_statement(self):
        v = M.is_falsifiable(
            "High urease activity reduces strength",
            "If NH4+ exceeds 120 mM, UCS declines below baseline",
        )
        assert v["verdict"] == "FALSIFIABLE"
        assert v["falsifiable"] is True

    def test_non_falsifiable_empty_refutation(self):
        v = M.is_falsifiable("Urea plays a role", "")
        assert v["verdict"] == "NOT_FALSIFIABLE"
        assert v["falsifiable"] is False

    def test_vague_marker_is_partial(self):
        # Has an observable (NH4+) but hedged with vague language -> partial
        v = M.is_falsifiable("X affects Y", "urea probably raises NH4+ levels")
        assert v["verdict"] == "PARTIALLY_FALSIFIABLE"

    def test_non_falsifiable_phrase_rejected(self):
        # No observable quantity at all -> genuinely unfalsifiable
        v = M.is_falsifiable("Urea affects strength", "urea probably plays a role in strength")
        assert v["verdict"] == "NOT_FALSIFIABLE"
        assert v["falsifiable"] is False

    def test_no_direction_is_partial(self):
        v = M.is_falsifiable("X affects Y", "measure NH4+ concentration")
        assert v["verdict"] == "PARTIALLY_FALSIFIABLE"


class TestMechanismChains:
    def test_normalize_arrow_string(self):
        assert M.normalize_chain("A -> B -> C") == ["A", "B", "C"]

    def test_normalize_unicode_arrow(self):
        assert M.normalize_chain("A → B → C") == ["A", "B", "C"]

    def test_normalize_list(self):
        assert M.normalize_chain(["A", "B"]) == ["A", "B"]

    def test_chain_min_length(self):
        assert M.chain_min_length(["A", "B"], 2) is True
        assert M.chain_min_length(["A"], 2) is False


class TestDAG:
    def _nodes(self):
        return [
            {"id": "A", "depends_on": []},
            {"id": "B", "depends_on": ["A"]},
            {"id": "C", "depends_on": ["A", "B"]},
        ]

    def test_topo_sort_linear(self):
        assert M.topo_sort(self._nodes()) == ["A", "B", "C"]

    def test_topo_sort_cycle_detected(self):
        cyclic = [
            {"id": "A", "depends_on": ["C"]},
            {"id": "B", "depends_on": ["A"]},
            {"id": "C", "depends_on": ["B"]},
        ]
        import pytest as _pytest

        with _pytest.raises(ValueError):
            M.topo_sort(cyclic)

    def test_ancestors_transitive(self):
        nodes = self._nodes()
        assert M.ancestors(nodes, "C") == {"A", "B"}
        assert M.ancestors(nodes, "A") == set()

    def test_descendants_transitive(self):
        nodes = self._nodes()
        assert M.descendants(nodes, "A") == {"B", "C"}
        assert M.descendants(nodes, "C") == set()


class TestInfoGain:
    def test_perfect_test_gives_one_bit(self):
        # prior 0.5, sens 1.0, spec 1.0 -> EIG = 1 bit
        eig = M.expected_information_gain(0.5, 1.0, 1.0)
        assert abs(eig - 1.0) < 1e-9

    def test_useless_test_gives_zero(self):
        # sens = P(+|H) = 0.5 = P(+), spec = 0.5 -> no info
        eig = M.expected_information_gain(0.5, 0.5, 0.5)
        assert abs(eig - 0.0) < 1e-9

    def test_clamps_probabilities(self):
        # Out-of-range priors are clamped to [0,1] before the entropy math,
        # never crashed; EIG stays in [0,1].
        assert 0.0 <= M.expected_information_gain(2.0, 1.0, 1.0) <= 1.0
        assert 0.0 <= M.expected_information_gain(-1.0, 1.0, 1.0) <= 1.0
        assert 0.0 <= M.expected_information_gain(0.5, 0.9, 0.7) <= 1.0
        # And clamping to a degenerate prior (p=1.0) yields no possible gain.
        assert M.expected_information_gain(2.0, 1.0, 1.0) == 0.0

    def test_entropy_extremes(self):
        assert M.entropy(0.0) == 0.0
        assert M.entropy(1.0) == 0.0
        assert abs(M.entropy(0.5) - 1.0) < 1e-9


class TestUreolysisStoichiometry:
    def test_note_present(self):
        assert "2 mol NH4" in M.UREOLYSIS_STOICHIOMETRY_NOTE
        assert "CALCULATED" in M.UREOLYSIS_STOICHIOMETRY_NOTE
        assert "not OBSERVED" in M.UREOLYSIS_STOICHIOMETRY_NOTE
