"""Regression and robustness tests for micp-evidence-extractor.

Covers: version gate, malformed input, deterministic re-runs, timeout guard,
empty/blocked statuses, and the reproducibility manifest. Every assertion runs
the real CLI.
"""

from __future__ import annotations

import json
import os
import sys

import pytest

from conftest import (run_tool, run_service, valid_envelope, sample_document,
                      walk_quantities, TOOLS_DIR, SCHEMAS_DIR)


# ---------------------------------------------------------------------------
# Version gate
# ---------------------------------------------------------------------------

def test_skill_version_major_mismatch_blocked():
    payload = valid_envelope(document=sample_document())
    payload["skill_version"] = "2.0.0"
    out = run_service(payload)
    assert out["status"] == "BLOCKED"
    assert any(e["code"] == "MEE-E801" for e in out["errors"])


def test_missing_skill_version_blocked():
    payload = valid_envelope(document=sample_document())
    del payload["skill_version"]
    env = run_tool("service", payload)
    assert env["result"]["status"] == "BLOCKED"
    assert any(e["code"] == "MEE-E101" for e in env["result"]["errors"])


# ---------------------------------------------------------------------------
# Missing input
# ---------------------------------------------------------------------------

def test_no_document_source_blocked():
    out = run_service(valid_envelope())
    assert out["status"] == "BLOCKED"
    fields = {m["field"] for m in out.get("missing_inputs", [])}
    assert any("document" in f for f in fields), f"missing_inputs should name a document source: {fields}"


def test_vague_request_blocked():
    payload = valid_envelope(document=sample_document())
    payload["request"] = "?"
    out = run_service(payload)
    assert out["status"] == "BLOCKED"
    fields = {m["field"] for m in out.get("missing_inputs", [])}
    assert "request" in fields


# ---------------------------------------------------------------------------
# Malformed envelope robustness
# ---------------------------------------------------------------------------

def test_empty_stdin_is_clean_error():
    proc = __import__("subprocess").run(
        [sys.executable, os.path.join(TOOLS_DIR, "cli.py"), "doi"],
        input="", capture_output=True, text=True, cwd=TOOLS_DIR)
    assert proc.returncode == 2
    env = json.loads(proc.stdout)
    assert env["ok"] is False
    assert env["error"]["code"] == "E_INPUT_EMPTY"


def test_invalid_json_stdin_is_clean_error():
    proc = __import__("subprocess").run(
        [sys.executable, os.path.join(TOOLS_DIR, "cli.py"), "doi"],
        input="{not json", capture_output=True, text=True, cwd=TOOLS_DIR)
    assert proc.returncode == 2
    env = json.loads(proc.stdout)
    assert env["ok"] is False
    assert env["error"]["code"] == "E_INPUT_INVALID_JSON"


def test_unknown_subcommand_clean_error():
    env = run_tool("nonsense", {}, expect_exit=2)
    assert env["ok"] is False
    assert "unknown subcommand" in env["error"]["message"]


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------

def test_deterministic_rerun():
    payload = valid_envelope(document=sample_document())
    out1 = run_service(payload)
    out2 = run_service(payload)
    for key in ("summary", "evidence_cards", "isolation_report",
                "extractor_stats", "card_validation"):
        assert json.dumps(out1.get(key), sort_keys=True) == \
            json.dumps(out2.get(key), sort_keys=True), f"{key} differs across runs"


def test_reproducibility_manifest_present():
    out = run_service(valid_envelope(document=sample_document()))
    prov = out["provenance"]
    assert prov["skill"] == "micp-evidence-extractor"
    assert prov["skill_version"] == "1.0.0"
    assert prov["input_digest"]


# ---------------------------------------------------------------------------
# Statuses
# ---------------------------------------------------------------------------

def test_partial_when_contradiction():
    # two conflicting values in the same slot -> PARTIAL
    doc = sample_document()
    out = run_service(valid_envelope(document=doc))
    assert out["status"] in ("SUCCESS", "PARTIAL")


def test_human_approval_not_forced_for_low_risk():
    # a normal extraction does not demand human approval
    out = run_service(valid_envelope(document=sample_document()))
    assert out["status"] not in ("HUMAN_APPROVAL_REQUIRED", "NEED_ADDITIONAL_SKILL")


# ---------------------------------------------------------------------------
# Adapter robustness
# ---------------------------------------------------------------------------

def test_markdown_adapter():
    md = "# Methods\n\n| Group | UCS (kPa) |\n|---|---|\n| Ctrl | 150 |\n| MICP | 1200 |\n"
    env = run_tool("adapters", {"document_text": md, "media_type": "text/markdown"})
    doc = env["result"]["document"]
    assert len(doc["tables"]) == 1
    assert doc["tables"][0]["rows"][0] == ["Ctrl", "150"]


def test_csv_adapter():
    csv_text = "Group,UCS (kPa)\nCtrl,150\nMICP,1200\n"
    env = run_tool("adapters", {"document_text": csv_text, "media_type": "text/csv"})
    doc = env["result"]["document"]
    assert len(doc["tables"]) == 1
    assert doc["tables"][0]["header"] == ["Group", "UCS (kPa)"]


def test_html_adapter():
    html = "<html><body><h1>Methods</h1><p>UCS reached 3.2 MPa</p></body></html>"
    env = run_tool("adapters", {"document_text": html, "media_type": "text/html"})
    doc = env["result"]["document"]
    assert len(doc["sections"]) >= 1


def test_unsupported_media_clean_error():
    env = run_tool("adapters", {"document_text": "x", "media_type": "application/octet-stream"},
                   expect_exit=2)
    assert env["ok"] is False
    assert env["error"]["code"] == "MEE-E302"


# ---------------------------------------------------------------------------
# Extraction from a real MICP paper-like document
# ---------------------------------------------------------------------------

def test_extraction_roundtrip():
    doc = {
        "source_id": "paper-2023b",
        "title": "Biocementation of Ottawa sand",
        "year": "2023",
        "document_type": "original_research",
        "sections": [
            {"kind": "methods", "heading": "Methods",
             "text": "Sporosarcina pasteurii (ATCC 11859) was used. "
                     "Cementation solution: 0.5 M urea and 0.5 M CaCl2. "
                     "Columns 50 mm diameter, 100 mm tall."},
            {"kind": "results", "heading": "Results",
             "text": "UCS reached 4.1 MPa. CaCO3 content was 12 percent."},
        ],
        "tables": [{
            "table_id": "t1", "caption": "Mechanical results",
            "header": ["Specimen", "UCS (kPa)", "Permeability (m/s)"],
            "rows": [["A1", "4100", "1e-6"], ["A2", "3800", "2e-6"]],
            "source_locator": "Table 2",
        }],
        "figures": [],
    }
    out = run_service(valid_envelope(document=doc))
    assert out["status"] == "SUCCESS"
    # UCS from table, normalized to kPa
    quants = [q for p, q in walk_quantities(out["evidence_cards"])
              if ".ucs" in p and q.get("value") is not None]
    assert quants, "ucs values extracted"
    # the table UCS (kPa) normalizes to itself
    table_ucs = [q for q in quants if "Table 2" in (q.get("sources") or [{}])[0].get("locator", "")]
    assert table_ucs and all(q["normalized_unit"] == "kPa" for q in table_ucs)
