"""Gate rule engine: state-transition whitelist + blocking-rule evaluation.

The whitelist and per-grade dimension floors are DATA in schemas/gate-rules.json
(validated against gate-rule.schema.json). This module loads that table and
answers three questions the gate needs:

  1. is_edge_legal(from, to)           — whitelist membership (ODG-E305 on miss)
  2. edge_rule(from, to)               — the matching edge meta
  3. blockers(...)                     — evaluate the 13 blocking rules against
                                         the assembled evidence context

Blocking-rule evaluation is pure and deterministic: given the same evidence
context it returns the same blockers. It never needs the model's opinion.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .errors import OdgError, OdgErrorCode
from .models import (
    ALL_DIMENSIONS,
    BlockingRule,
    BlockingWhen,
    ResearchState,
    STATE_GRADES,
)

_SCHEMA_DIR = Path(__file__).resolve().parent.parent.parent / "schemas"
DEFAULT_RULE_TABLE = _SCHEMA_DIR / "gate-rules.json"


@dataclass(frozen=True)
class Edge:
    from_state: ResearchState
    to_state: ResearchState
    grade: int
    min_dimension: float
    requires_human_approval: bool
    irreversible: bool
    note: str


@dataclass
class BlockingItem:
    rule: str
    severity: str
    evidence: str
    how_to_resolve: str

    def to_dict(self) -> dict:
        return {
            "rule": self.rule,
            "severity": self.severity,
            "evidence": self.evidence,
            "how_to_resolve": self.how_to_resolve,
        }


def _as_state(v: str) -> ResearchState:
    try:
        return ResearchState(v)
    except ValueError:
        raise OdgError(
            OdgErrorCode.INVALID_STATE_NAME,
            f"Unknown state '{v}'.",
            detail={"state": v, "valid": [s.value for s in ResearchState]},
        ) from None


class RuleTable:
    """Loaded, validated transition whitelist + floors."""

    def __init__(self, data: dict[str, Any]):
        self.version: str = str(data.get("version", "1.0.0"))
        self.states: list[ResearchState] = [_as_state(s) for s in data.get("states", [])]
        grades_raw = data.get("state_grades", {})
        self.grades: dict[ResearchState, int] = {
            _as_state(k): int(v) for k, v in grades_raw.items()
        }
        self.dimensions: list[str] = list(data.get("dimensions", []))
        floors_raw = data.get("dimension_floors", {})
        self.floors: dict[int, dict[str, float]] = {
            int(grade): {dim: float(v) for dim, v in floor.items()}
            for grade, floor in floors_raw.items()
        }
        self.blocking_rules: dict[str, dict[str, Any]] = {
            b["rule"]: b for b in data.get("blocking_rules", [])
        }
        self.edges: list[Edge] = []
        for e in data.get("edges", []):
            self.edges.append(
                Edge(
                    from_state=_as_state(e["from"]),
                    to_state=_as_state(e["to"]),
                    grade=int(e.get("grade", STATE_GRADES[_as_state(e["to"])])),
                    min_dimension=float(e.get("min_dimension", 0.0)),
                    requires_human_approval=bool(e.get("requires_human_approval", False)),
                    irreversible=bool(e.get("irreversible", False)),
                    note=str(e.get("note", "")),
                )
            )
        self._index: dict[tuple[ResearchState, ResearchState], Edge] = {}
        for e in self.edges:
            if (e.from_state, e.to_state) in self._index:
                raise OdgError(
                    OdgErrorCode.RULE_TABLE_UNAVAILABLE,
                    f"Duplicate edge {e.from_state.value}->{e.to_state.value} in gate-rules.json",
                )
            self._index[(e.from_state, e.to_state)] = e

    @classmethod
    def load(cls, path: Path | None = None) -> "RuleTable":
        target = path or DEFAULT_RULE_TABLE
        try:
            data = json.loads(target.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise OdgError(
                OdgErrorCode.RULE_TABLE_UNAVAILABLE,
                f"gate-rules.json unreadable: {exc}",
                detail={"path": str(target)},
            ) from exc
        return cls(data)

    def is_edge_legal(self, source: ResearchState, target: ResearchState) -> bool:
        return (source, target) in self._index

    def edge(self, source: ResearchState, target: ResearchState) -> Edge | None:
        return self._index.get((source, target))

    def legal_targets(self, source: ResearchState) -> list[ResearchState]:
        return sorted(
            (e.to_state for e in self.edges if e.from_state is source),
            key=lambda s: s.value,
        )

    def grade(self, state: ResearchState) -> int:
        return self.grades.get(state, STATE_GRADES[state])

    def floor_for(self, grade: int, dimension: str) -> float:
        return self.floors.get(grade, {}).get(dimension, 0.0)

    def floor_map(self, grade: int) -> dict[str, float]:
        return dict(self.floors.get(grade, {}))


def grade_gap(table: RuleTable, source: ResearchState, target: ResearchState) -> int:
    """Maturity distance between two states (non-negative)."""
    return max(0, table.grade(target) - table.grade(source))


# ---------------------------------------------------------------------------
# Blocking-rule evaluation
# ---------------------------------------------------------------------------

def _blk(rule: BlockingRule, severity: str, evidence: str, how: str) -> BlockingItem:
    return BlockingItem(rule.value, severity, evidence, how)


def evaluate_blockers(
    payload: dict[str, Any],
    table: RuleTable,
    source: ResearchState,
    target: ResearchState,
) -> list[BlockingItem]:
    """Evaluate the 13 blocking rules against the input envelope.

    `when` semantics (from gate-rule.schema):
      any_upgrade               — applies to any edge with grade(target) > grade(source)
      upgrade_to_validated_plus — applies when grade(target) >= 4
      upgrade_to_pilot_plus     — applies when grade(target) >= 5
      upgrade_to_deployable     — applies when grade(target) == 6
      always                    — applies to every evaluated edge
    """
    blockers: list[BlockingItem] = []
    target_grade = table.grade(target)
    is_upgrade = target_grade > table.grade(source)

    def when_active(when: str) -> bool:
        if when == BlockingWhen.ALWAYS.value:
            return True
        if when == BlockingWhen.ANY_UPGRADE.value:
            return is_upgrade
        if when == BlockingWhen.UPGRADE_TO_VALIDATED_PLUS.value:
            return is_upgrade and target_grade >= 4
        if when == BlockingWhen.UPGRADE_TO_PILOT_PLUS.value:
            return is_upgrade and target_grade >= 5
        if when == BlockingWhen.UPGRADE_TO_DEPLOYABLE.value:
            return is_upgrade and target_grade == 6
        return True

    rules = table.blocking_rules

    def active(rule: str) -> bool:
        r = rules.get(rule)
        return r is not None and when_active(r.get("when", BlockingWhen.ANY_UPGRADE.value))

    # B1 — Red Team BLOCKING
    if active("B1"):
        rt = payload.get("red_team_report") or {}
        if rt.get("status") == "failed" or any(
            f.get("severity") == "BLOCKING" and f.get("resolution") not in ("resolved", "accepted_risk")
            for f in rt.get("findings", [])
        ):
            unresolved = [
                f for f in rt.get("findings", [])
                if f.get("severity") == "BLOCKING" and f.get("resolution") not in ("resolved", "accepted_risk")
            ]
            blockers.append(_blk(
                BlockingRule.B1_RED_TEAM_BLOCKING, "BLOCKING",
                f"Red Team 报告存在 {len(unresolved)} 个未解除 BLOCKING 问题: "
                + ", ".join(f.get("id", "?") for f in unresolved),
                "解决全部 BLOCKING 问题并让 Red Team 复审通过后再申请升级。",
            ))

    # B2 — Evidence unverifiable
    if active("B2"):
        cards = payload.get("evidence_cards", []) or []
        bad = [c for c in cards if not c.get("verifiable")]
        if bad:
            blockers.append(_blk(
                BlockingRule.B2_EVIDENCE_UNVERIFIABLE, "BLOCKING",
                f"{len(bad)} 条证据来源不可核验: {', '.join(c.get('ref_id', '?') for c in bad)}",
                "补齐可解析的来源（DOI/路径/全文）并重新提取证据卡。",
            ))

    # B3 — Irreproducible
    if active("B3"):
        rep = payload.get("reproducibility") or {}
        if rep and rep.get("reproducible") is False:
            blockers.append(_blk(
                BlockingRule.B3_IRREPRODUCIBLE, "BLOCKING",
                "reproducibility.reproducible=false",
                "归档数据与代码、提供版本号、以相同参数重复运行验证可复现。",
            ))

    # B4 — Missing control
    if active("B4"):
        exps = payload.get("experiment_results", []) or []
        relevant = [e for e in exps if e.get("status") == "completed"]
        if any(e.get("has_control") is False for e in relevant):
            no_control = [e.get("id", "?") for e in relevant if e.get("has_control") is False]
            blockers.append(_blk(
                BlockingRule.B4_MISSING_CONTROL, "BLOCKING",
                f"实验缺少关键对照: {', '.join(no_control)}",
                "补充对照组（如未处理/安慰剂/基准材料）后重测。",
            ))

    # B5 — Mass balance failure
    if active("B5"):
        exps = payload.get("experiment_results", []) or []
        for e in exps:
            mb = e.get("mass_balance") or {}
            if mb.get("closed") is False or (
                mb.get("closure_error_percent") is not None
                and mb.get("tolerance_percent") is not None
                and mb["closure_error_percent"] > mb["tolerance_percent"]
            ):
                blockers.append(_blk(
                    BlockingRule.B5_MASS_BALANCE_FAILURE, "BLOCKING",
                    f"实验 {e.get('id', '?')} 质量守恒闭合失败: "
                    f"closure_error={mb.get('closure_error_percent')}% tolerance={mb.get('tolerance_percent')}%",
                    "核查物质流向、补齐未测组分或修正计量后再闭合质量平衡。",
                ))

    # B6 — Model without independent validation
    if active("B6"):
        model = payload.get("model_results")
        if model is not None and model.get("fitted") is True and not model.get("external_validation"):
            blockers.append(_blk(
                BlockingRule.B6_MODEL_NO_EXTERNAL_VALIDATION, "BLOCKING",
                f"模型 {model.get('name', '?')} 已拟合但无独立/留出验证",
                "在独立数据集或 hold-out 折上验证模型，报告验证指标。",
            ))

    # B7 — Scale ladder gap
    if active("B7"):
        ladder = _observed_scale_ladder(payload)
        reached_high = any(s in ("pilot", "field") for s in ladder)
        if not reached_high:
            blockers.append(_blk(
                BlockingRule.B7_NO_STAGED_SCALEUP, "BLOCKING",
                f"现场/中试尺度证据缺失（观测尺度: {', '.join(ladder) or '无'}）",
                "在受控中试/现场尺度完成阶段放大，记录尺度链 lab→bench→pilot→field。",
            ))

    # B8 — Environmental risk open
    if active("B8"):
        env = payload.get("environment_audit") or {}
        if env.get("status") in ("open", "expired") or any(
            f.get("severity") == "high" and f.get("status") not in ("closed", "waived")
            for f in env.get("findings", [])
        ):
            open_high = [f.get("id", "?") for f in env.get("findings", [])
                         if f.get("severity") == "high" and f.get("status") not in ("closed", "waived")]
            blockers.append(_blk(
                BlockingRule.B8_ENV_RISK_OPEN, "BLOCKING",
                f"环境审计未关闭: status={env.get('status')} 未关闭 high 项: {', '.join(open_high) or '—'}",
                "关闭全部 high 风险项（缓解/弃权记录）并复审环境审计。",
            ))

    # B9 — Regulatory unverified
    if active("B9"):
        reg = payload.get("regulatory_status") or {}
        if reg:
            if not reg.get("verified") or not reg.get("current"):
                blockers.append(_blk(
                    BlockingRule.B9_REGULATORY_UNVERIFIED, "BLOCKING",
                    f"法规状态未核验/已过期: verified={reg.get('verified')} current={reg.get('current')}",
                    "按当前管辖区域核验法规与许可状态并更新 regulatory_status。",
                ))

    # B10 — Human approval missing
    if active("B10"):
        edge = table.edge(source, target)
        if edge is not None and edge.requires_human_approval:
            ha = payload.get("human_approval_state") or {}
            ok = bool(ha.get("granted")) and ha.get("scope") in ("all", target.value)
            if not ok:
                blockers.append(_blk(
                    BlockingRule.B10_HUMAN_APPROVAL_MISSING, "BLOCKING",
                    f"{source.value}→{target.value} 需要人工批准，当前 granted={bool(ha.get('granted'))} "
                    f"scope={ha.get('scope', '—')}",
                    f"由人类通过 state-manager approval.grant 记录 scope={target.value} 的批准后再重试。",
                ))

    # B11 — No monitoring/shutdown conditions
    if active("B11"):
        sp = payload.get("scaleup_plan") or {}
        if not sp.get("monitoring_plan") or not sp.get("shutdown_conditions") or not sp.get("rollback_plan"):
            missing = [
                name for name, ok in (
                    ("monitoring_plan", bool(sp.get("monitoring_plan"))),
                    ("shutdown_conditions", bool(sp.get("shutdown_conditions"))),
                    ("rollback_plan", bool(sp.get("rollback_plan"))),
                ) if not ok
            ]
            blockers.append(_blk(
                BlockingRule.B11_NO_MONITORING_SHUTDOWN, "BLOCKING",
                f"中试/部署缺少: {', '.join(missing)}",
                "补全监测计划、停工条件与回退方案后重新提交。",
            ))

    # B12 — Success criteria not met
    # NOTE: the authoritative evaluation lives in the service, which runs the
    # mission check and injects the criterion-level verdict into the payload as
    # `_criteria_not_met`. This rule simply reflects that verdict; it never
    # attempts to re-derive it from raw strings (which would be ambiguous).
    if active("B12"):
        unmet = payload.get("_criteria_not_met") or []
        if unmet:
            blockers.append(_blk(
                BlockingRule.B12_SUCCESS_NOT_MET, "BLOCKING",
                f"成功指标未达标: {len(unmet)} 项 — " + "; ".join(u.get("why", "") for u in unmet[:3]),
                "补齐未达标指标的证据或调整任务目标（需人工决策）。",
            ))

    # B13 — Failure threshold triggered
    if active("B13"):
        ft = payload.get("failure_thresholds_triggered") or []
        if ft:
            blockers.append(_blk(
                BlockingRule.B13_FAILURE_TRIGGERED, "BLOCKING",
                f"失败阈值已触发: {', '.join(ft)}",
                "停止推进；评估止损、暂停或转向，必要时人工决策放弃路线。",
            ))

    return blockers


def _observed_scale_ladder(payload: dict[str, Any]) -> list[str]:
    """Infer the observed scale ladder from evidence cards + experiments + scaleup plan."""
    scales: list[str] = []
    for c in payload.get("evidence_cards", []) or []:
        s = c.get("scale")
        if s:
            scales.append(s)
    for e in payload.get("experiment_results", []) or []:
        s = e.get("scale")
        if s:
            scales.append(s)
    for st in (payload.get("scaleup_plan") or {}).get("stages", []) or []:
        s = st.get("scale")
        if s:
            scales.append(s)
    return list(dict.fromkeys(scales))


def has_field_or_pilot(payload: dict[str, Any]) -> bool:
    ladder = _observed_scale_ladder(payload)
    return any(s in ("field", "pilot") for s in ladder)
