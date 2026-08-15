"""Unit tests: pure modules (normalize, conflicts, store events, models)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from conftest import TOOLS_DIR

import sys

sys.path.insert(0, str(TOOLS_DIR))

from kg import store as kstore
from kg.errors import KgeError, KgeErrorCode
from kg.models import EvidenceTier, EpistemicLabel
from kg.normalize import (MINERAL_CANONICAL, STRAIN_CANONICAL, check_quantity,
                          lookup_synonyms, normalize_name, normalize_unit,
                          to_base, units_compatible)


# ---------------------------------------------------------------------------
# normalize: synonyms / units
# ---------------------------------------------------------------------------
class TestNormalizeNames:
    def test_strain_former_name_maps_to_canonical(self):
        assert normalize_name("Bacillus pasteurii") == "Sporosarcina pasteurii"
        assert normalize_name("bacillus pasteurii dsm 33") == "Sporosarcina pasteurii"

    def test_abbreviation_maps_to_canonical(self):
        assert normalize_name("s. pasteurii") == "Sporosarcina pasteurii"
        assert normalize_name("b. megaterium") == "Bacillus megaterium"

    def test_unknown_passes_through_unchanged(self):
        raw = "Halobacillus halophilus"
        assert normalize_name(raw) == raw  # never a guess

    def test_lookup_synonyms_returns_alias_set(self):
        syns = lookup_synonyms("bacillus pasteurii")
        assert "sporosarcina pasteurii" in syns
        assert "b. pasteurii" in syns

    def test_mineral_abbreviation(self):
        assert normalize_name("ACC") == "amorphous calcium carbonate (ACC)"
        assert MINERAL_CANONICAL["caco3-calcite"] == "calcite"


class TestUnits:
    def test_units_compatible(self):
        assert units_compatible("MPa", "kPa")
        assert units_compatible("mol/L", "mmol/L")
        assert not units_compatible("MPa", "m/s")

    def test_unknown_dimension_only_exact_comparable(self):
        assert units_compatible("foo", "foo")
        assert not units_compatible("foo", "bar")

    def test_to_base_temperature_offset(self):
        v, u = to_base(25.0, "degC")
        assert u == "K" and v == pytest.approx(298.15, abs=1e-6)

    def test_to_base_pressure(self):
        v, u = to_base(1.0, "MPa")
        assert u == "pa" and v == pytest.approx(1e6)

    def test_normalize_unit_alias(self):
        assert normalize_unit("kg/m3") == "kg/m^3"

    def test_check_quantity_rejects_bool(self):
        with pytest.raises(KgeError) as exc:
            check_quantity({"value": True, "unit": "MPa"})
        assert exc.value.code is KgeErrorCode.UNIT_INCONSISTENT

    def test_check_quantity_rejects_missing_unit(self):
        with pytest.raises(KgeError) as exc:
            check_quantity({"value": 1.0})
        assert exc.value.code is KgeErrorCode.UNIT_INCONSISTENT

    def test_check_quantity_rejects_nan(self):
        with pytest.raises(KgeError) as exc:
            check_quantity({"value": float("nan"), "unit": "MPa"})
        assert exc.value.code is KgeErrorCode.UNIT_INCONSISTENT


# ---------------------------------------------------------------------------
# store: event chain integrity
# ---------------------------------------------------------------------------
class TestStoreChain:
    def test_genesis_and_chain_links(self, tmp_path):
        ks = kstore.KnowledgeStore(tmp_path, clock=lambda: "2026-08-06T12:00:00.000Z")
        ev1 = ks.append("p1", "KB_INITIALIZED", {"title": "t"}, actor="test")
        assert ev1.revision == 1
        assert ev1.prev_hash == kstore.GENESIS_HASH
        ev2 = ks.append("p1", "ENTITY_UPSERTED", {"entity": {"id": "e1"}}, actor="test")
        assert ev2.prev_hash == ev1.hash
        ks.verify_chain(ks.read_events("p1"), project_id="p1")

    def test_tampered_payload_fails_chain(self, tmp_path):
        ks = kstore.KnowledgeStore(tmp_path, clock=lambda: "2026-08-06T12:00:00.000Z")
        ks.append("p1", "KB_INITIALIZED", {"title": "t"}, actor="test")
        ks.append("p1", "ENTITY_UPSERTED", {"entity": {"id": "e1"}}, actor="test")
        log = tmp_path / "p1" / "events.jsonl"
        lines = log.read_text(encoding="utf-8").splitlines()
        rec = json.loads(lines[1])
        rec["payload"]["entity"]["id"] = "tampered"
        lines[1] = json.dumps(rec, sort_keys=True, ensure_ascii=False)
        log.write_text("\n".join(lines) + "\n", encoding="utf-8")
        with pytest.raises(KgeError) as exc:
            ks.rebuild("p1")
        assert exc.value.code is KgeErrorCode.STORE_CORRUPT

    def test_path_traversal_rejected(self, tmp_path):
        ks = kstore.KnowledgeStore(tmp_path)
        with pytest.raises(KgeError) as exc:
            ks.stream_dir("../evil")
        assert exc.value.code is KgeErrorCode.INPUT_SCHEMA_VIOLATION

    def test_first_event_must_be_init(self, tmp_path):
        ks = kstore.KnowledgeStore(tmp_path)
        with pytest.raises(KgeError) as exc:
            ks.append("p1", "ENTITY_UPSERTED", {"entity": {"id": "e1"}}, actor="test")
        assert exc.value.code is KgeErrorCode.STORE_NOT_FOUND

    def test_rebuild_equals_snapshot_projection(self, tmp_path):
        ks = kstore.KnowledgeStore(tmp_path, clock=lambda: "2026-08-06T12:00:00.000Z")
        ks.append("p1", "KB_INITIALIZED", {"title": "t", "entity_types": ["STRAIN"]}, actor="test")
        ks.append("p1", "ENTITY_UPSERTED", {"entity": {"id": "e1", "entity_type": "STRAIN"},
                                            "aliases": ["sp"]}, actor="test")
        proj = ks.rebuild("p1")
        assert proj.entity_by_id("e1")["entity_type"] == "STRAIN"
        assert proj.aliases["sp"] == "e1"
        assert proj.revision == 2


# ---------------------------------------------------------------------------
# models: strength ordering is the gate for epistemic labels
# ---------------------------------------------------------------------------
class TestStrengthOrdering:
    def test_tier_strength_ordering(self):
        from kg.models import TIER_STRENGTH
        assert TIER_STRENGTH[EvidenceTier.HYPOTHESIS] == 1
        assert TIER_STRENGTH[EvidenceTier.VALIDATED] == 6
        assert TIER_STRENGTH[EvidenceTier.EXTERNAL_REPORTED] == 3

    def test_epistemic_strength_ordering(self):
        assert EpistemicLabel.OBSERVED.value == "OBSERVED"
        assert EpistemicLabel.RECOMMENDATION.value == "RECOMMENDATION"
