"""Failure tests — adversarial, malicious, and boundary inputs must be blocked
or handled gracefully, never crash, never fabricate.

Coverage per task-brief §十二: conflict, missing, boundary, malicious input,
non-JSON stdin, unknown action, pathological numerics.
"""

from __future__ import annotations

import json
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
        "contract_version": "1.0", "task_id": "ft", "project_id": "ft-proj",
        "request": "失败测试", "action": action,
        "skill_version": "1.0.0", "timestamp": "2026-08-06T00:00:00Z",
    }
    payload.update(extra)
    return payload


def test_unknown_action_blocked():
    out = invoke(base("not.a.real.action"))
    assert out["status"] in ("BLOCKED", "FAILED")
    assert out["errors"][0]["code"] == "OMM-E101"


def test_nan_in_values_handled():
    out = invoke(base("tools.xrd_match", samples=[
        {"id": "x", "data_type": "xrd_twotheta_intensity",
         "values": [10.0, float("nan"), 20.0, 5.0]}]))
    assert out["status"] in ("FAILED", "BLOCKED")
    assert out["errors"][0]["code"] == "OMM-E104"


def test_empty_samples_blocked():
    out = invoke(base("interpret.phases", samples=[]))
    assert out["status"] in ("FAILED", "BLOCKED")
    assert out["errors"][0]["code"] == "OMM-E101"


def test_non_object_stdin_returns_envelope():
    proc = subprocess.run([sys.executable, str(CLI)], input="[1,2,3]",
                          capture_output=True, text=True, timeout=30)
    out = json.loads(proc.stdout)
    assert out["status"] == "BLOCKED"


def test_contract_version_3_rejected():
    out = invoke(base("tools.xrd_match", contract_version="3.0"))
    assert out["errors"][0]["code"] == "OMM-E501"


def test_tga_out_of_range_rejected():
    out = invoke(base("interpret.phases", samples=[
        {"id": "t", "data_type": "tga_curve",
         "channels": [25.0, 100.0], "intensities": [100.0, 150.0]}]))
    assert out["errors"][0]["code"] == "OMM-E104"


def test_xrd_flat_profile_not_fabricated():
    """A flat XRD profile must yield PARTIAL with no winner, never a made-up phase."""
    out = invoke(base("interpret.phases", samples=[
        {"id": "x", "data_type": "xrd_twotheta_intensity",
         "values": [10.0, 5.0, 12.0, 5.0, 14.0, 5.0, 16.0, 5.0, 18.0, 5.0, 20.0, 5.0,
                    22.0, 5.0, 24.0, 5.0, 26.0, 5.0, 28.0, 5.0, 30.0, 5.0]}]))
    assert out["status"] in ("SUCCESS", "PARTIAL")
    winner = out["results"].get("fusion", {}).get("winner")
    assert winner is None  # no phase fabricated from noise


def test_eds_ca_absent_not_claiming_caco3():
    """No Ca peak in EDS must not produce a CaCO3 claim."""
    out = invoke(base("interpret.phases", samples=[
        {"id": "e", "data_type": "eds_spectrum",
         "channels": [1.0, 2.0, 3.0, 4.0, 5.0], "intensities": [0.0, 0.0, 0.0, 0.0, 0.0]}]))
    assert out["status"] in ("SUCCESS", "PARTIAL", "FAILED")
    # No finding should assert CaCO3 from an EDS without Ca.
    blob = json.dumps(out, ensure_ascii=False)
    assert "CaCO3" not in blob or "不证明" in blob


def test_path_traversal_project_id_rejected():
    out = invoke(base("tools.xrd_match", project_id="..%2f..%2fetc"))
    assert out["status"] == "BLOCKED"
    assert out["errors"][0]["code"] == "OMM-E101"


def test_extremely_large_samples_bounded():
    """Huge inputs should fail fast with a typed error, not OOM the machine."""
    out = invoke(base("tools.xrd_match", samples=[
        {"id": "x", "data_type": "xrd_twotheta_intensity",
         "values": [10.0] * 200000}]))
    assert out["errors"][0]["code"] == "OMM-E104"
