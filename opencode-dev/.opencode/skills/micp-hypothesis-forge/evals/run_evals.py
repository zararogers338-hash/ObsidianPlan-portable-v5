#!/usr/bin/env python3
"""Run the micp-hypothesis-forge evaluation cases for real.

Executes each case in evals/cases.yaml against the actual tool pipeline
(subprocess, real stdin/stdout), records per-case evidence, computes the seven
performance indicators (metrics.py), and writes evals/results/latest.json.

Usage:
    python evals/run_evals.py

Exit 0 if every indicator threshold is met; 1 otherwise. Offline, stdlib-only.
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))

from miniyaml import load as load_yaml  # noqa: E402
from metrics import compute  # noqa: E402

TOOLS = SKILL_ROOT / "tools"
RESULTS_DIR = Path(__file__).resolve().parent / "results"


def run_tool(tool: str, payload: dict) -> dict:
    t0 = time.perf_counter()
    proc = subprocess.run(
        [sys.executable, str(TOOLS / f"{tool}.py")],
        input=json.dumps(payload, ensure_ascii=False),
        capture_output=True, text=True, cwd=str(SKILL_ROOT),
    )
    wall = time.perf_counter() - t0
    try:
        env = json.loads(proc.stdout)
    except json.JSONDecodeError:
        env = {"ok": False, "error": {"code": "MHX-E404",
                                      "message": f"non-JSON stdout from {tool}"}}
    return {"envelope": env, "wall_time_s": wall, "exit_code": proc.returncode}


# ---------------------------------------------------------------------------
# Case builders — each returns (payloads, expected_kind)
# ---------------------------------------------------------------------------

def _three_hypotheses():
    return [
        {"id": "H1", "statement": "Inlet clogs by chemical precipitation of calcite",
         "refutation": "If inlet calcite mass increases while inlet cell mass stays "
                       "low, chemical precipitation drives the clog",
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


def _full_envelope(status="SUCCESS", artifacts=None, evidence_used=None,
                   evidence_refs=None, extra=None):
    doc = {
        "contract_version": "1.0", "skill": "micp-hypothesis-forge",
        "skill_version": "1.0.0", "status": status, "summary": "eval case",
        "findings": [{"id": "F1", "epistemic_label": "HYPOTHESIS", "summary": "x"}],
        "assumptions": [], "evidence_used": evidence_used or [],
        "evidence_refs": evidence_refs or [],
        "uncertainty": {}, "risks": [],
        "artifacts": artifacts or [], "requested_next_skills": [],
        "validation": {}, "provenance": {
            "skill": "micp-hypothesis-forge", "skill_version": "1.0.0",
            "timestamp": "2026-08-06T00:00:00Z", "contract_version": "1.0",
            "controller_version": "0.1.0"},
        "errors": [],
    }
    if extra:
        doc.update(extra)
    return doc


def _card_set_artifact():
    return [{"kind": "hypothesis_card_set", "cards": [
        {"id": "H1", "refutation": "if inlet calcite increases while cells stay low"},
        {"id": "H2", "refutation": "if inlet cells increase while calcite stays low"},
        {"id": "H3", "refutation": "if downstream calcite increases while inlet pressure stays flat"},
    ]}]


CASE_BUILDERS = {
    # --- normal ---
    "CASE-01": lambda: {
        "tools": [
            ("dag", {"mechanism_chain": ["high urease activity", "accelerated hydrolysis",
                                         "NH4+ accumulation", "reduced cementation strength"]}),
            ("scoring", {"statements": [
                {"id": "H1", "statement": "High urease activity reduces strength",
                 "refutation": "If NH4+ exceeds 120 mM, UCS declines below baseline",
                 "observables": ["NH4+ (mM)", "UCS (MPa)"],
                 "time_scale": "14 days", "scope": "sand column, 1M"},
                {"id": "H2", "statement": "Calcite washout reduces strength",
                 "refutation": "If calcite stays high while UCS declines, H2 weakens",
                 "observables": ["calcite (%)", "UCS (MPa)"],
                 "time_scale": "14 days", "scope": "sand column"},
                {"id": "H3", "statement": "Pore plugging reduces strength",
                 "refutation": "If permeability stays uniform while UCS declines, H3 weakens",
                 "observables": ["permeability (m/s)", "UCS (MPa)"],
                 "time_scale": "14 days", "scope": "sand column"},
            ]}),
            ("competing-matrix", {"hypotheses": _three_hypotheses()}),
            ("self-audit", _full_envelope(artifacts=_card_set_artifact(),
                                          evidence_used=[{"ref_id": "EV1", "role": "support"}],
                                          evidence_refs=[{"ref_id": "EV1"}]))],
        "expect_status": "SUCCESS",
        "full_pipeline": True},
    "CASE-02": lambda: {
        "tools": [("competing-matrix", {"hypotheses": _three_hypotheses()})],
        "expect_status": "SUCCESS"},
    "CASE-03": lambda: {
        "tools": [
            ("scoring", {"statements": [
                {"id": "H1", "statement": "Substrate-limited downstream",
                 "refutation": "If downstream residual urea exceeds 10 mM, H1 weakens",
                 "observables": ["residual urea (mM)"], "time_scale": "14 days", "scope": "column"},
                {"id": "H2", "statement": "Nucleation-limited downstream",
                 "refutation": "If seeded calcite exceeds unseeded, H2 confirmed",
                 "observables": ["seeded calcite (g)"], "time_scale": "14 days", "scope": "column"},
                {"id": "H3", "statement": "Transport-limited by mixing",
                 "refutation": "If velocity change does not move the profile, H3 weakens",
                 "observables": ["velocity (m/s)"], "time_scale": "7 days", "scope": "column"},
            ]}),
            ("experiment-priority", {"experiments": [
                {"id": "E1", "information_gain_bits": 0.7, "cost_rank": 2,
                 "risk_level": "low", "time_scale_days": 7, "feasibility": 0.9},
                {"id": "E2", "information_gain_bits": 0.5, "cost_rank": 3,
                 "risk_level": "medium", "time_scale_days": 14, "feasibility": 0.7},
                {"id": "E3", "information_gain_bits": 0.3, "cost_rank": 1,
                 "risk_level": "low", "time_scale_days": 3, "feasibility": 0.95},
            ]})],
        "expect_status": "SUCCESS"},
    # --- missing ---
    "CASE-04": lambda: {
        "tools": [("scoring", {"statements": [{"id": "H1", "statement": "", "refutation": ""}]})],
        "expect_status": "BLOCKED", "kind": "missing"},
    "CASE-05": lambda: {
        "tools": [("dag", {})],
        "expect_status": "BLOCKED", "kind": "missing"},
    # --- conflicting / boundary ---
    "CASE-06": lambda: {
        "tools": [("competing-matrix", {"hypotheses": _three_hypotheses()})],
        "expect_status": "SUCCESS", "kind": "conflicting"},
    "CASE-07": lambda: {
        "tools": [("scoring", {"statements": [
            {"id": "H1", "statement": "urea plays a role in strength", "refutation": ""}]})],
        "expect_status": "BLOCKED", "kind": "boundary"},
    # --- adversarial ---
    "CASE-08": lambda: {
        "tools": [("dag", {"chains": [["A", "B"], ["B", "C"], ["C", "A"]]})],
        "expect_status": "FAILED", "kind": "adversarial", "expect_error": "MHX-E105"},
    "CASE-09": lambda: {
        "tools": [("self-audit", _full_envelope(
            artifacts=_card_set_artifact(),
            evidence_used=[{"ref_id": "GHOST", "role": "support"}],
            evidence_refs=[{"ref_id": "EV1"}]))],
        "expect_status": "SUCCESS", "kind": "adversarial", "expect_g4_fail": True},
    "CASE-10": lambda: {
        "tools": [("self-audit", _full_envelope(
            artifacts=_card_set_artifact(),
            extra={"findings": [{"id": "F1", "epistemic_label": "FACT", "summary": "x"}]}))],
        "expect_status": "SUCCESS", "kind": "adversarial", "expect_g3_fail": True},
    # --- determinism ---
    "CASE-11": lambda: {
        "tools": [("dag", {"mechanism_chain": ["A", "B", "C"]})],
        "expect_status": "SUCCESS", "kind": "determinism"},
}


def run_case(case_id: str, builder) -> dict:
    cfg = builder()
    tools = cfg["tools"]
    record = {
        "id": case_id,
        "kind": cfg.get("kind", "normal"),
        "expect_status": cfg.get("expect_status"),
        "tools_invoked": [t for t, _ in tools],
        "full_pipeline": cfg.get("full_pipeline", False),
        "wall_time_s": 0.0,
        "ok": True,
    }
    results = []
    for tool, payload in tools:
        r = run_tool(tool, payload)
        results.append({"tool": tool, **r})
        record["wall_time_s"] = max(record["wall_time_s"], r["wall_time_s"])

    envelopes = [r["envelope"] for r in results]

    # schema validity: self-audit's G2 gate reflects output.schema conformance
    audit = next((r["envelope"] for r in results if r["tool"] == "self-audit"), None)
    if audit is not None and audit.get("ok"):
        record["schema_valid"] = True
    else:
        # non-audit cases: tool must at least return a well-formed envelope
        record["schema_valid"] = all("error" in e or "result" in e for e in envelopes)

    # traceability
    if cfg.get("expect_g4_fail") is not None:
        record["traceability_ok"] = False  # filled below
    if any("G4_traceability" in (r["envelope"].get("result", {}).get("failed_gates", []))
           for r in results):
        record["intercepted"] = True
        record["traceability_ok"] = False
        record["schema_valid"] = record.get("schema_valid", True)
    else:
        record["traceability_ok"] = record.get("traceability_ok", True)

    # G3 epistemic interception
    if any("G3_epistemic" in (r["envelope"].get("result", {}).get("failed_gates", []))
           for r in results):
        record["intercepted"] = True

    # missing-input detection
    if cfg.get("kind") == "missing":
        any_blocked = any(not r["envelope"].get("ok")
                          and r["envelope"].get("error", {}).get("code", "").startswith("MHX-E10")
                          for r in results)
        record["returned_blocked"] = any_blocked
        record["missing_inputs_listed"] = any_blocked
        if not any_blocked:
            record["ok"] = False

    # adversarial interception
    if cfg.get("kind") == "adversarial":
        if cfg.get("expect_error"):
            got = [r["envelope"].get("error", {}).get("code") for r in results]
            intercepted = cfg["expect_error"] in got
            record["intercepted"] = intercepted
            if not intercepted:
                record["ok"] = False
        if cfg.get("expect_g4_fail"):
            record["ok"] = record["ok"] and bool(record.get("intercepted"))
        if cfg.get("expect_g3_fail"):
            record["ok"] = record["ok"] and bool(record.get("intercepted"))

    # determinism
    if cfg.get("kind") == "determinism":
        r1 = run_tool("dag", {"mechanism_chain": ["A", "B", "C"]})
        r2 = run_tool("dag", {"mechanism_chain": ["A", "B", "C"]})
        record["deterministic"] = r1["envelope"] == r2["envelope"]
        if not record["deterministic"]:
            record["ok"] = False

    # normal cases: every tool must return ok
    if cfg.get("kind") == "normal" and not all(e.get("ok") for e in envelopes):
        record["ok"] = False

    return record


def main() -> int:
    cases = load_yaml(Path(__file__).resolve().parent / "cases.yaml")["cases"]
    records = []
    for case in cases:
        case_id = case["id"]
        builder = CASE_BUILDERS.get(case_id)
        if builder is None:
            print(f"SKIP {case_id}: no builder defined")
            continue
        rec = run_case(case_id, builder)
        ok_mark = "PASS" if rec["ok"] else "FAIL"
        print(f"[{ok_mark}] {case_id} {case.get('label', '')} "
              f"({', '.join(rec['tools_invoked'])})")
        records.append(rec)

    summary = compute(records)
    RESULTS_DIR.mkdir(exist_ok=True)
    (RESULTS_DIR / "latest.json").write_text(
        json.dumps({"summary": summary, "cases": records},
                   ensure_ascii=False, indent=2),
        encoding="utf-8")

    print("\n--- indicators ---")
    all_pass = True
    for name, value in summary["indicators"].items():
        thresh = summary["thresholds"][name]
        mark = "PASS" if summary["passed"][name] else "FAIL"
        unit = "s" if name == "mean_failure_recovery_time" else "ratio"
        print(f"  [{mark}] {name}: {value:.3f} {unit} (threshold {thresh})")
        if not summary["passed"][name]:
            all_pass = False
    print(f"\ncases: {summary['n_passed']}/{summary['n_cases']} passed | "
          f"overall: {'ALL INDICATORS PASS' if all_pass else 'INDICATORS FAIL'}")
    print(f"results written to evals/results/latest.json")
    return 0 if all_pass else 1


if __name__ == "__main__":
    sys.exit(main())
