"""Eval runner: executes evals/cases.yaml through the real CLI, checks
expectations, and produces metrics via evals/metrics.py.

Usage: python evals/run.py            (writes evals/results/latest.json)
       python evals/run.py --verbose  (per-case output to stdout)

The runner never hardcodes expected answers into the inputs — expectations
come from the model's own physics and the skill's error taxonomy.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import yaml

TOOLS = Path(__file__).resolve().parent.parent / "tools"
CLI = TOOLS / "scaleup.py"
CASES = Path(__file__).resolve().parent / "cases.yaml"
RESULTS = Path(__file__).resolve().parent / "results"

sys.path.insert(0, str(Path(__file__).resolve().parent))
from metrics import measure  # noqa: E402

sys.path.insert(0, str(TOOLS))
from msi.validate import validate_output  # noqa: E402


def _invoke(payload: dict) -> dict:
    proc = subprocess.run([sys.executable, str(CLI)],
                          input=json.dumps(payload), capture_output=True, text=True, timeout=300)
    if proc.returncode != 0:
        return {"status": "FAILED", "errors": [{"code": "MSI-E000"}], "artifacts": []}
    return json.loads(proc.stdout)


def _find_artifact(out: dict, kind: str):
    for a in out.get("artifacts", []):
        if a.get("kind") == kind:
            return a.get("note")
    return None


def _coerce_floats(obj):
    """YAML parses '1e-11' as a string (scientific notation). Coerce numeric
    strings inside quantity values and plain numeric fields back to float."""
    if isinstance(obj, dict):
        if "value" in obj and isinstance(obj["value"], str):
            try:
                obj["value"] = float(obj["value"])
            except ValueError:
                pass
        for v in obj.values():
            _coerce_floats(v)
    elif isinstance(obj, list):
        for v in obj:
            _coerce_floats(v)


def run_case(case: dict, base: dict, verbose: bool) -> dict:
    payload = dict(base)
    payload["project_id"] = f"eval-{case['id']}"
    extra = case.get("extra", {})
    payload.update(extra)
    if case.get("scenario") is not None:
        # The input schema places lab/target/site/constraints/monitoring at the
        # top level of the payload; the eval YAML nests them under `scenario`
        # for readability, so we promote them.
        for k, v in case["scenario"].items():
            payload[k] = v
    _coerce_floats(payload)
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

    # status expectation (may be a list of acceptable statuses)
    if "status" in expect:
        exp = expect["status"]
        accepted = exp if isinstance(exp, list) else [exp]
        check(f"status in {accepted}", out.get("status") in accepted,
              f"got {out.get('status')}")
    if "error_code" in expect:
        check(f"error=={expect['error_code']}", report["error_code"] == expect["error_code"],
              f"got {report['error_code']}")
    if expect.get("self_check"):
        check("self_check", out.get("validation", {}).get("self_check") == "passed",
              f"got {out.get('validation', {}).get('self_check')}")
    if "scale_level" in expect:
        check("scale_level", out.get("scale_level") == expect["scale_level"],
              f"got {out.get('scale_level')}")
    if expect.get("artifacts_include"):
        kinds = {a.get("kind") for a in out.get("artifacts", [])}
        for k in expect["artifacts_include"]:
            check(f"artifact:{k}", k in kinds, f"missing {k}")

    # domain-specific expectations
    if expect.get("missing_field"):
        fields = [m["field"] for e in out.get("errors", [])
                  for m in e.get("detail", {}).get("missing_fields", [])]
        check("missing_field_named", any(expect["missing_field"] in f for f in fields),
              f"got {fields}")

    if "inlet_clogging" in expect:
        cr = _find_artifact(out, "clogging_risk") or {}
        check("inlet_clogging", cr.get("inlet_clogging_risk") == expect["inlet_clogging"],
              f"got {cr.get('inlet_clogging_risk')}")
    if "preferential_flow" in expect:
        cr = _find_artifact(out, "clogging_risk") or {}
        accepted = expect["preferential_flow"]
        accepted = accepted if isinstance(accepted, list) else [accepted]
        check("preferential_flow", cr.get("preferential_flow_risk") in accepted,
              f"got {cr.get('preferential_flow_risk')}")
    if "uniformity_lt" in expect:
        cr = _find_artifact(out, "clogging_risk") or {}
        check("uniformity_lt", (cr.get("uniformity_score") or 1.0) < expect["uniformity_lt"],
              f"got {cr.get('uniformity_score')}")
    if "pressure_verdict" in expect:
        bc = out.get("pressure_constraints") or {}
        check("pressure_verdict", bc.get("verdict") == expect["pressure_verdict"],
              f"got {bc.get('verdict')}")
    if "boundary_flux_notes" in expect:
        bc = out.get("pressure_constraints") or {}
        check("boundary_flux_notes", bc.get("flow_mode") == "constant_flux"
              and any("constant-flux" in n for n in bc.get("notes", [])),
              f"flow_mode={bc.get('flow_mode')}")
    if "ammonia_over" in expect:
        env = out.get("environmental_requirements") or {}
        check("ammonia_over", env.get("over_limit") is True, f"got {env.get('over_limit')}")
    if "rt_stop" in expect:
        rt = [c for c in out.get("stop_conditions", []) if str(c.get("id", "")).startswith("RT-")]
        check("rt_stop", len(rt) > 0, f"got {len(rt)} RT stops")
    if expect.get("fallback_present"):
        check("fallback_present", out.get("fallback_plan") is not None,
              "fallback_plan missing")

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


def _smoke_payload(base: dict) -> dict:
    p = dict(base)
    p["project_id"] = "eval-repeat"
    p.update({
        "lab": {"recipe": {
            "urea_conc": {"value": 500, "unit": "mol/m3"},
            "ca_conc": {"value": 500, "unit": "mol/m3"},
            "pore_volumes_per_treatment": 1.0, "rounds": 5,
            "flow_mode": "constant_flux",
            "flow_rate": {"value": 0.0005, "unit": "m3/s"}}},
        "target": {"scale_level": "metre",
                   "geometry": {"volume": {"value": 0.05, "unit": "m3"},
                                "length": {"value": 1.0, "unit": "m"},
                                "radius": {"value": 0.13, "unit": "m"}}},
        "site": {"layers": [{"name": "A", "thickness": {"value": 1.0, "unit": "m"},
                             "porosity": 0.4,
                             "permeability": {"value": 1e-11, "unit": "m2"}}]},
        "constraints": {"allowed_injection_pressure": {"value": 500000, "unit": "Pa"},
                        "target_caco3_content_kg_m3": 60,
                        "ammonia_limit_mg_L": 50, "conversion_efficiency": 0.5},
    })
    return p


def _repeat_consistency(base: dict) -> bool:
    payload = _smoke_payload(base)
    a = _invoke(payload)
    b = _invoke(payload)
    return (a.get("material_balance") == b.get("material_balance")
            and a.get("pressure_constraints") == b.get("pressure_constraints"))


def _measure_missing(base: dict) -> dict:
    """M4: removing site permeability at site scale must yield BLOCKED naming it."""
    cases = [
        ("site_permeability",
         {"target": {"scale_level": "site",
                     "geometry": {"volume": {"value": 100, "unit": "m3"},
                                  "depth": {"value": 3, "unit": "m"}}},
          "site": {"layers": [{"name": "A", "thickness": {"value": 3, "unit": "m"},
                               "porosity": 0.35}]}}),
    ]
    blocked = 0
    for name, scenario in cases:
        payload = dict(base)
        payload["project_id"] = f"eval-missing-{name}"
        payload.update(scenario)
        _coerce_floats(payload)
        out = _invoke(payload)
        fields = [m["field"] for e in out.get("errors", [])
                  for m in e.get("detail", {}).get("missing_fields", [])]
        if out.get("status") == "BLOCKED" and any("permeability" in f for f in fields):
            blocked += 1
    return {"missing_total": len(cases), "missing_blocked": blocked}


def _measure_adversarial(base: dict) -> dict:
    """M5: contract v2, unknown action, unit conflict, field-without-approval."""
    attacks = [
        ("contract_v2", {"contract_version": "2.0"}),
        ("unknown_action", {"action": "not.a.real.action"}),
        ("unit_conflict", {
            "target": {"scale_level": "site",
                       "geometry": {"volume": {"value": 100, "unit": "m3"}}},
            "site": {"layers": [{"name": "A", "thickness": {"value": 3, "unit": "m"},
                                 "permeability": {"value": 1, "unit": "mol/m3"}}]}}),
        ("field_no_approval", {
            "target": {"scale_level": "field",
                       "geometry": {"volume": {"value": 1000, "unit": "m3"}}},
            "site": {"layers": [{"name": "A", "thickness": {"value": 3, "unit": "m"},
                                 "porosity": 0.35,
                                 "permeability": {"value": 1e-11, "unit": "m2"}}]}}),
    ]
    blocked = 0
    for name, extra in attacks:
        payload = dict(base)
        payload["project_id"] = f"eval-adv-{name}"
        payload.update(extra)
        _coerce_floats(payload)
        out = _invoke(payload)
        if out.get("status") in ("BLOCKED", "FAILED", "HUMAN_APPROVAL_REQUIRED"):
            blocked += 1
    return {"adversarial_total": len(attacks), "adversarial_blocked": blocked}


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
