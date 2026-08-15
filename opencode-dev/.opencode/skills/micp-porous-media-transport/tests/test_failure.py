"""Failure-path tests: missing input, bad units, bad versions, non-JSON stdin."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from conftest import CLI, SMOKE_SCENARIO, cli_call, deep_copy_smoke


def _payload(base, action, **extra):
    p = dict(base)
    p["action"] = action
    p.update(extra)
    return p


class TestModelBlocked:
    def test_missing_porosity_blocked(self, base):
        scenario = deep_copy_smoke()
        del scenario["porosity"]
        out = cli_call(_payload(base, "analyze", scenario=scenario), expect_ok=False)
        assert out["status"] == "BLOCKED"
        assert out["errors"][0]["code"] == "OPM-E102"
        fields = {m["field"] for m in out["errors"][0]["detail"]["missing_fields"]}
        assert "porosity" in fields
        assert out["errors"][0]["detail"]["missing_fields"][0]["why_critical"]
        assert out["errors"][0]["detail"]["missing_fields"][0]["how_to_obtain"]

    def test_missing_flow_blocked(self, base):
        scenario = deep_copy_smoke()
        del scenario["flow"]
        out = cli_call(_payload(base, "analyze", scenario=scenario), expect_ok=False)
        assert out["status"] == "BLOCKED"
        fields = {m["field"] for m in out["errors"][0]["detail"]["missing_fields"]}
        assert "flow" in fields

    def test_missing_scenario_entirely_blocked(self, base):
        out = cli_call(_payload(base, "analyze"), expect_ok=False)
        assert out["status"] == "BLOCKED"


class TestUnitFailures:
    def test_bad_unit_blocks(self, base):
        scenario = deep_copy_smoke()
        scenario["porosity"] = {"value": 0.4, "unit": "m2/s"}  # wrong family
        out = cli_call(_payload(base, "analyze", scenario=scenario), expect_ok=False)
        assert out["status"] == "BLOCKED"
        assert out["errors"][0]["code"] == "OPM-E202"

    def test_out_of_range_blocks(self, base):
        scenario = deep_copy_smoke()
        scenario["porosity"] = {"value": 1.5, "unit": "-"}
        out = cli_call(_payload(base, "analyze", scenario=scenario), expect_ok=False)
        assert out["status"] == "BLOCKED"
        assert out["errors"][0]["code"] == "OPM-E204"

    def test_unknown_unit_blocks(self, base):
        scenario = deep_copy_smoke()
        scenario["geometry"]["length"] = {"value": 1, "unit": "furlong"}
        out = cli_call(_payload(base, "analyze", scenario=scenario), expect_ok=False)
        assert out["status"] == "BLOCKED"
        assert out["errors"][0]["code"] == "OPM-E203"


class TestVersionGate:
    def test_contract_v2_rejected(self, base, smoke_scenario):
        p = _payload(base, "analyze", scenario=smoke_scenario)
        p["contract_version"] = "2.0"
        out = cli_call(p, expect_ok=False)
        assert out["status"] == "BLOCKED"
        assert out["errors"][0]["code"] == "OPM-E801"

    def test_unknown_action(self, base, smoke_scenario):
        out = cli_call(_payload(base, "not.a.real.action", scenario=smoke_scenario),
                       expect_ok=False)
        assert out["status"] == "BLOCKED"
        assert out["errors"][0]["code"] == "OPM-E103"


class TestMalformedStdin:
    def test_non_json_stdin_returns_envelope(self):
        proc = subprocess.run([sys.executable, str(CLI)],
                              input="not json at all", capture_output=True, text=True)
        assert proc.returncode == 0
        out = json.loads(proc.stdout)
        assert out["status"] == "BLOCKED"
        assert out["errors"]

    def test_json_array_stdin_returns_envelope(self):
        proc = subprocess.run([sys.executable, str(CLI)],
                              input="[1,2,3]", capture_output=True, text=True)
        out = json.loads(proc.stdout)
        assert out["status"] == "BLOCKED"


class TestApprovalGating:
    def test_high_risk_analyze_without_approval_blocked(self, base, smoke_scenario):
        """Field-scale scenarios are approval-gated; must not silently run."""
        p = _payload(base, "analyze", scenario=smoke_scenario)
        p["scenario"]["scale"] = "field"
        out = cli_call(p, expect_ok=False)
        assert out["status"] in ("BLOCKED", "HUMAN_APPROVAL_REQUIRED")
