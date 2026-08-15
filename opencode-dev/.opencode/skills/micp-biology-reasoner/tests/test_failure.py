"""Failure-mode and adversarial tests (spec §五, §十二: never only happy path)."""

from __future__ import annotations


class TestInputContract:
    def test_missing_contract_version_blocked(self, base, invoke_cli):
        payload = dict(base)
        del payload["contract_version"]
        out = invoke_cli(payload)
        assert out["status"] == "BLOCKED"
        assert out["errors"][0]["code"] == "MBR-E101"
        detail = out["errors"][0]["detail"]
        assert any("contract_version" in v for v in detail["violations"])

    def test_contract_v2_rejected(self, base, invoke_cli):
        payload = dict(base)
        payload["contract_version"] = "2.0"
        payload["action"] = "compare"
        out = invoke_cli(payload)
        assert out["status"] == "FAILED"
        assert out["errors"][0]["code"] == "MBR-E801"

    def test_unknown_action_blocked(self, base, invoke_cli):
        # `action` is an enum in the input schema, so an unknown action is a
        # contract violation and is blocked at schema validation (BLOCKED).
        payload = dict(base)
        payload["action"] = "not.a.real.action"
        out = invoke_cli(payload)
        assert out["status"] == "BLOCKED"
        assert out["errors"][0]["code"] == "MBR-E101"

    def test_additional_property_rejected(self, base, invoke_cli):
        payload = dict(base)
        payload["action"] = "compare"
        payload["sneaky"] = True
        out = invoke_cli(payload)
        assert out["status"] == "BLOCKED"
        assert out["errors"][0]["code"] == "MBR-E101"

    def test_missing_task_id_named(self, base, invoke_cli):
        payload = dict(base)
        del payload["task_id"]
        out = invoke_cli(payload)
        assert out["status"] == "BLOCKED"
        # The field name must be discoverable in the violation detail.
        text = repr(out["errors"][0]["detail"])
        assert "task_id" in text

    def test_non_json_stdin(self, invoke_cli):
        # drive the CLI directly with garbage
        import json
        import subprocess
        import sys
        from pathlib import Path

        cli = Path(__file__).resolve().parent.parent / "tools" / "micp_bio_reasoner.py"
        proc = subprocess.run(
            [sys.executable, str(cli)], input="not json{{{", capture_output=True, text=True, timeout=60)
        assert proc.returncode == 0
        out = json.loads(proc.stdout)
        assert out["status"] == "BLOCKED"
        assert out["errors"][0]["code"] == "MBR-E101"


class TestBiologyGates:
    def test_od600_not_activity_unit(self, base, invoke_cli):
        payload = dict(base)
        payload["action"] = "convert"
        payload["culture"] = {"urease_activity": 5.0, "urease_activity_unit": "OD600"}
        payload["metric_query"] = {"kind": "activity_normalization"}
        out = invoke_cli(payload)
        assert out["status"] == "FAILED"
        assert out["errors"][0]["code"] == "MBR-E204"

    def test_cell_conc_without_calibration(self, base, invoke_cli):
        payload = dict(base)
        payload["action"] = "convert"
        payload["culture"] = {"od600": 1.0}
        payload["metric_query"] = {"kind": "cell_concentration"}
        out = invoke_cli(payload)
        assert out["status"] == "FAILED"
        assert out["errors"][0]["code"] == "MBR-E203"

    def test_nan_activity_rejected(self, base, invoke_cli):
        payload = dict(base)
        payload["action"] = "compare"
        payload["culture"] = {"od600": 1.0, "urease_activity": "NaN", "urease_activity_unit": "U/mL"}
        payload["baseline"] = {"culture": {"od600": 1.0, "urease_activity": 2.0, "urease_activity_unit": "U/mL"}}
        out = invoke_cli(payload)
        # NaN is not JSON; ensure it's handled gracefully (rejected or BLOCKED).
        assert out["status"] in ("BLOCKED", "FAILED")
        assert out["errors"]


class TestSelfCheck:
    def test_self_check_passed_flag(self, base, invoke_cli):
        payload = dict(base)
        payload["action"] = "assess"
        payload["treatment"] = "bioaugmentation"
        out = invoke_cli(payload)
        assert out["status"] == "SUCCESS"
        assert out["validation"]["self_check"] == "passed"
        assert out["validation"]["output_schema"] == "passed"

    def test_high_risk_requests_biosafety_audit(self, base, invoke_cli):
        payload = dict(base)
        payload["action"] = "assess"
        payload["treatment"] = "bioaugmentation"
        payload["risk_level"] = "high"
        out = invoke_cli(payload)
        assert out["status"] == "SUCCESS"
        skills = [r["skill"] for r in out["requested_next_skills"]]
        assert "obsidian-env-biosafety-audit" in skills
