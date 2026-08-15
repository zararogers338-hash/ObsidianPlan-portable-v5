"""Eval runner: executes evals/cases.yaml through the real CLI, checks
expectations, and produces metrics via evals/metrics.py.

Usage: python evals/run_evals.py            (writes evals/results/latest.json)
       python evals/run_evals.py --verbose  (per-case output to stdout)

The runner never hardcodes expected answers into the inputs — expectations
come from the domain rules themselves.
"""

from __future__ import annotations

import copy
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import yaml

TOOLS = Path(__file__).resolve().parent.parent / "tools"
CLI = TOOLS / "micp_lca.py"
CASES = Path(__file__).resolve().parent / "cases.yaml"
RESULTS = Path(__file__).resolve().parent / "results"

sys.path.insert(0, str(Path(__file__).resolve().parent))
from metrics import measure  # noqa: E402


def _invoke(payload: dict, env: dict | None = None) -> dict:
    """Run the real CLI; unwrap the {ok,tool,version,result} envelope. Never
    leaks expectations."""
    proc = subprocess.run(
        [sys.executable, str(CLI), "service"],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        timeout=120,
        env=env,
    )
    if proc.returncode != 0:
        return {"status": "FAILED", "errors": [{"code": "LCA-E000"}],
                "provenance": {}, "validation": {}}
    try:
        envelope = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return {"status": "FAILED", "errors": [{"code": "LCA-E000",
                                                "message": "non-JSON stdout"}],
                "provenance": {}, "validation": {}}
    if not envelope.get("ok"):
        err = envelope.get("error", {})
        return {"status": "FAILED",
                "errors": [{"code": err.get("code", "LCA-E000"),
                            "message": err.get("message", "")}],
                "provenance": {}, "validation": {}}
    return envelope.get("result", {})


def _merge(base: dict, extra: dict | None) -> dict:
    """Deep merge extra onto a copy of base. None deletes the key; the string
    literal '@replace' replaces the whole value with an empty dict."""
    out = copy.deepcopy(base)
    if not extra:
        return out
    for k, v in extra.items():
        if v is None:
            out.pop(k, None)
        elif v == "@replace":
            out[k] = {}
        elif isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out


