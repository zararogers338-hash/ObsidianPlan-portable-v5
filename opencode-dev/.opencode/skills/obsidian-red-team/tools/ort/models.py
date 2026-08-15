"""Domain models for obsidian-red-team.

Enums serialize as plain strings so tool envelopes stay human-readable and
JSON-schema-validatable without custom encoders.
"""

from __future__ import annotations

import enum


class Severity(str, enum.Enum):
    INFO = "INFO"
    MINOR = "MINOR"
    MAJOR = "MAJOR"
    CRITICAL = "CRITICAL"
    BLOCKING = "BLOCKING"


SEVERITY_ORDER: dict[Severity, int] = {
    Severity.INFO: 0,
    Severity.MINOR: 1,
    Severity.MAJOR: 2,
    Severity.CRITICAL: 3,
    Severity.BLOCKING: 4,
}


class EpistemicLabel(str, enum.Enum):
    OBSERVED = "OBSERVED"
    REPORTED = "REPORTED"
    CALCULATED = "CALCULATED"
    INFERRED = "INFERRED"
    HYPOTHESIS = "HYPOTHESIS"
    RECOMMENDATION = "RECOMMENDATION"


# A claim may not be labeled stronger than its provenance supports.
# OBSERVED > CALCULATED > REPORTED > INFERRED > HYPOTHESIS; RECOMMENDATION is
# orthogonal (never mislabeled as fact).
EPISTEMIC_STRENGTH: dict[EpistemicLabel, int] = {
    EpistemicLabel.HYPOTHESIS: 1,
    EpistemicLabel.INFERRED: 2,
    EpistemicLabel.REPORTED: 3,
    EpistemicLabel.CALCULATED: 4,
    EpistemicLabel.OBSERVED: 5,
}


class ReviewDimension(str, enum.Enum):
    SOURCE_AUTHENTICITY = "source_authenticity"
    EPISTEMIC_ESCALATION = "epistemic_escalation"
    UNITS_DIMENSION = "units_dimension"
    EXPERIMENTAL_DESIGN = "experimental_design"
    STATISTICAL_ANALYSIS = "statistical_analysis"
    MICP_MECHANISM = "micp_mechanism"
    MODEL_BOUNDARY = "model_boundary"
    ENGINEERING_SCALEUP = "engineering_scaleup"
    ENVIRONMENT_SAFETY = "environment_safety"
    DECISION_GATE = "decision_gate"
    PERMISSION_BOUNDARY = "permission_boundary"


DIMENSION_LABELS: dict[str, str] = {
    "source_authenticity": "来源真实性",
    "epistemic_escalation": "认识论越级",
    "units_dimension": "数值与单位",
    "experimental_design": "实验设计",
    "statistical_analysis": "统计分析",
    "micp_mechanism": "MICP 专业机制",
    "model_boundary": "模型边界",
    "engineering_scaleup": "工程放大",
    "environment_safety": "环境与安全",
    "decision_gate": "决策门",
    "permission_boundary": "权限边界",
}


class StateRecommendation(str, enum.Enum):
    APPROVE = "APPROVE"
    NO_OBJECTION = "NO_OBJECTION"
    HOLD = "HOLD"
    REVIEW_FAIL = "REVIEW_FAIL"


class FindingStatus(str, enum.Enum):
    OPEN = "OPEN"
    FIXED = "FIXED"
    ACCEPTED_RISK = "ACCEPTED_RISK"
    VERIFIED = "VERIFIED"


class BlockingRuleId(str, enum.Enum):
    """The ten deterministic BLOCKING rules. Single source of truth lives in
    blocking_rules.py; these IDs keep the vocabulary stable."""

    FABRICATED_CITATION = "BLOCK-1"
    AMMONIA_EXCEEDANCE = "BLOCK-2"
    OPEN_BLOCKER_ESCALATION = "BLOCK-3"
    MASS_BALANCE_VIOLATION = "BLOCK-4"
    PSEUDOREPLICATION_CARRIES_KEY = "BLOCK-5"
    REGULATION_UNVERIFIED = "BLOCK-6"
    ENGINEERING_BLOCKER_RELEASE = "BLOCK-7"
    STATE_ESCALATION = "BLOCK-8"
    PERMISSION_BOUNDARY = "BLOCK-9"
    EPISTEMIC_ESCALATION_DEPLOY = "BLOCK-10"
    MODEL_BOUNDARY = "BLOCK-11"
