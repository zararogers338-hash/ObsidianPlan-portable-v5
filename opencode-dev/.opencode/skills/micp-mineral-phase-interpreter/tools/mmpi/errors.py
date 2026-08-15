"""OMM error code taxonomy (Obsidian Mineral-phase interpreter).

Every machine-facing failure in this skill carries one of these codes. Codes
are stable within a major version: new codes may be added in minor releases,
existing codes are never renumbered or removed.

Code classes mirror the OSR/OSM convention:
  input / dependency / policy / capability / state / internal
`retryable=True` means the caller may retry after fixing the reported cause.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ErrorSpec:
    code: str
    cls: str
    retryable: bool
    human: str  # human-readable summary, Chinese (project convention)


ERROR_SPECS: dict[str, ErrorSpec] = {
    "OMM-E101": ErrorSpec("OMM-E101", "input", False, "输入未通过 schemas/input.schema.json 校验"),
    "OMM-E102": ErrorSpec("OMM-E102", "input", False, "证据引用缺失、不可读或已损坏"),
    "OMM-E103": ErrorSpec("OMM-E103", "input", False, "单位/量纲不一致或缺少单位声明"),
    "OMM-E104": ErrorSpec("OMM-E104", "input", False, "数值数据存在 NaN/Inf、空值或越界"),
    "OMM-E201": ErrorSpec("OMM-E201", "dependency", True, "依赖的解析库不可用(jsonschema/PyYAML 等)"),
    "OMM-E202": ErrorSpec("OMM-E202", "dependency", True, "数值库不可用(numpy/scipy)"),
    "OMM-E203": ErrorSpec("OMM-E203", "dependency", True, "图像库不可用(PIL/numpy)"),
    "OMM-E204": ErrorSpec("OMM-E204", "dependency", True, "XRD 数据文件不可解析"),
    "OMM-E205": ErrorSpec("OMM-E205", "dependency", True, "光谱数据文件不可解析"),
    "OMM-E206": ErrorSpec("OMM-E206", "dependency", True, "SEM 图像文件不可读或损坏"),
    "OMM-E301": ErrorSpec("OMM-E301", "policy", False, "权限不足:所需操作未获授权"),
    "OMM-E302": ErrorSpec("OMM-E302", "policy", False, "人工批准未完成"),
    "OMM-E303": ErrorSpec("OMM-E303", "policy", False, "写入被 dry-run 或审批门拦截"),
    "OMM-E401": ErrorSpec("OMM-E401", "capability", False, "需要其他专业能力协作(未越权自行调用)"),
    "OMM-E501": ErrorSpec("OMM-E501", "state", False, "上下文、引用或审计日志损坏"),
    "OMM-E502": ErrorSpec("OMM-E502", "state", False, "工件文件损坏或版本不符"),
    "OMM-E601": ErrorSpec("OMM-E601", "input", False, "输出未通过自身输出契约自检"),
    "OMM-E602": ErrorSpec("OMM-E602", "internal", True, "实现内部错误"),
}


@dataclass
class OmError(Exception):
    code: str
    message: str
    cls: str = field(default="input")
    detail: dict[str, Any] = field(default_factory=dict)
    retryable: bool = False

    def __str__(self) -> str:
        return f"{self.code}: {self.message}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "detail": self.detail,
            "retryable": self.retryable,
        }


def make_error(code: str, message: str, detail: dict[str, Any] | None = None) -> OmError:
    spec = ERROR_SPECS.get(code)
    if spec is None:
        raise ValueError(f"unknown OMM error code: {code}")
    return OmError(code=code, message=message, cls=spec.cls,
                   detail=detail or {}, retryable=spec.retryable)


class OmErrorCode:
    """Stable alias constants (mirroring OSR/OSM style)."""

    INPUT_SCHEMA_VIOLATION = ERROR_SPECS["OMM-E101"]
    EVIDENCE_UNVERIFIABLE = ERROR_SPECS["OMM-E102"]
    UNIT_INCOMPATIBLE = ERROR_SPECS["OMM-E103"]
    NUMERIC_INVALID = ERROR_SPECS["OMM-E104"]
    DEPENDENCY_UNAVAILABLE = ERROR_SPECS["OMM-E201"]
    NUMERIC_LIB_UNAVAILABLE = ERROR_SPECS["OMM-E202"]
    IMAGE_LIB_UNAVAILABLE = ERROR_SPECS["OMM-E203"]
    XRD_FILE_UNPARSEABLE = ERROR_SPECS["OMM-E204"]
    SPECTRA_FILE_UNPARSEABLE = ERROR_SPECS["OMM-E205"]
    IMAGE_FILE_UNREADABLE = ERROR_SPECS["OMM-E206"]
    PERMISSION_DENIED = ERROR_SPECS["OMM-E301"]
    APPROVAL_PENDING = ERROR_SPECS["OMM-E302"]
    WRITE_GATE = ERROR_SPECS["OMM-E303"]
    CAPABILITY_GAP = ERROR_SPECS["OMM-E401"]
    CONTEXT_CORRUPTED = ERROR_SPECS["OMM-E501"]
    ARTIFACT_CORRUPTED = ERROR_SPECS["OMM-E502"]
    SELF_CHECK_FAILED = ERROR_SPECS["OMM-E601"]
    INTERNAL = ERROR_SPECS["OMM-E602"]
