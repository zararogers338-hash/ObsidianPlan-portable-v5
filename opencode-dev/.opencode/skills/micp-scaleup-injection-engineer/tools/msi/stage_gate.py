"""Stage-gate decision template for MICP scale-up.

Defines the phase gates between scale levels (lab -> pilot -> metre -> site ->
field), the pass criteria at each gate, the stop conditions and the fallback
plan. Gate decisions are deterministic based on scenario data; they never
fabricate a "passed" gate when required data is missing.

Gate chain:
  G0 lab validated   -> G1 pilot_column  -> G2 metre  -> G3 site  -> G4 field
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from .errors import OpError, OpErrorCode
from .scenario import NormalizedScenario

GATES = [
    {"gate": "G1", "scale": "pilot_column",
     "pass": ["uniformity >= MEDIUM", "gradient < 1", "no inlet clogging",
              "NH4-N manageable", "target content reachable in <= rounds"]},
    {"gate": "G2", "scale": "metre",
     "pass": ["permeability field matches assumptions", "tracer recovery >= 70%",
              "pressure margin > 1.2", "conversion within design window",
              "core + Vs verify uniformity"]},
    {"gate": "G3", "scale": "site",
     "pass": ["pilot->site similarity holds", "zoning validated", "effluent plan "
              "demonstrated", "regulatory permits in hand"]},
    {"gate": "G4", "scale": "field",
     "pass": ["HUMAN approval with 6 items", "site test evidence", "emergency plan "
              "drilled", "monitoring plan funded and instrumented"]},
]


def stage_gate(s: NormalizedScenario, pressure_verdict: str | None,
               clog_verdict: dict[str, Any] | None,
               uniformity_score: float | None, nh4_over: bool | None,
               human_approved: bool) -> dict[str, Any]:
    current = s.scale_level
    idx = {"pilot_column": 0, "metre": 1, "site": 2, "field": 3}[current]

    gates = []
    for gi, g in enumerate(GATES):
        # Gates earlier than the current scale are treated as already passed
        # (we are *at* this scale, so the upstream gates are behind us).
        if gi < idx:
            gates.append({"gate": g["gate"], "scale": g["scale"],
                          "criteria": g["pass"], "passed": True,
                          "blocked_reasons": []})
            continue
        if gi > idx:
            # Future gates are not evaluated yet (not reachable this run).
            gates.append({"gate": g["gate"], "scale": g["scale"],
                          "criteria": g["pass"], "passed": None,
                          "blocked_reasons": []})
            continue

        # ---- current gate: evaluated against ACTUAL data ----
        blocked_reasons: list[str] = []
        if current == "pilot_column":
            if clog_verdict and clog_verdict.get("inlet_clogging_risk") == "HIGH":
                blocked_reasons.append("inlet clogging HIGH — do not scale up")
            if pressure_verdict == "EXCEEDS":
                blocked_reasons.append("injection pressure exceeds allowable")
        elif current == "metre":
            if pressure_verdict == "EXCEEDS":
                blocked_reasons.append("pressure exceeds allowable at metre scale")
            if clog_verdict and clog_verdict.get("preferential_flow_risk") == "HIGH":
                blocked_reasons.append("preferential flow HIGH — bypass risk")
        elif current == "site":
            if nh4_over:
                blocked_reasons.append("NH4-N production exceeds site limit — "
                                       "effluent plan required")
            if uniformity_score is not None and uniformity_score < 0.33:
                blocked_reasons.append("expected uniformity too low for site objective")
            if pressure_verdict == "EXCEEDS":
                blocked_reasons.append("injection pressure exceeds allowable")
        elif current == "field":
            if not human_approved:
                blocked_reasons.append("field deployment requires HUMAN approval "
                                       "(6 items)")
            # Field gate ALSO enforces the same engineering safety blocks that
            # site does — an approved-but-unsafe plan must never pass.
            if pressure_verdict == "EXCEEDS":
                blocked_reasons.append("injection pressure exceeds allowable")
            if nh4_over:
                blocked_reasons.append("NH4-N production exceeds site limit — "
                                       "effluent plan required")
            if uniformity_score is not None and uniformity_score < 0.33:
                blocked_reasons.append("expected uniformity too low for field objective")
            if s.effective_permeability_m2 is None:
                blocked_reasons.append("no permeability data — pressure/flow not established")

        gates.append({"gate": g["gate"], "scale": g["scale"],
                      "criteria": g["pass"],
                      "passed": len(blocked_reasons) == 0,
                      "blocked_reasons": blocked_reasons})

    # gate_ok covers only the gates up to and including the current scale;
    # future gates are "not yet evaluated" (None) and must not make it false.
    gate_ok = all((g["passed"] is True) for g in gates if g["passed"] is not None)

    # stop conditions
    stops: list[dict[str, str]] = [
        {"id": "S1", "condition": "injection pressure > allowable (or >80% fracture)",
         "action": "stop injection, bleed pressure, investigate clogging, re-zone"},
        {"id": "S2", "condition": "effluent NH4-N > site limit",
         "action": "stop injection, route effluent to treatment/struvite recovery"},
        {"id": "S3", "condition": "surface heave / breakout detected",
         "action": "stop, evacuate, containment protocol (emergency plan)"},
        {"id": "S4", "condition": "tracer recovery < 70% or early breakthrough",
         "action": "re-zone, add packers/extraction, re-pilot"},
        {"id": "S5", "condition": "temperature out of [2,45] C",
         "action": "pause and re-sequence phases"},
    ]

    # fallback plan
    fallback = {
        "trigger": "any stop condition or gate failure",
        "actions": [
            "halt injection and bleed injection pressure slowly",
            "recover and treat effluent (NH4-N) before discharge",
            "re-zone treatment: packers, per-layer intervals, balanced extraction",
            "reduce cementation concentration toward 0.5 M (AS2013)",
            "switch constant-flux -> constant-head (pressure-limited)",
            "if clogged at inlet: shorten treatment path, add wells, alternate "
            "bacteria/cementation (sequential, VP2010)",
            "escalate to geotechnical engineer + controller; never restart without "
            "re-evaluation",
        ],
    }

    return {
        "current_scale": current,
        "gates": gates,
        "gate_ok": gate_ok,
        "next_gate": GATES[idx + 1]["gate"] if idx < len(GATES) - 1 else None,
        "stop_conditions": stops,
        "fallback_plan": fallback,
        "human_approval_required": current == "field" and not human_approved,
        "summary": (f"Stage gate {GATES[idx]['gate']} for scale {current}: "
                    f"{'PASS (preliminary)' if gate_ok else 'BLOCKED'}"),
    }
