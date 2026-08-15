"""Error code system for micp-literature-scout (MLS-E###).

Every error is human-readable AND machine-parseable: the CLI emits
{"code": "MLS-E###", "message": <zh, human>, "detail": {...}} so a controller
can switch on `code` while a human reads `message`.

Code ranges (see SKILL.md §9):
  E1xx  input contract       E2xx  evidence/citations
  E3xx  data/storage         E4xx  tooling/environment
  E5xx  permission/approval  E6xx  downstream capability
  E7xx  output/self-check    E8xx  version compatibility
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class MlsError:
    """A structured MLS error. `detail` is free-form (dict/str/list) and
    must be JSON-serializable."""

    code: str
    message: str
    detail: Any = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {"code": self.code, "message": self.message, "detail": self.detail}


# --- E1xx input contract -----------------------------------------------------

def e101_input_schema(violations: list[Any]) -> MlsError:
    return MlsError(
        "MLS-E101",
        "输入未通过 input.schema.json 校验，共 %d 处问题" % len(violations),
        {"violations": violations[:20]},
    )


def e102_missing_fields(missing: dict[str, str]) -> MlsError:
    """missing: {field: guidance} — guidance explains why critical + how to obtain."""
    return MlsError(
        "MLS-E102",
        "输入缺少必需字段: %s" % ", ".join(sorted(missing)),
        {"missing_fields": missing},
    )


def e103_invalid_action(action: Any, allowed: list[str]) -> MlsError:
    return MlsError(
        "MLS-E103",
        "action 非法: %r；合法取值: %s" % (action, ", ".join(allowed)),
        {"action": action, "allowed": allowed},
    )


def e104_version_mismatch(contract_version: Any) -> MlsError:
    return MlsError(
        "MLS-E104",
        "contract_version 主版本不符(需 1.x，收到 %r) — 请升级 payload 或 Skill" % (contract_version,),
        {"contract_version": contract_version, "supported_major": "1"},
    )


def e105_invalid_timestamp(ts: Any) -> MlsError:
    return MlsError(
        "MLS-E105",
        "timestamp 需为 ISO-8601，收到 %r" % (ts,),
        {"timestamp": ts},
    )


# --- E2xx evidence / citations ----------------------------------------------

def e201_doi_unresolved(doi: str, reason: str) -> MlsError:
    return MlsError(
        "MLS-E201",
        "DOI 无法核验存在: %s (%s)" % (doi, reason),
        {"doi": doi, "reason": reason},
    )


def e202_doi_metadata_mismatch(doi: str, claimed: dict[str, Any], actual: dict[str, Any]) -> MlsError:
    return MlsError(
        "MLS-E202",
        "DOI 元数据与声称不一致: %s" % doi,
        {"doi": doi, "claimed": claimed, "actual": actual},
    )


def e203_suspected_forged(doi: str, reason: str) -> MlsError:
    return MlsError(
        "MLS-E203",
        "疑似伪造引用: %s (%s) — 不采信" % (doi, reason),
        {"doi": doi, "reason": reason},
    )


def e204_unit_inconsistency(field: str, value: Any, reason: str) -> MlsError:
    return MlsError(
        "MLS-E204",
        "数值/单位不一致: %s=%r (%s)" % (field, value, reason),
        {"field": field, "value": value, "reason": reason},
    )


# --- E3xx data / storage -----------------------------------------------------

def e301_trace_corrupt(path: str, reason: str) -> MlsError:
    return MlsError(
        "MLS-E301",
        "trace 日志损坏或不可写: %s (%s) — 不静默丢弃，见故障排除" % (path, reason),
        {"path": path, "reason": reason},
    )


# --- E4xx tooling / environment ----------------------------------------------

def e401_adapters_unavailable(details: dict[str, str]) -> MlsError:
    return MlsError(
        "MLS-E401",
        "检索适配器全部不可用; 已尝试离线降级。可用离线 fixture 完成分层/去重/导出" ,
        {"adapters": details},
    )


def e402_network_unavailable() -> MlsError:
    return MlsError(
        "MLS-E402",
        "网络不可用且无离线降级 — 使用 --offline 走 fixture，或恢复网络后重试",
        {"hint": "--offline"},
    )


def e403_timeout(database: str, seconds: float) -> MlsError:
    return MlsError(
        "MLS-E403",
        "检索适配器超时: %s (%.1fs)" % (database, seconds),
        {"database": database, "timeout_seconds": seconds},
    )


def e404_database_error(database: str, status: int, detail: str) -> MlsError:
    return MlsError(
        "MLS-E404",
        "数据库返回错误: %s HTTP %d — %s" % (database, status, detail),
        {"database": database, "status": status, "detail": detail},
    )


# --- E5xx permission / approval ----------------------------------------------

def e501_network_approval_required(action: str) -> MlsError:
    return MlsError(
        "MLS-E501",
        "网络检索需人工审批: %s 需要 human_approval_state.granted=true（含 approver）" % action,
        {"action": action, "needed": "human_approval_state.granted=true"},
    )


def e502_write_approval_required(action: str) -> MlsError:
    return MlsError(
        "MLS-E502",
        "写盘/来源登记需人工审批: %s 需要 human_approval_state.granted=true" % action,
        {"action": action},
    )


def e503_role_forbidden(action: str, role: str, allowed: list[str]) -> MlsError:
    return MlsError(
        "MLS-E503",
        "角色 %s 无权执行 %s; 允许角色: %s" % (role, action, ", ".join(allowed)),
        {"action": action, "role": role, "allowed": allowed},
    )


# --- E6xx downstream capability ----------------------------------------------

def e601_need_additional_skill(skill: str, required_inputs: list[str], reason: str) -> MlsError:
    return MlsError(
        "MLS-E601",
        "需要其他能力 %s 才能继续: %s" % (skill, reason),
        {"skill": skill, "required_inputs": required_inputs, "reason": reason},
    )


# --- E7xx output / self-check ------------------------------------------------

def e701_output_schema_failed(issues: list[Any]) -> MlsError:
    return MlsError(
        "MLS-E701",
        "输出未通过 output.schema.json 自检 (%d 处问题)" % len(issues),
        {"issues": issues[:20]},
    )


def e702_epistemic_mislabel(statement: str, label: str, reason: str) -> MlsError:
    return MlsError(
        "MLS-E702",
        "认识论标签越级: %r 标为 %s (%s)" % (statement, label, reason),
        {"statement": statement, "label": label, "reason": reason},
    )


def e703_scale_mislabel(statement: str, scope: str, reason: str) -> MlsError:
    return MlsError(
        "MLS-E703",
        "证据尺度误标: %r 标为 %s (%s)" % (statement, scope, reason),
        {"statement": statement, "scope": scope, "reason": reason},
    )


# --- E8xx version compatibility ----------------------------------------------

def e801_old_major_rejected(version: str, detail: str) -> MlsError:
    return MlsError(
        "MLS-E801",
        "旧主版本输出被拒绝: %s — 无迁移策略，请升级到当前版本 (%s)" % (version, detail),
        {"version": version, "detail": detail},
    )


def e802_migrated(version: str, detail: str) -> MlsError:
    return MlsError(
        "MLS-E802",
        "输出已按迁移规则映射: %s (%s)" % (version, detail),
        {"version": version, "detail": detail},
    )
