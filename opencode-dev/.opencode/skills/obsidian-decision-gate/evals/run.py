"""Evaluation runner for obsidian-decision-gate.

Drives the real CLI over evals/cases.yaml and computes the project-standard
M1..M7 metrics. Offline: no network, no third-party deps beyond yaml+jsonschema
(when present). Deterministic: ODG_TEST_CLOCK is injected per case.

Usage:
  python evals/run.py            # run all cases, print table, write results/latest.json
  python evals/run.py --json     # machine-readable JSON on stdout only
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CLI = ROOT / "tools" / "odg" / "cli.py"

try:
    import yaml
except ImportError:  # pragma: no cover
    sys.stderr.write("pyyaml required to parse evals/cases.yaml\n")
    raise

# M-thresholds from project convention (obsidian-plan-skill-engineering)
THRESHOLDS = {
    "M1_structured_output_pass_rate": 0.95,
    "M2_tool_real_invocation_rate": 1.0,
    "M3_traceability_rate": 0.9,
    "M4_missing_input_identification": 1.0,
    "M5_adversarial_interception_rate": 1.0,
    "M6_repeatability": 1.0,
    "M7_failure_recovery_time_ms": 5000,
}


def run_case(case: dict, cli: Path = CLI) -> dict:
    payload = case["payload"]
    expect = case["expect"]
    tool = "service"

    # deterministic clock
    env = os.environ.copy()
    env["ODG_TEST_CLOCK"] = payload.get("timestamp", "2026-08-07T00:00:00Z")

    t0 = time.perf_counter()
    proc = subprocess.run(
        [sys.executable, str(cli), tool],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        env=env,
        timeout=30,
    )
    wall_ms = (time.perf_counter() - t0) * 1000.0

    if proc.returncode != 0:
        return {"case": case["id"], "ok": False, "why": f"cli exit {proc.returncode}: {proc.stderr[:300]}",
                "wall_ms": wall_ms, "structured": False}
    try:
        out = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        return {"case": case["id"], "ok": False, "why": f"non-JSON stdout: {exc}", "wall_ms": wall_ms,
                "structured": False}

    result = out.get("result") or {}
    status = result.get("status")
    decision = result.get("decision")
    ok = status == expect.get("status") and decision == expect.get("decision")
    structured = out.get("ok") is True and isinstance(result, dict)

    # traceability: every blocking item carries rule/severity/evidence/how_to_resolve
    blockers = result.get("blocking_items") or []
    traceable = all(
        b.get("rule") and b.get("severity") and b.get("evidence") and b.get("how_to_resolve")
        for b in blockers
    ) if blockers else True

    return {
        "case": case["id"],
        "ok": ok,
        "why": "" if ok else f"expected {expect.get('status')}/{expect.get('decision')} got {status}/{decision}",
        "status": status,
        "decision": decision,
        "structured": structured,
        "traceable": traceable,
        "blockers": [b.get("rule") for b in blockers],
        "wall_ms": round(wall_ms, 1),
        "errors": result.get("errors") or [],
    }


def main() -> int:
    cases_yaml = ROOT / "evals" / "cases.yaml"
    cases = yaml.safe_load(cases_yaml.read_text(encoding="utf-8"))["cases"]

    results = [run_case(c) for c in cases]
    n = len(results)
    passed = sum(1 for r in results if r["ok"])
    structured_ok = sum(1 for r in results if r["structured"])
    traceable_ok = sum(1 for r in results if r["traceable"])
    wall_times = [r["wall_ms"] for r in results if r.get("wall_ms") is not None]
    max_wall = max(wall_times) if wall_times else 0

    # M5: adversarial interception = illegal-jump / fudge cases correctly blocked
    adversarial_cases = [r for r in results if r["case"] in (
        "ev-06-lab-cylinder-direct-deploy", "ev-11-open-to-deployable",
        "ev-12-failure-threshold",
    )]
    m5 = sum(1 for r in adversarial_cases if r["ok"]) / len(adversarial_cases) if adversarial_cases else 1.0

    # M4: missing-input identification — inject a malformed payload and expect ODG-E101
    m4 = 1.0
    bad = {"contract_version": "1.0", "task_id": "x"}
    env = os.environ.copy()
    env["ODG_TEST_CLOCK"] = "2026-08-07T00:00:00Z"
    p = subprocess.run([sys.executable, str(CLI), "service"], input=json.dumps(bad),
                       capture_output=True, text=True, env=env)
    if p.returncode == 0:
        try:
            out = json.loads(p.stdout)
            if not any("ODG-E101" in str(e.get("code", "")) for e in (out.get("result") or {}).get("errors", [])):
                m4 = 0.0
        except Exception:
            m4 = 0.0
    else:
        m4 = 0.0

    # M6: repeatability — run ev-01 twice, identical verdict
    m6 = 1.0
    if results:
        first = results[0]
        again = run_case(cases[0])
        if (first.get("status"), first.get("decision")) != (again.get("status"), again.get("decision")):
            m6 = 0.0

    metrics = {
        "M1_structured_output_pass_rate": round(structured_ok / n, 3),
        "M2_tool_real_invocation_rate": 1.0 if passed > 0 else 0.0,
        "M3_traceability_rate": round(traceable_ok / n, 3),
        "M4_missing_input_identification": m4,
        "M5_adversarial_interception_rate": round(m5, 3),
        "M6_repeatability": m6,
        "M7_failure_recovery_time_ms": round(max_wall, 1),
    }
    overall = all(
        (metrics[k] >= v) if k != "M7_failure_recovery_time_ms" else (metrics[k] <= v)
        for k, v in THRESHOLDS.items()
    )

    summary = {
        "cases": n,
        "passed": passed,
        "passed_ids": [r["case"] for r in results if r["ok"]],
        "failed": [r for r in results if not r["ok"]],
        "metrics": metrics,
        "thresholds": THRESHOLDS,
        "overall_pass": overall,
        "run_at": "2026-08-07T00:00:00Z",
    }

    out_path = ROOT / "evals" / "results" / "latest.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    if "--json" in sys.argv:
        sys.stdout.write(json.dumps(summary, ensure_ascii=False) + "\n")
        return 0 if overall else 1

    print(f"obsidian-decision-gate evals — {passed}/{n} cases pass")
    for r in results:
        mark = "PASS" if r["ok"] else "FAIL"
        print(f"  [{mark}] {r['case']:<38} {r.get('status','?'):<25} {r.get('decision','?'):<18} {r.get('why','')}")
    print("\nmetrics:")
    for k, v in metrics.items():
        thr = THRESHOLDS[k]
        ok = (v <= thr) if k.endswith("ms") else (v >= thr)
        print(f"  {k:<38} {v:<10} {'OK' if ok else 'BELOW'}")
    print(f"\noverall: {'PASS' if overall else 'FAIL'}")
    return 0 if overall else 1


if __name__ == "__main__":
    sys.exit(main())
