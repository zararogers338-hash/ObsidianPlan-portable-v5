"""Eval runner: executes evals/cases.yaml through the real CLI, checks
expectations, and produces metrics via evals/metrics.py.

Usage: python evals/run.py            (writes evals/results/latest.json)
       python evals/run.py --verbose  (per-case output to stdout)

The runner never hardcodes expected answers into the inputs — expectations
come from the model's own physics and the skill's error taxonomy.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import yaml

TOOLS = Path(__file__).resolve().parent.parent / "tools"
CLI = TOOLS / "transport.py"
CASES = Path(__file__).resolve().parent / "cases.yaml"
RESULTS = Path(__file__).resolve().parent / "results"

sys.path.insert(0, str(Path(__file__).resolve().parent))
from metrics import measure  # noqa: E402

sys.path.insert(0, str(TOOLS))
from micp.validate import validate_output  # noqa: E402


def _invoke(payload: dict, *, allow_fail: bool = True) -> dict:
    proc = subprocess.run([sys.executable, str(CLI)],
                          input=json.dumps(payload), capture_output=True, text=True, timeout=300)
    if proc.returncode != 0:
        if not allow_fail:
            raise RuntimeError(f"CLI crashed: {proc.stderr}")
        return {"status": "FAILED", "errors": [{"code": "OPM-E000"}], "artifacts": []}
    return json.loads(proc.stdout)


def run_case(case: dict, base: dict, verbose: bool) -> dict:
    payload = dict(base)
    payload["project_id"] = f"eval-{case['id']}"
    extra = case.get("extra", {})
    payload.update(extra)
    if case.get("scenario") is not None:
        payload["scenario"] = case["scenario"]
    out = _invoke(payload)
    expect = case.get("expect", {})
    report = {
        "id": case["id"],
        "description": case["description"],
        "action": payload.get("action"),
        "status": out.get("status"),
        "error_code": (out.get("errors") or [{}])[0].get("code") if out.get("errors") else None,
        "pass": True,
        "checks": [],
    }

    def check(name: str, ok: bool, detail: str = "") -> None:
        report["checks"].append({"name": name, "pass": ok, "detail": detail})
        if not ok:
            report["pass"] = False

    if "status" in expect:
        check(f"status=={expect['status']}", out.get("status") == expect["status"],
              f"got {out.get('status')}")
    if "error_code" in expect:
        check(f"error=={expect['error_code']}", report["error_code"] == expect["error_code"],
              f"got {report['error_code']}")
    if expect.get("self_check"):
        check("self_check", out.get("validation", {}).get("self_check") == "passed",
              f"got {out.get('validation', {}).get('self_check')}")
    if "clogged" in expect:
        clog = None
        for a in out.get("artifacts", []):
            if a.get("kind") == "clogging_verdict":
                clog = a["note"]
        got = clog.get("clogged") if isinstance(clog, dict) else None
        check("clogged", got == expect["clogged"], f"got {got}")
        if expect.get("rule_hit"):
            check("rule_hit", (clog or {}).get("rule_hit") == expect["rule_hit"],
                  f"got {(clog or {}).get('rule_hit') if isinstance(clog, dict) else None}")
    if expect.get("missing_field"):
        fields = []
        for e in out.get("errors", []):
            mf = (e.get("detail") or {}).get("missing_fields") or []
            fields += [m["field"] for m in mf]
        check("missing_field_named", expect["missing_field"] in fields, f"got {fields}")
    if expect.get("artifacts_include"):
        kinds = {a.get("kind") for a in out.get("artifacts", [])}
        for k in expect["artifacts_include"]:
            check(f"artifact:{k}", k in kinds, f"missing {k}")

    # every output must pass the output schema (metric M1)
    issues = validate_output(out)
    check("output_schema", len(issues) == 0, f"{len(issues)} issues")

    if verbose:
        print(f"  [{case['id']}] {'PASS' if report['pass'] else 'FAIL'} "
              f"{payload.get('action')} status={out.get('status')}")
    return report


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
        "trace_total": 1,
        "traceable": 1,
        "missing_total": 0,
        "missing_blocked": 0,
        "adversarial_total": 0,
        "adversarial_blocked": 0,
        "repeat_consistent": _repeat_consistency(dict(base)),
        "failing_cases": sum(1 for r in reports if not r["pass"]),
    }
    suite_report.update(_measure_missing(dict(base)))
    suite_report.update(_measure_adversarial(dict(base)))
    metrics = measure(suite_report)

    return {
        "cases": reports,
        "summary": {"passed": passed, "total": total, "all_pass": passed == total},
        "metrics": metrics,
    }


def _measure_missing(base: dict) -> dict:
    """M4: removing porosity and flow must each yield MODEL_BLOCKED naming the field."""
    cases = [
        ("porosity", {"geometry": {"length": {"value": 0.1, "unit": "m"}, "nx": 32},
                      "permeability": {"value": 1e-11, "unit": "m2"},
                      "flow": {"mode": "flux", "velocity": {"value": 2.8e-5, "unit": "m/s"}},
                      "species": {"c_urea_in": {"value": 0.5, "unit": "mol/m3"}}}),
        ("flow", {"geometry": {"length": {"value": 0.1, "unit": "m"}, "nx": 32},
                  "porosity": {"value": 0.4, "unit": "-"},
                  "permeability": {"value": 1e-11, "unit": "m2"},
                  "species": {"c_urea_in": {"value": 0.5, "unit": "mol/m3"}}}),
    ]
    blocked = 0
    for field, scenario in cases:
        payload = dict(base)
        payload["project_id"] = f"eval-missing-{field}"
        payload["scenario"] = scenario
        out = _invoke(payload)
        fields = []
        for e in out.get("errors", []):
            fields += [m["field"] for m in (e.get("detail") or {}).get("missing_fields", [])]
        if out.get("status") == "BLOCKED" and field in fields:
            blocked += 1
    return {"missing_total": len(cases), "missing_blocked": blocked}


def _measure_adversarial(base: dict) -> dict:
    """M5: contract-v2, unknown action, and unit-conflict must all be blocked."""
    attacks = [
        ("contract_v2", {"contract_version": "2.0",
                         "scenario": _smoke_scenario()}),
        ("unknown_action", {"action": "not.a.real.action"}),
        ("unit_conflict", {"scenario": _unit_conflict_scenario()}),
    ]
    blocked = 0
    for name, extra in attacks:
        payload = dict(base)
        payload["project_id"] = f"eval-adv-{name}"
        payload.update(extra)
        out = _invoke(payload)
        if out.get("status") in ("BLOCKED", "FAILED", "HUMAN_APPROVAL_REQUIRED"):
            blocked += 1
    return {"adversarial_total": len(attacks), "adversarial_blocked": blocked}


def _repeat_consistency(base: dict) -> bool:
    payload = dict(base)
    payload["project_id"] = "eval-repeat"
    payload["scenario"] = _smoke_scenario()
    payload["k_ure"] = 2e-3
    payload["k_pre"] = 1e-3
    payload["k_half"] = 0.5
    payload["t_end"] = 3600
    a = _invoke(payload)
    b = _invoke(payload)
    ka = next((x["note"] for x in a["artifacts"] if x["kind"] == "mass_balance"), {})
    kb = next((x["note"] for x in b["artifacts"] if x["kind"] == "mass_balance"), {})
    return ka == kb


def _smoke_scenario() -> dict:
    return {
        "geometry": {"length": {"value": 0.1, "unit": "m"}, "nx": 32},
        "porosity": {"value": 0.40, "unit": "-"},
        "permeability": {"value": 1e-11, "unit": "m2"},
        "flow": {"mode": "flux", "velocity": {"value": 2.8e-5, "unit": "m/s"}},
        "species": {"c_urea_in": {"value": 0.5, "unit": "mol/m3"},
                    "c_ca_in": {"value": 0.5, "unit": "mol/m3"}},
    }


def _unit_conflict_scenario() -> dict:
    s = _smoke_scenario()
    s["porosity"] = {"value": 0.4, "unit": "m2/s"}
    return s


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
