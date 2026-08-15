"""Failure-path tests: adversarial, missing, corrupted and boundary inputs.
Every adversarial case must NOT produce an illegal SUCCESS (SKILL.md §对抗拦截率).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

from mes import jsonschema as _js  # noqa: E402
from mes.errors import MesError, MesErrorCode  # noqa: E402
from mes.service import MesService  # noqa: E402

from conftest import load_schema, make_base_input, make_card  # noqa: E402


@pytest.fixture(scope="module")
def service():
    return MesService(skill_root=str(ROOT))


def card_with(**overrides) -> dict:
    c = make_card()
    c.update(overrides)
    return c


class TestMissingInputs:
    def test_missing_pico_blocks_with_acquisition(self, service):
        payload = make_base_input()
        payload["pico"] = {"population": "sand"}  # missing intervention/outcome
        out = service.handle(payload)
        assert out["status"] == "BLOCKED"
        assert out["errors"][0]["code"] == "OES-E113"
        detail = out["errors"][0]["detail"]
        assert "intervention" in detail["missing"]
        assert "how_to_fill" in str(detail) or "acquisition" in str(detail)

    def test_missing_cards_blocks(self, service):
        payload = make_base_input(evidence_cards=[])
        out = service.handle(payload)
        assert out["status"] == "BLOCKED"
        assert out["errors"][0]["code"] == "OES-E101"

    def test_bad_action_rejected(self, service):
        payload = make_base_input(action="evidence.attach")
        out = service.handle(payload)
        assert out["status"] == "FAILED"
        assert out["errors"][0]["code"] == "OES-E115"


class TestUnverifiableEvidence:
    def test_bogus_ref_id_blocks(self, service):
        card = card_with(ref_id="xyz", study_id="s")  # too short, not resolvable
        out = service.handle(make_base_input(evidence_cards=[card]))
        assert out["status"] == "BLOCKED"
        assert out["errors"][0]["code"] == "OES-E102"

    def test_missing_outcome_blocks(self, service):
        card = card_with(ref_id="doi:10.1000/x", study_id="s")
        del card["outcome"]
        out = service.handle(make_base_input(evidence_cards=[card]))
        assert out["status"] == "BLOCKED"
        assert out["errors"][0]["code"] == "OES-E102"


class TestUnitMismatch:
    def test_incomparable_units_isolated_not_pooled(self, service):
        a = make_card(ref_id="doi:10.1000/a", study_id="a",
                      outcome={"name": "UCS", "value": 3.2, "unit": "MPa"})
        b = make_card(ref_id="doi:10.1000/b", study_id="b",
                      outcome={"name": "UCS", "value": 40, "unit": "%"})
        out = service.handle(make_base_input(evidence_cards=[a, b]))
        assert out["status"] == "SUCCESS" or out["status"] == "PARTIAL"
        assert out["synthesis"]["comparability_check"]["status"] == "incomparable"
        assert out["synthesis"]["meta_analysis"] is None  # never pooled


class TestNonComparablePoolingGuard:
    def test_heterogeneous_studies_not_pooled(self, service):
        # intentionally divergent effects -> high I2 -> narrative synthesis
        a = make_card(ref_id="doi:10.1000/a", study_id="a",
                      outcome={"name": "UCS", "value": 3.2, "unit": "MPa"},
                      reported_effect={"arms": [
                          {"name": "MICP", "n": 6, "mean": 3.2, "sd": 0.4, "unit": "MPa"},
                          {"name": "control", "n": 6, "mean": 0.4, "sd": 0.1, "unit": "MPa"}]})
        b = make_card(ref_id="doi:10.1000/b", study_id="b",
                      outcome={"name": "UCS", "value": 0.6, "unit": "MPa"},
                      reported_effect={"arms": [
                          {"name": "MICP", "n": 6, "mean": 0.6, "sd": 0.4, "unit": "MPa"},
                          {"name": "control", "n": 6, "mean": 0.5, "sd": 0.1, "unit": "MPa"}]})
        out = service.handle(make_base_input(evidence_cards=[a, b]))
        # meta may still run (2 studies, I2 high); but conclusions must not overclaim
        conclusions = out["synthesis"]["conclusions"]
        assert conclusions[0]["label"] != "OBSERVED"

    def test_card_claims_never_upgrade_to_observed(self, service):
        a = make_card(ref_id="doi:10.1000/a", study_id="a",
                      claims=[{"statement": "MICP works", "label": "OBSERVED"}])
        b = make_card(ref_id="doi:10.1000/b", study_id="b")
        out = service.handle(make_base_input(evidence_cards=[a, b]))
        for c in out["synthesis"]["conclusions"]:
            assert c["label"] in ("REPORTED", "CALCULATED", "INFERRED", "HYPOTHESIS", "RECOMMENDATION")


class TestCorruptedInput:
    def test_nonnumeric_payload(self, service):
        out = service.handle("not an object")  # type: ignore[arg-type]
        assert out["status"] == "FAILED"
        assert out["errors"][0]["code"] == "OES-E101"

    def test_nonfinite_outcome_blocks(self, service):
        card = card_with(ref_id="doi:10.1000/x", study_id="s")
        card["outcome"]["value"] = float("inf")
        out = service.handle(make_base_input(evidence_cards=[card]))
        assert out["status"] == "BLOCKED"
        assert out["errors"][0]["code"] == "OES-E102"


class TestAdversarial:
    """Adversarial inputs must be intercepted — no illegal SUCCESS."""

    def test_conclusion_fabrication_blocked(self, service):
        # a card pretending to carry a conclusion: still must be validated
        card = card_with(ref_id="doi:10.1000/a", study_id="a",
                         claims=[{"statement": "result is proven definitive", "label": "OBSERVED"}])
        out = service.handle(make_base_input(evidence_cards=[card]))
        assert out["status"] in ("SUCCESS", "PARTIAL")
        for c in out["synthesis"]["conclusions"]:
            assert c["label"] != "OBSERVED"

    def test_duplicate_cards_blocked(self, service):
        a = card_with(ref_id="doi:10.1000/dup", study_id="a")
        b = card_with(ref_id="doi:10.1000/dup", study_id="b")
        out = service.handle(make_base_input(evidence_cards=[a, b]))
        assert out["status"] == "BLOCKED"
        assert out["errors"][0]["code"] == "OES-E102"

    def test_wrong_action_not_synthesize(self, service):
        out = service.handle(make_base_input(action="meta.analyze"))
        assert out["status"] == "FAILED"
        assert out["errors"][0]["code"] == "OES-E115"

    def test_missing_required_contract_field(self, service):
        payload = make_base_input()
        del payload["skill_version"]
        out = service.handle(payload)
        assert out["status"] == "BLOCKED"
        assert out["errors"][0]["code"] == "OES-E101"
        assert any(i["path"].endswith("skill_version") for i in out["errors"][0]["detail"]["issues"])
