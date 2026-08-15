"""Unit tests: dedup (three rules), DOI structural/forgery, triage layering,
citation exporters, query building / repro_id determinism."""

from __future__ import annotations

import pytest

from micp_lit import dedup, doi, triage, cite, adapters


# --- dedup ----------------------------------------------------------------

class TestDedup:
    def test_doi_rule(self):
        recs = [
            {"ref_id": "a", "doi": "10.1000/xyz", "title": "T", "year": 2020, "container": "J"},
            {"ref_id": "b", "doi": "https://doi.org/10.1000/XYZ", "title": "T", "year": 2020, "container": "J"},
        ]
        out = dedup.dedup_records(recs)
        assert out["input_count"] == 2
        assert out["output_count"] == 1
        assert out["merged_groups"][0]["rule"] == "doi"

    def test_title_rule(self):
        # Same title + same year + same journal → stronger rule wins.
        recs = [
            {"ref_id": "a", "doi": "", "title": "Calcite Precipitation in Porous Media!", "year": 2019, "container": "J"},
            {"ref_id": "b", "doi": "", "title": "calcite precipitation  in porous media", "year": 2019, "container": "J"},
        ]
        out = dedup.dedup_records(recs)
        assert out["output_count"] == 1
        assert out["merged_groups"][0]["rule"] == "title_year_journal"

    def test_title_rule_no_disambiguator(self):
        # Same title, no year/journal → falls back to title_norm.
        recs = [
            {"ref_id": "a", "doi": "", "title": "Calcite Precipitation"},
            {"ref_id": "b", "doi": "", "title": "calcite precipitation  "},
        ]
        out = dedup.dedup_records(recs)
        assert out["output_count"] == 1
        assert out["merged_groups"][0]["rule"] == "title_norm"

    def test_title_year_journal_rule(self):
        recs = [
            {"ref_id": "a", "doi": "", "title": "Same Title", "year": 2015, "container": "Acta Geotech"},
            {"ref_id": "b", "doi": "", "title": "Same Title", "year": 2015, "container": "Acta Geotech"},
        ]
        out = dedup.dedup_records(recs)
        assert out["output_count"] == 1
        assert out["merged_groups"][0]["rule"] == "title_year_journal"

    def test_same_title_diff_year_not_merged(self):
        recs = [
            {"ref_id": "a", "doi": "", "title": "Same Title", "year": 2015, "container": "J"},
            {"ref_id": "b", "doi": "", "title": "Same Title", "year": 2018, "container": "J"},
        ]
        out = dedup.dedup_records(recs)
        assert out["output_count"] == 2

    def test_duplicate_refid_collapses(self):
        recs = [
            {"ref_id": "a", "doi": "10.1/a", "title": "T"},
            {"ref_id": "a", "doi": "10.1/a", "title": "T"},
        ]
        out = dedup.dedup_records(recs)
        assert out["output_count"] == 1


# --- doi ------------------------------------------------------------------

class TestDoi:
    def test_structural_valid(self):
        assert doi.is_structural_doi("10.1061/(asce)gt.1943-5606.0000787")
        assert doi.is_structural_doi("10.1002/jctb.280520402")

    def test_structural_invalid(self):
        assert not doi.is_structural_doi("not-a-doi")
        assert not doi.is_structural_doi("")
        assert not doi.is_structural_doi("10.1234/<>bad")

    def test_offline_verdict_no_false_verify(self):
        r = doi.verify_doi("10.1016/j.bgtech.2023.100002", online=False)
        assert r["status"] == "offline_unverified"
        assert r["resolved"] is False
        assert r["evidence"] == "offline_rule"

    def test_offline_forged_detection(self):
        r = doi.verify_doi("10.9999/fake.2024.00001", online=False)
        assert r["status"] == "suspected_forged"

    def test_online_verified(self):
        def transport(doi, timeout):
            return {"DOI": doi, "title": ["MICP review"], "container-title": ["Biogeotechnics"],
                    "type": "journal-article", "published": {"date-parts": [[2023]]}}
        fetcher = doi.CrossrefFetcher(transport=transport)
        r = doi.verify_doi("10.1016/j.bgtech.2023.100002", online=True, fetcher=fetcher)
        assert r["status"] == "verified"

    def test_online_metadata_mismatch(self):
        def transport(doi, timeout):
            return {"DOI": doi, "title": ["MICP review"], "container-title": ["Biogeotechnics"],
                    "type": "journal-article", "published": {"date-parts": [[2023]]}}
        fetcher = doi.CrossrefFetcher(transport=transport)
        r = doi.verify_doi("10.1016/j.bgtech.2023.100002",
                           claimed={"title": "Totally Wrong", "year": 1999},
                           online=True, fetcher=fetcher)
        assert r["status"] == "suspected_forged"
        fields = {m["field"] for m in r.get("mismatches", [])}
        assert "title" in fields and "year" in fields

    def test_online_404(self):
        fetcher = doi.CrossrefFetcher(transport=lambda doi, timeout: None)
        r = doi.verify_doi("10.9999/nonexistent.2024.1", online=True, fetcher=fetcher)
        assert r["status"] == "not_found"


