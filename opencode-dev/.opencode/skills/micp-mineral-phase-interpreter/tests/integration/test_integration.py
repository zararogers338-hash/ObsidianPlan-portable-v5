"""Integration tests — drive the real CLI via subprocess, verify envelopes,
schema conformance, and end-to-end fusion. No mocked computation."""

from __future__ import annotations

import json
import math
import subprocess
import sys
from pathlib import Path

import pytest

SKILL_ROOT = Path(__file__).resolve().parent.parent.parent
CLI = SKILL_ROOT / "tools" / "mmpi_cli.py"


def invoke(payload: dict) -> dict:
    proc = subprocess.run([sys.executable, str(CLI)],
                          input=json.dumps(payload), capture_output=True, text=True, timeout=60)
    if proc.returncode != 0:
        raise RuntimeError(f"CLI crashed: {proc.stderr}")
    return json.loads(proc.stdout)


def base(action: str, **extra) -> dict:
    payload = {
        "contract_version": "1.0", "task_id": "it", "project_id": "it-proj",
        "request": "集成测试", "action": action,
        "skill_version": "1.0.0", "timestamp": "2026-08-06T00:00:00Z",
    }
    payload.update(extra)
    return payload


def interleaved(peaks: list[tuple[float, float]], spread: float = 0.08) -> list[float]:
    from mmpi.minerals import CU_KALPHA1_A
    out: list[float] = []
    for d, rel in peaks:
        c = math.degrees(2 * math.asin(CU_KALPHA1_A / (2 * d)))
        for k in range(-3, 4):
            out.extend([c + k * 0.05, rel * math.exp(-(k * 0.05 / spread) ** 2)])
    return [round(x, 3) for x in out]


def _assert_ok_envelope(out: dict, status: str | None = None) -> None:
    assert out["skill"] == "micp-mineral-phase-interpreter"
    assert out["contract_version"] == "1.0"
    assert out["validation"]["output_schema"] == "passed"
    assert out["validation"]["self_check"] == "passed"
    if status:
        assert out["status"] == status


def test_interpret_vaterite_end_to_end():
    payload = base("interpret.phases", samples=[
        {"id": "x1", "data_type": "xrd_twotheta_intensity",
         "values": interleaved([(3.57, 100), (3.29, 25), (2.73, 30)])},
    ])
    out = invoke(payload)
    _assert_ok_envelope(out)
    assert out["results"]["fusion"]["winner"]["phase"] == "vaterite"


def test_xrd_match_calcite():
    payload = base("tools.xrd_match", samples=[
        {"id": "x1", "data_type": "xrd_twotheta_intensity",
         "values": interleaved([(3.035, 100), (2.495, 14), (2.285, 18)])},
    ])
    out = invoke(payload)
    _assert_ok_envelope(out)
    matches = out["results"]["matches"]
    assert matches[0]["phase"] == "calcite"
    assert matches[0]["verdict"] == "identified"


def test_missing_required_fields_blocked_with_guidance():
    payload = base("interpret.phases")
    del payload["project_id"]
    out = invoke(payload)
    assert out["status"] == "BLOCKED"
    assert out["errors"][0]["code"] == "OMM-E101"
    guidance = out["errors"][0]["detail"]["field_guidance"]
    assert "project_id" in guidance
    assert "如何" in guidance["project_id"] or len(guidance["project_id"]) > 10


def test_contract_v2_rejected():
    payload = base("tools.xrd_match", contract_version="2.0",
                   samples=[{"id": "x", "data_type": "xrd_twotheta_intensity",
                             "values": [10.0, 5.0, 20.0, 6.0]}])
    out = invoke(payload)
    assert out["status"] == "FAILED"
    assert out["errors"][0]["code"] == "OMM-E501"


def test_bad_json_stdin_returns_envelope():
    proc = subprocess.run([sys.executable, str(CLI)], input="not json",
                          capture_output=True, text=True, timeout=30)
    out = json.loads(proc.stdout)
    assert out["status"] == "BLOCKED"
    assert out["errors"][0]["code"] == "OMM-E101"


def test_tools_validate_action():
    payload = base("tools.validate", candidate_output={
        "contract_version": "1.0", "skill": "micp-mineral-phase-interpreter",
        "skill_version": "1.0.0", "status": "SUCCESS", "summary": "s", "action": None,
        "project_id": None, "task_id": None, "findings": [], "assumptions": [],
        "evidence_used": [], "uncertainty": [], "risks": [], "artifacts": [],
        "requested_next_skills": [], "results": {},
        "validation": {"input_schema": "passed", "output_schema": "passed",
                       "self_check": "passed", "checks": []},
        "provenance": {"started_at": None, "completed_at": None, "skill_version": "1.0.0",
                       "sources": [], "audit_log": None},
        "errors": [],
    })
    out = invoke(payload)
    _assert_ok_envelope(out)
    assert out["results"]["valid"] is True


def test_sem_stats_action():
    payload = base("tools.sem_stats", samples=[
        {"id": "s1", "data_type": "sem_particle_list", "particle_units": "um",
         "particles": [[10, 20, 4.0], [12, 22, 5.0], [14, 24, 6.0]]},
    ])
    out = invoke(payload)
    _assert_ok_envelope(out)
    assert out["results"]["stats"]["n"] == 3
