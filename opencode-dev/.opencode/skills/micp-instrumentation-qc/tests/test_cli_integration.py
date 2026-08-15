"""Integration tests: CLI dispatch (calibration / control / sample-chain / integrity / qc pipeline)."""

import json
import os
import subprocess
import sys
import tempfile

import pytest

TOOLS = os.path.join(os.path.dirname(__file__), "..", "tools")
PY = sys.executable

sys.path.insert(0, TOOLS)
import _common  # noqa: E402


def run_cli(sub, data):
    proc = subprocess.run([PY, os.path.join(TOOLS, "cli.py"), sub], input=json.dumps(data),
                          capture_output=True, text=True, encoding="utf-8")
    return proc.returncode, json.loads(proc.stdout)


def _envelope(**kw):
    e = {
        "task_id": "task-1", "project_id": "proj-1", "request": "run QC",
        "skill_version": "1.0.0", "controller_version": "1.0.0",
        "timestamp": "2026-08-06T12:00:00+00:00",
    }
    e.update(kw)
    return e


def test_calibration_cli():
    code, out = run_cli("calibration", {
        "calibration_id": "cal-1", "instrument_id": "pH-1", "method": "linear",
        "status": "passed",
        "standards": [{"concentration": 1.0, "response": 2.0},
                      {"concentration": 2.0, "response": 4.0},
                      {"concentration": 3.0, "response": 6.0}]})
    assert code == 0
    assert out["result"]["r2"] == 1.0


def test_control_cli():
    code, out = run_cli("control", {
        "measurements": [{"measurement_id": "m0", "instrument_id": "pH-1", "sample_id": "s1",
                          "value": 14.0, "unit": "pH", "timestamp": "2026-08-01T10:00:00"}],
        "instruments": [{"instrument_id": "pH-1", "measurement_range": [0, 14], "saturation_threshold": 14.0}]})
    assert code == 0
    flags = [f["flag"] for f in out["result"]["flags"]]
    assert "SATURATION" in flags


def test_sample_chain_cli():
    code, out = run_cli("sample-chain", {"samples": [
        {"sample_id": "S-1", "collection_time": "2026-08-01T09:00:00"},
        {"sample_id": "S-1", "collection_time": "2026-08-01T09:00:00"}]})
    assert code == 0
    assert out["result"]["duplicate_ids"] == ["S-1"]


def test_integrity_log_cli(tmp_path):
    log = tmp_path / "audit.jsonl"
    code, out = run_cli("integrity", {"action": "log-append", "entry": {"kind": "qc", "task_id": "t1"},
                                      "log_path": str(log)})
    assert code == 0
    code2, out2 = run_cli("integrity", {"action": "log-verify", "log_path": str(log)})
    assert out2["result"]["chain_ok"] is True


def test_qc_pipeline_full():
    data = _envelope(requested_output_format="qc_report", qc_input={
        "instruments": [{"instrument_id": "pH-1", "kind": "pH", "model": "Mettler S220",
                         "measurement_range": [0, 14], "saturation_threshold": 14.0}],
        "calibrations": [{"calibration_id": "cal-1", "instrument_id": "pH-1", "method": "linear",
                          "status": "passed",
                          "standards": [{"concentration": 4.0, "response": -170.0},
                                        {"concentration": 7.0, "response": 0.0},
                                        {"concentration": 10.0, "response": 177.0}]}],
        "measurements": [{"measurement_id": "m0", "instrument_id": "pH-1", "sample_id": "s1",
                          "value": 7.02, "unit": "pH", "timestamp": "2026-08-01T10:00:00"}],
        "samples": [{"sample_id": "s1", "collection_time": "2026-08-01T09:00:00"}],
    })
    code, out = run_cli("qc", data)
    assert code == 0
    assert out["qc_report"]["overall_passed"] is True
    assert out["qc_report"]["calibration"]["r2"] > 0.999


def test_qc_pipeline_rejects_bad_units():
    data = _envelope(requested_output_format="qc_report", qc_input={
        "calibrations": [{"calibration_id": "cal-1", "instrument_id": "pH-1", "method": "linear",
                          "status": "passed",
                          "standards": [{"concentration": 4.0, "response": -170.0, "unit": "M"},
                                        {"concentration": 7.0, "response": 0.0, "unit": "mM"}]}]})
    code, out = run_cli("qc", data)
    assert code == 0  # pipeline reports, does not crash
    codes = [e["code"] for e in out["qc_report"]["errors"]]
    assert "MICQ-E1003" in codes


def test_check_self():
    code, out = run_cli("check-self", {})
    assert code == 0
    assert out["result"]["imports_ok"] is True
    assert "MICQ-E1001" in out["result"]["error_codes"]


def test_unknown_subcommand():
    code, out = run_cli("nope", {})
    assert code == 3
    assert out["errors"][0]["code"] == "MICQ-E1003"


def test_missing_required_schema_field():
    # Input missing required fields should be flagged by the pipeline's checks.
    code, out = run_cli("qc", {"requested_output_format": "qc_report", "qc_input": {}})
    assert code == 0
    assert out["qc_report"]["overall_passed"] is False
