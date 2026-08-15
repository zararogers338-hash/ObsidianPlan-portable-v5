"""Blocking rule engine (阻断规则引擎) — SINGLE SOURCE OF TRUTH for BLOCKING.

Ten deterministic rules decide whether a finding is BLOCKING, and derive the
state recommendation for the requested gate. The rules are data-driven over a
structured finding description; the engine never invents a BLOCKING out of
nothing, and a genuine BLOCKING pattern can never be downgraded by a caller.

Rule → input signal
  BLOCK-1  fabricated citation / fabricated data     citation verdict REJECTED/SUSPECTED or data untraceable
  BLOCK-2  ammonia exceedance still deployable       ammonia_concentration > limit AND recommends deployment
  BLOCK-3  open blocker + escalation/roll-forward     open_blockers > 0 AND claims upgrade/release
  BLOCK-4  mass balance violation                    balance.closed == false (beyond tolerance)
  BLOCK-5  pseudo-replication carries key conclusion  effective_n << rows AND significance rests on it
  BLOCK-6  regulations unverified for deployment      deployment AND no applicable-limit verification
  BLOCK-7  engineering blocker released               strength up but permeability down / no stop condition / release
  BLOCK-8  state escalation illegal                   escalation legal == false
  BLOCK-9  permission boundary crossed                long-term write without approval / audited mutation
  BLOCK-10 epistemic escalation supports deployment   HYPOTHESIS/INFERRED presented as OBSERVED to release

State recommendation:
  no BLOCKING  + gate VALIDATED/PILOT_READY/DEPLOYABLE  → APPROVE
  no BLOCKING  + gate REVIEW or none                    → NO_OBJECTION
  BLOCKING     + gate VALIDATED/PILOT_READY/DEPLOYABLE  → REVIEW_FAIL
  BLOCKING     + gate REVIEW or none                    → HOLD
"""

from __future__ import annotations

from typing import Any

from common import ToolError, emit_progress
from errors import OrtErrorCode, OrtError
from models import BlockingRuleId

# Default ammonia limit table (mg/L). Overridable via ammonia_limit_source /
# per-finding limit. Based on GB/T 14848-2017 Class III for groundwater.
DEFAULT_AMMONIA_LIMIT_MG_L = 0.5

# Default engineering closure tolerance for mass balance.
DEFAULT_BALANCE_TOLERANCE = 0.05


def _blocking_rule(finding: dict[str, Any]) -> str | None:
    """Return the BlockingRuleId that fires for this finding, or None."""
    rule = finding.get("rule")  # explicit rule request
    if rule:
        return rule

    # BLOCK-1 fabricated citation / data
    if finding.get("citation_verdict") in ("REJECTED", "SUSPECTED"):
        return BlockingRuleId.FABRICATED_CITATION.value
    if finding.get("data_fabricated"):
        return BlockingRuleId.FABRICATED_CITATION.value

    # BLOCK-2 ammonia exceedance still deployable
    ammonia = finding.get("ammonia_concentration")
    if ammonia is not None and finding.get("recommends_deployment"):
        limit = finding.get("ammonia_limit_mg_l", DEFAULT_AMMONIA_LIMIT_MG_L)
        try:
            if float(ammonia) > float(limit):
                return BlockingRuleId.AMMONIA_EXCEEDANCE.value
        except (TypeError, ValueError):
            pass

    # BLOCK-3 open blocker + escalation
    if finding.get("open_blockers", 0) > 0 and (
        finding.get("claims_upgrade") or finding.get("recommends_deployment")):
        return BlockingRuleId.OPEN_BLOCKER_ESCALATION.value

    # BLOCK-4 mass balance violation
    if finding.get("mass_balance_closed") is False:
        return BlockingRuleId.MASS_BALANCE_VIOLATION.value

    # BLOCK-5 pseudo-replication carries the key conclusion
    if finding.get("pseudo_replication"):
        if finding.get("pseudo_replication_carries_significance"):
            return BlockingRuleId.PSEUDOREPLICATION_CARRIES_KEY.value
        # effective_n tiny (e.g. < 8) AND significance rests on rows
        eff = finding.get("effective_n")
        rows = finding.get("rows")
        if eff is not None and rows is not None and eff < 8 and rows > eff:
            if finding.get("significance_rests_on_inflated_n"):
                return BlockingRuleId.PSEUDOREPLICATION_CARRIES_KEY.value

    # BLOCK-6 regulations unverified for deployment
    if finding.get("recommends_deployment") and finding.get("regulations_unverified"):
        return BlockingRuleId.REGULATION_UNVERIFIED.value

    # BLOCK-7 engineering blocker released
    if finding.get("recommends_deployment") and (
        finding.get("engineering_blocker") or
        finding.get("permeability_degraded") or
        finding.get("missing_stop_condition")):
        return BlockingRuleId.ENGINEERING_BLOCKER_RELEASE.value

    # BLOCK-8 state escalation illegal
    if finding.get("state_escalation_illegal"):
        return BlockingRuleId.STATE_ESCALATION.value

    # BLOCK-9 permission boundary crossed
    if finding.get("long_term_write_without_approval") or finding.get("mutates_audited"):
        return BlockingRuleId.PERMISSION_BOUNDARY.value

    # BLOCK-10 epistemic escalation supporting deployment
    if finding.get("epistemic_escalation") and finding.get("recommends_deployment"):
        return BlockingRuleId.EPISTEMIC_ESCALATION_DEPLOY.value

    # BLOCK-11 model boundary violation (same-data calibration+validation,
    # scale overflow) — a model that cannot support the claimed conclusion
    # blocks upgrade/deployment.
    if finding.get("model_boundary_blocking"):
        return BlockingRuleId.MODEL_BOUNDARY.value

    return None


