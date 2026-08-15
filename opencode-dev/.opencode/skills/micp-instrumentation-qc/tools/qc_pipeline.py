"""micp-instrumentation-qc: full QC pipeline orchestration.

Pure Python standard library. Deterministic. Pipeline:
  unit/dimension check -> calibration (if present) -> control chart (if measurements)
  -> sample chain (if samples) -> integrity (if raw/derived) -> QC report.

Hard gates (return BLOCKED with MICQ codes):
  - unit/dimension inconsistency across a dimension        -> MICQ-E1003
  - unverifiable evidence/data references                 -> MICQ-E1002
  - missing audit-log capability when integrity requested -> MICQ-E1004
  - calibration failure                                    -> FAIL/blocker in report
"""

from __future__ import annotations

import json
import os
from typing import Any

from _common import check_numeric, is_dimensionless, to_si, is_semver, parse_semver

from calibration import compute as calib_compute
from control_chart import check_measurements
from sample_chain import check_samples
from integrity import verify_raw, append_log, verify_log


def validate_envelope(data: dict[str, Any]) -> list[dict[str, Any]]:
    """Envelope-level gates: required fields, version compatibility, schema.

    Returns a list of error objects (empty when the envelope is acceptable).
    Schema validation uses jsonschema when available (test/CI environments);
    the required-field and version gates are enforced unconditionally.
    """
    errors: list[dict[str, Any]] = []

    required = ["task_id", "project_id", "request", "skill_version", "controller_version", "timestamp"]
    missing = [f for f in required if not data.get(f)]
    if missing:
        errors.append({
            "code": "MICQ-E1001",
            "message": "输入未通过 input.schema.json 校验",
            "retryable": False,
            "details": {
                "missing": [
                    {"field": f,
                     "why_critical": _MISSING_WHY.get(f, "信封必需字段"),
                     "how_to_obtain": _MISSING_HOW.get(f, "由 Obsidian Controller 注入"),
                     "blocking": True}
                    for f in missing
                ],
            },
        })

    # Version gate: skill major == 1; controller >= 1.0.0.
    sv = data.get("skill_version")
    if sv and not is_semver(sv):
        errors.append({"code": "MICQ-E1010", "message": "skill/controller 版本不受支持",
                       "retryable": False, "details": {"reason": f"skill_version '{sv}' is not semver"}})
    elif sv and parse_semver(sv)[0] != 1:
        errors.append({"code": "MICQ-E1010", "message": "skill/controller 版本不受支持",
                       "retryable": False, "details": {"reason": f"skill_version '{sv}' major != 1"}})
    cv = data.get("controller_version")
    if cv and is_semver(cv) and parse_semver(cv) < (1, 0, 0):
        errors.append({"code": "MICQ-E1010", "message": "skill/controller 版本不受支持",
                       "retryable": False, "details": {"reason": f"controller_version '{cv}' < 1.0.0"}})

    # Optional full schema validation (jsonschema present in CI/test).
    try:
        import jsonschema

        schema_path = os.path.join(os.path.dirname(__file__), "..", "schemas", "input.schema.json")
        if os.path.isfile(schema_path):
            with open(schema_path, encoding="utf-8") as f:
                schema = json.load(f)
            verr = sorted(jsonschema.Draft7Validator(schema).iter_errors(data), key=lambda e: list(e.path))
            if verr:
                errors.append({
                    "code": "MICQ-E1001",
                    "message": "输入未通过 input.schema.json 校验",
                    "retryable": False,
                    "details": {"schema_errors": [e.message for e in verr[:10]]},
                })
    except ImportError:
        pass
    except Exception as exc:  # pragma: no cover
        errors.append({"code": "MICQ-E1011", "message": "实现内部错误",
                       "retryable": True, "details": {"reason": f"schema validation error: {exc}"}})

    return errors


_MISSING_WHY = {
    "task_id": "审计日志锚点与复现依据",
    "project_id": "选择审计日志文件与归属",
    "request": "触发与能力匹配的唯一文本信号",
    "skill_version": "版本兼容门(不兼容拒绝)",
    "controller_version": "权限模型版本门",
    "timestamp": "审计与复现时间基准",
}
_MISSING_HOW = {
    "task_id": "由 Task Decomposer 分配",
    "project_id": "由项目注册表提供",
    "request": "由 Mission Lock 的任务合同提供",
    "skill_version": "本 Skill frontmatter 声明",
    "controller_version": "Controller 版本常量注入",
    "timestamp": "Controller 调用时注入",
}


