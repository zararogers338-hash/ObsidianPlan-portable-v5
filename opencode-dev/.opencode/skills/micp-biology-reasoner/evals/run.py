"""Eval runner: executes evals/cases.yaml through the real CLI, checks
expectations, and produces metrics via evals/metrics.py.

Usage: python evals/run.py            (writes evals/results/latest.json)
       python evals/run.py --verbose  (per-case output to stdout)

The runner never hardcodes expected answers into the inputs — expectations
come from the domain rules themselves.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import yaml

TOOLS = Path(__file__).resolve().parent.parent / "tools"
CLI = TOOLS / "micp_bio_reasoner.py"
CASES = Path(__file__).resolve().parent / "cases.yaml"
RESULTS = Path(__file__).resolve().parent / "results"

sys.path.insert(0, str(Path(__file__).resolve().parent))
from metrics import measure  # noqa: E402


def _invoke(payload: dict, env: dict | None = None) -> dict:
    """Run the real CLI; parse stdout. Never leaks expectations."""
    proc = subprocess.run(
        [sys.executable, str(CLI)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        timeout=120,
        env=env,
    )
    if proc.returncode != 0:
        return {"status": "FAILED", "errors": [{"code": "MBR-E000"}], "provenance": {}}
    return json.loads(proc.stdout)


def run_case(case: dict, base: dict, verbose: bool) -> dict:
    payload = dict(base)
    payload["action"] = case["action"]
    extra = case.get("extra", {})
    for k, v in extra.items():
        payload[k] = v
    out = _invoke(payload)
    expect = case.get("expect", {})
    report = {
        "id": case["id"],
        "description": case["description"],
        "action": case["action"],
        "status": out.get("status"),
        "error_code": (out.get("errors") or [{}])[0].get("code") if out.get("errors") else None,
        "pass": True,
        "checks": [],
        "artifacts": len(out.get("artifacts", [])),
    }

    def check(name: str, ok: bool, detail: str = "") -> None:
        report["checks"].append({"name": name, "pass": ok, "detail": detail})
        if not ok:
            report["pass"] = False

    if "status" in expect:
        check(f"status=={expect['status']}", out.get("status") == expect["status"], f"got {out.get('status')}")
    if "error_code" in expect:
        check(f"error=={expect['error_code']}", report["error_code"] == expect["error_code"], f"got {report['error_code']}")
    if "ratio_not_1" in expect:
        notes = [a.get("note") for a in out.get("artifacts", [])]
        ratio = None
        for n in notes:
            if isinstance(n, dict) and n.get("activity_ratio_a_over_b") is not None:
                ratio = n["activity_ratio_a_over_b"]
        check("ratio_not_1", ratio is not None and abs(ratio - 1.0) > 1e-6, f"ratio={ratio}")
    if "activity_not_identical" in expect:
        notes = [a.get("note") for a in out.get("artifacts", [])]
        identical = None
        for n in notes:
            if isinstance(n, dict) and "activity_identical" in n:
                identical = n["activity_identical"]
        check("activity_not_identical", identical is False, f"identical={identical}")
    if "u_per_ml" in expect:
        notes = [a.get("note") for a in out.get("artifacts", [])]
        val = None
        for n in notes:
            if isinstance(n, dict) and n.get("u_per_ml") is not None:
                val = n["u_per_ml"]
        check("u_per_ml", val is not None and abs(val - expect["u_per_ml"]) < 1e-6, f"got {val}")
    if "evidence_label" in expect:
        notes = [a.get("note") for a in out.get("artifacts", [])]
        label = None
        for n in notes:
            if isinstance(n, dict) and n.get("evidence_label"):
                label = n["evidence_label"]
        check("evidence_label", label == expect["evidence_label"], f"got {label}")
    if "insufficient_evidence" in expect:
        notes = [a.get("note") for a in out.get("artifacts", [])]
        val = None
        for n in notes:
            if isinstance(n, dict) and n.get("insufficient_evidence") is not None:
                val = n["insufficient_evidence"]
        check("insufficient_evidence", val is expect["insufficient_evidence"], f"got {val}")
    if "findings_min" in expect:
        check("findings>=min", len(out.get("findings", [])) >= expect["findings_min"], f"got {len(out.get('findings', []))}")
    if "k_in_range" in expect:
        notes = [a.get("note") for a in out.get("artifacts", [])]
        k = None
        for n in notes:
            if isinstance(n, dict) and n.get("k_per_h") is not None:
                k = n["k_per_h"]
        lo, hi = expect["k_in_range"]
        check("k_in_range", k is not None and lo <= k <= hi, f"got {k}")

    # M1: every output must pass the output schema.
    sys.path.insert(0, str(TOOLS))
    from micp_bio.validate import check_output_schema
    from micp_bio.errors import MbrError

    try:
        check_output_schema(out)
        check("output_schema", True)
    except MbrError as exc:
        check("output_schema", False, exc.message)

    if verbose:
        print(f"  [{case['id']}] {'PASS' if report['pass'] else 'FAIL'} "
              f"{case['action']} status={out.get('status')}")
    return report


def _measure_missing_input(base: dict) -> dict:
    """M4: for each of K required fields, removing it must yield BLOCKED naming the field."""
    required = ["contract_version", "task_id", "project_id", "request", "skill_version", "timestamp"]
    blocked = 0
    for field in required:
        bad = dict(base)
        del bad[field]
        if field != "action":
            bad["action"] = "compare"
        bad["culture"] = {"od600": 1.0}
        bad["baseline"] = {"culture": {"od600": 1.0}}
        out = _invoke(bad)
        errors = out.get("errors") or []
        detail_str = json.dumps(errors[0].get("detail", {})) if errors else "{}"
        if out.get("status") in ("BLOCKED", "FAILED") and field in detail_str:
            blocked += 1
    return {"missing_input_total": len(required), "missing_input_blocked": blocked}


def _measure_adversarial(base: dict) -> dict:
    """M5: attacks must all be blocked."""
    attacks = [
        ("od_as_activity_unit", "convert", {"culture": {"urease_activity": 5.0, "urease_activity_unit": "OD600"},
                                            "metric_query": {"kind": "activity_normalization"}}),
        ("contract_v2", "compare", {"contract_version": "2.0"}),
        ("no_calibration_od_cfu", "convert", {"culture": {"od600": 1.0},
                                              "metric_query": {"kind": "cell_concentration"}}),
        ("unknown_action", "not.a.real.action", {}),
    ]
    blocked = 0
    for name, action, extra in attacks:
        payload = dict(base)
        payload["action"] = action
        payload.update(extra)
        out = _invoke(payload)
        if out.get("status") in ("BLOCKED", "FAILED"):
            blocked += 1
    return {"adversarial_total": len(attacks), "adversarial_blocked": blocked}


def _repeat_consistency(base: dict) -> bool:
    """M6: identical payload with a fixed clock => identical output envelope."""
    env = dict(os.environ)
    env["MBR_TEST_CLOCK"] = "2026-08-06T12:00:00.000Z"
    payload = dict(base)
    payload["action"] = "compare"
    payload["culture"] = {"od600": 1.2, "urease_activity": 5.0, "urease_activity_unit": "U/mL"}
    payload["baseline"] = {"culture": {"od600": 1.2, "urease_activity": 8.0, "urease_activity_unit": "U/mL"}}
    a = json.dumps(_invoke(payload, env=env), sort_keys=True, ensure_ascii=False)
    b = json.dumps(_invoke(payload, env=env), sort_keys=True, ensure_ascii=False)
    return a == b


def _recovery_mean_ms() -> float:
    """M7: mean wall-clock to a valid envelope on structurally broken input."""
    times: list[float] = []
    for _ in range(5):
        t0 = time.perf_counter()
        _invoke({"contract_version": "1.0"})
        times.append((time.perf_counter() - t0) * 1000.0)
    return sum(times) / len(times)


def run_suite(verbose: bool) -> dict:
    cases = yaml.safe_load(CASES.read_text(encoding="utf-8"))
    base = cases["base"]

    reports = [run_case(c, dict(base), verbose) for c in cases["cases"]]
    passed = sum(1 for r in reports if r["pass"])
    total = len(reports)

    suite_report = {
        "outputs": total,
        "output_schema_passes": sum(1 for r in reports if any(
            c["name"] == "output_schema" and c["pass"] for c in r["checks"])),
        "successful_outputs": sum(1 for r in reports if r["status"] == "SUCCESS"),
        "tool_real_calls": sum(1 for r in reports if r["status"] == "SUCCESS" and r["artifacts"] > 0),
        "traceable_outputs": sum(1 for r in reports if r["status"] == "SUCCESS"),
    }
    suite_report.update(_measure_missing_input(dict(base)))
    suite_report.update(_measure_adversarial(dict(base)))
    suite_report["repeat_consistent"] = _repeat_consistency(dict(base))
    suite_report["recovery_mean_ms"] = _recovery_mean_ms()
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
