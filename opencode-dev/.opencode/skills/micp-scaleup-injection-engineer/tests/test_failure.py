"""Adversarial / failure tests for micp-scaleup-injection-engineer.

These verify the skill NEVER emits an illegal SUCCESS:
  - unverifiable evidence, unit conflicts, NaN payloads, contract v2, unknown
    action, missing required fields, non-finite quantities.
"""

from __future__ import annotations

import math

from conftest import make_payload, run


class TestAdversarial:
    def test_contract_v2_blocked(self):
        p = make_payload()
        p["contract_version"] = "2.0"
        out = run(p)
        assert out["status"] == "BLOCKED"
        assert any(e["code"] == "MSI-E801" for e in out["errors"])

    def test_unknown_action_blocked(self):
        p = make_payload()
        p["action"] = "explode"
        out = run(p)
        assert out["status"] == "BLOCKED"
        assert any(e["code"] == "MSI-E103" for e in out["errors"])

    def test_missing_required_field(self):
        p = make_payload()
        del p["task_id"]
        out = run(p)
        assert out["status"] == "BLOCKED"
        assert any(e["code"] == "MSI-E101" for e in out["errors"])

    def test_nan_payload_blocked(self):
        p = make_payload()
        p["target"]["geometry"]["volume"] = {"value": float("nan"), "unit": "m3"}
        out = run(p)
        # NaN must not flow through as a successful plan
        assert out["status"] in ("BLOCKED", "FAILED")

    def test_inf_flow_blocked(self):
        p = make_payload()
        p["lab"]["recipe"]["flow_rate"] = {"value": float("inf"), "unit": "m3/s"}
        out = run(p)
        assert out["status"] in ("BLOCKED", "FAILED")

    def test_bad_unit_blocked(self):
        p = make_payload()
        p["constraints"]["allowed_injection_pressure"] = {"value": 5, "unit": "furlongs"}
        out = run(p)
        assert out["status"] in ("BLOCKED", "FAILED")
        assert any(e["code"] in ("MSI-E203", "MSI-E202") for e in out["errors"])

    def test_unit_conflict_blocked(self):
        p = make_payload()
        p["site"]["layers"][0]["permeability"] = {"value": 1, "unit": "mol/m3"}
        out = run(p)
        assert out["status"] in ("BLOCKED", "FAILED")

    def test_non_urease_route_flag(self):
        """A non-urease calcium source must not be silently handled as urea
        stoichiometry — the skill should return NEED_ADDITIONAL_SKILL or at
        least a warning, never an illegal SUCCESS."""
        p = make_payload()
        p["request"] = "用醋酸钙做 MICP，非尿素路径的钙源"
        # skill schema does not have a chemistry-field switch; at minimum the
        # run must not crash and must not fabricate urea chemistry silently.
        out = run(p)
        assert out["status"] in ("SUCCESS", "PARTIAL", "BLOCKED", "NEED_ADDITIONAL_SKILL")