def _evaluate_finding(finding: dict[str, Any]) -> dict[str, Any]:
    f_id = str(finding.get("id", "?"))
    rule = _blocking_rule(finding)
    if rule is None:
        return {"id": f_id, "blocking": False, "rule": None}
    return {
        "id": f_id,
        "blocking": True,
        "rule": rule,
        "detail": "BLOCKING rule fired; state upgrade must be refused while open",
    }


def _state_recommendation(gate: str, blocking_count: int) -> dict[str, Any]:
    if blocking_count > 0:
        if gate in ("VALIDATED", "PILOT_READY", "DEPLOYABLE"):
            return {
                "recommendation": "REVIEW_FAIL",
                "reason": f"{blocking_count} BLOCKING finding(s) open; state upgrade must be refused",
                "blocking_count": blocking_count,
            }
        return {
            "recommendation": "HOLD",
            "reason": f"{blocking_count} BLOCKING finding(s) open; hold pending closure",
            "blocking_count": blocking_count,
        }
    if gate in ("VALIDATED", "PILOT_READY", "DEPLOYABLE"):
        return {
            "recommendation": "APPROVE",
            "reason": "no BLOCKING findings; gate may proceed (conditions may still apply)",
            "blocking_count": 0,
        }
    return {
        "recommendation": "NO_OBJECTION",
        "reason": "no BLOCKING findings",
        "blocking_count": 0,
    }


def main(payload: dict[str, Any]) -> dict[str, Any]:
    emit_progress("blocking: evaluating BLOCKING rules and state recommendation")
    findings = payload.get("findings")
    if not findings:
        raise OrtError(OrtErrorCode.INPUT_SCHEMA_VIOLATION,
                       "blocking: findings array is required",
                       detail={"how_to_fix": "attach the candidate findings with rule signals"})
    results = [_evaluate_finding(f) for f in findings]
    blocking_ids = [r["id"] for r in results if r["blocking"]]
    gate = str(payload.get("state_gate", "REVIEW"))
    rec = _state_recommendation(gate, len(blocking_ids))
    return {
        "evaluations": results,
        "blocking_ids": blocking_ids,
        "blocking_count": len(blocking_ids),
        "rules_fired": sorted({r["rule"] for r in results if r["blocking"]}),
        "state_recommendation": rec,
        "note": "BLOCK-1..BLOCK-10 are the single source of truth; overrides must cite a rule",
    }


if __name__ == "__main__":
    from common import read_stdin_envelope, run_tool
    run_tool("blocking", lambda: main(read_stdin_envelope()))
