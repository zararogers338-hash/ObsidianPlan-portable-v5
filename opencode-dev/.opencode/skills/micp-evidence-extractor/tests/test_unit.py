"""Unit tests for micp-evidence-extractor tools.

Covers the extraction invariants at the tool level: unit normalization
(including the molar/metre and OD600/urease disambiguation), quantity
placeholder discipline, card invariant checks, isolation checks, exporters,
digitization interface, and the input/output schema contract.
"""

from __future__ import annotations

import json
import os
import sys

import pytest

from conftest import (run_tool, run_service, valid_envelope, sample_document,
                      walk_quantities, TOOLS_DIR, SCHEMAS_DIR)


# ---------------------------------------------------------------------------
# Units
# ---------------------------------------------------------------------------

def test_molar_metre_disambiguation():
    import units
    # "M" with a concentration label is molar; alone it is metre
    assert units.canonicalize("M", label="urea concentration") == ("mol/L", 1.0)
    assert units.canonicalize("M", label="specimen height") == ("mm", 1000.0)
    assert units.canonicalize("mM") == ("mol/L", 1e-3)
    assert units.canonicalize("MPa") == ("kPa", 1000.0)


def test_urease_and_od600_units():
    import units
    assert units.canonicalize("mM urea/min/OD")[0] == "mmol_urea/min/OD"
    assert units.canonicalize("OD600") == ("OD600", 1.0)
    assert units.canonicalize("U/OD") == ("U/OD", 1.0)
    # distinct quantities are never inter-converted
    assert units.classify_role("Urease activity", "mM urea/min/OD", None) == "urease_activity"
    assert units.classify_role("OD600", "OD600", None) == "od600"
    assert units.classify_role("OD", "OD600", None) == "od600"


def test_conflation_guard():
    import units
    issues = units.detect_distinct_conflation([
        {"role": "od600", "unit": "OD600"},
        {"role": "cfu", "unit": "cfu/ml"},
        {"role": "urease_activity", "unit": "U/OD"},
    ])
    # three distinct roles is fine; no conflation (only an info note)
    assert [i for i in issues if i["severity"] == "error"] == []
    issues = units.detect_distinct_conflation([
        {"role": "od600", "unit": "cfu/ml"},
    ])
    assert issues and issues[0]["severity"] == "error"
    assert issues[0]["code"] == "OD600_CONFLATION"


def test_units_cli():
    env = run_tool("units", {"quantities": [
        {"label": "UCS (kPa)", "value": 2.5, "unit": "MPa"},
        {"label": "urea concentration", "value": 0.5, "unit": "M"},
    ]})
    norm = {x["label"]: x for x in env["result"]["normalized"]}
    assert norm["UCS (kPa)"]["normalized_value"] == 2500.0
    assert norm["UCS (kPa)"]["normalized_unit"] == "kPa"
    assert norm["urea concentration"]["normalized_unit"] == "mol/L"


# ---------------------------------------------------------------------------
# Quantity placeholder discipline
# ---------------------------------------------------------------------------

def test_placeholder_never_in_arithmetic():
    import quantity
    q = quantity.placeholder("NOT_REPORTED")
    assert q["value"] is None
    assert quantity.is_placeholder(q)
    # arithmetic over placeholders returns None, never a number
    assert quantity.mean([q]) is None
    assert quantity.total([q]) is None


def test_digitized_requires_error_estimate():
    import quantity
    with pytest.raises(Exception) as exc:
        quantity.reported(3.2, "kPa", acquisition_mode="DIGITIZED_FROM_FIGURE")
    assert "error_estimate" in str(exc.value)


def test_digitized_ok_with_estimate():
    import quantity
    q = quantity.reported(
        3.2, "kPa", acquisition_mode="DIGITIZED_FROM_FIGURE",
        digitization={"error_estimate": 0.1, "method": "cursor",
                      "figure_ref": "fig1"})
    assert q["acquisition_mode"] == "DIGITIZED_FROM_FIGURE"
    assert q["digitization"]["error_estimate"] == 0.1