# --- triage ----------------------------------------------------------------

class TestTriage:
    def test_field_tier1(self):
        out = triage.screen([{"ref_id": "f", "doi": "10.1234/f", "title": "Field trial", "scale": "field"}])
        assert out["levels"][0]["level"] == "TIER1"

    def test_lab_tier2(self):
        out = triage.screen([{"ref_id": "l", "doi": "10.1234/l", "title": "Lab column", "scale": "lab_column"}])
        assert out["levels"][0]["level"] == "TIER2"

    def test_review_tier3(self):
        out = triage.screen([{"ref_id": "r", "doi": "10.1234/r", "title": "A Review of MICP", "scale": "review"}])
        assert out["levels"][0]["level"] == "TIER3"

    def test_reject_no_doi_no_title(self):
        out = triage.screen([{"ref_id": "x", "doi": "", "title": ""}])
        assert len(out["rejections"]) == 1
        assert len(out["levels"]) == 0

    def test_reject_bad_doi(self):
        out = triage.screen([{"ref_id": "x", "doi": "not-a-doi", "title": "Some paper"}])
        assert len(out["rejections"]) == 1

    def test_suspected_forged_rejected(self):
        out = triage.screen([{"ref_id": "x", "doi": "10.1234/x", "title": "T", "doi_status": "suspected_forged"}])
        assert len(out["rejections"]) == 1


# --- cite ------------------------------------------------------------------

class TestCite:
    def test_bibtex_shape(self):
        text = cite.to_bibtex([{"ref_id": "rec-a", "doi": "10.1/a", "title": "Biocementation {Test}",
                                "year": 2020, "container": "Journal", "authors": ["Wang Y", "Li Z"]}])
        assert "@article{rec-a," in text
        assert "journal = {Journal}," in text
        assert "doi = {10.1/a}," in text

    def test_csl_json(self):
        import json
        items = json.loads(cite.to_csl_json([{"ref_id": "r1", "title": "T", "year": 2021,
                                              "authors": ["Wang Y"], "container": "J", "doi": "10.1/t"}]))
        assert items[0]["type"] == "article-journal"
        assert items[0]["issued"]["date-parts"] == [[2021]]

    def test_csv(self):
        text = cite.to_csv([{"ref_id": "r1", "doi": "10.1/t", "title": "T", "year": 2021,
                             "container": "J", "authors": ["Wang Y"]}])
        assert "ref_id,doi,title,year,container,authors,kind,scale,doi_status" in text

    def test_ris(self):
        text = cite.to_ris([{"ref_id": "r1", "doi": "10.1/t", "title": "T", "year": 2021,
                             "authors": ["Wang Y"], "container": "J"}])
        assert "TY  - JOUR" in text
        assert "DO  - 10.1/t" in text

    def test_unknown_format(self):
        with pytest.raises(ValueError):
            cite.export([{"title": "T"}], "xml")


# --- adapters ---------------------------------------------------------------

class TestAdapters:
    def test_build_query_domain_grounding(self):
        q = adapters.build_query("improve MICP uniformity")
        assert "calcium carbonate precipitation" in q

    def test_build_query_urea_ammonium(self):
        q = adapters.build_query("ureolysis pathway")
        assert "ammonium" in q

    def test_repro_id_deterministic(self):
        a = adapters.repro_id("same query", database="crossref", n=10)
        b = adapters.repro_id("same query", database="crossref", n=10)
        assert a == b

    def test_repro_id_differs_on_query(self):
        a = adapters.repro_id("query one", database="crossref", n=10)
        b = adapters.repro_id("query two", database="crossref", n=10)
        assert a != b

    def test_parse_time_range(self):
        assert adapters.parse_time_range("2015-2026") == (2015, 2026)
        assert adapters.parse_time_range("2020-") == (2020, None)
        assert adapters.parse_time_range("garbage") == (None, None)

    def test_offline_fixture_deterministic(self):
        a = adapters.OfflineFixtureAdapter()
        r1 = a.search("MICP uniformity", n=10)
        r2 = a.search("MICP uniformity", n=10)
        assert r1 == r2
        assert r1

    def test_offline_fixture_time_filter(self):
        a = adapters.OfflineFixtureAdapter()
        r = a.search("MICP", n=50, time_range=(2022, None))
        assert all(int(x["year"]) >= 2022 for x in r)
