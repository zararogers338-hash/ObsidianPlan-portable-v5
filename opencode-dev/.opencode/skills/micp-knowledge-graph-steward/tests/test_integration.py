"""Integration tests: real CLI, end-to-end knowledge base flows."""

from __future__ import annotations

import json

from conftest import BASE, cli_call  # noqa: F401


def test_kb_init_and_get(cli):
    out = cli_call(cli, "kb.init", extra={"title": "MICP KB"})
    assert out["status"] == "SUCCESS"
    assert out["provenance"]["head_revision"] == 1
    got = cli_call(cli, "kb.get")
    note = [a for a in got["artifacts"] if a["kind"] == "kb_view"][0]["note"]
    assert note["counts"]["entities"] == 0
    assert got["validation"]["rebuild_matches_snapshot"] is True


def test_init_is_once_only(cli):
    cli_call(cli, "kb.init", extra={"title": "once"})
    out = cli_call(cli, "kb.init", extra={"title": "twice"}, expect_ok=False)
    assert out["status"] == "BLOCKED"
    assert out["errors"][0]["code"] == "KGE-E101"


def test_entity_relation_claim_flow(cli):
    cli_call(cli, "kb.init", extra={"title": "flow"})
    cli_call(cli, "graph.upsert_entity",
             extra={"entity": {"id": "e-urease", "entity_type": "ENZYME",
                               "canonical_name": "urease"},
                    "aliases": ["urease (EC 3.5.1.5)"]})
    cli_call(cli, "graph.upsert_entity",
             extra={"entity": {"id": "e-strain", "entity_type": "STRAIN",
                               "canonical_name": "Sporosarcina pasteurii"}})
    out = cli_call(cli, "graph.add_relation", extra={"relation": {
        "id": "r1", "from_id": "e-strain", "to_id": "e-urease",
        "relation_type": "PRODUCES"}})
    assert out["status"] == "SUCCESS"
    cli_call(cli, "graph.evidence_register",
             extra={"evidence": {"ref": "doi:10.1000/urease", "sha256": "a" * 64,
                                 "tier": "EXTERNAL_REPORTED", "source": "literature"}})
    out = cli_call(cli, "graph.add_claim", extra={"claim": {
        "id": "c1", "claim_kind": "TYPE", "subject": "e-urease",
        "predicate": "activity", "object": "catalyzes urea hydrolysis",
        "evidence_tier": "EXTERNAL_REPORTED", "epistemic_label": "REPORTED",
        "evidence_refs": ["doi:10.1000/urease"]}})
    assert out["status"] == "SUCCESS"
    chain = cli_call(cli, "graph.evidence_chain", extra={"claim_id": "c1"})
    note = [a for a in chain["artifacts"] if a["kind"] == "evidence_chain"][0]["note"]
    assert len(note["evidence_chain"]) == 1
    assert note["evidence_chain"][0]["sha256"] == "a" * 64


def test_value_claim_unit_checked_and_queryable(cli):
    cli_call(cli, "kb.init", extra={"title": "vals"})
    cli_call(cli, "graph.upsert_entity",
             extra={"entity": {"id": "e-samp", "entity_type": "ARTIFACT"}})
    out = cli_call(cli, "graph.add_claim", extra={"claim": {
        "id": "v1", "claim_kind": "VALUE", "subject": "e-samp", "predicate": "ucs",
        "quantity": {"value": 1.2, "unit": "MPa"},
        "evidence_tier": "INTERNAL_OBSERVED", "epistemic_label": "OBSERVED"}})
    assert out["status"] == "SUCCESS"
    q = cli_call(cli, "graph.query", extra={"query": {"kind": "claim_by_subject",
                                                      "subject": "e-samp"}})
    note = [a for a in q["artifacts"] if a["kind"] == "query_result"][0]["note"]
    assert note["count"] == 1
    assert note["results"][0]["quantity"]["unit"] == "MPa"