def _check_units(qc_input: dict[str, Any]) -> list[dict[str, Any]]:
    """Verify unit consistency within each dimension group. Returns problems."""
    problems: list[dict[str, Any]] = []

    # Calibration: standard concentrations must share a unit dimension.
    for c in qc_input.get("calibrations") or []:
        standards = c.get("standards") or []
        units = {s.get("unit") or "" for s in standards}
        if len(units) > 1:
            problems.append({
                "field": f"calibrations[{c.get('calibration_id')}].standards.unit",
                "problem": f"mixed units in standards: {sorted(units)}",
            })

    # Measurements: value must be finite, unit must exist or be dimensionless.
    for m in qc_input.get("measurements") or []:
        probs = check_numeric(m.get("value"), f"measurements[{m.get('measurement_id')}].value", finite=True)
        if probs:
            problems.extend(probs)
        u = m.get("unit")
        if u is None or (not is_dimensionless(u) and not u.strip()):
            problems.append({
                "field": f"measurements[{m.get('measurement_id')}].unit",
                "problem": "unit missing (must be provided or explicitly dimensionless)",
            })

    return problems


def _check_evidence(qc_input: dict[str, Any]) -> list[dict[str, Any]]:
    """Evidence/data references must be resolvable (file exists or inline)."""
    problems: list[dict[str, Any]] = []
    import os

    for r in qc_input.get("data_refs") or []:
        if isinstance(r, str) and not os.path.isfile(r) and not r.startswith(("http://", "https://", "doi:")):
            problems.append({"field": "data_refs", "problem": f"unresolvable reference '{r}'"})
    return problems


def build_qc_report(qc_input: dict[str, Any], requested_format: str) -> dict[str, Any]:
    """Run the pipeline and return the qc_report section + hard-gate errors."""
    errors: list[dict[str, Any]] = []
    findings: list[dict[str, Any]] = []
    overall_passed = True
    pass_units = 0
    pass_total = 0

    # 0. Minimum input gate: for data-producing formats, at least one data
    #    category must be present, else we return BLOCKED-style missing inputs
    #    (MICQ-E1001) instead of silently reporting a vacuous pass.
    data_present = any(bool(qc_input.get(k)) for k in
                       ("instruments", "calibrations", "measurements", "samples", "raw", "derived"))
    if not data_present and requested_format != "qc_plan":
        errors.append({
            "code": "MICQ-E1001",
            "message": "输入未通过 input.schema.json 校验",
            "retryable": False,
            "details": {
                "missing": [
                    {"field": "qc_input.measurements",
                     "why_critical": "QC 判定的主体数据;没有测量就没有可审核的对象",
                     "how_to_obtain": "从实验记录或仪器导出文件提供 measurements 数组",
                     "blocking": True},
                    {"field": "qc_input.instruments",
                     "why_critical": "数据必须绑定仪器与校准(验收门槛 1);缺失则无法确认数据来源",
                     "how_to_obtain": "从仪器台账提供 instruments 数组",
                     "blocking": True},
                    {"field": "qc_input.calibrations",
                     "why_critical": "不确定度与漂移判定依据;缺失则无法传播 LOD/LOQ/不确定度",
                     "how_to_obtain": "从标定记录提供 calibrations 数组",
                     "blocking": True},
                ],
            },
        })
        overall_passed = False

    # 1. unit/dimension check
    unit_problems = _check_units(qc_input)
    if unit_problems:
        errors.append({
            "code": "MICQ-E1003", "message": "数值单位/量纲不一致或不可换算",
            "retryable": False, "details": {"problems": unit_problems},
        })
        overall_passed = False

    # 2. evidence/data references
    ev_problems = _check_evidence(qc_input)
    if ev_problems:
        errors.append({
            "code": "MICQ-E1002", "message": "证据或数据引用缺失、不可读或损坏",
            "retryable": False, "details": {"problems": ev_problems},
        })
        overall_passed = False

    # 3. calibration
    calibration_result: dict[str, Any] | None = None
    for c in qc_input.get("calibrations") or []:
        try:
            res = calib_compute(c)
        except ValueError as exc:
            calibration_result = {"status": "failed", "error": str(exc)}
            overall_passed = False
            errors.append({"code": "MICQ-E1001", "message": str(exc), "retryable": False})
            break
        calibration_result = res
        if res.get("status") == "failed":
            overall_passed = False
        pass_units += 1
        pass_total += 1

    # 4. control chart
    control_result: dict[str, Any] | None = None
    if qc_input.get("measurements"):
        try:
            control_result = check_measurements(qc_input)
        except ValueError as exc:
            errors.append({"code": "MICQ-E1001", "message": str(exc), "retryable": False})
            overall_passed = False
            control_result = None
        else:
            if control_result["out_of_control_count"] > 0 or control_result["over_range_count"] > 0 \
                    or control_result["saturation_count"] > 0 or control_result["drift_count"] > 0 \
                    or control_result["timestamp_misalignment_count"] > 0:
                overall_passed = False
            pass_total += 1

    # 5. sample chain
    sample_chain_result: dict[str, Any] | None = None
    if qc_input.get("samples"):
        try:
            sample_chain_result = check_samples(qc_input)
        except ValueError as exc:
            errors.append({"code": "MICQ-E1001", "message": str(exc), "retryable": False})
            overall_passed = False
            sample_chain_result = None
        else:
            if sample_chain_result.get("duplicate_ids"):
                overall_passed = False
            pass_total += 1

    # 6. integrity
    integrity_result: dict[str, Any] | None = None
    if qc_input.get("raw") or qc_input.get("derived"):
        try:
            integrity_result = verify_raw(qc_input.get("raw") or [])
        except Exception as exc:
            errors.append({"code": "MICQ-E1004", "message": f"integrity tool unavailable: {exc}", "retryable": True})
            overall_passed = False

    # Aggregate findings + restrictions.
    restrictions: list[str] = []
    retest: list[str] = []
    instrument_status: list[dict[str, Any]] = []
    sample_flags: list[dict[str, Any]] = []

    for instr in qc_input.get("instruments") or []:
        instrument_status.append({
            "instrument_id": instr.get("instrument_id"),
            "kind": instr.get("kind"),
            "status": "PASS",
            "reason": "registered",
            "lod": instr.get("detection_limit"),
            "loq": instr.get("quantification_limit"),
            "expanded_uncertainty": instr.get("expanded_uncertainty"),
            "certified": instr.get("calibration_ref") is not None,
        })

    if control_result:
        for f in control_result["flags"]:
            sample_flags.append({"sample_id": f["sample_id"], "flag": f["flag"], "severity": f["severity"],
                                 "details": f.get("details")})
            if f["severity"] == "blocker":
                retest.append(f["sample_id"])
        if control_result["out_of_control_count"] or control_result["over_range_count"] \
                or control_result["saturation_count"]:
            restrictions.append("measurements with OUT_OF_CONTROL/OVER_RANGE/SATURATION must not enter formal analysis")
        if control_result["drift_count"]:
            restrictions.append("instrument drift detected; recalibrate before further quantitative use")

    if sample_chain_result:
        for f in sample_chain_result["flags"]:
            sample_flags.append({"sample_id": f["sample_id"], "flag": f["flag"], "severity": f["severity"],
                                 "details": f.get("details")})
        if sample_chain_result.get("duplicate_ids"):
            restrictions.append("duplicate sample IDs break the chain of custody; resolve before analysis")

    if errors and all(e["code"] in ("MICQ-E1003", "MICQ-E1002") for e in errors):
        pass

    if control_result is not None and calibration_result is not None:
        pass_units += 1
        pass_total += 1

    return {
        "report_type": requested_format,
        "overall_passed": overall_passed and not any(e["code"] == "MICQ-E1003" for e in errors),
        "pass_rate": round(pass_units / max(1, pass_total), 4),
        "instrument_status": instrument_status,
        "sample_flags": sample_flags,
        "analysis_restrictions": restrictions,
        "retest_items": sorted(set(retest)),
        "calibration": calibration_result,
        "control": control_result,
        "sample_chain": sample_chain_result,
        "integrity": integrity_result,
        "errors": errors,
    }


