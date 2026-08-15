"""Regression tests for review-fix blockers (Red Team / Environment Auditor /
Decision Gate findings). These lock in the fixes so they cannot regress.

Fixes verified here:
  R1  Stage gate current gate now evaluates data (gate_ok meaningful)
  R2  Blocked gate -> status PARTIAL (not SUCCESS) + gate-block findings
  R3  Field approval enforced on EVERY action (not just scaleup)
  R4  NH4-N conservative accounting (from injected urea, not just precipitated)
  R5  Missing ammonia limit NOT silently fabricated as 50 mg/L
  R6  Groundwater plume reading -> stop
  R7  Monitoring stop signal -> status PARTIAL
  R8  Back-calculated flow reaches schedule (no zero durations)
  R9  Schedule retention accounting = len(phases)-1 gaps
  R10 Tracer NaN/injected_conc=0 -> honest verdict, no crash
  R11 Uniformity degrades with scale
  R12 nh4_over flag consistent between scaleup and stage_gate actions
"""

from __future__ import annotations

from conftest import make_payload, run


def _all_six_approvals(payload: dict) -> dict:
    p = dict(payload)
    site = dict(p.get("site") or {})
    for k in ("geotechnical_approval", "biosafety_review",
              "regulatory_verification", "construction_risk_assessment",
              "waste_ammonia_plan", "emergency_plan"):
        site[k] = {"approved": True}
    p["site"] = site
    p["human_approval_state"] = {"granted": True, "approver": "geo",
                                 "revision": 1, "scope": "field"}
    return p


class TestR1_StageGateMeaningful:
    def test_clean_metre_gate_passes(self):
        # Use a modest flow + generous allowable so the metre gate truly passes.
        p = make_payload()
        p["target"]["scale_level"] = "metre"
        p["lab"]["recipe"]["flow_rate"] = {"value": 5e-5, "unit": "m3/s"}
        p["constraints"]["allowed_injection_pressure"] = {"value": 2e6, "unit": "Pa"}
        out = run(p)
        sg = next(a["note"] for a in out["artifacts"] if a["kind"] == "stage_gate")
        assert sg["gate_ok"] is True
        assert sg["gates"][1]["passed"] is True  # metre gate evaluated, not False

    def test_exceeding_pressure_gate_blocks(self):
        p = make_payload()
        p["lab"]["recipe"]["flow_rate"] = {"value": 0.1, "unit": "m3/s"}
        p["constraints"]["allowed_injection_pressure"] = {"value": 20000, "unit": "Pa"}
        out = run(p)
        sg = next(a["note"] for a in out["artifacts"] if a["kind"] == "stage_gate")
        assert sg["gate_ok"] is False
        assert any("pressure" in b for g in sg["gates"] for b in g["blocked_reasons"])


class TestR2_GateBlockForcesPartial:
    def test_exceeding_pressure_not_success(self):
        p = make_payload()
        p["lab"]["recipe"]["flow_rate"] = {"value": 0.1, "unit": "m3/s"}
        p["constraints"]["allowed_injection_pressure"] = {"value": 20000, "unit": "Pa"}
        out = run(p)
        assert out["status"] == "PARTIAL"
        assert any("gate block" in f["statement"].lower()
                   for f in out["findings"])


class TestR3_FieldApprovalAllActions:
    def test_generate_tables_requires_approval(self):
        p = make_payload()
        p["target"]["scale_level"] = "field"
        p["target"]["geometry"] = {"volume": {"value": 1000, "unit": "m3"},
                                   "depth": {"value": 3, "unit": "m"}}
        p["action"] = "generate_tables"
        out = run(p)
        assert out["status"] == "HUMAN_APPROVAL_REQUIRED"

    def test_injection_schedule_requires_approval(self):
        p = make_payload()
        p["target"]["scale_level"] = "field"
        p["target"]["geometry"] = {"volume": {"value": 1000, "unit": "m3"},
                                   "depth": {"value": 3, "unit": "m"}}
        p["action"] = "injection_schedule"
        out = run(p)
        assert out["status"] == "HUMAN_APPROVAL_REQUIRED"

    def test_monitoring_plan_requires_approval(self):
        p = make_payload()
        p["target"]["scale_level"] = "field"
        p["target"]["geometry"] = {"volume": {"value": 1000, "unit": "m3"},
                                   "depth": {"value": 3, "unit": "m"}}
        p["action"] = "monitoring_plan"
        out = run(p)
        assert out["status"] == "HUMAN_APPROVAL_REQUIRED"


class TestR4_ConservativeNH4:
    def test_nh4_from_injected_urea(self):
        p = make_payload()
        out = run(p)
        mb = out["material_balance"]
        assert abs(mb["nh4_n_mol"] - 2.0 * mb["urea_mol"]) < 1e-6
        # conservative: strictly more than the precipitate-tied amount
        assert mb["nh4_n_mol"] > 2.0 * mb["caco3_mol"]

    def test_low_conversion_not_hiding_ammonia(self):
        """At VP2010's ~12% conversion, the ammonium from injected urea is
        ~8x the precipitate-tied amount and must be flagged."""
        p = make_payload()
        p["constraints"]["conversion_efficiency"] = 0.12
        p["constraints"]["ammonia_limit_mg_L"] = 50000
        out = run(p)
        env = out["environmental_requirements"]
        assert env["over_limit"] is True  # conservative count must not false-safe


