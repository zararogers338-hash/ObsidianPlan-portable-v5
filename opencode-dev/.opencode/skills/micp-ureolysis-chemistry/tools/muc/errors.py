"""MUC (MICP Ureolysis Chemistry) — typed error codes.

Machine-parseable, human-readable error taxonomy for the skill. Every failure
path returns one of these codes so the Obsidian controller can route
programmatically. Error payloads follow the project envelope convention:
  {"ok": false, "tool": <name>, "version": <semver>,
   "error": {"code", "message", "retryable", "details"}}

Code family: MUC-E1xxx (input/contract), MUC-E2xxx (numerics), MUC-E3xxx
(environment/tools), MUC-E4xxx (self-check).
"""

from __future__ import annotations

from typing import Any

DESCRIPTIONS: dict[str, dict[str, str]] = {
    "MUC-E1001": {"en": "Input failed schema validation", "zh": "输入未通过 schema 校验"},
    "MUC-E1002": {"en": "Evidence reference could not be verified", "zh": "证据引用不可核验"},
    "MUC-E1003": {"en": "Unit, scale, or quantity inconsistency", "zh": "单位/量纲/量值不一致"},
    "MUC-E1004": {"en": "A required external tool is unavailable", "zh": "依赖外部工具不可用"},
    "MUC-E1005": {"en": "Insufficient permission for the requested action", "zh": "权限不足"},
    "MUC-E1006": {"en": "A required downstream skill/capability is missing", "zh": "下游能力缺失"},
    "MUC-E1007": {"en": "Required human approval gate has not been completed", "zh": "人工审批未完成"},
    "MUC-E1008": {"en": "Generated output failed the skill's self-check", "zh": "结果未通过自检"},
    "MUC-E1009": {"en": "Context or referenced file is corrupted or unreadable", "zh": "上下文或文件损坏"},
    "MUC-E1010": {"en": "Schema/contract version is incompatible and no migration exists", "zh": "版本不兼容且无迁移路径"},
    "MUC-E2001": {"en": "Numerical solve failed to converge", "zh": "数值求解未收敛"},
    "MUC-E2002": {"en": "Mathematically infeasible system (e.g. negative species from conservation)", "zh": "数学上不可行的系统"},
    "MUC-E2003": {"en": "Mass-balance self-check failed (elemental imbalance too large)", "zh": "质量守恒自检失败"},
    "MUC-E2004": {"en": "Non-finite or out-of-range quantity", "zh": "非有限或越界数值"},
    "MUC-E3001": {"en": "External geochemical engine (PHREEQC) not available", "zh": "PHREEQC 不可用"},
    "MUC-E3002": {"en": "External tool produced malformed output", "zh": "外部工具输出格式异常"},
    "MUC-E3003": {"en": "Network required but unavailable (offline degradation applied)", "zh": "需要网络但不可用"},
    "MUC-E4001": {"en": "Self-check failure: SI equated to yield without a yield model", "zh": "自检失败:将 SI 等同于产率"},
    "MUC-E4002": {"en": "Self-check failure: epistemic label misused", "zh": "自检失败:认识论标签误用"},
}

_RETRYABLE = {
    "MUC-E1007",  # approval can be granted later
    "MUC-E2001",  # retry with better initial guess / tighter tolerance
    "MUC-E3001",  # install/configure PHREEQC then retry
    "MUC-E3002",  # transient malformed output
    "MUC-E3003",  # connectivity may return
}


class MUCError(Exception):
    """An expected, classifiable failure carrying a machine-readable code."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        retryable: bool | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = DESCRIPTIONS.get(code, {}).get("en") is not None and (
            retryable if retryable is not None else code in _RETRYABLE
        )
        self.details = details or {}

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "name": self.__class__.__name__,
            "message": self.message,
            "retryable": self.retryable,
            "details": self.details,
        }


def describe(code: str) -> dict[str, str]:
    return DESCRIPTIONS.get(code, {"en": "unknown error", "zh": "未知错误"})