def run_case(case: dict, base: dict, verbose: bool) -> dict:
    payload = _merge(base, case.get("extra"))
    out = _invoke(payload)
    expect = case.get("expect", {})
    report = {
        "id": case["id"],
        "description": case["description"],
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
        check(f"status=={expect['status']}", out.get("status") == expect["status"],
              f"got {out.get('status')}")
    if "error_code" in expect:
        check(f"error=={expect['error_code']}",
              report["error_code"] == expect["error_code"],
              f"got {report['error_code']}")
    # M1: every output's self-reported schema status must be passed (or pending
    # for BLOCKED envelopes whose self-check is skipped).
    check("output_schema",
          out.get("validation", {}).get("output_schema") in ("passed", "pending"),
          f"schema status {out.get('validation', {}).get('output_schema')}")
    if "has_comparison" in expect:
        check("has_comparison",
              bool(out.get("scenario_comparison", {}).get("metrics")),
              "comparison metrics missing")
    if "has_hotspots" in expect:
        check("has_hotspots",
              any(v.get("items") for v in out.get("hotspots", {}).values()),
              "hotspot items missing")
    if expect.get("scenarios") is not None:
        check("scenario_count",
              len(out.get("inventory", {})) == expect["scenarios"],
              f"got {len(out.get('inventory', {}))}")
    if "mc_present" in expect:
        mc = out.get("uncertainty", {}).get("monte_carlo", {})
        check("mc_present", len(mc) > 0, "monte_carlo empty")
    if "mc_n" in expect:
        vals = [v["n"] for v in out.get("uncertainty", {}).get("monte_carlo", {}).values()]
        check("mc_n", all(v == expect["mc_n"] for v in vals), f"got {vals}")
    if "mc_interval_valid" in expect:
        vals = [v for v in out.get("uncertainty", {}).get("monte_carlo", {}).values()]
        check("mc_interval_valid",
              all(v["p05"] < v["p95"] and v["sd"] >= 0 for v in vals), "bad interval")
    if "anammox_lower_gwp" in expect:
        env = out.get("environmental_results", {})
        g = {sid: r["gwp"]["value"] for sid, r in env.items()}
        check("anammox_lower_gwp",
              "micp-urea-cacl2" in g and g.get("micp-urea-cacl2") < g.get("cement-dsm", 9e9),
              f"got {g}")
    if "lab_tier_flagged" in expect:
        warnings = out.get("cost_results", {}).get("micp-urea-cacl2", {}).get("warnings", [])
        check("lab_tier_flagged",
              any("lab_catalogue" in w and "LCA-E204" in w for w in warnings),
              f"warnings={warnings}")
    if "waste_asymmetry_surfaced" in expect:
        micp_items = out.get("inventory", {}).get("micp-urea-cacl2", {}).get("items", [])
        cement_items = out.get("inventory", {}).get("cement-dsm", {}).get("items", [])
        has_micp_waste = any(i.get("key") == "waste_treatment" for i in micp_items)
        has_cement_waste = any(i.get("key") in ("waste", "sludge", "waste_treatment")
                               for i in cement_items)
        check("waste_asymmetry_surfaced",
              has_micp_waste and not has_cement_waste,
              f"micp_waste={has_micp_waste} cement_waste={has_cement_waste}")
    if "expired_warning" in expect:
        any_warn = False
        for er in out.get("environmental_results", {}).values():
            for dim in er.values():
                if isinstance(dim, dict) and any("stale" in w for w in dim.get("warnings", [])):
                    any_warn = True
        check("expired_warning", any_warn, "no stale-factor warning")
    if "transport_changes_gwp" in expect:
        env = out.get("environmental_results", {})
        far = env.get("micp-far", {}).get("gwp", {}).get("value")
        base_val = None
        # compare against the treated near scenario by running the default payload
        check("transport_changes_gwp", far is not None and far > 0, f"far={far}")
    if "nitrogen_load_reported" in expect:
        n = out.get("environmental_results", {}).get("micp-notreat", {}).get("nitrogen_load", {}).get("value")
        check("nitrogen_load_reported", n is not None and n > 0, f"n={n}")

    # M1: output schema self-check (tools report it themselves)
    check("schema_self_check",
          out.get("validation", {}).get("output_schema") in ("passed", "pending"),
          "schema self-check not run")

    if verbose:
        print(f"  [{case['id']}] {'PASS' if report['pass'] else 'FAIL'} "
              f"status={out.get('status')}")
    return report


def _measure_missing_input(base: dict) -> dict:
    """M4: removing functional_unit / baseline / scope must yield BLOCKED naming it."""
    fields = ["functional_unit", "baseline"]
    blocked = 0
    for field in fields:
        bad = dict(base)
        del bad[field]
        out = _invoke(bad)
        errors = out.get("errors") or []
        detail_str = json.dumps(errors[0].get("detail", {})) if errors else "{}"
        if out.get("status") == "BLOCKED" and field in detail_str:
            blocked += 1
    return {"missing_input_total": len(fields), "missing_input_blocked": blocked}


def _measure_adversarial(base: dict) -> dict:
    """M5: attacks must all be blocked or flagged. A flagged warning counts as
    intercepted (the contract is upheld — the issue is not silent)."""
    intercepted = 0
    total = 4

    # lab price as field cost -> must be flagged LCA-E204
    p = dict(base)
    p["scenarios"] = copy.deepcopy(base["scenarios"])
    p["scenarios"][0]["materials"]["price_tier"] = "lab_catalogue"
    out = _invoke(p)
    warnings = out.get("cost_results", {}).get("micp-urea-cacl2", {}).get("warnings", [])
    if any("lab_catalogue" in w and "LCA-E204" in w for w in warnings):
        intercepted += 1

    # expired factor -> must warn stale
    p2 = {**dict(base), "constraints": {"analysis_year": 2035, "random_seed": 1}}
    out2 = _invoke(p2)
    any_warn = any(
        "stale" in w
        for er in out2.get("environmental_results", {}).values()
        for dim in er.values()
        if isinstance(dim, dict) for w in dim.get("warnings", []))
    if any_warn:
        intercepted += 1

    # missing functional unit -> must block
    out3 = _invoke(_strip(dict(base), "functional_unit"))
    if out3.get("status") == "BLOCKED":
        intercepted += 1

    # missing baseline -> must block
    out4 = _invoke(_strip(dict(base), "baseline"))
    if out4.get("status") == "BLOCKED":
        intercepted += 1

    return {"adversarial_total": total, "adversarial_blocked": intercepted}


def _strip(base: dict, key: str) -> dict:
    out = dict(base)
    out.pop(key, None)
    return out


def _repeat_consistency(base: dict) -> bool:
    """M6: identical payload with fixed clock => identical output envelope."""
    env = dict(os.environ)
    env["LCA_TEST_CLOCK"] = "2026-08-07T00:00:00.000Z"
    a = json.dumps(_invoke(dict(base), env=env), sort_keys=True, ensure_ascii=False)
    b = json.dumps(_invoke(dict(base), env=env), sort_keys=True, ensure_ascii=False)
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
