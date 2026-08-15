"""Failure-path and regression tests for obsidian-red-team.

Covers error codes, blocking invariants, and the "never announce completion
without a blocking-upgrade test" guarantee.
"""

from __future__ import annotations

from conftest import run_cli


class TestFailurePaths:
    def test_empty_stdin_envelope(self):
        from conftest import CLI
        import json
        import subprocess
        import sys
        import os
        proc = subprocess.run([sys.executable, CLI, "review"], input="",
                              capture_output=True, text=True,
                              cwd=os.path.dirname(os.path.dirname(CLI)))
        out = json.loads(proc.stdout or "{}")
        assert out["ok"] is False
        assert out["error"]["code"] == "ORT-E301"

    def test_invalid_json_stdin(self):
        from conftest import CLI
        import json
        import subprocess
        import sys
        import os
        proc = subprocess.run([sys.executable, CLI, "review"], input="{not json",
                              capture_output=True, text=True,
                              cwd=os.path.dirname(os.path.dirname(CLI)))
        out = json.loads(proc.stdout or "{}")
        assert out["ok"] is False
        assert out["error"]["code"] == "ORT-E301"

    def test_unknown_subcommand(self):
        out = run_cli("nonexistent", {})
        assert out["ok"] is False
        assert out["error"]["code"] == "ORT-E103"

    def test_version_mismatch(self, review_clean_payload):
        payload = dict(review_clean_payload)
        payload["skill_version"] = "2.0.0"
        out = run_cli("review", payload)
        assert out["ok"] is False
        assert out["error"]["code"] == "ORT-E801"

    def test_invalid_state_gate(self, review_clean_payload):
        payload = dict(review_clean_payload)
        payload["constraints"] = {"state_gate": "BOGUS"}
        out = run_cli("review", payload)
        assert out["ok"] is False
        assert out["error"]["code"] in ("ORT-E101", "ORT-E104")


class TestBlockingInvariants:
    """The system never announces success while BLOCKING findings are open."""

    def test_blocking_forces_blocked_status(self, review_blocked_payload):
        out = run_cli("review", review_blocked_payload)
        r = out["result"]
        assert r["status"] == "BLOCKED"
        assert r["state_recommendation"]["recommendation"] == "REVIEW_FAIL"

    def test_no_blocking_never_review_fail(self, review_clean_payload):
        out = run_cli("review", review_clean_payload)
        r = out["result"]
        assert r["blocking_findings"] == []
        assert r["state_recommendation"]["recommendation"] in ("APPROVE", "NO_OBJECTION")

    def test_check_self_rejects_success_with_blocking(self):
        bad = {
            "status": "SUCCESS",
            "findings": [{"finding_id": "b1"}],
            "blocking_findings": [{"finding_id": "b1"}],
            "state_recommendation": {"recommendation": "APPROVE", "blocking_count": 1},
        }
        out = run_cli("check-self", bad)
        assert out["result"]["valid"] is False
        assert any("BLOCKING" in i for i in out["result"]["issues"])


class TestRegression:
    """Regressions found during adversarial self-review."""

    def test_od600_urease_trap_not_weakened(self):
        # The MICP trap (OD600-as-urease) must never be downgraded to MINOR.
        out = run_cli("review", {
            "task_id": "reg-01", "project_id": "panshi-test",
            "request": "审查将 OD600 当作脲酶活性的结论",
            "skill_version": "1.0.0", "controller_version": "obsidian-ctl-0.1.0",
            "timestamp": "2026-08-07T11:00:00Z",
            "targets": [
                {"id": "T1", "type": "conclusion",
                 "summary": "菌株 OD600 达 1.5，脲酶活性显著提高",
                 "location": "data.xlsx", "epistemic_label": "INFERRED",
                 "claims": ["OD600 达到 1.5，表明脲酶活性显著提高"]},
            ],
        })
        r = out["result"]
        micp_findings = [f for f in r["findings"] if f["dimension"] == "micp_mechanism"]
        assert micp_findings, "OD600-as-urease trap must be detected"
        assert micp_findings[0]["severity"] in ("CRITICAL", "BLOCKING")

    def test_blocking_findings_never_mutate_conclusion(self, review_blocked_payload):
        # Red Team output must not contain any modified conclusion/data.
        out = run_cli("review", review_blocked_payload)
        r = out["result"]
        for f in r["findings"]:
            assert f["status"] in ("OPEN", "FIXED", "ACCEPTED_RISK", "VERIFIED")
        # No field in the output re-states a corrected conclusion.
        assert "corrected" not in r["summary"].lower()
        assert "修正结论" not in r["summary"]