def test_ontology_update_then_query_preserves_history(cli):
    cli_call(cli, "kb.init", extra={"title": "onto"})
    cli_call(cli, "graph.upsert_entity",
             extra={"entity": {"id": "e-samp", "entity_type": "ARTIFACT"}})
    cli_call(cli, "graph.add_claim", extra={"claim": {
        "id": "c1", "claim_kind": "TYPE", "subject": "e-samp",
        "predicate": "mineral_phase", "object": "calcite",
        "evidence_tier": "INTERNAL_OBSERVED", "epistemic_label": "OBSERVED"}})
    out = cli_call(cli, "graph.ontology_update",
                   extra={"add_entity_types": ["NANOPARTICLE"]})
    assert out["status"] == "SUCCESS"
    onto = cli_call(cli, "graph.ontology")
    note = [a for a in onto["artifacts"] if a["kind"] == "ontology"][0]["note"]
    assert "NANOPARTICLE" in note["ontology"]["entity_types"]
    # old claim still queryable -> history preserved
    q = cli_call(cli, "graph.query", extra={"query": {"kind": "claim_by_subject",
                                                      "subject": "e-samp"}})
    note = [a for a in q["artifacts"] if a["kind"] == "query_result"][0]["note"]
    assert any(r["id"] == "c1" for r in note["results"])


def test_backup_and_integrity(cli):
    cli_call(cli, "kb.init", extra={"title": "bu"})
    out = cli_call(cli, "kb.backup", extra={"label": "pre"})
    assert out["status"] == "SUCCESS"
    path = out["artifacts"][-1]["path"]
    assert path.endswith(".zip")
    integ = cli_call(cli, "kb.integrity")
    note = [a for a in integ["artifacts"] if a["kind"] == "integrity_report"][0]["note"]
    assert note["chain_ok"] is True
    assert note["snapshot_ok"] is True


def test_export_json_roundtrip_via_import(cli):
    cli_call(cli, "kb.init", extra={"title": "exp"})
    cli_call(cli, "graph.upsert_entity",
             extra={"entity": {"id": "e-strain", "entity_type": "STRAIN",
                               "canonical_name": "Sporosarcina pasteurii"}})
    out = cli_call(cli, "graph.export", extra={"format": "json"})
    assert out["status"] == "SUCCESS"
    doc = [a for a in out["artifacts"] if a["kind"] == "export_document"][0]["note"]["content"]
    assert '"entities"' in doc
    # import into a fresh base (approval-gated)
    imp = cli_call(cli, "graph.import",
                   extra={"content": json.dumps({
                       "ontology": {"entity_types": ["STRAIN", "ARTIFACT"], "version": 1},
                       "entities": [{"id": "e-strain", "entity_type": "STRAIN",
                                     "canonical_name": "Sporosarcina pasteurii"}],
                       "aliases": {"sp": "e-strain"},
                       "relations": [], "claims": [], "evidence": []})},
                   overrides={"project_id": "imported"},
                   expect_ok=False)  # approval-gated
    assert imp["status"] == "HUMAN_APPROVAL_REQUIRED"
    imp2 = cli_call(cli, "graph.import",
                    extra={"content": json.dumps({
                        "ontology": {"entity_types": ["STRAIN", "ARTIFACT"], "version": 1},
                        "entities": [{"id": "e-strain", "entity_type": "STRAIN",
                                      "canonical_name": "Sporosarcina pasteurii"}],
                        "aliases": {"sp": "e-strain"},
                        "relations": [], "claims": [], "evidence": []}),
                        "human_approval_state": {"granted": True, "approver": "pi"}},
                    overrides={"project_id": "imported"})
    assert imp2["status"] == "SUCCESS"
    got = cli_call(cli, "kb.get", overrides={"project_id": "imported"})
    note = [a for a in got["artifacts"] if a["kind"] == "kb_view"][0]["note"]
    assert note["counts"]["entities"] == 1
