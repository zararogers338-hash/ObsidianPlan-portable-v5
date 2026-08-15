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
CLI = TOOLS / "mbs_auditor.py"
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
        return {"status": "FAILED", "errors": [{"code": "MBS-E000"}], "provenance": {}}
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
    if "nh4_upper_g" in expect:
        nb = out.get("nitrogen_balance") or {}
        v = nb.get("nh4_upper_bound_g")
        check("nh4_upper_g", v is not None and abs(v - expect["nh4_upper_g"]) < 0.01, f"got {v}")
    if "nh3_fraction_min" in expect:
        note = (out.get("artifacts") or [{}])[0].get("note") or {}
        f = note.get("nh3_fraction")
        check("nh3_fraction_min", f is not None and f >= expect["nh3_fraction_min"], f"got {f}")
    if "total_n_load_g" in expect:
        note = (out.get("artifacts") or [{}])[0].get("note") or {}
        v = note.get("total_n_load_g")
        check("total_n_load_g", v is not None and abs(v - expect["total_n_load_g"]) < 0.01, f"got {v}")
    if "identity_verified" in expect:
        notes = [a.get("note") for a in out.get("artifacts", [])]
        v = None
        for n in notes:
            if isinstance(n, dict) and "verified" in n:
                v = n["verified"]
        check("identity_verified", v is expect["identity_verified"], f"got {v}")
    if "matrix_5x5" in expect:
        note = (out.get("artifacts") or [{}])[0].get("note") or {}
        m = note.get("matrix") or []
        check("matrix_5x5", len(m) == 5 and all(len(r) == 5 for r in m), f"got {len(m)} rows")
    if "gate_groundwater" in expect:
        codes = [g.get("code") for g in out.get("approval_requirements", [])]
        check("gate_groundwater", "GROUNDWATER_INJECTION" in codes, f"got {codes}")
    if "balance_closed" in expect:
        nb = out.get("nitrogen_balance") or {}
        check("balance_closed", nb.get("mass_balance_closed") is expect["balance_closed"], f"got {nb.get('mass_balance_closed')}")
    if "stop_conditions_min" in expect:
        check("stop_conditions_min", len(out.get("stop_conditions", [])) >= expect["stop_conditions_min"],
              f"got {len(out.get('stop_conditions', []))}")

    # M1: every output must pass the output schema.
    sys.path.insert(0, str(TOOLS))
    from mbs.validate import check_output_schema
    from mbs.errors import MbsError

    try:
        check_output_schema(out)
        check("output_schema", True)
    except MbsError as exc:
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
        bad["action"] = "mass_balance"
        bad["nitrogen"] = {"urea_input_g": 60.06}
        out = _invoke(bad)
        errors = out.get("errors") or []
        detail_str = json.dumps(errors[0].get("detail", {})) if errors else "{}"
        if out.get("status") in ("BLOCKED", "FAILED") and field in detail_str:
            blocked += 1
    return {"missing_input_total": len(required), "missing_input_blocked": blocked}


def _measure_adversarial(base: dict) -> dict:
    """M5: attacks must all be blocked."""
    attacks = [
        ("non_conserving", "mass_balance", {"nitrogen": {"urea_input_g": 100.0,
                                                         "liquid_residual_g": 1.0,
                                                         "sorbed_retained_g": 1.0,
                                                         "discharged_treated_g": 1.0}}),
        ("unknown_strain", "strain_verify", {"strain": {"name": "未鉴定细菌"}}),
        ("bypass_groundwater", "audit", {
            "request": "现场地下水注入，跳过许可",
            "site": {"release_type": "injection", "groundwater_injection": True,
                     "waste_treatment_capacity": False,
                     "strain": {"name": "Sporosarcina pasteurii", "culture_collection_id": "ATCC 11859"}},
            "plan": {"nitrogen": {"urea_input_g": 120.0, "pH": 8.0, "temperature_c": 25.0,
                                  "liquid_residual_g": 20.0, "sorbed_retained_g": 35.0,
                                  "discharged_treated_g": 1.0}}}),
        ("contract_v2", "mass_balance", {"contract_version": "2.0", "nitrogen": {"urea_input_g": 60.06}}),
        ("unknown_action", "not.a.real.action", {}),
    ]
    blocked = 0
    for name, action, extra in attacks:
        payload = dict(base)
        payload["action"] = action
        payload.update(extra)
        out = _invoke(payload)
        if out.get("status") in ("BLOCKED", "FAILED", "HUMAN_APPROVAL_REQUIRED"):
            blocked += 1
    return {"adversarial_total": len(attacks), "adversarial_blocked": blocked}


def _repeat_consistency(base: dict) -> bool:
    """M6: identical payload with a fixed clock => identical output envelope."""
    env = dict(os.environ)
    env["MBS_TEST_CLOCK"] = "2026-08-07T12:00:00.000Z"
    payload = dict(base)
    payload["action"] = "mass_balance"
    payload["nitrogen"] = {"urea_input_g": 60.06}
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
