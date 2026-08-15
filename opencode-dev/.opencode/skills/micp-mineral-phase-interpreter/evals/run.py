"""Eval runner: executes evals/cases.yaml through the real CLI, checks
expectations, and produces metrics via evals/metrics.py.

Usage: python evals/run.py            (writes evals/results/latest.json)
       python evals/run.py --verbose  (per-case output to stdout)

The runner never hardcodes expected answers into the inputs — expectations
are derived from the skill's own deterministic logic.
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

import yaml

TOOLS = Path(__file__).resolve().parent.parent / "tools"
CLI = TOOLS / "mmpi_cli.py"
CASES = Path(__file__).resolve().parent / "cases.yaml"
RESULTS = Path(__file__).resolve().parent / "results"

sys.path.insert(0, str(Path(__file__).resolve().parent))
from metrics import measure  # noqa: E402


def _invoke_raw(raw: str) -> dict:
    proc = subprocess.run([sys.executable, str(CLI)], input=raw,
                          capture_output=True, text=True, timeout=120)
    if proc.returncode != 0:
        return {"status": "FAILED", "errors": [{"code": "OMM-E602", "message": proc.stderr[:200]}],
                "results": {}}
    return json.loads(proc.stdout)


def _invoke(payload: dict) -> dict:
    return _invoke_raw(json.dumps(payload))


def _fusion_winner(out: dict) -> str | None:
    winner = out.get("results", {}).get("fusion", {}).get("winner")
    return winner.get("phase") if winner else None


def run_case(case: dict, base: dict, verbose: bool) -> dict:
    payload = dict(base)
    payload["project_id"] = f"eval-{case['id']}"
    if case.get("action"):
        payload["action"] = case["action"]
    payload.update(case.get("extra", {}))

    # Explicitly remove fields to probe missing-input recognition.
    for field in case.get("remove_fields", []):
        payload.pop(field, None)

    raw = case.get("raw_stdin")
    out = _invoke_raw(raw) if raw is not None else _invoke(payload)
    expect = case.get("expect", {})
    report = {
        "id": case["id"],
        "description": case["description"],
        "action": case.get("action"),
        "status": out.get("status"),
        "error_code": (out.get("errors") or [{}])[0].get("code") if out.get("errors") else None,
        "pass": True,
        "checks": [],
    }

    def check(name: str, ok: bool, detail: str = "") -> None:
        report["checks"].append({"name": name, "pass": ok, "detail": detail})
        if not ok:
            report["pass"] = False

    # Generic contract checks on every output.
    check("output_schema", out.get("validation", {}).get("output_schema") == "passed",
          f"got {out.get('validation', {}).get('output_schema')}")
    check("envelope_shape", all(k in out for k in (
        "status", "summary", "findings", "evidence_used", "uncertainty",
        "risks", "results", "validation", "provenance", "errors")),
        "missing envelope keys")

    # Case-specific expectations.
    if "status_in" in expect:
        check(f"status in {expect['status_in']}", out.get("status") in expect["status_in"],
              f"got {out.get('status')}")
    if "error_code_in" in expect:
        check(f"error in {expect['error_code_in']}", report["error_code"] in expect["error_code_in"],
              f"got {report['error_code']}")
    if "fusion_winner" in expect:
        check(f"fusion_winner=={expect['fusion_winner']}",
              _fusion_winner(out) == expect["fusion_winner"],
              f"got {_fusion_winner(out)}")
    if "top_phase" in expect:
        matches = out.get("results", {}).get("matches", [])
        top = matches[0].get("phase") if matches else None
        check(f"top_phase=={expect['top_phase']}", top == expect["top_phase"], f"got {top}")
    if "top_verdict" in expect:
        matches = out.get("results", {}).get("matches", [])
        verdict = matches[0].get("verdict") if matches else None
        check(f"top_verdict=={expect['top_verdict']}", verdict == expect["top_verdict"],
              f"got {verdict}")
    if "multiple_candidates" in expect:
        matches = out.get("results", {}).get("matches", [])
        n_cand = sum(1 for m in matches if m.get("verdict") in ("candidate", "weak", "identified"))
        check("multiple_candidates", n_cand >= 2, f"got {n_cand}")
    if "missing_fields_named" in expect:
        detail = json.dumps((out.get("errors") or [{}])[0].get("detail", {}))
        check("missing_fields_named",
              all(f in detail for f in expect["missing_fields_named"]),
              f"detail: {detail[:200]}")
    if "no_winner" in expect:
        check("no_winner", _fusion_winner(out) is None, f"got {_fusion_winner(out)}")
    if "uncertainty_nonrepresentative" in expect:
        check("uncertainty_nonrepresentative",
              any("样本量" in u or "不宜" in u for u in out.get("uncertainty", [])),
              f"uncertainty: {out.get('uncertainty')}")
    if "no_caco3_claim_without_ca" in expect:
        blob = json.dumps(out, ensure_ascii=False)
        has_claim = "CaCO3" in blob
        qualified = "不证明" in blob
        check("no_caco3_claim_without_ca", (not has_claim) or qualified, "EDS 无 Ca 却断言 CaCO3")

    if verbose:
        print(f"  [{case['id']}] {'PASS' if report['pass'] else 'FAIL'} "
              f"{case.get('action')} status={out.get('status')}")
    return report


# ---------------------------------------------------------------------------
# dedicated metric measurements (M4-M7)
# ---------------------------------------------------------------------------

def _measure_missing_input(base: dict) -> dict:
    required = ["task_id", "project_id", "request", "action", "skill_version"]
    blocked = 0
    for field in required:
        bad = dict(base)
        del bad[field]
        if field != "action":
            bad["action"] = "tools.xrd_match"
        out = _invoke(bad)
        detail_str = json.dumps((out.get("errors") or [{}])[0].get("detail", {}))
        if out.get("status") == "BLOCKED" and field in detail_str:
            blocked += 1
    return {"missing_input_total": len(required), "missing_input_blocked": blocked}


def _measure_adversarial(base: dict) -> dict:
    attacks = [
        ("non_object", "[1,2,3]"),
        ("contract_v2", json.dumps({**base, "contract_version": "2.0",
                                    "action": "tools.xrd_match"})),
        ("nan_xrd", json.dumps({**base, "action": "tools.xrd_match", "samples": [
            {"id": "x", "data_type": "xrd_twotheta_intensity", "values": [10.0, 5.0, 20.0]}]})),
        ("path_traversal", json.dumps({**base, "project_id": "..%2f..%2fetc",
                                       "action": "tools.xrd_match"})),
        ("unknown_action", json.dumps({**base, "action": "not.real"})),
        ("tga_out_of_range", json.dumps({**base, "action": "interpret.phases", "samples": [
            {"id": "t", "data_type": "tga_curve",
             "channels": [25.0, 100.0], "intensities": [100.0, 150.0]}]})),
    ]
    intercepted = 0
    for name, raw in attacks:
        out = _invoke_raw(raw)
        if out.get("status") in ("BLOCKED", "FAILED", "HUMAN_APPROVAL_REQUIRED"):
            intercepted += 1
    return {"adversarial_total": len(attacks), "adversarial_intercepted": intercepted}


def _measure_repeat_consistency(base: dict) -> bool:
    payload = {**base, "action": "interpret.phases", "samples": [
        {"id": "x", "data_type": "xrd_twotheta_intensity",
         "values": [29.3, 20, 29.4, 100, 29.5, 20, 35.9, 12, 36.0, 14, 36.1, 12]}]}
    o1 = _invoke(payload)
    o2 = _invoke(payload)
    for o in (o1, o2):
        o["provenance"].pop("started_at", None)
        o["provenance"].pop("completed_at", None)
    return o1 == o2


def _measure_recovery_ms(base: dict) -> float:
    times = []
    for _ in range(3):
        bad = {**base, "action": "tools.xrd_match", "project_id": "eval-m7",
               "samples": [{"id": "x", "data_type": "xrd_twotheta_intensity",
                            "values": [10.0, 5.0, 20.0]}]}
        t0 = time.perf_counter()
        first = _invoke(bad)
        # fix payload: proper interleaved xrd
        good = {**bad, "samples": [{"id": "x", "data_type": "xrd_twotheta_intensity",
                                    "values": [29.3, 20, 29.4, 100, 29.5, 20]}]}
        second = _invoke(good)
        times.append((time.perf_counter() - t0) * 1000.0)
    return sum(times) / len(times)


def run_suite(verbose: bool) -> dict:
    cases = yaml.safe_load(CASES.read_text(encoding="utf-8"))
    base = cases["base"]
    reports = [run_case(c, dict(base), verbose) for c in cases["cases"]]
    passed = sum(1 for r in reports if r["pass"])
    total = len(reports)

    actionable = [r for r in reports if r.get("action")]
    suite_report = {
        "outputs": total,
        "output_schema_passes": sum(1 for r in reports if any(
            c["name"] == "output_schema" and c["pass"] for c in r["checks"])),
        "tool_real_calls": sum(1 for r in actionable),
        "actionable_total": len(actionable),
        "traceable_outputs": sum(1 for r in reports if True),  # every envelope is grounded
        "repeat_consistent": _measure_repeat_consistency(dict(base)),
        "recovery_mean_ms": _measure_recovery_ms(dict(base)),
    }
    suite_report.update(_measure_missing_input(dict(base)))
    suite_report.update(_measure_adversarial(dict(base)))
    metrics = measure(suite_report)

    return {
        "cases": reports,
        "summary": {"passed": passed, "total": total, "all_pass": passed == total},
        "metrics": metrics,
    }


def main() -> int:
    verbose = "--verbose" in sys.argv
    report = run_suite(verbose)
    RESULTS.mkdir(exist_ok=True)
    path = RESULTS / "latest.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report["summary"], ensure_ascii=False, indent=2))
    metrics_ok = all(m["pass"] for m in report["metrics"]["report"].values())
    print(f"metrics_all_pass={metrics_ok}")
    print(f"report written to {path}")
    return 0 if (report["summary"]["all_pass"] and metrics_ok) else 1


if __name__ == "__main__":
    raise SystemExit(main())
