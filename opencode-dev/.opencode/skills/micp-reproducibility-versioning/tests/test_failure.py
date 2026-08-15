"""Failure-path tests: hostile input, missing fields, adversarial requests.

Proves the tools never crash on hostile input and always return a clean error
envelope or a structured BLOCKED with per-field guidance.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys

import pytest

from conftest import base_payload, make_sandbox, run_cli


class TestHostileInput:
    def test_empty_stdin_clean_error(self) -> None:
        script = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                              "tools", "mrv", "cli.py")
        proc = subprocess.run([sys.executable, script, "env"], input="",
                              capture_output=True, text=True,
                              cwd=os.path.dirname(script))
        env = json.loads(proc.stdout)
        assert env["ok"] is False
        assert env["error"]["code"] == "E_INPUT_EMPTY"

    def test_invalid_json_clean_error(self) -> None:
        script = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                              "tools", "mrv", "cli.py")
        proc = subprocess.run([sys.executable, script, "env"], input="{oops",
                              capture_output=True, text=True,
                              cwd=os.path.dirname(script))
        env = json.loads(proc.stdout)
        assert env["ok"] is False
        assert env["error"]["code"] == "E_INPUT_INVALID_JSON"

    def test_non_object_envelope_clean_error(self) -> None:
        script = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                              "tools", "mrv", "cli.py")
        proc = subprocess.run([sys.executable, script, "env"], input="[1,2]",
                              capture_output=True, text=True,
                              cwd=os.path.dirname(script))
        env = json.loads(proc.stdout)
        assert env["ok"] is False

    def test_unknown_subcommand(self) -> None:
        env = run_cli("frobnicate", {"a": 1}, expect_exit=2)
        assert env["ok"] is False
        assert env["error"]["code"] == "MRV-E103"

    def test_non_finite_number_rejected(self) -> None:
        env = run_cli("env", {"nan": float("nan")}, expect_exit=2)
        assert env["ok"] is False
        assert env["error"]["code"] == "E_NUMERIC_NON_FINITE"


class TestMissingInputs:
    def test_service_blocks_with_field_guidance(self, tmp_path) -> None:
        root = make_sandbox(tmp_path)
        p = base_payload(root)
        del p["request"]
        env = run_cli("service", p)
        assert env["result"]["status"] == "BLOCKED"
        assert env["result"]["errors"][0]["code"] == "MRV-E101"
        fields = [m["field"] for m in env["result"]["missing_inputs"]]
        assert "request" in fields

    def test_reproduce_without_commands_blocked(self, tmp_path) -> None:
        root = make_sandbox(tmp_path)
        env = run_cli("reproduce", base_payload(root, action="reproduce"), expect_exit=2)
        assert env["ok"] is False
        assert env["error"]["code"] == "MRV-E105"

    def test_diff_without_baseline_blocked(self, tmp_path) -> None:
        root = make_sandbox(tmp_path)
        env = run_cli("diff", base_payload(root, action="diff"), expect_exit=2)
        assert env["ok"] is False
        assert env["error"]["code"] == "MRV-E102"

    def test_compat_without_schema_versions_blocked(self, tmp_path) -> None:
        root = make_sandbox(tmp_path)
        env = run_cli("compat", base_payload(root, action="compat"), expect_exit=2)
        assert env["ok"] is False
        assert env["error"]["code"] == "MRV-E102"

    def test_root_unreadable(self, tmp_path) -> None:
        env = run_cli("env", {
            "task_id": "t", "project_id": "p", "request": "x",
            "skill_version": "1.0.0", "controller_version": "c",
            "timestamp": "2026-08-07T00:00:00Z",
            "root": str(tmp_path / "does-not-exist")}, expect_exit=2)
        assert env["ok"] is False
        assert env["error"]["code"] == "MRV-E104"


class TestAdversarial:
    def test_path_escape_rejected(self, tmp_path) -> None:
        root = make_sandbox(tmp_path)
        env = run_cli("manifest", base_payload(
            root, action="manifest", targets=["../escape"]), expect_exit=2)
        assert env["ok"] is False
        assert env["error"]["code"] == "MRV-E302"

    def test_fabricated_evidence_never_cited(self, tmp_path) -> None:
        root = make_sandbox(tmp_path)
        p = base_payload(root, action="env", evidence_refs=[
            {"ref_id": "doi:10.1000/xyz", "locator": "https://doi.org/10.1000/xyz"}])
        env = run_cli("service", p)
        assert env["result"]["status"] == "SUCCESS"
        refs = [e["ref_id"] for e in env["result"]["evidence_used"]]
        assert "doi:10.1000/xyz" in refs
        # no fabricated ref beyond the provided ones
        assert set(refs) <= {"doi:10.1000/xyz"}

    def test_high_risk_without_approval(self, tmp_path) -> None:
        root = make_sandbox(tmp_path)
        p = base_payload(root, action="env",
                         risk_level="high",
                         human_approval_state="not_required",
                         request="现场注入并评估环境影响，采集环境信息")
        env = run_cli("service", p)
        assert env["result"]["status"] == "HUMAN_APPROVAL_REQUIRED"
        assert env["result"]["errors"][0]["code"] == "MRV-E502"

    def test_high_risk_with_approval_proceeds(self, tmp_path) -> None:
        root = make_sandbox(tmp_path)
        p = base_payload(root, action="env",
                         risk_level="high",
                         human_approval_state="approved",
                         request="现场注入并评估环境影响，采集环境信息")
        env = run_cli("service", p)
        assert env["result"]["status"] == "SUCCESS"