# ---------------------------------------------------------------------------
# Card invariants
# ---------------------------------------------------------------------------

def test_card_unresolved_group():
    import card_check
    card = {
        "card_id": "c1", "epistemic_tag": "REPORTED", "acquisition_mode": "REPORTED_TABLE",
        "literature": {"source_id": "s", "title": "t", "year": "2020"},
        "scope": {"scale": "lab_column", "system_kind": "pure_culture"},
        "experimental_groups": [{"group_id": "g1", "label": "A"}],
        "time_points": [],
        "conditions": {}, "results": {}, "sources": [{"page": "p1", "locator_type": "table"}],
    }
    r = card_check.validate_card(card)
    assert r["valid"] is True

    # unresolved group reference
    card["results"]["ucs"] = [{
        "value": 100, "unit": "kPa", "normalized_value": 100, "normalized_unit": "kPa",
        "acquisition_mode": "REPORTED_TABLE", "group_id": "g99",
        "sources": [{"page": "p1", "locator_type": "table"}], "epistemic_tag": "REPORTED",
    }]
    r2 = card_check.validate_card(card)
    codes = [i["code"] for i in r2["invariant_issues"]]
    assert "UNRESOLVED_GROUP" in codes


def test_card_placeholder_value_guard():
    import card_check
    card = {
        "card_id": "c1", "epistemic_tag": "REPORTED", "acquisition_mode": "REPORTED_TABLE",
        "literature": {"source_id": "s", "title": "t", "year": "2020"},
        "scope": {"scale": "lab_column", "system_kind": "pure_culture"},
        "experimental_groups": [], "time_points": [],
        "conditions": {}, "results": {}, "sources": [{"page": "p1", "locator_type": "table"}],
    }
    card["results"]["ucs"] = [{
        "value": 100, "unit": "kPa", "normalized_value": None, "normalized_unit": "",
        "acquisition_mode": "NOT_REPORTED",
        "sources": [{"page": "p1", "locator_type": "table"}], "epistemic_tag": "REPORTED",
    }]
    r = card_check.validate_card(card)
    codes = [i["code"] for i in r["invariant_issues"]]
    assert "PLACEHOLDER_WITH_VALUE" in codes


# ---------------------------------------------------------------------------
# Isolation
# ---------------------------------------------------------------------------

def test_isolation_unresolved_timepoint():
    import isolation
    cards = [{
        "card_id": "c1",
        "experimental_groups": [{"group_id": "g1", "label": "A"}],
        "time_points": [{"timepoint_id": "t1", "label": "Day 7"}],
        "results": {"ucs": [{
            "value": 100, "unit": "kPa", "normalized_value": 100, "normalized_unit": "kPa",
            "acquisition_mode": "REPORTED_TABLE", "group_id": "g1", "timepoint_id": "t9",
            "sources": [{"page": "p1", "locator_type": "table"}], "epistemic_tag": "REPORTED",
        }]},
    }]
    rep = isolation.check_cards(cards)
    assert rep["passed"] is False
    assert any(i["code"] == "TIME_UNRESOLVED" for i in rep["issues"])


def test_isolation_group_smear_warning():
    import isolation
    cards = [{
        "card_id": "c1",
        "experimental_groups": [{"group_id": "g1", "label": "A"},
                                {"group_id": "g2", "label": "B"}],
        "time_points": [],
        "results": {"ucs": [{
            "value": 100, "unit": "kPa", "normalized_value": 100, "normalized_unit": "kPa",
            "acquisition_mode": "REPORTED_TABLE",
            "sources": [{"page": "p1", "locator_type": "table"}], "epistemic_tag": "REPORTED",
        }]},
    }]
    rep = isolation.check_cards(cards)
    assert any(i["code"] == "GROUP_SMEAR" for i in rep["issues"])


