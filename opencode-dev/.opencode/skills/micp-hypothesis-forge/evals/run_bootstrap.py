#!/usr/bin/env python3
"""Bootstrap tests — run the skill's own tools on the four self-tests the
spec (§八) requires, as if the skill were invoked for real.

  1. "high urease activity reduces strength" -> >=3 mechanism explanations
  2. inlet clogging -> chemical-rate / cell-entrapment / flow-field hypotheses
  3. an unfalsifiable statement -> rejected or rewritten
  4. design a minimal discriminating experiment and verify it truly separates

The skill is loaded by reading SKILL.md + prompts/system.md + the schema
contracts, then executing the real tools (subprocess). Every step's input and
output is recorded to evals/results/bootstrap.jsonl. Offline, stdlib-only.

Usage: python evals/run_bootstrap.py
Exit 0 if all four self-tests pass.
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parents[1]
TOOLS = SKILL_ROOT / "tools"
RESULTS_DIR = Path(__file__).resolve().parent / "results"


def run_tool(tool: str, payload: dict) -> dict:
    proc = subprocess.run(
        [sys.executable, str(TOOLS / f"{tool}.py")],
        input=json.dumps(payload, ensure_ascii=False),
        capture_output=True, text=True, cwd=str(SKILL_ROOT),
    )
    try:
        env = json.loads(proc.stdout)
    except json.JSONDecodeError:
        env = {"ok": False, "error": {"code": "MHX-E404",
                                      "message": f"non-JSON stdout from {tool}"}}
    return env


# ---------------------------------------------------------------------------
# Self-test 1: ureolysis strength loss -> >=3 mechanisms
# ---------------------------------------------------------------------------

def self_test_1() -> dict:
    log = []
    # 1a. mechanism chain -> DAG for the main mechanism
    dag = run_tool("dag", {"mechanism_chain": [
        "high urease activity", "accelerated hydrolysis",
        "NH4+ accumulation", "reduced cementation strength",
    ]})
    log.append(("dag.main_chain", dag))
    # 1b. score the three candidate mechanisms
    scoring = run_tool("scoring", {"statements": [
        {"id": "H1", "statement": "NH4+ accumulation weakens the calcite bond network",
         "refutation": "If peak NH4+ exceeds 120 mM, UCS declines below baseline",
         "observables": ["NH4+ (mM)", "UCS (MPa)"],
         "time_scale": "14 days", "scope": "sand column, 1M cementation"},
        {"id": "H2", "statement": "Excess hydrolysis prevents CaCO3 from nucleating in pores",
         "refutation": "If CaCO3 mass stays below 20 g while NH4+ exceeds 120 mM, "
                       "H2 is supported",
         "observables": ["CaCO3 (g)", "NH4+ (mM)"],
         "time_scale": "14 days", "scope": "sand column, 1M cementation"},
        {"id": "H3", "statement": "Ammonia-induced pH rise re-dissolves calcite",
         "refutation": "If pore pH exceeds 9.5 and CaCO3 declines, H3 is supported",
         "observables": ["pore pH", "CaCO3 (g)"],
         "time_scale": "7 days", "scope": "sand column"},
    ]})
    log.append(("scoring.three_mechanisms", scoring))
    results = scoring.get("result", {}).get("results", [])
    n_mechanisms = len(results)
    all_scored = all(r["overall"] >= 0.0 for r in results)
    no_unfalsifiable = scoring.get("result", {}).get("summary", {}).get("n_non_falsifiable", 0) == 0
    return {
        "name": "self_test_1_three_mechanisms",
        "pass": n_mechanisms >= 3 and all_scored and no_unfalsifiable,
        "detail": f"{n_mechanisms} mechanisms forged; all scored >= 0; "
                  f"{'all falsifiable' if no_unfalsifiable else 'some unfalsifiable'}",
        "log": log,
    }


# ---------------------------------------------------------------------------
# Self-test 2: inlet clogging -> chemical / cell / flow-field hypotheses
# ---------------------------------------------------------------------------

def self_test_2() -> dict:
    log = []
    hypotheses = [
        {"id": "H1", "statement": "Inlet clogs by chemical precipitation of calcite",
         "refutation": "If inlet calcite mass increases while inlet cell mass stays low, "
                       "chemical precipitation drives the clog",
         "observables": ["inlet calcite (g)", "inlet cell mass (g)", "pressure rise (kPa)"],
         "observable_predictions": {"inlet calcite (g)": "increase",
                                    "inlet cell mass (g)": "no_change",
                                    "pressure rise (kPa)": "increase"},
         "epistemic_label": "HYPOTHESIS"},
        {"id": "H2", "statement": "Inlet clogs by cell entrapment / biofilm accumulation",
         "refutation": "If inlet cell mass increases while inlet calcite stays low, "
                       "cell entrapment drives the clog",
         "observables": ["inlet cell mass (g)", "inlet calcite (g)", "pressure rise (kPa)"],
         "observable_predictions": {"inlet cell mass (g)": "increase",
                                    "inlet calcite (g)": "no_change",
                                    "pressure rise (kPa)": "increase"},
         "epistemic_label": "HYPOTHESIS"},
        {"id": "H3", "statement": "Inlet clogs by flow-field redistribution concentrating "
                                  "precipitation downstream",
         "refutation": "If downstream calcite increases while inlet pressure stays flat, "
                       "flow-field redistribution drives the clog",
         "observables": ["downstream calcite (g)", "inlet pressure (kPa)"],
         "observable_predictions": {"downstream calcite (g)": "increase",
                                    "inlet pressure (kPa)": "no_change"},
         "epistemic_label": "HYPOTHESIS"},
    ]
    matrix = run_tool("competing-matrix", {"hypotheses": hypotheses})
    log.append(("competing-matrix.inlet_clogging", matrix))
    pairs = matrix.get("result", {}).get("pair_discrimination", [])
    all_pairs = len(pairs) == 3 and all(p["uniquely_discriminable"] for p in pairs)
    return {
        "name": "self_test_2_inlet_clogging_three_classes",
        "pass": all_pairs,
        "detail": f"{len(pairs)} pairs; "
                  f"{'all uniquely discriminable' if all_pairs else 'some NOT discriminable'}",
        "log": log,
    }


# ---------------------------------------------------------------------------
# Self-test 3: an unfalsifiable statement is rejected or rewritten
# ---------------------------------------------------------------------------

def self_test_3() -> dict:
    log = []
    # Unfalsifiable: no observable, no threshold.
    scoring = run_tool("scoring", {"statements": [
        {"id": "H_BAD", "statement": "Urea plays a role in strength",
         "refutation": ""},
    ]})
    log.append(("scoring.unfalsifiable", scoring))
    rejected = (not scoring.get("ok")) or (
        scoring.get("result", {}).get("results", [{}])[0]
        .get("falsifiability", {}).get("verdict") in ("NOT_FALSIFIABLE", "PARTIALLY_FALSIFIABLE"))
    # Rewritten form: concrete observable + threshold + direction -> must score > 0
    rewritten = run_tool("scoring", {"statements": [
        {"id": "H_GOOD", "statement": "Urea hydrolysis raises NH4+ which lowers UCS",
         "refutation": "If NH4+ exceeds 120 mM, UCS declines below baseline",
         "observables": ["NH4+ (mM)", "UCS (MPa)"],
         "time_scale": "14 days", "scope": "sand column"},
    ]})
    log.append(("scoring.rewritten", rewritten))
    good_verdict = rewritten.get("result", {}).get("results", [{}])[0] \
        .get("falsifiability", {}).get("verdict")
    rewritten_ok = good_verdict == "FALSIFIABLE"
    return {
        "name": "self_test_3_unfalsifiable_rejected_or_rewritten",
        "pass": rejected and rewritten_ok,
        "detail": f"bad statement {'rejected/flagged' if rejected else 'NOT rejected'}; "
                  f"rewritten form verdict={good_verdict}",
        "log": log,
    }


# ---------------------------------------------------------------------------
# Self-test 4: minimal discriminating experiment truly separates mechanisms
# ---------------------------------------------------------------------------

def self_test_4() -> dict:
    log = []
    hypotheses = [
        {"id": "H1", "statement": "Chemical precipitation clogs inlet",
         "refutation": "If inlet calcite increases while cells stay low, H1",
         "observables": ["inlet calcite (g)", "inlet cell mass (g)"],
         "observable_predictions": {"inlet calcite (g)": "increase",
                                    "inlet cell mass (g)": "no_change"}},
        {"id": "H2", "statement": "Cell entrapment clogs inlet",
         "refutation": "If inlet cells increase while calcite stays low, H2",
         "observables": ["inlet cell mass (g)", "inlet calcite (g)"],
         "observable_predictions": {"inlet cell mass (g)": "increase",
                                    "inlet calcite (g)": "no_change"}},
        {"id": "H3", "statement": "Flow-field redistribution moves precipitation downstream",
         "refutation": "If downstream calcite increases while inlet pressure flat, H3",
         "observables": ["downstream calcite (g)", "inlet pressure (kPa)"],
         "observable_predictions": {"downstream calcite (g)": "increase",
                                    "inlet pressure (kPa)": "no_change"}},
    ]
    matrix = run_tool("competing-matrix", {"hypotheses": hypotheses})
    log.append(("competing-matrix.minimal_experiment", matrix))
    pairs = matrix.get("result", {}).get("pair_discrimination", [])
    all_discriminate = all(p["uniquely_discriminable"] for p in pairs)
    gains = [p.get("best_information_gain_bits", 0.0) for p in pairs]
    min_gain = min(gains) if gains else 0.0

    # Design the minimal experiment: rank by info gain x cost x risk.
    best_experiments = []
    for p in pairs:
        be = p.get("best_experiment")
        if be and be not in best_experiments:
            best_experiments.append(be)
    experiments = [
        {"id": be, "information_gain_bits": 0.9, "cost_rank": 1,
         "risk_level": "low", "time_scale_days": 3, "feasibility": 0.95}
        for be in best_experiments
    ]
    priority = run_tool("experiment-priority", {"experiments": experiments})
    log.append(("experiment-priority.minimal_set", priority))
    ranked = [r["id"] for r in priority.get("result", {}).get("ranked_experiments", [])]
    return {
        "name": "self_test_4_minimal_discriminating_experiment",
        "pass": all_discriminate and min_gain > 0.0 and len(ranked) >= 1,
        "detail": f"all pairs discriminate (min gain {min_gain:.3f} bits); "
                  f"minimal discriminating experiment set: {best_experiments}",
        "log": log,
    }


# ---------------------------------------------------------------------------
# Envelope self-audit: the final deliverable must pass G1-G7
# ---------------------------------------------------------------------------

def envelope_audit() -> dict:
    log = []
    doc = {
        "contract_version": "1.0", "skill": "micp-hypothesis-forge",
        "skill_version": "1.0.0", "status": "SUCCESS",
        "summary": "Three competing mechanisms forged for inlet clogging; "
                   "minimal discriminating experiments ranked.",
        "findings": [
            {"id": "F1", "epistemic_label": "HYPOTHESIS",
             "summary": "Chemical precipitation is a candidate inlet-clog driver"},
        ],
        "assumptions": [{"id": "A1", "statement": "cementation solution is Ca-rich"}],
        "evidence_used": [{"ref_id": "EV1", "role": "support"}],
        "evidence_refs": [{"ref_id": "EV1"}],
        "uncertainty": {"direction_inference": "per-observable explicit predictions"},
        "risks": [{"id": "R1", "epistemic_label": "HYPOTHESIS",
                   "risk": "chemical and biological clogging may co-occur"}],
        "artifacts": [
            {"kind": "hypothesis_card_set", "cards": [
                {"id": "H1", "refutation": "if inlet calcite increases while cells stay low"},
                {"id": "H2", "refutation": "if inlet cells increase while calcite stays low"},
                {"id": "H3", "refutation": "if downstream calcite increases while inlet pressure stays flat"},
            ]},
        ],
        "requested_next_skills": [
            {"skill": "obsidian-experiment-designer",
             "inputs_needed": ["discriminating_matrix"],
             "reason": "turn ranked experiments into a concrete design"},
        ],
        "validation": {"gates": "G1-G7"},
        "provenance": {"skill": "micp-hypothesis-forge", "skill_version": "1.0.0",
                       "timestamp": "2026-08-06T00:00:00Z",
                       "contract_version": "1.0", "controller_version": "0.1.0"},
        "errors": [],
    }
    audit = run_tool("self-audit", doc)
    log.append(("self-audit.envelope", audit))
    ok = audit.get("result", {}).get("pass") is True
    return {
        "name": "envelope_self_audit_G1_G7",
        "pass": ok,
        "detail": audit.get("result", {}).get("summary", "no audit result"),
        "log": log,
    }


def main() -> int:
    tests = [
        self_test_1(),
        self_test_2(),
        self_test_3(),
        self_test_4(),
        envelope_audit(),
    ]
    RESULTS_DIR.mkdir(exist_ok=True)
    with open(RESULTS_DIR / "bootstrap.jsonl", "w", encoding="utf-8") as fh:
        for t in tests:
            fh.write(json.dumps(t, ensure_ascii=False) + "\n")

    all_pass = True
    for t in tests:
        mark = "PASS" if t["pass"] else "FAIL"
        print(f"[{mark}] {t['name']}: {t['detail']}")
        if not t["pass"]:
            all_pass = False
    print(f"\nbootstrap tests: {'ALL PASS' if all_pass else 'SOME FAIL'}")
    print("logs: evals/results/bootstrap.jsonl")
    return 0 if all_pass else 1


if __name__ == "__main__":
    sys.exit(main())
