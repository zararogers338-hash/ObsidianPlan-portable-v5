"""State-escalation checker (状态越级检查器).

Checks whether a claimed state upgrade (SUPPORTED→VALIDATED→PILOT_READY→
DEPLOYABLE) is legal given the gates that must precede it.

The project's state machine (obsidian-state-manager) requires, for the three
load-bearing upgrades, the following preconditions:

  SUPPORTED → VALIDATED     requires review (verdict pass) + approval
  VALIDATED → PILOT_READY   requires red-team audit with no BLOCKING + approval
  PILOT_READY → DEPLOYABLE  requires red-team audit with no BLOCKING + human
                            approval (irreversible)

An escalation is ILLEGAL when any declared gate is missing or failed, or when
a BLOCKING finding from a prior red-team audit is still open.

Input shape (`escalations`):
  [
    {
      "target_id": "...",
      "from": "SUPPORTED",
      "to": "DEPLOYABLE",
      "review_verdict": "pass|fail|missing",
      "red_team_verdict": "pass|fail|missing",
      "approval": "granted|missing",
      "open_blockers": 0
    }
  ]
"""

from __future__ import annotations

from typing import Any

from common import ToolError, emit_progress
from errors import OrtErrorCode, OrtError

STATE_ORDER = ["OPEN", "SCOPED", "EVIDENCE_GATHERING", "HYPOTHESIS_BUILDING",
               "DESIGNING", "AWAITING_DATA", "ANALYZING", "UNDER_REVIEW",
               "SUPPORTED", "VALIDATED", "PILOT_READY", "DEPLOYABLE", "REJECTED"]


def _required_gates(from_state: str, to_state: str) -> list[str]:
    gates = []
    if to_state == "VALIDATED":
        gates.append("review_verdict")
    if to_state in ("PILOT_READY", "DEPLOYABLE"):
        gates.append("red_team_verdict")
        gates.append("review_verdict")
    if to_state == "DEPLOYABLE":
        gates.append("human_approval")
    return gates


def _audit_escalation(esc: dict[str, Any]) -> dict[str, Any]:
    target = str(esc.get("target_id", "?"))
    frm = str(esc.get("from", "OPEN"))
    to = str(esc.get("to", ""))
    issues: list[dict] = []

    if to not in STATE_ORDER:
        issues.append({
            "target_id": target, "severity": "CRITICAL", "dimension": "decision_gate",
            "message": f"unknown target state {to!r}",
            "code": "ESC_UNKNOWN_STATE",
        })
        return {"target_id": target, "legal": False, "issues": issues}

    # gap-skipping: a single transition may not skip a load-bearing state.
    # The project state machine has no direct SUPPORTED->DEPLOYABLE edge.
    if frm in ("SUPPORTED", "VALIDATED") and to == "DEPLOYABLE" and frm != "PILOT_READY":
        issues.append({
            "target_id": target, "severity": "BLOCKING", "dimension": "decision_gate",
            "message": f"state escalation {frm}→{to} skips intermediate gates; "
                       "project machine requires SUPPORTED→VALIDATED→PILOT_READY→DEPLOYABLE",
            "code": "ESC_SKIP_GATE",
        })

    gates = _required_gates(frm, to)
    if "review_verdict" in gates:
        verdict = esc.get("review_verdict", "missing")
        if verdict != "pass":
            issues.append({
                "target_id": target, "severity": "BLOCKING", "dimension": "decision_gate",
                "message": f"{frm}→{to} requires a passing review; verdict={verdict}",
                "code": "ESC_NO_REVIEW",
            })
    if "red_team_verdict" in gates:
        verdict = esc.get("red_team_verdict", "missing")
        if verdict != "pass":
            issues.append({
                "target_id": target, "severity": "BLOCKING", "dimension": "decision_gate",
                "message": f"{frm}→{to} requires a passing red-team audit; verdict={verdict}",
                "code": "ESC_NO_REDTEAM",
            })
    if "human_approval" in gates:
        approval = esc.get("approval", "missing")
        if approval != "granted":
            issues.append({
                "target_id": target, "severity": "BLOCKING", "dimension": "decision_gate",
                "message": f"{frm}→{to} requires human approval; approval={approval}",
                "code": "ESC_NO_APPROVAL",
            })

    open_blockers = int(esc.get("open_blockers", 0))
    if open_blockers > 0:
        issues.append({
            "target_id": target, "severity": "BLOCKING", "dimension": "decision_gate",
            "message": f"{open_blockers} BLOCKING finding(s) still open; escalation blocked",
            "code": "ESC_OPEN_BLOCKER",
        })

    return {"target_id": target, "from": frm, "to": to, "legal": not issues, "issues": issues}


def main(payload: dict[str, Any]) -> dict[str, Any]:
    emit_progress("escalation: checking state-upgrade legality")
    escalations = payload.get("escalations")
    if not escalations:
        raise OrtError(OrtErrorCode.INPUT_SCHEMA_VIOLATION,
                       "escalation: escalations array is required",
                       detail={"how_to_fix": "attach the claimed state upgrades to audit"})
    results = [_audit_escalation(e) for e in escalations]
    blocking = [i for r in results for i in r["issues"] if i["severity"] == "BLOCKING"]
    return {
        "escalations": results,
        "summary": {
            "escalations_checked": len(escalations),
            "legal": sum(1 for r in results if r["legal"]),
            "illegal": sum(1 for r in results if not r["legal"]),
            "blocking_issues": len(blocking),
            "codes": sorted({i["code"] for i in blocking}),
        },
    }


if __name__ == "__main__":
    from common import read_stdin_envelope, run_tool
    run_tool("escalation", lambda: main(read_stdin_envelope()))
