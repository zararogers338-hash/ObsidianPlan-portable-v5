"""Tests for the v1.1 additions:
  * tools.image_hash — SHA-256 image integrity + append-only hash chain (spec §九 test #8)
  * tools.report — structured analysis report generator (spec §七)
  * flat business fields candidate/confirmed/rejected/unexplained on interpret.phases (spec §八)
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
from mmpi import hashcheck, report as report_mod  # noqa: E402
from mmpi.errors import OmError  # noqa: E402
from mmpi import service  # noqa: E402


# ---------------------------------------------------------------------------
# hashcheck
# ---------------------------------------------------------------------------

def test_sha256_file_matches_known_digest(tmp_path):
    p = tmp_path / "img.png"
    p.write_bytes(b"fake-png-bytes-123")
    expected = hashlib.sha256(b"fake-png-bytes-123").hexdigest()
    assert hashcheck.sha256_file(str(p)) == expected
    assert hashcheck.sha256_bytes(b"fake-png-bytes-123") == expected


def test_verify_file_hash_mismatch_raises(tmp_path):
    p = tmp_path / "img.png"
    p.write_bytes(b"original-bytes")
    wrong = hashlib.sha256(b"tampered-bytes").hexdigest()
    with pytest.raises(OmError) as ei:
        hashcheck.verify_file_hash(str(p), wrong)
    assert ei.value.code == "OMM-E501"


def test_verify_file_hash_match_ok(tmp_path):
    p = tmp_path / "img.png"
    p.write_bytes(b"original-bytes")
    good = hashlib.sha256(b"original-bytes").hexdigest()
    res = hashcheck.verify_file_hash(str(p), good)
    assert res["match"] is True
    assert res["algo"] == "sha256"


def test_verify_file_hash_missing_file_raises(tmp_path):
    with pytest.raises(OmError) as ei:
        hashcheck.sha256_file(str(tmp_path / "nope.png"))
    assert ei.value.code == "OMM-E206"


def test_append_chain_dry_run_writes_nothing(tmp_path):
    chain = str(tmp_path / "chain.jsonl")
    res = hashcheck.append_chain(chain, {"path": "a.png", "sha256": "aa"}, dry_run=True)
    assert res["dry_run"] is True
    assert not os.path.exists(chain)


def test_append_chain_requires_approval(tmp_path):
    chain = str(tmp_path / "chain.jsonl")
    with pytest.raises(OmError) as ei:
        hashcheck.append_chain(chain, {"path": "a.png", "sha256": "aa"}, dry_run=False, approval_granted=False)
    assert ei.value.code == "OMM-E303"


def test_append_chain_verify_roundtrip(tmp_path):
    chain = str(tmp_path / "chain.jsonl")
    hashcheck.append_chain(chain, {"path": "raw.png", "sha256": "aaa"}, dry_run=False, approval_granted=True)
    hashcheck.append_chain(chain, {"path": "proc.png", "sha256": "bbb"}, dry_run=False, approval_granted=True)
    v = hashcheck.verify_chain(chain)
    assert v["ok"] is True
    assert v["entries"] == 2


def test_append_chain_tamper_detected(tmp_path):
    chain = str(tmp_path / "chain.jsonl")
    hashcheck.append_chain(chain, {"path": "raw.png", "sha256": "aaa"}, dry_run=False, approval_granted=True)
    hashcheck.append_chain(chain, {"path": "proc.png", "sha256": "bbb"}, dry_run=False, approval_granted=True)
    # tamper with the first entry's stored sha256 payload
    lines = open(chain, encoding="utf-8").read().splitlines()
    tampered = lines[0].replace('"aaa"', '"zzz"')
    open(chain, "w", encoding="utf-8").write("\n".join([tampered] + lines[1:]) + "\n")
    v = hashcheck.verify_chain(chain)
    assert v["ok"] is False
    assert any(i["kind"] == "entry_hash_mismatch" for i in v["issues"])


def test_describe_processing_diff_records_params():
    d = hashcheck.describe_processing_diff("h1", "h2", params={"threshold": "otsu"})
    assert d["changed"] is True
    assert d["processing_params_recorded"] == {"threshold": "otsu"}
    same = hashcheck.describe_processing_diff("h1", "h1")
    assert same["changed"] is False


# ---------------------------------------------------------------------------
# report generator
# ---------------------------------------------------------------------------

def _minimal_envelope():
    return {
        "contract_version": "1.0", "skill": "micp-mineral-phase-interpreter",
        "skill_version": "1.0.0", "status": "SUCCESS", "summary": "主导相: vaterite (confirmed)",
        "action": "interpret.phases", "project_id": "p", "task_id": "t",
        "findings": [], "assumptions": [], "evidence_used": [], "uncertainty": [],
        "risks": [], "artifacts": [], "requested_next_skills": [],
        "results": {
            "xrd": [{"phase": "vaterite", "verdict": "identified", "score": 0.8,
                     "peaks": [{"obs_2theta": 25.3, "obs_d_A": 3.57, "rel_intensity_pct": 100.0}]}],
            "eds_ca_present": True,
            "tga_co2_likely": True,
            "fusion": {"winner": {"phase": "vaterite", "confidence": "confirmed", "score": 0.78}},
        },
        "validation": {}, "provenance": {}, "errors": [],
    }


def test_build_report_shape():
    r = report_mod.build_report(_minimal_envelope())
    assert r["conclusion"]["winner_phase"] == "vaterite"
    assert r["conclusion"]["winner_confidence"] == "confirmed"
    assert r["evidence_summary"]
    assert "XRD" in r["evidence_summary"][0]


def test_build_report_ascii_chart():
    r = report_mod.build_report(_minimal_envelope(), include_chart=True)
    assert "XRD 峰匹配图" in r["xrd_chart_ascii"]
    assert "vaterite" in r["xrd_chart_ascii"]


def test_build_report_rejects_non_dict():
    with pytest.raises(OmError):
        report_mod.build_report("nope")


def test_render_text_deterministic():
    a = report_mod.render_text(report_mod.build_report(_minimal_envelope()))
    b = report_mod.render_text(report_mod.build_report(_minimal_envelope()))
    assert a == b
    assert "主导相: vaterite" in a


# ---------------------------------------------------------------------------
# service: tools.image_hash action
# ---------------------------------------------------------------------------

def _cli_payload(action: str, **extra):
    base = {
        "contract_version": "1.0", "task_id": "t", "project_id": "p",
        "request": "hash test", "action": action, "skill_version": "1.0.0",
        "timestamp": "2026-08-07T00:00:00Z",
    }
    base.update(extra)
    return base


def test_image_hash_action(tmp_path):
    p = tmp_path / "raw.png"
    p.write_bytes(b"raw-image-bytes")
    good = hashlib.sha256(b"raw-image-bytes").hexdigest()
    payload = _cli_payload(
        "tools.image_hash",
        samples=[{"id": "s1", "data_type": "sem_image", "path": str(p), "expected_sha256": good}],
    )
    env = service.handle(payload)
    assert env["status"] == "SUCCESS"
    assert env["results"]["verify"]["match"] is True


def test_image_hash_mismatch_fails(tmp_path):
    p = tmp_path / "raw.png"
    p.write_bytes(b"raw-image-bytes")
    bad = hashlib.sha256(b"different").hexdigest()
    payload = _cli_payload(
        "tools.image_hash",
        samples=[{"id": "s1", "data_type": "sem_image", "path": str(p), "expected_sha256": bad}],
    )
    env = service.handle(payload)
    assert env["status"] == "FAILED"
    assert env["errors"][0]["code"] == "OMM-E501"


def test_image_hash_missing_path_blocked():
    payload = _cli_payload(
        "tools.image_hash",
        samples=[{"id": "s1", "data_type": "sem_image"}],
    )
    env = service.handle(payload)
    assert env["status"] == "FAILED"


# ---------------------------------------------------------------------------
# service: tools.report action
# ---------------------------------------------------------------------------

def test_report_action(tmp_path):
    candidate = _minimal_envelope()
    payload = _cli_payload("tools.report", candidate_output=candidate)
    env = service.handle(payload)
    assert env["status"] == "SUCCESS"
    assert env["results"]["report"]["conclusion"]["winner_phase"] == "vaterite"
    assert "主导相: vaterite" in env["results"]["report_text"]


def test_report_action_rejects_missing_candidate():
    payload = _cli_payload("tools.report")
    env = service.handle(payload)
    assert env["status"] == "FAILED"


# ---------------------------------------------------------------------------
# service: interpret.phases flat business fields (spec §八)
# ---------------------------------------------------------------------------

def _interpret_payload(**extra):
    payload = _cli_payload("interpret.phases")
    payload["samples"] = [
        # vaterite-dominant XRD (primary 3.57-3.58 family + 3.29 secondary + 2.73)
        {"id": "x1", "data_type": "xrd_twotheta_intensity",
         "values": [27.0,18,27.1,25,27.2,18,32.7,22,32.8,30,32.9,22,24.9,14,25.0,20,25.1,14,
                    25.2,85,25.3,100,25.4,70,25.5,55]},
        # FTIR vaterite marker 745
        {"id": "f1", "data_type": "ftir_spectrum",
         "channels": [740,745,750,870,875,880,1085,1090,1490],
         "intensities": [10,100,10,8,9,8,20,22,25]},
        # EDS Ca at 3.69 keV
        {"id": "e1", "data_type": "eds_spectrum",
         "channels": [3.4,3.5,3.69,3.8], "intensities": [20,50,100,50]},
        # TGA: >40% loss -> carbonate stoichiometry
        {"id": "t1", "data_type": "tga_curve",
         "channels": [25,200,600,800,900], "intensities": [100,98,60,50,55]},
    ]
    payload.update(extra)
    return payload


def test_interpret_confirmed_phases_separated():
    env = service.handle(_interpret_payload())
    assert env["status"] == "SUCCESS"
    assert "vaterite" in env["confirmed_phases"]
    # calcite should NOT be confirmed without its own evidence
    assert "calcite" not in env["confirmed_phases"]
    # flat fields present and schema-consistent
    for key in ("candidate_phases", "confirmed_phases", "rejected_phases",
                "unexplained_features", "morphology", "spatial_distribution", "bridge_evidence"):
        assert key in env


def test_interpret_no_winner_flat_fields_empty():
    # flat XRD -> no winner, PARTIAL, empty flat lists
    payload = _cli_payload("interpret.phases")
    payload["samples"] = [{"id": "x1", "data_type": "xrd_twotheta_intensity",
                           "values": [10,5,12,5,14,5,16,5,18,5,20,5]}]
    env = service.handle(payload)
    assert env["status"] == "PARTIAL"
    assert env["confirmed_phases"] == []
    assert env["candidate_phases"] == []
