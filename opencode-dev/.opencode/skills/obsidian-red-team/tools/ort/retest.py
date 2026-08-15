"""Fix re-test verifier (修复复验工具).

Checks that a claimed fix is actually executable and verifiable:

  - executable: the fix names a concrete action (tool, re-run, data change,
    reference swap), not a wish ("improve", "consider")
  - verifiable: the acceptance criterion is falsifiable (a check exists that
    can pass or fail)
  - closure: the fix maps to a finding and a verification_method

Verdicts:
  PASS     — fix is executable and verifiable
  FAIL     — fix is not executable or not verifiable (MAJOR finding on the fix)
  PARTIAL  — one of the two is missing

Offline, deterministic, pure stdlib.
"""

from __future__ import annotations

import re
from typing import Any

from common import ToolError, emit_progress
from errors import OrtErrorCode, OrtError

# Vague, non-executable verbs → the fix does not name a concrete action.
VAGUE_VERBS = (
    "improve", "consider", "review", "think about", "look into", "explore",
    "should be", "may be", "hopefully", "增强", "考虑", "希望", "尽量", "进一步研究",
    "更多研究", "建议", "再想想", "better",
)

# Falsifiable acceptance markers: a number, a comparison, a tool run, a datum.
VERIFIABLE_PATTERNS = [
    re.compile(r"(?:≥|<=|>|<|=)\s*\d"),
    re.compile(r"\b(pass|fail|less than|greater than|below|above|within|equal|match|verify|confirm|证明|通过|不超过|达到)\b", re.IGNORECASE),
    re.compile(r"\b(re-?run|recompute|re-?calculate|re-?measure|re-?test|re-?assess|rerun|重算|复测|重测|复验|重新计算)\b", re.IGNORECASE),
    re.compile(r"\b(tool|pytest|eval|cli\.py|unit test|integration test)\b", re.IGNORECASE),
]


def _audit_fix(fix: dict[str, Any]) -> dict[str, Any]:
    f_id = str(fix.get("finding_id", "?"))
    fix_text = str(fix.get("fix", ""))
    acceptance = str(fix.get("acceptance", ""))
    verify_by = str(fix.get("verify_by", ""))
    issues: list[str] = []

    executable = True
    if not fix_text.strip():
        executable = False
        issues.append("fix is empty")
    else:
        lower = fix_text.lower()
        if any(v in lower for v in VAGUE_VERBS) and not re.search(r"\b(run|recompute|re-measure|replace|add|remove|change|rerun|重算|替换|删除|补充|改为|执行)\b", lower, re.IGNORECASE):
            executable = False
            issues.append("fix uses vague language without a concrete action")

    verifiable = True
    if not acceptance.strip():
        verifiable = False
        issues.append("acceptance criterion is empty")
    else:
        if not any(p.search(acceptance) for p in VERIFIABLE_PATTERNS):
            verifiable = False
            issues.append("acceptance criterion is not falsifiable (no check/number/comparison)")

    if not verify_by.strip():
        issues.append("verify_by (who/what verifies) is empty")

    if executable and verifiable:
        verdict = "PASS"
    elif executable or verifiable:
        verdict = "PARTIAL"
    else:
        verdict = "FAIL"

    return {
        "finding_id": f_id,
        "verdict": verdict,
        "executable": executable,
        "verifiable": verifiable,
        "issues": issues,
    }


def main(payload: dict[str, Any]) -> dict[str, Any]:
    emit_progress("retest: verifying fix executability and verifiability")
    fixes = payload.get("required_fixes")
    if not fixes:
        raise OrtError(OrtErrorCode.INPUT_SCHEMA_VIOLATION,
                       "retest: required_fixes array is required",
                       detail={"how_to_fix": "attach the proposed fixes with acceptance criteria"})
    results = [_audit_fix(f) for f in fixes]
    passed = sum(1 for r in results if r["verdict"] == "PASS")
    return {
        "fixes": results,
        "summary": {
            "total": len(results),
            "pass": passed,
            "partial": sum(1 for r in results if r["verdict"] == "PARTIAL"),
            "fail": sum(1 for r in results if r["verdict"] == "FAIL"),
            "all_executable_and_verifiable": passed == len(results),
        },
    }


if __name__ == "__main__":
    from common import read_stdin_envelope, run_tool
    run_tool("retest", lambda: main(read_stdin_envelope()))
