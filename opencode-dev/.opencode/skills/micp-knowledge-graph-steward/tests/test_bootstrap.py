"""Bootstrap self-tests — the four acceptance gates from the spec (§八).

1. A strain recorded under different names/conditions must NOT be wrongly merged.
2. Contradictory crystal-phase conclusions must coexist and be traceable.
3. An ontology field change + migration must preserve history.
4. Querying your own writes must not present a hypothesis as fact.
"""

from __future__ import annotations

from conftest import cli_call


def _init(cli):
    cli_call(cli, "kb.init", extra={"title": "bootstrap"})


def _sample(cli, eid="e-samp"):
    cli_call(cli, "graph.upsert_entity",
             extra={"entity": {"id": eid, "entity_type": "ARTIFACT"}})


# ---------------------------------------------------------------------------
# Gate 1: same strain, different names/conditions -> never silently merged
# ---------------------------------------------------------------------------
def test_gate1_same_strain_names_are_not_merged(cli):
    _init(cli)
    # Same canonical name via two different spellings, two distinct entity ids.
    cli_call(cli, "graph.upsert_entity", extra={"entity": {
        "id": "strain-a", "entity_type": "STRAIN",
        "canonical_name": "Bacillus pasteurii"}})   # normalized -> Sporosarcina pasteurii
    out = cli_call(cli, "graph.upsert_entity", extra={"entity": {
        "id": "strain-b", "entity_type": "STRAIN",
        "canonical_name": "S. pasteurii"}})          # also -> Sporosarcina pasteurii
    # Both entities exist; the second upsert surfaced a NOT-merged recommendation.
    recs = [f for f in out["findings"] if f["label"] == "RECOMMENDATION"]
    assert recs, "must surface an identity-candidate recommendation"
    assert "NOT merged" in recs[0]["statement"] or "not merged" in recs[0]["statement"].lower()

    got = cli_call(cli, "kb.get")
    note = [a for a in got["artifacts"] if a["kind"] == "kb_view"][0]["note"]
    assert note["counts"]["entities"] == 2, "distinct entities must not be merged"

    # Explicit identity can be established only via an IDENTITY claim.
    out = cli_call(cli, "graph.add_claim", extra={"claim": {
        "id": "id1", "claim_kind": "IDENTITY", "subject": "strain-a",
        "predicate": "same_as", "object": "strain-b",
        "evidence_tier": "INTERNAL_OBSERVED", "epistemic_label": "OBSERVED"}})
    assert out["status"] == "SUCCESS"


# ---------------------------------------------------------------------------
# Gate 2: contradictory crystal-phase conclusions coexist and stay traceable
# ---------------------------------------------------------------------------
def test_gate2_contradictory_phases_coexist(cli):
    _init(cli)
    _sample(cli)
    cli_call(cli, "graph.add_claim", extra={"claim": {
        "id": "p1", "claim_kind": "TYPE", "subject": "e-samp",
        "predicate": "mineral_phase", "object": "calcite",
        "evidence_tier": "INTERNAL_OBSERVED", "epistemic_label": "OBSERVED"}})
    out = cli_call(cli, "graph.add_claim", extra={"claim": {
        "id": "p2", "claim_kind": "TYPE", "subject": "e-samp",
        "predicate": "mineral_phase", "object": "vaterite",
        "evidence_tier": "EXTERNAL_REPORTED", "epistemic_label": "REPORTED"}})
    assert out["status"] == "SUCCESS"
    opened = [f for f in out["findings"] if "open conflict" in f["statement"]]
    assert opened, "a second contradictory phase must open a conflict, not overwrite"

    # Both claims coexist in the graph.
    q = cli_call(cli, "graph.query", extra={"query": {"kind": "claim_by_subject",
                                                      "subject": "e-samp"}})
    note = [a for a in q["artifacts"] if a["kind"] == "query_result"][0]["note"]
    assert note["count"] == 2
    ids = {r["id"] for r in note["results"]}
    assert ids == {"p1", "p2"}, "both conclusions must remain queryable"

    # Both are traceable via the evidence chain (empty chains are reported as
    # 0 records — never fabricated).
    for cid in ("p1", "p2"):
        chain = cli_call(cli, "graph.evidence_chain", extra={"claim_id": cid})
        note = [a for a in chain["artifacts"] if a["kind"] == "evidence_chain"][0]["note"]
        assert note["claim_id"] == cid

    # Conflict scan reports exactly one open conflict.
    scan = cli_call(cli, "graph.conflict_scan")
    note = [a for a in scan["artifacts"] if a["kind"] == "conflict_report"][0]["note"]
    assert note["count"] == 1