# ---------------------------------------------------------------------------
# Conflict
# ---------------------------------------------------------------------------

def test_duplicate_value_detected():
    import conflict
    cards = [{
        "card_id": "c1",
        "experimental_groups": [{"group_id": "g1", "label": "A"}],
        "time_points": [],
        "results": {"ucs": [
            {"value": 100, "unit": "kPa", "normalized_value": 100, "normalized_unit": "kPa",
             "acquisition_mode": "REPORTED_TABLE", "group_id": "g1",
             "sources": [{"page": "p1", "locator": "Table 1"}], "epistemic_tag": "REPORTED"},
            {"value": 100, "unit": "kPa", "normalized_value": 100, "normalized_unit": "kPa",
             "acquisition_mode": "REPORTED_TABLE", "group_id": "g1",
             "sources": [{"page": "p2", "locator": "Table 2"}], "epistemic_tag": "REPORTED"},
        ]},
    }]
    rep = conflict.detect_issues(cards)
    assert any(i["code"] == "DUPLICATE_VALUE" for i in rep["issues"])


def test_methods_results_conflict_direct():
    import conflict
    rep = conflict.detect_issues([], methods_claims=[{
        "label": "urea", "value": 0.5, "unit": "M", "locator": "p3",
        "result_value": 0.05, "result_unit": "M", "result_locator": "Table 1",
    }])
    assert any(i["code"] == "METHODS_RESULTS_CONFLICT" and i["severity"] == "error"
               for i in rep["issues"])


# ---------------------------------------------------------------------------
# Exporters
# ---------------------------------------------------------------------------

def test_exporter_json_csv_yaml():
    import exporter
    cards = [{
        "card_id": "c1",
        "literature": {"source_id": "s", "title": "t", "year": "2020"},
        "scope": {"scale": "lab_column"},
        "experimental_groups": [], "time_points": [],
        "results": {"ucs": [{
            "value": 100, "unit": "kPa", "normalized_value": 100, "normalized_unit": "kPa",
            "acquisition_mode": "REPORTED_TABLE", "group_id": None,
            "sources": [{"page": "p1", "locator_type": "table"}], "epistemic_tag": "REPORTED",
        }]},
    }]
    js = exporter.to_json(cards)
    assert json.loads(js)[0]["card_id"] == "c1"
    y = exporter.to_yaml(cards)
    assert "card_id" in y
    csv_out = exporter.to_csv(cards)
    assert "normalized_unit" in csv_out
    assert "kPa" in csv_out


# ---------------------------------------------------------------------------
# Digitizer
# ---------------------------------------------------------------------------

def test_digitizer_error_estimate():
    import digitizer
    est = digitizer.estimate_reading_error(100.0)
    assert est == 0.02
    assert digitizer.estimate_reading_error(0) is None
    assert digitizer.resolution_from_axis(4.0, 400) == 100.0


# ---------------------------------------------------------------------------
# Schema contract
# ---------------------------------------------------------------------------

def test_input_schema_rejects_extra_fields():
    env = run_tool("service", {"task_id": "x", "nonsense": 1},
                   expect_exit=0)
    # service returns BLOCKED (exit 0), not a crash
    assert env["ok"] is True
    assert env["result"]["status"] == "BLOCKED"


def test_output_schema_self_check():
    out = run_service(valid_envelope(document=sample_document()))
    assert out["status"] == "SUCCESS"
    assert out["validation"]["self_audit_pass"] is True
    # the twelve contract fields are all present
    for field in ("status", "summary", "findings", "assumptions", "evidence_used",
                  "uncertainty", "risks", "artifacts", "requested_next_skills",
                  "validation", "provenance", "errors"):
        assert field in out, f"missing envelope field {field}"


def test_evidence_cards_validate_against_card_schema():
    out = run_service(valid_envelope(document=sample_document()))
    cv = out["card_validation"]
    assert cv["valid"] == cv["total"] == 3
    assert cv["passed"] is True
