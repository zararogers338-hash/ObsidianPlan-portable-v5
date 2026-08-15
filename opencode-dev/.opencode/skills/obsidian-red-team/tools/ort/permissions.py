"""Permission-boundary checker (权限越界检查器).

Audits declared/observed actions against the skill's permission boundary:

  - this skill (obsidian-red-team) is read-only: `tool_permissions: [read]`,
    `network: false`, `writes: audit/**` only.
  - audited conclusions, data, and long-term knowledge are NEVER writable by
    this skill.
  - a Skill writing to the long-term knowledge base (`verified_knowledge` /
    `project_memory`) without approval is BLOCKING (BLOCK-9).

Input shape (`actions`):
  [
    {
      "actor": "skill:micp-data-analyst",
      "action": "memory.promote",
      "target_tier": "verified_knowledge",
      "approval": "granted|missing",
      "writes": ["audit/report.json"],
      "mutation_of_audited_conclusion": false
    }
  ]

The checker is generic: it validates declared actions against a boundary
table, so it can audit ANY skill's permission claims, not just this one.
"""

from __future__ import annotations

from typing import Any

from common import ToolError, emit_progress
from errors import OrtErrorCode, OrtError

# Targets a skill may NEVER write without human approval, regardless of role.
SENSITIVE_TIERS = ("verified_knowledge", "project_memory")

# Long-term knowledge targets (writing here = promotion, gated by approval).
LONG_TERM_TARGETS = ("verified_knowledge", "project_memory")


def _audit_action(act: dict[str, Any]) -> dict[str, Any]:
    actor = str(act.get("actor", "?"))
    action = str(act.get("action", ""))
    writes = act.get("writes") or []
    findings: list[dict] = []

    # 1) sensitive-tier write without approval
    tier = act.get("target_tier")
    if tier in SENSITIVE_TIERS:
        approval = act.get("approval", "missing")
        if approval != "granted":
            findings.append({
                "actor": actor, "severity": "BLOCKING", "dimension": "permission_boundary",
                "message": f"action {action} writes to long-term tier {tier!r} without human approval",
                "code": "PERM_LONG_TERM_WRITE",
            })

    # 2) mutating an audited conclusion
    if act.get("mutation_of_audited_conclusion"):
        findings.append({
            "actor": actor, "severity": "BLOCKING", "dimension": "permission_boundary",
            "message": f"action {action} mutates an audited conclusion: Red Team may not modify "
                       "the audited conclusion or data",
            "code": "PERM_MUTATE_AUDITED",
        })

    # 3) writes outside the allowed subtree
    allowed_prefixes = act.get("allowed_writes") or ["audit/"]
    for w in writes:
        if not any(str(w).startswith(p) for p in allowed_prefixes):
            findings.append({
                "actor": actor, "severity": "CRITICAL", "dimension": "permission_boundary",
                "message": f"write target {w!r} outside allowed subtrees {allowed_prefixes}",
                "code": "PERM_WRITE_OUTSIDE",
            })

    # 4) direct downstream invocation by a specialist skill (star topology)
    if act.get("invokes_other_skill") and actor.startswith("skill:"):
        findings.append({
            "actor": actor, "severity": "MAJOR", "dimension": "permission_boundary",
            "message": "specialist skill invokes another skill directly; star topology requires "
                       "routing via the Controller",
            "code": "PERM_DIRECT_INVOKE",
        })

    return {"actor": actor, "action": action, "legal": not findings, "findings": findings}


def main(payload: dict[str, Any]) -> dict[str, Any]:
    emit_progress("permissions: checking permission boundaries")
    actions = payload.get("actions")
    if not actions:
        raise OrtError(OrtErrorCode.INPUT_SCHEMA_VIOLATION,
                       "permissions: actions array is required",
                       detail={"how_to_fix": "attach the declared/observed actions to audit"})
    results = [_audit_action(a) for a in actions]
    blocking = [f for r in results for f in r["findings"] if f["severity"] == "BLOCKING"]
    return {
        "actions": results,
        "summary": {
            "actions_checked": len(actions),
            "legal": sum(1 for r in results if r["legal"]),
            "illegal": sum(1 for r in results if not r["legal"]),
            "blocking": len(blocking),
            "codes": sorted({f["code"] for f in blocking}),
        },
    }


if __name__ == "__main__":
    from common import read_stdin_envelope, run_tool
    run_tool("permissions", lambda: main(read_stdin_envelope()))
