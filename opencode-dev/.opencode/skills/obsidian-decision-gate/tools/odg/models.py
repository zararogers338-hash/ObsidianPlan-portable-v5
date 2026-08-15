"""obsidian-decision-gate domain models: states, dimensions, blocking rules.

All enums serialize as plain strings for schema-validatable JSON envelopes.
The state-transition whitelist and per-grade dimension floors live in
schemas/gate-rules.json (data, not code) so rules can be audited and versioned
without touching engine code. This module mirrors that data as typed constants
used by the engine and by tests.
"""

from __future__ import annotations

import enum


class ResearchState(str, enum.Enum):
    """Obsidian Plan decision-gate states (spec §三)."""

    REJECTED = "REJECTED"
    OPEN = "OPEN"
    EVIDENCE_GATHERING = "EVIDENCE_GATHERING"
    SUPPORTED = "SUPPORTED"
    VALIDATED = "VALIDATED"
    PILOT_READY = "PILOT_READY"
    DEPLOYABLE = "DEPLOYABLE"
    SUSPENDED = "SUSPENDED"
    EXPIRED = "EXPIRED"


ALL_STATES: tuple[ResearchState, ...] = tuple(ResearchState)

# Terminal states: DEPLOYABLE is terminal & irreversible; REJECTED is
# terminal-ish (reopen requires human approval, which is itself a decision).
TERMINAL_STATES: frozenset[ResearchState] = frozenset(
    {ResearchState.REJECTED, ResearchState.DEPLOYABLE}
)

# Maturity grade per state; used for illegal-jump detection (grade gap).
STATE_GRADES: dict[ResearchState, int] = {
    ResearchState.REJECTED: 0,
    ResearchState.OPEN: 1,
    ResearchState.EVIDENCE_GATHERING: 2,
    ResearchState.SUPPORTED: 3,
    ResearchState.VALIDATED: 4,
    ResearchState.PILOT_READY: 5,
    ResearchState.DEPLOYABLE: 6,
    ResearchState.SUSPENDED: 2,
    ResearchState.EXPIRED: 1,
}


class DecisionDimension(str, enum.Enum):
    """The 12 decision dimensions (spec §四)."""

    SCIENTIFIC_VALIDITY = "SCIENTIFIC_VALIDITY"
    EVIDENCE_QUALITY = "EVIDENCE_QUALITY"
    REPRODUCIBILITY = "REPRODUCIBILITY"
    ENGINEERING_FEASIBILITY = "ENGINEERING_FEASIBILITY"
    SCALE_READINESS = "SCALE_READINESS"
    ENVIRONMENTAL_ACCEPTABILITY = "ENVIRONMENTAL_ACCEPTABILITY"
    BIOSAFETY = "BIOSAFETY"
    REGULATORY_STATUS = "REGULATORY_STATUS"
    ECONOMIC_VIABILITY = "ECONOMIC_VIABILITY"
    MONITORABILITY = "MONITORABILITY"
    REVERSIBILITY = "REVERSIBILITY"
    RESIDUAL_RISK = "RESIDUAL_RISK"  # inverse: 1 = negligible residual risk


ALL_DIMENSIONS: tuple[DecisionDimension, ...] = tuple(DecisionDimension)


class BlockingRule(str, enum.Enum):
    """The 13 machine-enforced blocking rules (spec §五)."""

    B1_RED_TEAM_BLOCKING = "B1"
    B2_EVIDENCE_UNVERIFIABLE = "B2"
    B3_IRREPRODUCIBLE = "B3"
    B4_MISSING_CONTROL = "B4"
    B5_MASS_BALANCE_FAILURE = "B5"
    B6_MODEL_NO_EXTERNAL_VALIDATION = "B6"
    B7_NO_STAGED_SCALEUP = "B7"
    B8_ENV_RISK_OPEN = "B8"
    B9_REGULATORY_UNVERIFIED = "B9"
    B10_HUMAN_APPROVAL_MISSING = "B10"
    B11_NO_MONITORING_SHUTDOWN = "B11"
    B12_SUCCESS_NOT_MET = "B12"
    B13_FAILURE_TRIGGERED = "B13"


BLOCKING_RULE_DESCRIPTIONS: dict[BlockingRule, str] = {
    BlockingRule.B1_RED_TEAM_BLOCKING: "Red Team 存在 BLOCKING 级别问题",
    BlockingRule.B2_EVIDENCE_UNVERIFIABLE: "证据来源不可核验（ref 无法解析/校验）",
    BlockingRule.B3_IRREPRODUCIBLE: "数据不可复现（reproducibility 未达标）",
    BlockingRule.B4_MISSING_CONTROL: "缺少关键对照（experiment 无对照/对照组缺失）",
    BlockingRule.B5_MASS_BALANCE_FAILURE: "质量守恒失败（mass balance 闭合失败）",
    BlockingRule.B6_MODEL_NO_EXTERNAL_VALIDATION: "模型无独立验证（model 无 external_validation）",
    BlockingRule.B7_NO_STAGED_SCALEUP: "现场尺度未经阶段放大（scale ladder 断档）",
    BlockingRule.B8_ENV_RISK_OPEN: "环境风险未关闭（环境审计存在未关闭 high 风险）",
    BlockingRule.B9_REGULATORY_UNVERIFIED: "法规未核验（法规状态非 verified/current）",
    BlockingRule.B10_HUMAN_APPROVAL_MISSING: "人类审批缺失（目标要求人工批准但未记录/已过期）",
    BlockingRule.B11_NO_MONITORING_SHUTDOWN: "没有监测和停工条件（PILOT_READY/DEPLOYABLE 必需）",
    BlockingRule.B12_SUCCESS_NOT_MET: "成功指标没有达到（mission success criteria 未达标）",
    BlockingRule.B13_FAILURE_TRIGGERED: "失败阈值已经触发（mission failure thresholds 触发）",
}


class BlockingWhen(str, enum.Enum):
    """When a blocking rule applies (gate-rule.schema `when`)."""

    ANY_UPGRADE = "any_upgrade"
    UPGRADE_TO_VALIDATED_PLUS = "upgrade_to_validated_plus"
    UPGRADE_TO_PILOT_PLUS = "upgrade_to_pilot_plus"
    UPGRADE_TO_DEPLOYABLE = "upgrade_to_deployable"
    ALWAYS = "always"


class Decision(str, enum.Enum):
    """Decision vocabulary (spec §九)."""

    PASS = "PASS"
    CONDITIONAL_PASS = "CONDITIONAL_PASS"
    HOLD = "HOLD"
    REJECT = "REJECT"
    REQUEST_REVIEW = "REQUEST_REVIEW"
    SUSPEND = "SUSPEND"
    EXPIRE = "EXPIRE"


class OutputStatus(str, enum.Enum):
    """Unified output status (project convention)."""

    SUCCESS = "SUCCESS"
    PARTIAL = "PARTIAL"
    BLOCKED = "BLOCKED"
    FAILED = "FAILED"
    NEED_ADDITIONAL_SKILL = "NEED_ADDITIONAL_SKILL"
    HUMAN_APPROVAL_REQUIRED = "HUMAN_APPROVAL_REQUIRED"


class EpistemicLabel(str, enum.Enum):
    """Required claim labels (project convention §九)."""

    OBSERVED = "OBSERVED"
    REPORTED = "REPORTED"
    CALCULATED = "CALCULATED"
    INFERRED = "INFERRED"
    HYPOTHESIS = "HYPOTHESIS"
    RECOMMENDATION = "RECOMMENDATION"
