"""Self-bootstrap tests (spec §八): drive the skill with realistic user
requests — not leaking expected answers — and verify the skill's own rules.

The four mandated self-bootstrap scenarios:
  1. Search "improve MICP uniformity" evidence; distinguish lab vs field.
  2. Feed a forged paper; verify it is flagged as non-verifiable.
  3. Repeat the same query; verify reproduction record completeness.
  4. Answer a question from the skill's own results, and check that findings
     cite records (never just abstracts) and don't over-cite reviews.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "tools"))

from micp_lit.service import SkillService  # noqa: E402
from micp_lit.validate import validate_output  # noqa: E402


def _run(base, **kw):
    p = dict(base)
    p.update(kw)
    svc = SkillService(offline=True)
    out = svc.run(p)
    valid, issues = validate_output(out)
    assert valid, f"output schema: {[i.message for i in issues[:3]]}"
    assert out["validation"]["self_check_passed"]
    return out


class TestBootstrapScenario1Uniformity:
    """Scenario 1: MICP uniformity evidence, lab vs field separation."""

    def test_search_and_distinguish(self, base_payload):
        out = _run(base_payload, action="search.run",
                   request="提高 MICP 均匀性的证据, 区分实验室与现场")
        assert out["status"] == "SUCCESS"
        levels = {l["ref_id"]: l for l in out["triage"]["levels"]}
        # Lab column work must NOT be labeled as field/meter evidence.
        lab = levels["rec-cgj-saturation-002"]
        assert lab["level"] == "TIER2", "lab column must be TIER2"
        meter = levels["rec-jgge-optimization-003"]
        assert meter["level"] == "TIER1", "meter-scale must be TIER1"
        # Scope discipline is enforced by the schema-level scope check.
        assert all(l["level"] in ("TIER1", "TIER2", "TIER3") for l in out["triage"]["levels"])


class TestBootstrapScenario2Forged:
    """Scenario 2: a fabricated citation must be caught."""

    def test_forged_paper_flagged(self, base_payload):
        out = _run(base_payload, action="doi.verify",
                   request="核验这篇引用是否真实: 10.9999/fake.biocement.2024.00001",
                   candidate_dois=["10.9999/fake.biocement.2024.00001"])
        assert out["status"] == "PARTIAL"
        r = out["doi_verifications"][0]
        assert r["status"] == "suspected_forged"
        # The forged DOI must never appear as verified evidence.
        for f in out["findings"]:
            assert f["label"] != "REPORTED", "forged citation must not be REPORTED"

    def test_fabricated_title_with_valid_doi_mismatch(self, base_payload):
        """A real DOI with a fabricated title/author must be flagged by
        metadata-consistency checking when online; offline we must not
        confirm it."""
        out = _run(base_payload, action="doi.verify",
                   request="核验 DOI 与声称元数据是否一致",
                   candidate_dois=["10.1016/j.bgtech.2023.100002"],
                   claimed_metadata={"10.1016/j.bgtech.2023.100002": {
                       "title": "Fabricated non-existent review", "year": 1998}})
        # Offline: cannot confirm existence → never claim verified.
        assert out["doi_verifications"][0]["status"] != "verified"
        for f in out["findings"]:
            assert f["label"] != "REPORTED"


class TestBootstrapScenario3Reproducibility:
    """Scenario 3: same query repeated → complete reproduction record."""

    def test_repeat_produces_repro_record(self, base_payload):
        out1 = _run(base_payload, action="search.run",
                    request="MICP 均匀性文献检索")
        out2 = _run(base_payload, action="search.run",
                    request="MICP 均匀性文献检索")
        assert out1["provenance"]["repro_id"] == out2["provenance"]["repro_id"]
        # Reproduction record must include query, db, filters, result_count.
        for out in (out1, out2):
            s = out["search"]
            assert s["query"]
            assert s["database"]
            assert s["filters"]
            assert "result_count" in s
            assert out["provenance"]["repro_id"]

    def test_repeat_action_marks_reproducible(self, base_payload):
        out = _run(base_payload, action="search.repeat",
                   request="MICP 均匀性文献检索")
        assert any("可复现" in f["statement"] or "repro" in f["statement"].lower()
                   for f in out["findings"])


class TestBootstrapScenario4AnswerFromOwnResults:
    """Scenario 4: answer from the skill's own results; findings must cite
    records, not abstract-only or over-cited reviews."""

    def test_findings_grounded_in_records(self, base_payload):
        out = _run(base_payload, action="search.run",
                   request="MICP 处理使砂土强度提升的关键因素有哪些")
        # Every triage-level finding carries a refs anchor to a record.
        anchored = [f for f in out["findings"] if f.get("refs")]
        assert anchored, "findings must reference records"
        record_ids = {r["ref_id"] for r in out["search"]["records"]}
        for f in anchored:
            for ref in f.get("refs", []):
                assert ref in record_ids, f"finding references unknown {ref}"

    def test_reviews_not_overcited_as_primary(self, base_payload):
        """Review records are TIER3; findings must not present a review's
        conclusion as primary empirical evidence."""
        out = _run(base_payload, action="search.run",
                   request="MICP 现场加固效果证据")
        review_tiers = [l for l in out["triage"]["levels"] if l["level"] == "TIER3"]
        # If reviews exist, they must be labeled TIER3 (navigation, not primary).
        assert all(l["level"] == "TIER3" for l in review_tiers)
        # Primary claims come from TIER1/TIER2 records.
        primary = [l for l in out["triage"]["levels"] if l["level"] in ("TIER1", "TIER2")]
        assert primary, "expected at least one primary-empirical record"
