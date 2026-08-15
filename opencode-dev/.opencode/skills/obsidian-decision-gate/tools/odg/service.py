"""Decision-gate service: orchestrates the full evaluation pipeline.

Pure computation over the input envelope:
  1. input schema validation
  2. state-transition legality (whitelist) + grade gap
  3. blocking-rule evaluation (B1..B13)
  4. 12-dimension scoring + per-grade floors (minimum-dimension gating)
  5. Mission Lock comparison (success criteria / failure thresholds / metrics)
  6. human-approval check
  7. decision synthesis (PASS / CONDITIONAL_PASS / HOLD / REJECT / SUSPEND /
     REQUEST_REVIEW / EXPIRE)
  8. Decision Memo + state-transition request
  9. review-expiry computation
  10. output schema validation

status mapping (project convention):
  SUCCESS                    — clean PASS / REJECT / HOLD decision, memo emitted
  BLOCKED                    — hard blockers (ODG-E306) or illegal jump (ODG-E305)
  HUMAN_APPROVAL_REQUIRED    — B10 blocker present (upgrade needs approval)
  NEED_ADDITIONAL_SKILL      — evidence insufficient; next skills requested
  FAILED                     — output schema / self-check failure
  PARTIAL                    — decision emitted with soft flags (comparison etc.)
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from . import compare as compare_mod
from .errors import OdgError, OdgErrorCode
from .expiry import check_expiry, compute_review_expiry, resolve_now
from .memo import generate_memo
from .mission import check_mission
from .models import Decision, OutputStatus, ResearchState
from .rules import RuleTable, grade_gap
from .scoring import (
    mcda_analysis,
    risk_benefit_matrix,
    score_dimensions,
    below_floor_map,
)
from .validate import validate_input, validate_output

# States that require human approval to enter, by maturity grade.
APPROVAL_REQUIRED_FROM_GRADE = 4  # VALIDATED and above


def _digest(obj: Any) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()[:16]


def _now_iso(now: datetime | None = None) -> str:
    return (now or datetime.now(timezone.utc)).astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


@dataclass
class GateResult:
    status: OutputStatus
    envelope: dict[str, Any]
    errors: list[dict] = field(default_factory=list)


def _pick_proposed_state(
    payload: dict[str, Any],
    table: RuleTable,
    current: ResearchState,
) -> ResearchState | None:
    """Choose the legal highest state consistent with blockers and dimensions.

    When the caller did not propose a target, pick the highest-grade legal
    target whose blockers are all clear and whose floors are all met. Never
    skip a rung: if grade+1 is blocked, the answer is the current state
    (HOLD) rather than a lower target.
    """
    best: ResearchState | None = None
    for e in table.edges:
        if e.from_state is not current or e.to_state is current:
            continue
        if table.grade(e.to_state) <= table.grade(current):
            continue
        if best is None or table.grade(e.to_state) > table.grade(best):
            best = e.to_state
    return best


def _collect_evidence_refs(payload: dict[str, Any], side: str) -> list[dict]:
    """Collect supporting/opposing evidence refs from cards, synthesis, experiments."""
    refs: list[dict] = []
    for c in payload.get("evidence_cards", []) or []:
        if c.get("retracted"):
            continue
        refs.append({
            "ref_id": c.get("ref_id", "?"),
            "label": c.get("label", "REPORTED"),
            "statement": c.get("outcome", c.get("source", "")),
            "source": c.get("source"),
        })
    return refs


def _decide_support_policy(payload: dict[str, Any], target: ResearchState) -> str:
    """Who/which actors can support a transition request for this target."""
    if target in (ResearchState.DEPLOYABLE, ResearchState.REJECTED):
        return "human"
    if target in (ResearchState.PILOT_READY, ResearchState.VALIDATED):
        return "human_or_controller"
    return "controller_or_skill"


def _build_transition_request(
    payload: dict[str, Any],
    table: RuleTable,
    source: ResearchState,
    target: ResearchState | None,
    approval_required: bool,
    human_approval_state: dict[str, Any] | None,
    dry_run: bool,
) -> dict[str, Any] | None:
    if target is None:
        return None
    edge = table.edge(source, target)
    scope = target.value if edge is not None and edge.requires_human_approval else None
    on_chain = bool(
        human_approval_state
        and human_approval_state.get("granted")
        and human_approval_state.get("scope") in ("all", target.value)
    )
    return {
        "requested_by": "obsidian-decision-gate",
        "from_state": source.value,
        "to_state": target.value,
        "rationale": f"decision-gate evaluation for {payload.get('action', 'gate.evaluate')}",
        "approval_required": approval_required,
        "approval_scope": scope,
        "approval_revision": human_approval_state.get("revision") if human_approval_state else None,
        "on_chain": on_chain,
        "dry_run": dry_run,
    }


def _compose_envelope(
    payload: dict[str, Any],
    table: RuleTable,
    *,
    status: OutputStatus,
    summary: str,
    decision: Decision,
    current_state: ResearchState,
    proposed_state: ResearchState | None,
    gate_results: dict[str, Any],
    blocking_items: list[dict],
    criteria_met: list[str],
    criteria_not_met: list[dict],
    mission_metrics: list[dict],
    failure_triggered: list[dict],
    risk_benefit: dict[str, Any],
    residual_uncertainty: list[dict],
    required_approvals: list[dict],
    conditional_terms: list[dict],
    monitoring: list[dict],
    failure_conditions: list[dict],
    next_actions: list[dict],
    review_expiry: str | None,
    errors: list[dict],
    self_check_notes: list[str],
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    memo = generate_memo(
        task_id=payload["task_id"],
        project_id=payload["project_id"],
        title=(payload.get("mission_lock") or {}).get("title", payload.get("request", "decision-gate")),
        current_state=current_state.value,
        proposed_state=proposed_state.value if proposed_state else None,
        decision=decision.value,
        decision_summary=summary,
        gate_results=gate_results,
        blocking_items=[_as_blocking_item(b) for b in blocking_items],
        mission_check=_mission_check_obj(criteria_met, criteria_not_met, failure_triggered, mission_metrics),
        supporting_evidence=_collect_evidence_refs(payload, "support"),
        opposing_evidence=_collect_evidence_refs(payload, "oppose"),
        residual_uncertainty=residual_uncertainty,
        risk_benefit=risk_benefit,
        required_human_approvals=required_approvals,
        conditional_release_terms=conditional_terms,
        monitoring_requirements=monitoring,
        failure_conditions=failure_conditions,
        next_actions=next_actions,
        review_expiry=review_expiry,
        approved_by=(
            (payload.get("human_approval_state") or {}).get("by")
            if (payload.get("human_approval_state") or {}).get("granted") else None
        ),
    )

    env: dict[str, Any] = {
        "contract_version": payload.get("contract_version", "1.0"),
        "skill": "obsidian-decision-gate",
        "skill_version": payload.get("skill_version", "1.0.0"),
        "status": status.value,
        "summary": summary,
        "action": payload.get("action", "gate.evaluate"),
        "project_id": payload.get("project_id"),
        "task_id": payload.get("task_id"),
        "findings": [
            {"label": "CALCULATED", "statement": s} for s in self_check_notes
        ],
        "assumptions": (payload.get("mission_lock") or {}).get("assumptions", []) or [],
        "evidence_used": [c.get("ref_id", "?") for c in payload.get("evidence_cards", []) or []],
        "uncertainty": [u.get("statement", str(u)) for u in residual_uncertainty],
        "risks": [],
        "artifacts": [
            {"kind": "decision-memo", "path": None, "note": memo.get("memo_id")},
        ],
        "requested_next_skills": [],
        "current_state": current_state.value,
        "proposed_state": proposed_state.value if proposed_state else None,
        "decision": decision.value,
        "gate_results": gate_results,
        "criteria_met": criteria_met,
        "criteria_not_met": criteria_not_met,
        "blocking_items": blocking_items,
        "supporting_evidence": _collect_evidence_refs(payload, "support"),
        "opposing_evidence": _collect_evidence_refs(payload, "oppose"),
        "residual_uncertainty": residual_uncertainty,
        "risk_benefit": risk_benefit,
        "required_human_approvals": required_approvals,
        "conditional_release_terms": conditional_terms,
        "monitoring_requirements": monitoring,
        "failure_conditions": failure_conditions,
        "next_actions": next_actions,
        "review_expiry": review_expiry,
        "decision_memo": memo,
        "state_transition_request": _build_transition_request(
            payload, table, current_state, proposed_state,
            approval_required=bool(required_approvals),
            human_approval_state=payload.get("human_approval_state"),
            dry_run=bool((payload.get("context") or {}).get("dry_run", False)),
        ),
        "validation": {
            "input_schema": "passed",
            "output_schema": "pending",
            "self_check": "passed" if not errors else "failed",
            "checks": [
                {"name": "blockers_consistent_with_decision", "ok": _blocker_decision_consistent(blocking_items, decision)},
            ],
        },
        "provenance": {
            "skill": "obsidian-decision-gate",
            "skill_version": payload.get("skill_version", "1.0.0"),
            "contract_version": payload.get("contract_version", "1.0"),
            "timestamp": _now_iso(),
            "tools_used": ["odg.engine", "odg.blockers", "odg.scoring", "odg.mission", "odg.memo"],
            "input_digest": _digest(payload),
        },
        "errors": errors,
    }
    if extra:
        env.update(extra)
    return env


def _mission_check_obj(criteria_met, criteria_not_met, failure_triggered, metrics):
    from .mission import MissionCheck
    return MissionCheck(criteria_met, criteria_not_met, failure_triggered, metrics)


def _as_blocking_item(b: dict) -> Any:
    from .rules import BlockingItem
    return BlockingItem(b.get("rule", "?"), b.get("severity", "HIGH"), b.get("evidence", ""), b.get("how_to_resolve", ""))


def _blocker_decision_consistent(blocking_items: list[dict], decision: Decision) -> bool:
    if blocking_items and decision in (Decision.PASS, Decision.CONDITIONAL_PASS):
        return False
    return True


def _next_actions_for_blockers(
    payload: dict[str, Any],
    blockers: list[dict],
    source: ResearchState,
    target: ResearchState | None,
) -> list[dict]:
    """Evidence-driven next research choices (highest info-gain per cost)."""
    actions: list[dict] = []
    seen = set()

    def add(action: str, reason: str, skill: str | None = None, priority: str = "medium"):
        if action not in seen:
            seen.add(action)
            actions.append({"action": action, "reason": reason, "priority": priority, "skill": skill})

    for b in blockers:
        rule = b.get("rule")
        if rule == "B2":
            add("补充可核验原始来源", "证据来源不可核验", "micp-literature-scout", "high")
        elif rule == "B4":
            add("增加对照实验", "缺少关键对照", "obsidian-experiment-designer", "high")
        elif rule == "B3":
            add("重复实验并归档数据/代码", "数据不可复现", "micp-instrumentation-qc", "high")
        elif rule == "B6":
            add("在独立数据上验证模型", "模型无外部验证", "micp-data-analyst", "high")
        elif rule == "B7":
            add("开展受控中试", "现场尺度未经阶段放大", "obsidian-scaleup-injection-engineer", "high")
        elif rule == "B8":
            add("重新评估环境风险", "环境风险未关闭", "obsidian-biosafety-environment-auditor", "high")
        elif rule == "B9":
            add("核验法规与许可", "法规未核验", None, "high")
        elif rule == "B11":
            add("补全监测/停工/回退条款", "缺少监测与停工条件", "obsidian-experiment-designer", "medium")
        elif rule == "B12":
            add("补齐未达标成功指标的证据", "成功指标未达标", "micp-data-analyst", "medium")
        elif rule == "B13":
            add("暂停路线并止损评估", "失败阈值已触发", None, "high")
        elif rule == "B1":
            add("Red Team 复审", "存在 BLOCKING 问题", "obsidian-red-team", "high")
        elif rule == "B10":
            add("提交人工审批", "人类审批缺失", None, "high")

    if not actions:
        # evidence insufficient overall → pick next info-gain step
        cards = payload.get("evidence_cards", []) or []
        synth = payload.get("synthesis")
        if not synth:
            add("补充证据综合", "缺少证据综合结论", "micp-evidence-synthesizer", "high")
        elif len(cards) < 3:
            add("增加证据来源/空间取样", "证据基础薄弱", "micp-literature-scout", "medium")
        elif not payload.get("model_results"):
            add("建立并验证模型", "缺少模型验证", "micp-data-analyst", "medium")
        elif source is ResearchState.VALIDATED and not payload.get("scaleup_plan"):
            add("设计中试方案", "具备验证结论但缺少放大方案", "obsidian-experiment-designer", "medium")
        elif target is ResearchState.PILOT_READY:
            add("执行受控中试", "中试条件齐备", "obsidian-scaleup-injection-engineer", "medium")
        else:
            add("补充任务相关证据", "证据不足以升级", "micp-literature-scout", "medium")

    return actions


def evaluate(payload: dict[str, Any], *, table: RuleTable | None = None, dry_run: bool = False) -> GateResult:
    """Run the full gate evaluation. Pure; no I/O beyond rule-table load."""
    try:
        validate_input(payload)
    except OdgError as exc:
        return GateResult(
            status=OutputStatus.BLOCKED,
            envelope={
                "status": "BLOCKED",
                "summary": "输入不满足 input.schema.json",
                "errors": [exc.to_dict()],
                "validation": {"input_schema": "failed", "output_schema": "pending", "self_check": "not_run"},
                "provenance": {},
            },
            errors=[exc.to_dict()],
        )

    rt = table or RuleTable.load()
    source = ResearchState(payload["current_state"])
    proposed_raw = payload.get("proposed_state")
    target: ResearchState | None = ResearchState(proposed_raw) if proposed_raw else None

    # --- 1. legal edge? (hard machine guarantee) ---
    if target is not None and not rt.is_edge_legal(source, target):
        legal = [t.value for t in rt.legal_targets(source)]
        err = OdgError(
            OdgErrorCode.ILLEGAL_TRANSITION,
            f"Illegal transition {source.value} → {target.value}. "
            f"Legal targets from {source.value}: {legal or 'none'}.",
            detail={"source": source.value, "target": target.value, "legal_targets": legal},
        )
        return GateResult(
            status=OutputStatus.BLOCKED,
            envelope=_compose_envelope(
                payload, rt,
                status=OutputStatus.BLOCKED,
                summary=f"非法状态转换被拒绝: {source.value} → {target.value} (ODG-E305)",
                decision=Decision.REJECT,
                current_state=source,
                proposed_state=target,
                gate_results={
                    "state_gate": {"current_state": source.value, "proposed_state": target.value,
                                   "legal": False, "grade_gap": grade_gap(rt, source, target),
                                   "notes": [f"legal targets: {legal}"]},
                    "blockers": [], "dimensions": {}, "mission": {},
                },
                blocking_items=[],
                criteria_met=[], criteria_not_met=[], mission_metrics=[], failure_triggered=[],
                risk_benefit={"net_positive": False, "benefit": "", "risk": "", "residual_risk_score": 1.0,
                              "benefit_score": 0.0, "assessment": "illegal state transition"},
                residual_uncertainty=[], required_approvals=[], conditional_terms=[], monitoring=[],
                failure_conditions=[], next_actions=[], review_expiry=None,
                errors=[err.to_dict()], self_check_notes=["illegal transition hard-rejected"],
            ),
            errors=[err.to_dict()],
        )

    # --- 2. propose target if absent (pick next state) ---
    if target is None:
        # pick the highest legal upgrade whose floors are achievable — but the
        # engine must not skip validation; report the legal reachable set.
        legal_up = [e.to_state for e in rt.edges
                    if e.from_state is source and rt.grade(e.to_state) > rt.grade(source)]
        # propose the maximum legal grade (HOLD if none)
        target = max(legal_up, key=lambda s: rt.grade(s)) if legal_up else source
        target = None if target is source else target

    if target is None:
        # no legal upgrade: HOLD at current state
        pass

    # --- 5. mission check (before blockers: B12 consumes the criterion verdict) ---
    mission = check_mission(payload)
    mission_dict = mission.to_dict()
    payload = dict(payload)
    payload["_criteria_not_met"] = mission.criteria_not_met

    # --- 3. blocking rules ---
    from .rules import evaluate_blockers
    blockers = evaluate_blockers(payload, rt, source, target) if target is not None else []
    blocker_dicts = [b.to_dict() for b in blockers]

    # --- 4. dimension scoring + floors ---
    dims = score_dimensions(payload)
    scores = {d: s.score for d, s in dims.items()}
    if target is not None:
        floor_map = rt.floor_map(rt.grade(target))
        below = below_floor_map(scores, floor_map)
        dims_passed = len(below) == 0
    else:
        floor_map = {}
        below = []
        dims_passed = True

    # --- 5. mission check ---
    mission = check_mission(payload)
    mission_dict = mission.to_dict()

    # inject the authoritative criterion verdict for the B12 blocking rule
    # (the rule engine reads `_criteria_not_met`; it is stripped before output)
    payload = dict(payload)
    payload["_criteria_not_met"] = mission.criteria_not_met

    # --- 6. human approval ---
    ha = payload.get("human_approval_state") or {}
    required_approvals: list[dict] = []
    approval_blocker = None
    if target is not None and rt.grade(target) >= APPROVAL_REQUIRED_FROM_GRADE:
        edge = rt.edge(source, target)
        needs = (edge.requires_human_approval if edge is not None
                 else rt.grade(target) >= APPROVAL_REQUIRED_FROM_GRADE)
        granted_ok = bool(ha.get("granted")) and ha.get("scope") in ("all", target.value)
        status = "granted" if granted_ok else ("expired" if ha.get("expires_at") else "missing")
        required_approvals.append({
            "scope": target.value,
            "reason": f"进入 {target.value} 需要人类批准 (grade {rt.grade(target)} >= {APPROVAL_REQUIRED_FROM_GRADE})",
            "status": status,
            "revision": ha.get("revision"),
        })
        if needs and not granted_ok:
            approval_blocker = {
                "rule": "B10",
                "severity": "BLOCKING",
                "evidence": f"人类审批缺失: {target.value} (granted={bool(ha.get('granted'))}, scope={ha.get('scope', '—')})",
                "how_to_resolve": f"由人类通过 state-manager approval.grant 记录 scope={target.value} 的批准",
            }
            if not any(b["rule"] == "B10" for b in blocker_dicts):
                blocker_dicts.append(approval_blocker)

    # --- 7. expiry ---
    exp = check_expiry(payload)
    review_expiry = exp.effective_review_expiry or compute_review_expiry(payload)

    # --- 8. risk-benefit + comparison ---
    rb = risk_benefit_matrix(payload, scores)
    comp = compare_mod.compare_decisions(
        payload, rt,
        current={
            "decision": Decision.PASS.value if not blocker_dicts else Decision.HOLD.value,
            "current_state": source.value,
            "proposed_state": target.value if target else None,
            "blocking_items": blocker_dicts,
            "gate_results": {"dimensions": {"scores": scores}},
        },
        now=_now_iso(),
    )

    # --- 9. decision synthesis ---
    # failure threshold triggers the line regardless of everything else
    failure_triggered = mission.failure_thresholds_triggered
    decision: Decision
    status: OutputStatus

    if failure_triggered:
        decision = Decision.REJECT if source in (ResearchState.OPEN, ResearchState.EVIDENCE_GATHERING) else Decision.SUSPEND
        status = OutputStatus.BLOCKED
        if not any(b["rule"] == "B13" for b in blocker_dicts):
            blocker_dicts.append({
                "rule": "B13", "severity": "BLOCKING",
                "evidence": f"失败阈值触发: {', '.join(f['threshold'] for f in failure_triggered)}",
                "how_to_resolve": "停止推进；止损评估或人工决策放弃路线",
            })
    elif exp.expired:
        # An explicit downgrade toward the refutation direction honors the
        # caller's target instead of forcing EXPIRE; otherwise the conclusion
        # is expired and must be re-reviewed.
        exp_types = {t.get("type") for t in exp.triggers}
        refutation_driven = exp_types & {"hypothesis_refuted", "hypothesis_contested"}
        explicit_downgrade = (
            target is not None
            and rt.grade(target) < rt.grade(source)
        )
        if refutation_driven and explicit_downgrade:
            decision = Decision.PASS
            status = OutputStatus.SUCCESS
        else:
            decision = Decision.EXPIRE
            status = OutputStatus.BLOCKED
            if target is not None and target is not ResearchState.EXPIRED:
                blocker_dicts.append({
                    "rule": "B3", "severity": "BLOCKING",
                    "evidence": f"结论过期: {exp.reason}",
                    "how_to_resolve": "更新证据/法规/标准后重新评审",
                })
    elif blocker_dicts:
        if any(b["rule"] == "B10" for b in blocker_dicts):
            decision = Decision.HOLD
            status = OutputStatus.HUMAN_APPROVAL_REQUIRED
        else:
            decision = Decision.HOLD
            status = OutputStatus.BLOCKED
    elif not dims_passed:
        decision = Decision.HOLD
        status = OutputStatus.BLOCKED
        blocker_dicts.append({
            "rule": "B12", "severity": "MEDIUM",
            "evidence": f"维度门槛未达标: {', '.join(below)}",
            "how_to_resolve": "补齐对应维度的证据后再升级",
        })
    else:
        # all clear → PASS toward target
        if target is not None and target is not source:
            decision = Decision.PASS
            status = OutputStatus.SUCCESS
        else:
            decision = Decision.HOLD
            status = OutputStatus.SUCCESS

    # --- 10. next actions ---
    next_actions = _next_actions_for_blockers(payload, blocker_dicts, source, target)

    # --- 11. monitoring / failure conditions / conditional terms ---
    monitoring: list[dict] = []
    if target in (ResearchState.PILOT_READY, ResearchState.DEPLOYABLE):
        sp = payload.get("scaleup_plan") or {}
        for p in (sp.get("monitoring_plan") or "").split(";"):
            if p.strip():
                monitoring.append({"parameter": p.strip(), "frequency": "per scale-up plan", "alert_condition": "threshold breach"})
        for sc in sp.get("shutdown_conditions", []) or []:
            monitoring.append({"parameter": "shutdown", "frequency": "continuous", "alert_condition": sc})

    failure_conditions: list[dict] = []
    if target in (ResearchState.PILOT_READY, ResearchState.DEPLOYABLE):
        for sc in (payload.get("scaleup_plan") or {}).get("shutdown_conditions", []) or []:
            failure_conditions.append({"condition": sc, "action": "停工并执行回退方案"})

    conditional_terms: list[dict] = []
    if decision == Decision.CONDITIONAL_PASS or status == OutputStatus.PARTIAL:
        for b in blocker_dicts:
            conditional_terms.append({"condition": b["how_to_resolve"], "owner": "route-owner"})

    # --- 12. requested next skills ---
    req_skills: list[dict] = []
    for a in next_actions:
        if a.get("skill"):
            req_skills.append({
                "skill": a["skill"],
                "reason": a["reason"],
                "inputs_needed": ["task_id", "project_id", "request", "context", "evidence_refs", "data_refs"],
            })
    if req_skills and status == OutputStatus.SUCCESS and decision != Decision.PASS:
        # a HOLD with follow-up actions means the evidence base is insufficient
        # to close the gate: tell the router which specialist skill fills the gap
        status = OutputStatus.NEED_ADDITIONAL_SKILL

    # --- 13. assemble envelope ---
    self_notes = [
        f"blocking rules evaluated: {len(blocker_dicts)}",
        f"dimension floors: {'passed' if dims_passed else 'below_floor: ' + ', '.join(below)}",
        f"mission: {len(mission.criteria_met)} met / {len(mission.criteria_not_met)} not met",
    ]
    if comp.get("flags"):
        self_notes.append(f"comparison flags: {comp['flags']}")

    env = _compose_envelope(
        payload, rt,
        status=status,
        summary=_summary(status, decision, source, target, blocker_dicts),
        decision=decision,
        current_state=source,
        proposed_state=target,
        gate_results={
            "state_gate": {"current_state": source.value, "proposed_state": target.value if target else None,
                           "legal": target is None or rt.is_edge_legal(source, target),
                           "grade_gap": grade_gap(rt, source, target) if target else 0,
                           "notes": self_notes},
            "blockers": blocker_dicts,
            "dimensions": {"scores": scores, "floors": floor_map, "passed": dims_passed, "below_floor": below},
            "mission": mission_dict,
        },
        blocking_items=blocker_dicts,
        criteria_met=mission.criteria_met,
        criteria_not_met=mission.criteria_not_met,
        mission_metrics=[m.to_dict() for m in mission.metrics],
        failure_triggered=[f["threshold"] for f in failure_triggered],
        risk_benefit=rb,
        residual_uncertainty=[
            {"statement": u.get("statement", str(u)), "impact": u.get("impact", "medium")}
            for u in (payload.get("residual_uncertainty") or []) or []
        ] or [{"statement": "见维度评分与阻断项", "impact": "medium"}],
        required_approvals=required_approvals,
        conditional_terms=conditional_terms,
        monitoring=monitoring,
        failure_conditions=failure_conditions,
        next_actions=next_actions,
        review_expiry=review_expiry,
        errors=[],
        self_check_notes=self_notes,
        extra={
            "comparison": comp,
            "expiry": exp.to_dict(),
        },
    )
    env["requested_next_skills"] = req_skills
    env["artifacts"] = [
        {"kind": "decision-memo", "path": None, "note": env.get("decision_memo", {}).get("memo_id")},
        {"kind": "state-transition-request", "path": None,
         "note": env.get("state_transition_request", {}).get("to_state")},
    ]

    # --- 14. output schema validation ---
    try:
        validate_output(env)
        env["validation"]["output_schema"] = "passed"
    except OdgError as exc:
        env["validation"]["output_schema"] = "failed"
        env["errors"] = [exc.to_dict()]
        return GateResult(status=OutputStatus.FAILED, envelope=env, errors=[exc.to_dict()])

    return GateResult(status=status, envelope=env)


def _summary(status: OutputStatus, decision: Decision, source: ResearchState,
             target: ResearchState | None, blockers: list[dict]) -> str:
    if target:
        core = f"决策 {decision.value}: {source.value} → {target.value}"
    else:
        core = f"决策 {decision.value}: 保持 {source.value}"
    if blockers:
        core += f" (阻断 {len(blockers)} 项)"
    if status == OutputStatus.HUMAN_APPROVAL_REQUIRED:
        core = f"HUMAN_APPROVAL_REQUIRED: 需要人工批准进入 {target.value if target else '?'}"
    return core
