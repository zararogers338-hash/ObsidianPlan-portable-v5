"""Integration tests: SkillService end-to-end actions against the offline
fixture path. Every output must validate against output.schema.json and pass
the built-in self-check."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

from micp_lit.service import SkillService  # noqa: E402
from micp_lit.validate import validate_output  # noqa: E402


def _payload(base, **kw):
    p = dict(base)
    p.update(kw)
    return p


def _assert_valid(out) -> None:
    valid, issues = validate_output(out)
    assert valid, f"output.schema failed: {[i.message for i in issues[:5]]}"
    assert out["validation"]["self_check_passed"], "self-check failed"


class TestSearchRunOffline:
    def test_offline_fixture(self, base_payload):
        svc = SkillService(offline=True)
        out = svc.run(_payload(base_payload, action="search.run"))
        assert out["status"] == "SUCCESS"
        assert out["search"]["database"] == "offline_fixture"
        assert out["search"]["result_count"] > 0
        assert out["provenance"]["repro_id"]
        _assert_valid(out)

    def test_offline_reproducible(self, base_payload):
        svc = SkillService(offline=True)
        out1 = svc.run(_payload(base_payload, action="search.run"))
        out2 = svc.run(_payload(base_payload, action="search.run"))
        assert out1["provenance"]["repro_id"] == out2["provenance"]["repro_id"]
        assert out1["search"]["records"] == out2["search"]["records"]
        _assert_valid(out1)

    def test_time_range_filter(self, base_payload):
        svc = SkillService(offline=True)
        out = svc.run(_payload(base_payload, action="search.run",
                               constraints=["time_range:2022-"]))
        assert out["status"] == "SUCCESS"
        years = [r["year"] for r in out["search"]["records"]]
        assert all(int(y) >= 2022 for y in years if y is not None)
        _assert_valid(out)

    def test_findings_lab_vs_field_distinguished(self, base_payload):
        """MICP uniformity evidence must separate lab vs field scope."""
        svc = SkillService(offline=True)
        out = svc.run(_payload(base_payload, action="search.run",
                               request="提高 MICP 均匀性的证据"))
        levels = out["triage"]["levels"]
        scales = {lvl["ref_id"]: lvl["level"] for lvl in levels}
        # meter-scale JGGE optimization is TIER1; lab CGJ saturation is TIER2.
        assert scales.get("rec-jgge-optimization-003") == "TIER1"
        assert scales.get("rec-cgj-saturation-002") == "TIER2"
        _assert_valid(out)


class TestSearchRepeat:
    def test_repeat_marks_reproducible(self, base_payload):
        svc = SkillService(offline=True)
        out = svc.run(_payload(base_payload, action="search.repeat"))
        assert out["status"] == "SUCCESS"
        assert out["provenance"]["repro_id"]
        assert any("repro" in f["statement"].lower() for f in out["findings"])
        _assert_valid(out)


class TestDoiVerifyOffline:
    def test_mixed_dois(self, base_payload):
        svc = SkillService(offline=True)
        out = svc.run(_payload(base_payload, action="doi.verify",
                               candidate_dois=["10.1016/j.bgtech.2023.100002",
                                               "garbage-not-a-doi",
                                               "10.9999/reserved.prefix"]))
        statuses = {r["doi"]: r["status"] for r in out["doi_verifications"]}
        assert statuses["10.1016/j.bgtech.2023.100002"] == "offline_unverified"
        assert statuses["garbage-not-a-doi"] == "suspected_forged"
        assert statuses["10.9999/reserved.prefix"] == "suspected_forged"
        _assert_valid(out)


class TestDedupMerge:
    def test_merges_doi_dupes(self, base_payload):
        svc = SkillService(offline=True)
        recs = [
            {"ref_id": "a", "doi": "10.1000/xy", "title": "T", "year": 2020, "container": "J"},
            {"ref_id": "b", "doi": "10.1000/XY", "title": "T", "year": 2020, "container": "J"},
        ]
        out = svc.run(_payload(base_payload, action="dedup.merge", records=recs))
        assert out["dedup"]["input_count"] == 2
        assert out["dedup"]["output_count"] == 1
        _assert_valid(out)


class TestTriageScreen:
    def test_screen_records(self, base_payload):
        svc = SkillService(offline=True)
        recs = [
            {"ref_id": "f", "doi": "10.1234/f", "title": "Field trial", "scale": "field"},
            {"ref_id": "l", "doi": "10.1234/l", "title": "Lab study", "scale": "lab_column"},
            {"ref_id": "r", "doi": "10.1234/r", "title": "A Review", "scale": "review"},
        ]
        out = svc.run(_payload(base_payload, action="triage.screen", records=recs))
        by_id = {lvl["ref_id"]: lvl["level"] for lvl in out["triage"]["levels"]}
        assert by_id["f"] == "TIER1"
        assert by_id["l"] == "TIER2"
        assert by_id["r"] == "TIER3"
        _assert_valid(out)


class TestCiteExport:
    def test_bibtex(self, base_payload):
        svc = SkillService(offline=True)
        recs = [{"ref_id": "a", "doi": "10.1000/x", "title": "Biocementation",
                 "year": 2020, "container": "JGGE", "authors": ["Wang Y"]}]
        out = svc.run(_payload(base_payload, action="cite.export", records=recs, format="bibtex"))
        assert out["status"] == "SUCCESS"
        assert "@article{a," in out["exports"][0]["content"]
        _assert_valid(out)

    def test_export_to_file(self, base_payload, tmp_path):
        svc = SkillService(cwd=tmp_path)
        recs = [{"ref_id": "a", "doi": "10.1000/x", "title": "Biocementation",
                 "year": 2020, "container": "JGGE", "authors": ["Wang Y"]}]
        target = tmp_path / "refs.bib"
        out = svc.run(_payload(base_payload, action="cite.export", records=recs,
                               format="bibtex", out_file=str(target)))
        assert out["status"] == "SUCCESS"
        assert target.is_file()
        assert "@article{a," in target.read_text(encoding="utf-8")
        _assert_valid(out)


class TestValidateSelf:
    def test_self_check_passes(self, base_payload, tmp_path):
        svc = SkillService(cwd=tmp_path)
        out = svc.run(_payload(base_payload, action="validate.self"))
        assert out["status"] == "SUCCESS"
        assert out["selfcheck"]["passed"]
        _assert_valid(out)