class TestR5_MissingAmmoniaLimit:
    def test_no_silent_50_default(self):
        p = make_payload()
        del p["constraints"]["ammonia_limit_mg_L"]
        out = run(p)
        env = out["environmental_requirements"]
        assert env["limit_missing"] is True
        # monitoring plan must NOT fabricate 50 mg/L
        mp = out["monitoring_plan"]
        nh4_param = next(x for x in mp["parameters"] if x["name"] == "nh4_conc")
        assert nh4_param["thresholds"]["stop_high"] is None


class TestR6_GroundwaterPlumeStop:
    def test_gw_exceedance_stops(self):
        p = make_payload()
        p["monitoring"] = {"groundwater_nh4_mol_m3": 5.0,
                           "groundwater_baseline_nh4_mol_m3": 0.1}
        out = run(p)
        stops = [c["condition"] for c in out["stop_conditions"]]
        assert any("groundwater" in s for s in stops)


class TestR7_StopSignalForcesPartial:
    def test_monitoring_stop_partial(self):
        p = make_payload()
        p["monitoring"] = {"injection_pressure_pa": 900000}
        out = run(p)
        assert out["status"] == "PARTIAL"
        assert any(str(c.get("id", "")).startswith("RT-") for c in out["stop_conditions"])


class TestR8_FlowReachesSchedule:
    def test_back_calculated_flow_not_zero_duration(self):
        p = make_payload()
        del p["lab"]["recipe"]["flow_rate"]  # no lab flow -> boundary derives it
        out = run(p)
        bc = out["pressure_constraints"]
        sched = out["injection_schedule"]
        mb = out["material_balance"]
        assert bc.get("injection_flow_m3_s") is not None
        assert mb.get("injection_flow_m3_s") == bc["injection_flow_m3_s"]
        assert sched["total_duration_days"] > 0
        # cementation phases all have positive durations with the derived flow
        cementation = [ph for ph in sched["phases"] if ph["phase"] == "cementation"]
        assert cementation
        assert all(ph.get("duration_days", 0) > 0 for ph in cementation)
        assert all(ph.get("flow_rate_m3_s") == bc["injection_flow_m3_s"]
                   for ph in sched["phases"] if ph.get("flow_rate_m3_s") is not None)


class TestR9_RetentionAccounting:
    def test_retention_gaps_are_phases_minus_one(self):
        p = make_payload()
        p["constraints"]["retention_time"] = {"value": 86400, "unit": "s"}  # 1 day
        out = run(p)
        sched = out["injection_schedule"]
        n_phases = len(sched["phases"])
        # phase durations are tiny (~0.003 d); total ≈ (n_phases-1) retention days
        assert sched["total_duration_days"] > (n_phases - 1) * 0.9
        assert sched["total_duration_days"] < (n_phases - 1) * 1.1 + 0.1


class TestR10_TracerHonestVerdict:
    def test_zero_injected_conc_no_crash(self):
        p = make_payload()
        p["tracer"] = {"time_s": [0, 1, 2], "conc": [0, 1, 0.5],
                       "injected_conc": 0}
        out = run(p)
        assert out["status"] in ("SUCCESS", "PARTIAL", "BLOCKED")
        ta = next((a["note"] for a in out["artifacts"] if a["kind"] == "tracer_analysis"), None)
        if ta is not None:
            assert ta["recovered_fraction"] is None
            assert "could not be computed" in ta["verdict"]


class TestR11_UniformityScalePenalty:
    def test_field_uniformity_penalized(self):
        p_metre = make_payload()
        p_metre["target"]["scale_level"] = "metre"
        p_field = make_payload()
        p_field["target"]["scale_level"] = "field"
        p_field["target"]["geometry"] = {"volume": {"value": 1000, "unit": "m3"},
                                         "depth": {"value": 3, "unit": "m"}}
        p_field = _all_six_approvals(p_field)
        out_m = run(p_metre)
        out_f = run(p_field)
        cr_m = next(a["note"] for a in out_m["artifacts"] if a["kind"] == "clogging_risk")
        cr_f = next(a["note"] for a in out_f["artifacts"] if a["kind"] == "clogging_risk")
        assert cr_f["uniformity_score"] < cr_m["uniformity_score"]


class TestR12_Nh4OverConsistent:
    def test_stage_gate_and_scaleup_agree(self):
        # limit high enough that conservative NH4 is under it
        p1 = make_payload()
        p1["constraints"]["ammonia_limit_mg_L"] = 200000
        out_scale = run(p1)
        sg_scale = next(a["note"] for a in out_scale["artifacts"] if a["kind"] == "stage_gate")
        assert any("NH4" not in b for g in sg_scale["gates"] for b in g["blocked_reasons"])

        p2 = make_payload()
        p2["constraints"]["ammonia_limit_mg_L"] = 200000
        p2["action"] = "stage_gate"
        out_gate = run(p2)
        sg_gate = next(a["note"] for a in out_gate["artifacts"] if a["kind"] == "stage_gate")
        # neither may claim NH4 over-limit
        for g in sg_gate["gates"]:
            assert not any("NH4" in b for b in g["blocked_reasons"])
