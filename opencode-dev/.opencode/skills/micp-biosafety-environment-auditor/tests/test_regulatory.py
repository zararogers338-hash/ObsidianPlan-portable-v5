"""Unit tests for the regulatory module: verification, staleness, no-fabrication.

The auditor must never assert a limit value it cannot verify, and must never
treat an empty/absent database as "verified".
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from tools.mbs import regulatory
from tools.mbs.errors import MbsError

DB = regulatory._REGULATORY_DB_DIR


@pytest.fixture
def reg_db(tmp_path, monkeypatch) -> Path:
    """A copy of the real regulatory DB in a temp dir so tests cannot corrupt it."""
    monkeypatch.setattr(regulatory, "_REGULATORY_DB_DIR", tmp_path)
    src = Path(__file__).resolve().parent.parent / "references" / "regulatory_db"
    for p in src.glob("*.json"):
        shutil.copy2(p, tmp_path / p.name)
    return tmp_path


class TestRegulatory:
    def test_lookup_fresh_record(self, reg_db) -> None:
        res = regulatory.lookup_regulation(record_id="cn-gbz2.1-2019-ammonia")
        assert res["verified"] is True
        assert res["records"][0]["verified_now"] is True

    def test_lookup_unknown_record_raises(self, reg_db) -> None:
        with pytest.raises(MbsError) as e:
            regulatory.lookup_regulation(record_id="does-not-exist")
        assert e.value.code.code == "MBS-E201"

    def test_stale_record_flagged(self, reg_db, monkeypatch) -> None:
        # Write a record verified 2 years ago -> must be stale.
        rec = {
            "id": "stale-test",
            "region": "China",
            "name": "旧法规",
            "doc_id": "OLD-1",
            "issued_date": "2010-01-01",
            "status": "effective",
            "category": "water",
            "verified": True,
            "verified_on": "2024-01-01",
            "source": "https://example.test/old",
        }
        (reg_db / "stale-test.json").write_text(json.dumps(rec, ensure_ascii=False), encoding="utf-8")
        res = regulatory.lookup_regulation(record_id="stale-test", allow_stale=True)
        assert res["records"][0]["stale"] is True
        assert res["records"][0]["verified_now"] is False
        assert "stale-test" in res["verification_required"]

    def test_stale_record_not_allowed_by_default(self, reg_db) -> None:
        rec = {
            "id": "stale2",
            "region": "China", "name": "旧", "doc_id": "OLD", "issued_date": "2010-01-01",
            "status": "effective", "category": "water", "verified": True,
            "verified_on": "2024-01-01", "source": "https://example.test",
        }
        (reg_db / "stale2.json").write_text(json.dumps(rec, ensure_ascii=False), encoding="utf-8")
        with pytest.raises(MbsError) as e:
            regulatory.lookup_regulation(record_id="stale2")
        assert e.value.code.code == "MBS-E201"
        assert "verification_required" in e.value.detail

    def test_record_without_verified_on_is_stale(self, reg_db) -> None:
        rec = {
            "id": "no-ver-date", "region": "China", "name": "无核验日", "doc_id": "X",
            "issued_date": "2020-01-01", "status": "effective", "category": "water",
            "verified": True, "source": "https://example.test",
        }
        (reg_db / "no-ver-date.json").write_text(json.dumps(rec, ensure_ascii=False), encoding="utf-8")
        res = regulatory.lookup_regulation(record_id="no-ver-date", allow_stale=True)
        assert res["records"][0]["stale"] is True

    def test_all_context_with_records_verifies(self, reg_db) -> None:
        ctx = regulatory.all_regulatory_context()
        assert ctx["regulations"]  # records exist
        # Fully-verified categories (every record verified_now).
        assert ctx["categories"]["biosafety"]["fully_verified"] is True
        assert ctx["categories"]["laboratory"]["fully_verified"] is True
        assert ctx["categories"]["waste"]["fully_verified"] is True
        assert ctx["fully_verified"] is False  # water carries unverified records => global not fully verified

    def test_all_context_categories_known_unverified(self, reg_db) -> None:
        ctx = regulatory.all_regulatory_context()
        # The water category contains 2 intentionally-unverified records
        # (cn-gb5084-2021 conflicting limits, cn-gb18918-2025 amendment):
        # per red-team fix #1, the whole category must NOT be fully verified —
        # the auditor never asserts coverage while an applicable limit is still
        # REGULATORY_VERIFICATION_REQUIRED.
        assert ctx["categories"]["water"]["fully_verified"] is False
        assert ctx["categories"]["water"]["verified_records"] == 5

    def test_all_context_empty_db_is_NOT_verified(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setattr(regulatory, "_REGULATORY_DB_DIR", tmp_path)  # empty dir
        ctx = regulatory.all_regulatory_context()
        assert ctx["regulations"] == []
        assert ctx["fully_verified"] is False
        assert any("category-" in v for v in ctx["verification_required"])

    def test_required_categories_contained_vs_field(self) -> None:
        contained = regulatory.required_categories_for_site({"release_type": "contained"})
        assert "biosafety" in contained and "waste" in contained
        assert "water" not in contained and "groundwater" not in contained
        field = regulatory.required_categories_for_site(
            {"release_type": "injection", "groundwater_injection": True, "confined_space": True})
        assert "water" in field and "groundwater" in field and "occupational" in field

    def test_required_categories_declared_discharge(self) -> None:
        # Non-optional signal: plan.waste.discharge_to_environment=True must
        # force water/emissions/groundwater verification even without flags
        # (red-team fix #2: never let absent optional flags downgrade a
        # physically-releasing plan to contained).
        site = {"release_type": "contained",
                "plan": {"waste": {"discharge_to_environment": True}}}
        cats = regulatory.required_categories_for_site(site)
        assert "water" in cats and "emissions" in cats and "groundwater" in cats

    def test_regulatory_gaps_for_site(self, reg_db) -> None:
        ctx = regulatory.all_regulatory_context()
        # Contained site: biosafety/laboratory/waste all verified -> no gaps.
        gaps_contained = regulatory.regulatory_gaps_for_site({"release_type": "contained"}, ctx)
        assert gaps_contained == []
        # A site that declares discharge requires water/emissions/groundwater —
        # the water category carries unverified limit records, so a gap exists
        # (red-team fix #1: any unverified record in a site-relevant category
        # keeps it a gap).
        gaps_discharge = regulatory.regulatory_gaps_for_site(
            {"release_type": "contained", "plan": {"waste": {"discharge_to_environment": True}}}, ctx)
        assert "water" in gaps_discharge

    def test_gap_when_category_missing(self, tmp_path, monkeypatch) -> None:
        # Only biosafety records exist; a site needing water verification has a gap.
        for rid in ("cn-gb19489-2008", "cn-pathogen-list-2023"):
            src = Path(__file__).resolve().parent.parent / "references" / "regulatory_db" / f"{rid}.json"
            shutil.copy2(src, tmp_path / src.name)
        monkeypatch.setattr(regulatory, "_REGULATORY_DB_DIR", tmp_path)
        ctx = regulatory.all_regulatory_context()
        gaps = regulatory.regulatory_gaps_for_site({"release_type": "injection"}, ctx)
        assert "water" in gaps

    def test_evaluate_against_limits_unknown_without_limit(self, reg_db) -> None:
        # No limit record for "zygote_n" => UNKNOWN, not compliance.
        res = regulatory.evaluate_against_limits(substance="zygote_n",
                                                 concentration_mgL=999.0,
                                                 matrix="wastewater")
        assert res["exceeded"] == "UNKNOWN"
        assert res["verification_required"]

    def test_evaluate_against_verified_limit(self, reg_db) -> None:
        # cn-gb14848-2017 (groundwater) is verified with nh4_n limit 0.50 mg/L.
        res = regulatory.evaluate_against_limits(
            substance="nh4_n", concentration_mgL=500.0,
            limit_record_ids=["cn-gb14848-2017"],
        )
        assert res["exceeded"] == "YES"
        assert res["limit_mgL"] == 0.50

    def test_evaluate_against_unverified_limit_is_unknown(self, reg_db) -> None:
        # cn-gb5084-2021 carries verified=False (conflicting ammonia limits):
        # evaluation must be UNKNOWN, never a compliance assertion.
        res = regulatory.evaluate_against_limits(
            substance="nh4_n", concentration_mgL=5.0,
            limit_record_ids=["cn-gb5084-2021"],
        )
        assert res["exceeded"] == "UNKNOWN"
        assert res["verification_required"]
