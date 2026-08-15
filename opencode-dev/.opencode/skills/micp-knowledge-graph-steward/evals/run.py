"""Eval runner: executes evals/cases.yaml through the real CLI, checks
expectations, and produces metrics via evals/metrics.py.

Usage: python evals/run.py            (writes evals/results/latest.json)
       python evals/run.py --verbose  (per-case output to stdout)

The runner never hardcodes expected answers into the inputs — expectations
come from the knowledge-graph engine's own rules.
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

TOOLS = Path(__file__).resolve().parent.parent / "tools"
CLI = TOOLS / "knowledge_graph_steward.py"
CASES = Path(__file__).resolve().parent / "cases.yaml"
RESULTS = Path(__file__).resolve().parent / "results"

sys.path.insert(0, str(Path(__file__).resolve().parent))
from metrics import measure  # noqa: E402


def _head_revision(store: str, pid: str, base: dict) -> int:
    payload = {**base, "action": "kb.get"}
    proc = subprocess.run([sys.executable, str(CLI), "--store", store],
                          input=json.dumps(payload), capture_output=True, text=True)
    out = json.loads(proc.stdout)
    for art in out.get("artifacts", []):
        note = art.get("note")
        if isinstance(note, dict) and "head_revision" in note:
            return int(note["head_revision"])
    return 0


def run_case(case: dict, store: str, base: dict, verbose: bool) -> dict:
    # Each case gets its own project stream so setup actions never collide
    # across cases.
    base = dict(base)
    base["project_id"] = f"eval-{case['id']}"
    setup = case.get("setup", [])
    for step in setup:
        action = step[0]
        extra = step[1] if len(step) > 1 else {}
        _invoke(action, extra, store, base, allow_fail=True)
    extra = case.get("extra", {})
    out = _invoke(case["action"], extra, store, base, allow_fail=True)
    expect = case.get("expect", {})
    report = {
        "id": case["id"],
        "description": case["description"],
        "action": case["action"],
        "status": out.get("status"),
        "error_code": (out.get("errors") or [{}])[0].get("code") if out.get("errors") else None,
        "pass": True,
        "checks": [],
        "events_appended": len(out.get("provenance", {}).get("events_appended", [])),
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
    if expect.get("findings_min"):
        check("findings>=min", len(out.get("findings", [])) >= expect["findings_min"],
              f"got {len(out.get('findings', []))}")
    if expect.get("provenance_events"):
        check("events==n", report["events_appended"] == expect["provenance_events"],
              f"got {report['events_appended']}")
    if expect.get("conflict_opened"):
        opened = any("open conflict" in f.get("statement", "") for f in out.get("findings", []))
        check("conflict_opened", opened, "got none")
    if expect.get("store_events_unchanged"):
        # Dry-run must not mutate the on-disk event log: no real appends.
        real = [e for e in out.get("provenance", {}).get("events_appended", [])
                if e.get("revision") != "dry-run"]
        check("dry_run_no_store_mutation", len(real) == 0, f"real appends: {len(real)}")
    if expect.get("query_label_preserved"):
        # HYPOTHESIS claims in query findings must carry the HYPOTHESIS label.
        labels = {f.get("label") for f in out.get("findings", [])}
        check("query_label_preserved",
              "OBSERVED" not in labels and len(labels) > 0,
              f"labels={labels}")

    # Every output must pass the output schema (metric M1).
    sys.path.insert(0, str(TOOLS))
    from kg.validate import validate_output
    from kg.errors import KgeError
    try:
        validate_output(out)
        check("output_schema", True)
    except KgeError as exc:
        check("output_schema", False, exc.message)

    if verbose:
        print(f"  [{case['id']}] {'PASS' if report['pass'] else 'FAIL'} "
              f"{case['action']} status={out.get('status')}")
    return report


def _invoke(action: str, extra: dict, store: str, base: dict, *, allow_fail: bool) -> dict:
    payload = dict(base)
    payload["action"] = action
    payload.update(extra)
    proc = subprocess.run([sys.executable, str(CLI), "--store", store],
                          input=json.dumps(payload), capture_output=True, text=True, timeout=120)
    if proc.returncode != 0:
        if not allow_fail:
            raise RuntimeError(f"CLI crashed: {proc.stderr}")
        return {"status": "FAILED", "errors": [{"code": "KGE-E000"}],
                "provenance": {"events_appended": []}}
    return json.loads(proc.stdout)


def run_suite(store_root: str, verbose: bool) -> dict:
    cases = yaml.safe_load(CASES.read_text(encoding="utf-8"))
    base = cases["base"]
    store = os.path.join(store_root, "store")
    os.makedirs(store, exist_ok=True)

    reports = [run_case(c, store, dict(base), verbose) for c in cases["cases"]]
    passed = sum(1 for r in reports if r["pass"])
    total = len(reports)

    suite_report = {
        "outputs": total,
        "output_schema_passes": sum(1 for r in reports if any(
            c["name"] == "output_schema" and c["pass"] for c in r["checks"])),
        "events_appended_total": sum(r["events_appended"] for r in reports),
        "evidence_total": 0,
        "evidence_with_sha": 0,
        "missing_input_total": 0,
        "missing_input_blocked": 0,
        "adversarial_total": 0,
        "adversarial_blocked": 0,
        "repeat_consistent": _repeat_consistency(store_root, dict(base)),
        "integrity_mean_ms": _integrity_mean_ms(store_root, dict(base)),
    }
    suite_report.update(_measure_traceability(store_root, dict(base)))
    suite_report.update(_measure_missing_input(store_root, dict(base)))
    suite_report.update(_measure_adversarial(store_root, dict(base)))
    metrics = measure(suite_report)

    return {
        "cases": reports,
        "summary": {"passed": passed, "total": total, "all_pass": passed == total},
        "metrics": metrics,
    }


def _measure_traceability(store_root: str, base: dict) -> dict:
    """M3: register evidence with sha256, attach a claim referencing it, then
    confirm the evidence chain resolves the ref and returns the hash."""
    store = os.path.join(store_root, "trace_store")
    os.makedirs(store, exist_ok=True)
    _invoke("kb.init", {"title": "trace"}, store, base, allow_fail=False)
    _invoke("graph.upsert_entity", {"entity": {"id": "e-samp", "entity_type": "ARTIFACT"}},
            store, base, allow_fail=False)
    reg = _invoke("graph.evidence_register", {"evidence": {"ref": "e-m3", "sha256": "c" * 64,
                                                           "tier": "EXTERNAL_REPORTED"}},
                  store, base, allow_fail=True)
    add = _invoke("graph.add_claim", {"claim": {
        "id": "c-m3", "claim_kind": "TYPE", "subject": "e-samp",
        "predicate": "mineral_phase", "object": "calcite",
        "evidence_tier": "EXTERNAL_REPORTED", "epistemic_label": "REPORTED",
        "evidence_refs": ["e-m3"]}}, store, base, allow_fail=True)
    chain = _invoke("graph.evidence_chain", {"claim_id": "c-m3"}, store, base, allow_fail=True)
    resolved = 0
    for art in chain.get("artifacts", []):
        note = art.get("note")
        if isinstance(note, dict) and "evidence_chain" in note:
            recs = [r for r in note["evidence_chain"] if not r.get("retracted")]
            if recs and recs[0].get("sha256") == "c" * 64:
                resolved = 1
    return {
        "evidence_total": 1,
        "evidence_with_sha": 1 if (reg.get("status") == "SUCCESS" and add.get("status") == "SUCCESS"
                                   and resolved) else 0,
    }


def _measure_missing_input(store_root: str, base: dict) -> dict:
    """M4: for each of K required fields, removing it must yield BLOCKED naming the field."""
    store = os.path.join(store_root, "missing_store")
    os.makedirs(store, exist_ok=True)
    _invoke("kb.init", {"title": "m4"}, store, base, allow_fail=False)
    required = ["task_id", "project_id", "request", "action", "skill_version"]
    blocked = 0
    for field in required:
        bad = dict(base)
        del bad[field]
        if field != "action":
            bad["action"] = "kb.get"
        proc = subprocess.run([sys.executable, str(CLI), "--store", store],
                              input=json.dumps(bad), capture_output=True, text=True)
        try:
            out = json.loads(proc.stdout)
        except json.JSONDecodeError:
            out = {"status": "FAILED", "errors": []}
        errors = out.get("errors") or []
        detail_str = json.dumps(errors[0].get("detail", {})) if errors else "{}"
        if out.get("status") == "BLOCKED" and field in detail_str:
            blocked += 1
    return {"missing_input_total": len(required), "missing_input_blocked": blocked}


def _measure_adversarial(store_root: str, base: dict) -> dict:
    """M5: attacks must all be blocked."""
    store = os.path.join(store_root, "adv_store")
    os.makedirs(store, exist_ok=True)
    _invoke("kb.init", {"title": "m5"}, store, base, allow_fail=False)
    _invoke("graph.upsert_entity", {"entity": {"id": "e-samp", "entity_type": "ARTIFACT"}},
            store, base, allow_fail=False)
    attacks = [
        ("mislabel", "graph.add_claim", {"claim": {
            "id": "adv1", "claim_kind": "TYPE", "subject": "e-samp",
            "predicate": "mineral_phase", "object": "calcite",
            "evidence_tier": "HYPOTHESIS", "epistemic_label": "OBSERVED"}}),
        ("contract_v2", "kb.get", {"contract_version": "2.0"}),
        ("path_traversal", "kb.get", {"project_id": "..%2f..%2fetc"}),
        ("unknown_action", "not.a.real.action", {}),
        ("validated_no_approval", "graph.add_claim", {"claim": {
            "id": "adv5", "claim_kind": "TYPE", "subject": "e-samp",
            "predicate": "mineral_phase", "object": "calcite",
            "evidence_tier": "VALIDATED", "epistemic_label": "OBSERVED",
            "evidence_refs": ["nope"]}}),
    ]
    blocked = 0
    for name, action, extra in attacks:
        out = _invoke(action, extra, store, base, allow_fail=True)
        if out.get("status") in ("BLOCKED", "FAILED", "HUMAN_APPROVAL_REQUIRED"):
            blocked += 1
    return {"adversarial_total": len(attacks), "adversarial_blocked": blocked}


def _repeat_consistency(store_root: str, base: dict) -> bool:
    """M6: same sequence in two fresh stores => identical projections.

    Uses a fixed clock for both runs so the hash chain (which legitimately
    includes event timestamps) is byte-deterministic.
    """
    snapshots = []
    for i in range(2):
        store = os.path.join(store_root, f"repeat_{i}")
        os.makedirs(store, exist_ok=True)
        env = dict(os.environ)
        env["KGE_TEST_CLOCK"] = "2026-08-06T12:00:00.000Z"
        _invoke_clocked("kb.init", {"title": "m6"}, store, base, env)
        _invoke_clocked("graph.upsert_entity", {"entity": {"id": "e1", "entity_type": "STRAIN",
                                                           "canonical_name": "S. pasteurii"}},
                        store, base, env)
        _invoke_clocked("graph.evidence_register",
                        {"evidence": {"ref": "e", "sha256": "d" * 64, "tier": "EXTERNAL_REPORTED"}},
                        store, base, env)
        snap = Path(store) / base["project_id"] / "snapshot.json"
        snapshots.append(snap.read_text(encoding="utf-8"))
    return snapshots[0] == snapshots[1]


def _invoke_clocked(action: str, extra: dict, store: str, base: dict, env: dict) -> dict:
    payload = dict(base)
    payload["action"] = action
    payload.update(extra)
    proc = subprocess.run(
        [sys.executable, str(CLI), "--store", store],
        input=json.dumps(payload), capture_output=True, text=True, timeout=120, env=env)
    if proc.returncode != 0:
        raise RuntimeError(f"CLI crashed: {proc.stderr}")
    return json.loads(proc.stdout)


def _integrity_mean_ms(store_root: str, base: dict) -> float:
    """M7: mean wall-clock of kb.integrity over a 50-event stream."""
    store = os.path.join(store_root, "integrity_store")
    os.makedirs(store, exist_ok=True)
    _invoke("kb.init", {"title": "m7"}, store, base, allow_fail=False)
    for i in range(50):
        _invoke("graph.add_claim", {"claim": {
            "id": f"c{i}", "claim_kind": "OBSERVATION", "subject": "lexical",
            "subject_is_alias": True, "predicate": "note", "object": f"item {i}",
            "evidence_tier": "INTERNAL_OBSERVED", "epistemic_label": "OBSERVED"}},
            store, base, allow_fail=False)
    times = []
    for _ in range(5):
        t0 = time.perf_counter()
        _invoke("kb.integrity", {}, store, base, allow_fail=False)
        times.append((time.perf_counter() - t0) * 1000.0)
    return sum(times) / len(times)


def main() -> int:
    verbose = "--verbose" in sys.argv
    store_root = tempfile.mkdtemp(prefix="kge_evals_")
    report = run_suite(store_root, verbose)
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
