#!/usr/bin/env python3
"""Eval runner for micp-experiment-designer.

Runs the cases in `evals/cases.yaml` for real (no mocks): each `tool` case
invokes the actual tool module with its payload via the standard envelope;
each `check` case invokes `sop_check` in check mode. Computes the metrics in
`evals/metrics.md` and writes `audit/evals-latest.json`.

Offline and deterministic by construction. Exit 0 when all metrics meet their
thresholds, 1 otherwise.
"""

from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tools import _common  # noqa: E402
from tools import sop_check  # noqa: E402
from tools.mini_yaml import loads as yaml_loads  # noqa: E402


def _load_cases() -> list[dict[str, Any]]:
    path = Path(__file__).resolve().parent / "cases.yaml"
    doc = yaml_loads(path.read_text(encoding="utf-8"))
    return doc["cases"]


def _run_tool_case(case: dict[str, Any]) -> dict[str, Any]:
    tool = case["tool"]
    payload = case.get("payload") or {}
    try:
        mod = importlib.import_module(f"tools.{tool}")
        result = mod.main(payload)
        return {"ok": True, "exit": 0, "result": result}
    except _common.ToolError as err:
        return {"ok": False, "exit": err.exit_code, "error": {
            "code": err.code, "message": err.message,
            "retryable": err.retryable, "details": err.details}}


def _run_check_case(case: dict[str, Any]) -> dict[str, Any]:
    design = case["design"]
    try:
        result = sop_check.main({"design": design})
        return {"ok": True, "exit": 0, "result": result}
    except _common.ToolError as err:
        return {"ok": False, "exit": err.exit_code, "error": {"code": err.code}}


def _norm(v: Any) -> str:
    return json.dumps(v, sort_keys=True, default=str)


def _check_expected(case: dict[str, Any], outcome: dict[str, Any]) -> list[str]:
    """Return a list of unmet expected assertions (empty = case passed)."""
    expected = case["expected"]
    unmet: list[str] = []
    ok = outcome.get("ok")
    exit_code = outcome.get("exit")

    if expected.get("tool_ok") is not None and expected["tool_ok"] is not ok:
        unmet.append(f"expected tool_ok={expected['tool_ok']}, got {ok}")
    if expected.get("exit") is not None and expected["exit"] != exit_code:
        unmet.append(f"expected exit={expected['exit']}, got {exit_code}")

    for key, want in (expected.get("result_passes") or {}).items():
        got = outcome.get("result", {}).get(key)
        if isinstance(want, int) and key == "tradeoffs":
            # `tradeoffs` is a list; int expectation means min length
            if not isinstance(got, list) or len(got) < want:
                unmet.append(f"expected result.{key} to have >= {want} items, got {got!r}")
        elif isinstance(want, list):
            # want a non-empty list at least as long as `want`
            if not isinstance(got, list) or len(got) < len(want):
                unmet.append(f"expected result.{key} to have >= {len(want)} items, got {got!r}")
        else:
            if got != want:
                unmet.append(f"expected result.{key}={want}, got {got!r}")

    if expected.get("blocks"):
        issues = outcome.get("result", {}).get("blocking_issues") or []
        if not issues:
            unmet.append("expected blocking_issues non-empty")
    for field in expected.get("blocks_contain") or []:
        issues = outcome.get("result", {}).get("blocking_issues") or []
        if field not in issues:
            unmet.append(f"expected blocking_issues to contain '{field}', got {issues!r}")

    if expected.get("passes") is not None:
        got_pass = outcome.get("result", {}).get("pass")
        if got_pass is not expected["passes"]:
            unmet.append(f"expected pass={expected['passes']}, got {got_pass}")
    return unmet


def _score(results: list[tuple[dict[str, Any], dict[str, Any], list[str]]]) -> dict[str, Any]:
    total = sum(c["score"] for c, _, _ in results)
    passed = sum(c["score"] for c, _, unmet in results if not unmet)
    return {
        "structured_output_pass_rate": round(passed / total * 100, 2) if total else 100.0,
        "pass_threshold": 95.0,
        "cases": [
            {
                "id": c["id"],
                "name": c["name"],
                "score": c["score"],
                "passed": not unmet,
                "unmet": unmet,
            }
            for c, _, unmet in results
        ],
    }


def main() -> int:
    cases = _load_cases()
    results: list[tuple[dict[str, Any], dict[str, Any], list[str]]] = []
    for case in cases:
        mode = case["mode"]
        outcome = _run_tool_case(case) if mode == "tool" else _run_check_case(case)
        unmet = _check_expected(case, outcome)
        results.append((case, outcome, unmet))
        flag = "PASS" if not unmet else "FAIL"
        print(f"[{flag}] {case['id']} {case['name']}" + (f"  unmet={unmet}" if unmet else ""))

    metrics = _score(results)
    audit_dir = ROOT / "audit"
    audit_dir.mkdir(exist_ok=True)
    report = {"metrics": metrics, "thresholds_met": metrics["structured_output_pass_rate"] >= 95.0}
    (audit_dir / "evals-latest.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\nstructured_output_pass_rate = {metrics['structured_output_pass_rate']}% "
          f"(threshold 95%)")
    ok = metrics["structured_output_pass_rate"] >= 95.0
    print("METRICS " + ("PASS" if ok else "FAIL"))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
