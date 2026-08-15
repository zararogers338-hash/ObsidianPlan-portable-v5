"""Eval runner: executes evals/cases.yaml through the real CLI, checks
expectations, and produces M1–M7 metrics via evals/metrics.py.

Usage: python evals/run.py             (writes evals/results/latest.json)
       python evals/run.py --verbose   (per-case output to stdout)

The runner never hardcodes expected answers into inputs — expectations come
from the skill's own rules (status codes / schema / reproducibility).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import yaml

SKILL_ROOT = Path(__file__).resolve().parent.parent
TOOLS = SKILL_ROOT / "tools"
CLI = TOOLS / "literature_scout.py"
CASES = Path(__file__).resolve().parent / "cases.yaml"
RESULTS = Path(__file__).resolve().parent / "results"

sys.path.insert(0, str(Path(__file__).resolve().parent))
from metrics import measure  # noqa: E402

sys.path.insert(0, str(SKILL_ROOT / "tools"))

REQUIRED_FIELDS = ["task_id", "project_id", "request", "action", "skill_version",
                   "contract_version", "timestamp"]


def _invoke(payload: dict, offline: bool = True) -> dict:
    args = [sys.executable, str(CLI)]
    if offline:
        args.append("--offline")
    proc = subprocess.run(args, input=json.dumps(payload), capture_output=True,
                          text=True, timeout=120)
    if proc.returncode == 0:
        return json.loads(proc.stdout)
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError:
        return {"status": "FAILED", "summary": "CLI crash",
                "findings": [], "assumptions": [], "evidence_used": [],
                "uncertainty": [], "risks": [], "artifacts": [],
                "requested_next_skills": [], "validation": {}, "provenance": {},
                "errors": [{"code": "MLS-E000", "message": proc.stderr[:200], "detail": {}}]}


def run_case(case: dict, base: dict, verbose: bool) -> dict:
    payload = dict(base)
    payload["action"] = case["action"]
    payload.update(case.get("extra", {}))
    for field in case.get("drop_fields", []):
        payload.pop(field, None)
    if "project_id" in payload:
        payload["project_id"] = f"{payload['project_id']}-{case['id']}"

    t0 = time.perf_counter()
    out = _invoke(payload)
    elapsed_ms = (time.perf_counter() - t0) * 1000.0

    expect = case.get("expect", {})
    report = {
        "id": case["id"],
        "description": case["description"],
        "action": case["action"],
        "status": out.get("status"),
        "error_code": (out.get("errors") or [{}])[0].get("code"),
        "elapsed_ms": round(elapsed_ms, 2),
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
    if "named_field" in expect:
        detail = (out.get("errors") or [{}])[0].get("detail", {})
        check("field_named", expect["named_field"] in detail.get("missing_fields", {}),
              f"missing_fields={list(detail.get('missing_fields', {}).keys())}")
    if expect.get("result_count_gt"):
        check("result_count>0", (out.get("search") or {}).get("result_count", 0) > 0,
              f"got {(out.get('search') or {}).get('result_count')}")
    if expect.get("triage_tier1_gt"):
        tiers = out.get("triage", {}).get("levels", [])
        check("tier1>0", sum(1 for t in tiers if t["level"] == "TIER1") > 0,
              "no TIER1 found")
    if expect.get("doi_statuses_include"):
        statuses = {r["status"] for r in out.get("doi_verifications", [])}
        check("doi_statuses", set(expect["doi_statuses_include"]).issubset(statuses),
              f"got {sorted(statuses)}")
    if expect.get("all_forged"):
        statuses = {r["status"] for r in out.get("doi_verifications", [])}
        check("all_forged", statuses == {"suspected_forged"}, f"got {sorted(statuses)}")
        check("no_reported_forged", all(f.get("label") != "REPORTED"
                                        for f in out.get("findings", [])), "")
    if expect.get("all_years_ge"):
        years = [r.get("year") for r in out.get("search", {}).get("records", [])]
        check("years>=limit", all(y is None or y >= expect["all_years_ge"] for y in years),
              f"years={years}")
    if expect.get("export_contains"):
        content = (out.get("exports") or [{}])[0].get("content", "")
        check("export_contains", expect["export_contains"] in content, "substring missing")
    if expect.get("dedup_input"):
        check("dedup_input", out.get("dedup", {}).get("input_count") == expect["dedup_input"],
              f"got {out.get('dedup', {}).get('input_count')}")
    if expect.get("dedup_output"):
        check("dedup_output", out.get("dedup", {}).get("output_count") == expect["dedup_output"],
              f"got {out.get('dedup', {}).get('output_count')}")
    if expect.get("selfcheck_passed"):
        check("selfcheck", out.get("selfcheck", {}).get("passed") is True,
              f"got {out.get('selfcheck', {}).get('passed')}")

    # Every output must validate against output.schema.json (M1).
    from micp_lit.validate import validate_output

    valid, _issues = validate_output(out)
    check("output_schema", valid)
    report["output_schema_pass"] = valid

    if verbose:
        print(f"  [{case['id']}] {'PASS' if report['pass'] else 'FAIL'} "
              f"{case['action']} status={out.get('status')}")
    return report


def _measure_reproducibility(store_dir: str, base: dict) -> bool:
    """M6: same query twice (separate processes) → identical repro_id + records."""
    payload = dict(base)
    payload["action"] = "search.run"
    payload["query"] = {"text": "MICP uniformity"}
    payload["project_id"] = "m6"
    first = _invoke(payload)
    second = _invoke(payload)
    if first.get("status") != "SUCCESS" or second.get("status") != "SUCCESS":
        return False
    return (first["provenance"].get("repro_id") == second["provenance"].get("repro_id")
            and first.get("search", {}).get("records") == second.get("search", {}).get("records"))


def _measure_traceability(base: dict) -> dict:
    """M3: fraction of returned records whose DOI is traceable."""
    payload = dict(base)
    payload["action"] = "search.run"
    payload["query"] = {"text": "MICP uniformity", "n": 50}
    payload["project_id"] = "m3"
    out = _invoke(payload)
    records = out.get("search", {}).get("records", [])
    if not records:
        return {"total_records": 0, "traceable_records": 0}
    from micp_lit.doi import is_structural_doi

    traceable = sum(1 for r in records if is_structural_doi(r.get("doi") or ""))
    return {"total_records": len(records), "traceable_records": traceable}


def _measure_missing_input(base: dict) -> dict:
    """M4: for each required field dropped, BLOCKED + E102 naming the field."""
    named = 0
    for field in REQUIRED_FIELDS:
        payload = dict(base)
        payload["action"] = "search.run"
        payload.pop(field, None)
        out = _invoke(payload)
        if out.get("status") != "BLOCKED":
            continue
        detail = (out.get("errors") or [{}])[0].get("detail", {})
        if field in detail.get("missing_fields", {}):
            named += 1
    return {"missing_input_total": len(REQUIRED_FIELDS), "missing_input_named": named}


def _measure_adversarial(base: dict) -> dict:
    """M5: forged DOI, unknown action, contract conflict → all intercepted."""
    blocked = 0
    attacks = [
        {"id": "adv-forged", "action": "doi.verify",
         "extra": {"candidate_dois": ["10.9999/fake.biocement.2024.00001"]},
         "ok": ("PARTIAL", "FAILED", "BLOCKED")},
        {"id": "adv-action", "action": "not.a.real.action", "extra": {},
         "ok": ("FAILED", "BLOCKED")},
        {"id": "adv-contract", "action": "search.run",
         "extra": {"contract_version": "2.0"}, "ok": ("BLOCKED",)},
    ]
    for attack in attacks:
        payload = dict(base)
        payload["action"] = attack["action"]
        payload.update(attack["extra"])
        payload["project_id"] = f"adv-{attack['id']}"
        out = _invoke(payload)
        if out.get("status") in attack["ok"]:
            blocked += 1
    return {"adversarial_total": len(attacks), "adversarial_blocked": blocked}


def _measure_recovery_ms(base: dict) -> float:
    """M7: mean wall-clock to produce a BLOCKED envelope (missing field)."""
    samples = []
    for _ in range(5):
        payload = dict(base)
        payload["action"] = "search.run"
        payload.pop("request", None)
        t0 = time.perf_counter()
        _invoke(payload)
        samples.append((time.perf_counter() - t0) * 1000.0)
    return sum(samples) / len(samples)


def run_suite(verbose: bool) -> dict:
    cases = yaml.safe_load(CASES.read_text(encoding="utf-8"))
    base = cases["base"]

    reports = [run_case(c, dict(base), verbose) for c in cases["cases"]]
    passed = sum(1 for r in reports if r["pass"])
    total = len(reports)

    output_schema_passes = sum(1 for r in reports if r["output_schema_pass"])
    # M2: tool real-call rate = search.* cases that reached the handler AND
    # returned records / all search.* cases that reached the handler.
    # Cases blocked before dispatch (missing-request, conflict-contract,
    # boundary-short-query) never invoked the tool, so they don't count as
    # attempts — the rate measures tool honesty, not envelope handling.
    _reached_handler = {c["id"] for c in cases["cases"]
                        if c["action"].startswith("search.")
                        and "dry_run" not in str(c.get("extra", {}))}
    _blocked_pre_dispatch = {"missing-request", "conflict-contract", "boundary-short-query"}
    _attempts = _reached_handler - _blocked_pre_dispatch
    tool_real_attempts = max(len(_attempts), 1)
    tool_real_calls = sum(1 for r in reports
                          if r["action"].startswith("search.")
                          and r["id"] in _attempts
                          and r["status"] in ("SUCCESS", "PARTIAL"))

    suite = {
        "outputs": total,
        "output_schema_passes": output_schema_passes,
        "tool_real_attempts": max(tool_real_attempts, 1),
        "tool_real_calls": tool_real_calls,
        **(_measure_traceability(base)),
        **(_measure_missing_input(base)),
        **(_measure_adversarial(base)),
        "repeat_consistent": _measure_reproducibility("", base),
        "recovery_mean_ms": _measure_recovery_ms(base),
    }
    metrics = measure(suite)
    return {
        "cases": reports,
        "summary": {"passed": passed, "total": total, "all_pass": passed == total},
        "metrics": metrics,
        "suite_counts": suite,
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
    for key, m in report["metrics"]["report"].items():
        print(f"  {key}: measured={m['measured']:.3f} threshold={m['threshold']} pass={m['pass']}")
    print(f"report written to {path}")
    return 0 if (report["summary"]["all_pass"] and metrics_ok) else 1


if __name__ == "__main__":
    raise SystemExit(main())