def run(data: dict[str, Any]) -> dict[str, Any]:
    """Full pipeline: validate envelope, run build_qc_report on qc_input, optionally append audit entry."""
    envelope_errors = validate_envelope(data)
    if envelope_errors:
        return {
            "qc_report": {
                "report_type": data.get("requested_output_format", "qc_report"),
                "overall_passed": False,
                "pass_rate": 0.0,
                "instrument_status": [],
                "sample_flags": [],
                "analysis_restrictions": ["envelope invalid; no data cleared for analysis"],
                "retest_items": [],
                "errors": envelope_errors,
            },
            "errors": envelope_errors,
            "envelope_errors": envelope_errors,
        }

    qc_input = dict(data.get("qc_input") or {})
    # Thread envelope-level evidence/data references into the QC checks.
    if data.get("data_refs") and "data_refs" not in qc_input:
        qc_input["data_refs"] = data["data_refs"]
    if data.get("evidence_refs") and "evidence_refs" not in qc_input:
        qc_input["evidence_refs"] = data["evidence_refs"]

    requested_format = data.get("requested_output_format", "qc_report")
    report = build_qc_report(qc_input, requested_format)
    out: dict[str, Any] = {"qc_report": report}
    if data.get("append_audit") and report["overall_passed"]:
        log_path = data.get("audit_log_path")
        if not log_path:
            out["errors"] = [{"code": "MICQ-E1004", "message": "audit log path required for append", "retryable": True}]
        else:
            try:
                entry = {"kind": "qc_report", "task_id": data.get("task_id"),
                         "project_id": data.get("project_id"), "report": report}
                out["audit"] = append_log(entry, log_path)
            except ValueError as exc:
                out["errors"] = [{"code": "MICQ-E1009", "message": str(exc), "retryable": False}]
    return out
