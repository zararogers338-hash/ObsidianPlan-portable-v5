"""Failure tests: every governance gate must fail loudly with the right code."""

from __future__ import annotations

from conftest import cli_call


def _init(cli):
    cli_call(cli, "kb.init", extra={"title": "fail"})


def _sample(cli):
    cli_call(cli, "graph.upsert_entity",
             extra={"entity": {"id": "e-samp", "entity_type": "ARTIFACT"}})


def test_unknown_action_blocked(cli):
    _init(cli)
    out = cli_call(cli, "not.a.real.action", expect_ok=False)
    assert out["status"] == "BLOCKED"
    assert out["errors"][0]["code"] == "KGE-E101"


def test_missing_required_field_blocked(cli):
    # Send a payload without `action`; the CLI must still produce an envelope.
    out = cli_call(cli, "state.get", overrides={"project_id": None}, expect_ok=False)
    # project_id=None violates the pattern -> schema violation
    assert out["errors"][0]["code"] == "KGE-E101"


def test_kb_get_on_uninitialized_blocked(cli):
    out = cli_call(cli, "kb.get", overrides={"project_id": "nope"}, expect_ok=False)
    assert out["status"] == "BLOCKED"
    assert out["errors"][0]["code"] == "KGE-E303"


def test_reference_unknown_entity_blocked(cli):
    _init(cli)
    out = cli_call(cli, "graph.add_relation", extra={"relation": {
        "id": "r1", "from_id": "ghost", "to_id": "ghost2", "relation_type": "RELATED_TO"}},
        expect_ok=False)
    assert out["status"] == "BLOCKED"
    assert out["errors"][0]["code"] == "KGE-E104"


def test_claim_with_unverifiable_evidence_blocked(cli):
    _init(cli)
    _sample(cli)
    out = cli_call(cli, "graph.add_claim", extra={"claim": {
        "id": "c1", "claim_kind": "TYPE", "subject": "e-samp",
        "predicate": "mineral_phase", "object": "calcite",
        "evidence_tier": "EXTERNAL_REPORTED", "epistemic_label": "REPORTED",
        "evidence_refs": ["doi:does-not-exist"]}}, expect_ok=False)
    assert out["status"] == "BLOCKED"
    assert out["errors"][0]["code"] == "KGE-E201"


def test_epistemic_mislabel_blocked(cli):
    _init(cli)
    _sample(cli)
    out = cli_call(cli, "graph.add_claim", extra={"claim": {
        "id": "c1", "claim_kind": "TYPE", "subject": "e-samp",
        "predicate": "mineral_phase", "object": "calcite",
        "evidence_tier": "EXTERNAL_REPORTED", "epistemic_label": "OBSERVED"}},
        expect_ok=False)  # OBSERVED is stronger than EXTERNAL_REPORTED
    assert out["status"] == "BLOCKED"
    assert out["errors"][0]["code"] == "KGE-E204"


def test_validated_without_approval_human_approval_required(cli):
    _init(cli)
    _sample(cli)
    cli_call(cli, "graph.evidence_register",
             extra={"evidence": {"ref": "doi:10.1000/x", "sha256": "a" * 64,
                                 "tier": "EXTERNAL_REPORTED"}})
    out = cli_call(cli, "graph.add_claim", extra={"claim": {
        "id": "c1", "claim_kind": "TYPE", "subject": "e-samp",
        "predicate": "mineral_phase", "object": "calcite",
        "evidence_tier": "VALIDATED", "epistemic_label": "OBSERVED",
        "evidence_refs": ["doi:10.1000/x"]}}, expect_ok=False)
    assert out["status"] == "HUMAN_APPROVAL_REQUIRED"
    assert out["errors"][0]["code"] == "KGE-E502"


def test_stale_approval_rejected(cli):
    _init(cli)
    _sample(cli)
    cli_call(cli, "graph.evidence_register",
             extra={"evidence": {"ref": "doi:10.1000/x", "sha256": "a" * 64,
                                 "tier": "EXTERNAL_REPORTED"}})
    out = cli_call(cli, "graph.add_claim", extra={"claim": {
        "id": "c1", "claim_kind": "TYPE", "subject": "e-samp",
        "predicate": "mineral_phase", "object": "calcite",
        "evidence_tier": "VALIDATED", "epistemic_label": "OBSERVED",
        "evidence_refs": ["doi:10.1000/x"]},
        "human_approval_state": {"granted": True, "approver": "pi", "revision": 0}},
        expect_ok=False)
    assert out["status"] == "HUMAN_APPROVAL_REQUIRED"
    assert out["errors"][0]["code"] == "KGE-E503"


def test_unit_inconsistency_blocked(cli):
    _init(cli)
    _sample(cli)
    # Two VALUE claims on the same subject+predicate with incompatible units
    # must fail with KGE-E203 during conflict detection (a missing unit is a
    # schema violation KGE-E101; incompatibility is the unit-consistency gate).
    cli_call(cli, "graph.add_claim", extra={"claim": {
        "id": "v1", "claim_kind": "VALUE", "subject": "e-samp", "predicate": "ucs",
        "quantity": {"value": 1.0, "unit": "MPa"},
        "evidence_tier": "INTERNAL_OBSERVED", "epistemic_label": "OBSERVED"}})
    out = cli_call(cli, "graph.add_claim", extra={"claim": {
        "id": "v2", "claim_kind": "VALUE", "subject": "e-samp", "predicate": "ucs",
        "quantity": {"value": 1.0, "unit": "m/s"},
        "evidence_tier": "INTERNAL_OBSERVED", "epistemic_label": "OBSERVED"}},
        expect_ok=False)
    assert out["errors"][0]["code"] == "KGE-E203"


def test_contract_v2_rejected(cli):
    _init(cli)
    out = cli_call(cli, "kb.get", overrides={"contract_version": "2.0"}, expect_ok=False)
    assert out["errors"][0]["code"] == "KGE-E801"


def test_conflict_resolve_requires_approval(cli):
    _init(cli)
    _sample(cli)
    cli_call(cli, "graph.add_claim", extra={"claim": {
        "id": "c1", "claim_kind": "TYPE", "subject": "e-samp",
        "predicate": "mineral_phase", "object": "calcite",
        "evidence_tier": "INTERNAL_OBSERVED", "epistemic_label": "OBSERVED"}})
    cli_call(cli, "graph.add_claim", extra={"claim": {
        "id": "c2", "claim_kind": "TYPE", "subject": "e-samp",
        "predicate": "mineral_phase", "object": "vaterite",
        "evidence_tier": "INTERNAL_OBSERVED", "epistemic_label": "OBSERVED"}})
    scan = cli_call(cli, "graph.conflict_scan")
    conflict_id = None
    for a in scan["artifacts"]:
        if a["kind"] == "conflict_report":
            note = a["note"]
            if note["count"] > 0:
                conflict_id = note["open"][0]["id"]
    assert conflict_id, "expected an open conflict"
    out = cli_call(cli, "graph.conflict_resolve",
                   extra={"conflict_id": conflict_id, "preferred_claim": "c1"},
                   expect_ok=False)
    assert out["status"] == "HUMAN_APPROVAL_REQUIRED"
