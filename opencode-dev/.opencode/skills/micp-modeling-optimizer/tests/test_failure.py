"""Failure-path tests: every error code maps to the right status, and the
envelope stays valid on every failure (M5 adversarial interception)."""

from __future__ import annotations

import json

import pytest

from errors import MmoError, MmoErrorCode


class TestInputFailures:
    def test_malformed_json(self, invoke_cli) -> None:
        import subprocess
        import sys

        from pathlib import Path

        cli = Path(__file__).resolve().parent.parent / "tools" / "modeling.py"
        proc = subprocess.run([sys.executable, str(cli)], input="{not json",
                              capture_output=True, text=True, timeout=30)
        assert proc.returncode == 2
        out = json.loads(proc.stdout)
        assert out["status"] == "FAILED"
        assert out["errors"][0]["code"] == "MMO-E000"

    def test_unknown_action_blocked(self, base, invoke_cli) -> None:
        p = dict(base)
        p["action"] = "teleport"
        out = invoke_cli(p)
        assert out["status"] == "BLOCKED"
        assert "MMO-E103" in [e["code"] for e in out["errors"]]

    def test_bad_contract_version_blocked(self, base, invoke_cli) -> None:
        p = dict(base)
        p["action"] = "validate"
        p["contract_version"] = "2.0"
        out = invoke_cli(p)
        assert out["status"] == "BLOCKED"
        assert "MMO-E801" in [e["code"] for e in out["errors"]]

    def test_missing_action_blocked(self, base, invoke_cli) -> None:
        p = dict(base)
        p["action"] = None
        out = invoke_cli(p)
        assert out["status"] == "BLOCKED"
        assert "MMO-E103" in [e["code"] for e in out["errors"]]

    def test_missing_task_id_blocked(self, base, invoke_cli) -> None:
        p = dict(base)
        p["action"] = "validate"
        del p["task_id"]
        out = invoke_cli(p)
        assert out["status"] == "BLOCKED"
        assert "MMO-E101" in [e["code"] for e in out["errors"]]

    def test_unknown_kinetics_model_blocked(self, base, invoke_cli) -> None:
        p = dict(base)
        p["action"] = "solve"
        from test_integration import _model_spec

        spec = _model_spec()
        spec["kinetics"] = {"ureolysis": "banana_model"}
        p["model_specification"] = spec
        out = invoke_cli(p)
        assert out["status"] == "BLOCKED"
        assert "MMO-E104" in [e["code"] for e in out["errors"]]

    def test_missing_optimization_block_blocked(self, base, invoke_cli) -> None:
        p = dict(base)
        p["action"] = "optimize"
        out = invoke_cli(p)
        assert out["status"] == "BLOCKED"
        assert "MMO-E105" in [e["code"] for e in out["errors"]]

    def test_sensitivity_mismatch_blocked(self, base, invoke_cli) -> None:
        p = dict(base)
        p["action"] = "sensitivity"
        p["sensitivity"] = {"parameters": ["a", "b"], "bounds": [[0, 1]]}
        out = invoke_cli(p)
        assert out["status"] == "BLOCKED"
        assert "MMO-E106" in [e["code"] for e in out["errors"]]


class TestEnvelopeIntegrity:
    def test_blocked_envelope_has_missing_inputs(self, base, invoke_cli) -> None:
        p = dict(base)
        p["action"] = "solve"
        p["model_specification"] = {"purpose": "PREDICTION"}  # truncated spec
        out = invoke_cli(p)
        assert out["status"] == "BLOCKED"
        assert "missing_inputs" in out
        assert out["missing_inputs"], "BLOCKED must carry per-field guidance"

    def test_every_status_has_valid_envelope(self, base, invoke_cli) -> None:
        # drive several failure statuses and assert the envelope shape holds
        cases = [
            dict(base, action="validate", contract_version="9.9"),  # BLOCKED
            dict(base, action="solve"),  # BLOCKED (missing spec)
        ]
        for p in cases:
            out = invoke_cli(p)
            assert out["status"] in ("SUCCESS", "PARTIAL", "BLOCKED", "FAILED",
                                     "NEED_ADDITIONAL_SKILL", "HUMAN_APPROVAL_REQUIRED")
            assert "summary" in out
            assert isinstance(out["errors"], list)


class TestErrorCodes:
    def test_error_code_layout(self) -> None:
        # every code follows MMO-E### and the category mapping
        for member in MmoErrorCode:
            code = member.value[0]
            assert code.startswith("MMO-E")
            assert len(code) == 8  # MMO-E (5) + 3 digits
            cat = int(code[-3])
            assert 1 <= cat <= 8