# ---------------------------------------------------------------------------
# Gate 3: ontology field change + migration preserves history
# ---------------------------------------------------------------------------
def test_gate3_ontology_change_preserves_history(cli):
    _init(cli)
    _sample(cli)
    cli_call(cli, "graph.add_claim", extra={"claim": {
        "id": "c1", "claim_kind": "TYPE", "subject": "e-samp",
        "predicate": "mineral_phase", "object": "calcite",
        "evidence_tier": "INTERNAL_OBSERVED", "epistemic_label": "OBSERVED"}})
    before = cli_call(cli, "kb.get")
    before_note = [a for a in before["artifacts"] if a["kind"] == "kb_view"][0]["note"]
    assert before_note["ontology_version"] == 1

    # Ontology evolution: add a new entity type.
    out = cli_call(cli, "graph.ontology_update",
                   extra={"add_entity_types": ["NANOPARTICLE"]})
    assert out["status"] == "SUCCESS"

    # The old claim and entity survive the schema change.
    q = cli_call(cli, "graph.query", extra={"query": {"kind": "claim_by_subject",
                                                      "subject": "e-samp"}})
    note = [a for a in q["artifacts"] if a["kind"] == "query_result"][0]["note"]
    assert any(r["id"] == "c1" for r in note["results"])

    # Export contains the evolved ontology AND the preserved history.
    exp = cli_call(cli, "graph.export", extra={"format": "json"})
    doc = [a for a in exp["artifacts"] if a["kind"] == "export_document"][0]["note"]["content"]
    assert "NANOPARTICLE" in doc
    assert '"id": "c1"' in doc

    # Migration decision: current layout needs no migration; integrity passes.
    mig = cli_call(cli, "kb.migrate")
    assert mig["status"] == "SUCCESS"
    integ = cli_call(cli, "kb.integrity")
    note = [a for a in integ["artifacts"] if a["kind"] == "integrity_report"][0]["note"]
    assert note["chain_ok"] is True and note["snapshot_ok"] is True


# ---------------------------------------------------------------------------
# Gate 4: querying own writes never presents a hypothesis as fact
# ---------------------------------------------------------------------------
def test_gate4_hypothesis_never_presented_as_fact(cli):
    _init(cli)
    _sample(cli)
    cli_call(cli, "graph.add_claim", extra={"claim": {
        "id": "h1", "claim_kind": "TYPE", "subject": "e-samp",
        "predicate": "mineral_phase", "object": "aragonite",
        "evidence_tier": "HYPOTHESIS", "epistemic_label": "HYPOTHESIS"}})

    q = cli_call(cli, "graph.query", extra={"query": {"kind": "claim_by_subject",
                                                      "subject": "e-samp"}})
    note = [a for a in q["artifacts"] if a["kind"] == "query_result"][0]["note"]
    results = {r["id"]: r for r in note["results"]}
    assert results["h1"]["epistemic_label"] == "HYPOTHESIS"

    # Findings in the output envelope must label it HYPOTHESIS, never OBSERVED.
    labels = {f["label"] for f in q["findings"]}
    assert "OBSERVED" not in labels or "h1" not in str(q["findings"])
    hyp = [f for f in q["findings"] if "h1" in f["statement"]]
    assert hyp and hyp[0]["label"] == "HYPOTHESIS"

    # Evidence chain reports the label too.
    chain = cli_call(cli, "graph.evidence_chain", extra={"claim_id": "h1"})
    note = [a for a in chain["artifacts"] if a["kind"] == "evidence_chain"][0]["note"]
    assert note["epistemic_label"] == "HYPOTHESIS"
