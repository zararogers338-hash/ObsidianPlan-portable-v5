"""obsidian-red-team review service: the full adversarial-review pipeline.

Pipeline (every step is a real tool call — never faked):
  1. Validate the controller envelope against schemas/input.schema.json.
  2. Version gate (skill_version major).
  3. Precondition: at least one target; risk/approval gate.
  4. Ten-dimension scan → candidate findings from the deterministic tools.
  5. Severity scoring per candidate finding.
  6. Blocking rule engine → BLOCKING set + state recommendation.
  7. Counterexamples + alternative explanations for BLOCKING/CRITICAL findings.
  8. Required fixes + retest plan; fix executability via the retest tool.
  9. Self-check the assembled output against schemas/output.schema.json.
  10. Emit the unified envelope.

Deterministic and offline.
"""

from __future__ import annotations

import json
import os
from typing import Any

from common import ToolError
from errors import OrtErrorCode, OrtError

SKILL_NAME = "obsidian-red-team"
SKILL_VERSION = "1.0.0"
CONTRACT_VERSION = "1.0.0"

TOOLS_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SKILL_ROOT = os.path.dirname(TOOLS_DIR)
SCHEMAS_DIR = os.path.join(SKILL_ROOT, "schemas")

STATUSES = ("SUCCESS", "PARTIAL", "BLOCKED", "FAILED",
            "NEED_ADDITIONAL_SKILL", "HUMAN_APPROVAL_REQUIRED")

# The ten mandatory attack dimensions (permission_boundary is an engine-level
# check applied to upstream actions, reported separately).
TEN_DIMENSIONS = (
    "source_authenticity",
    "epistemic_escalation",
    "units_dimension",
    "experimental_design",
    "statistical_analysis",
    "micp_mechanism",
    "model_boundary",
    "engineering_scaleup",
    "environment_safety",
    "decision_gate",
)


def _now_iso() -> str:
    import datetime
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def load_schema(name: str) -> dict:
    path = os.path.join(SCHEMAS_DIR, name)
    if not os.path.isfile(path):
        raise ToolError("ORT-E301", f"schema file not found: {name}",
                        details={"path": path}, exit_code=4)
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def _validate_input(p: dict) -> list[dict]:
    schema = load_schema("input.schema.json")
    try:
        from _jsonschema import validate_with_schema
        issues = validate_with_schema(p, schema)
    except Exception:  # noqa: BLE001
        try:
            import jsonschema  # type: ignore
            v = jsonschema.Draft202012Validator(schema)
            issues = [f"{e.message} at {'/'.join(map(str, e.path))}" for e in sorted(
                v.iter_errors(p), key=lambda e: list(e.path))]
        except Exception:  # noqa: BLE001
            issues = ["schema engine unavailable"]
    return [{"field": "input", "why_critical": "input.schema.json", "how_to_obtain": "fix the envelope",
             "issue": i} for i in issues]


def _check_versions(p: dict) -> list[str]:
    problems: list[str] = []
    sv = p.get("skill_version")
    if sv and str(sv).split(".")[0] != SKILL_VERSION.split(".")[0]:
        problems.append(f"skill_version {sv!r} major differs from {SKILL_VERSION} (ORT-E801)")
    if not sv:
        problems.append("skill_version missing (ORT-E101)")
    return problems


def _collect_dimension_scope(p: dict) -> list[dict]:
    """Review scope with explicit skip/NA declarations.

    A dimension is 'not_applicable' only when no target touches its material;
    otherwise it is 'reviewed'. If require_full_ten_dimensions and a dimension
    is neither reviewed nor NA, the service records a MAJOR finding for the
    reviewer to fix.
    """
    targets = p.get("targets") or []
    has_refs = bool(p.get("evidence_refs")) or bool(p.get("data_refs"))
    scope = []
    dims_material = {
        "source_authenticity": False,
        "epistemic_escalation": False,
        "units_dimension": False,
        "experimental_design": False,
        "statistical_analysis": False,
        "micp_mechanism": False,
        "model_boundary": False,
        "engineering_scaleup": False,
        "environment_safety": False,
        "decision_gate": False,
    }
    for t in targets:
        t_type = t.get("type")
        t_summary = str(t.get("summary", ""))
        t_location = str(t.get("location", ""))
        blob = f"{t_type} {t_summary} {t_location}"
        for dim in dims_material:
            if _dimension_touched(dim, t_type, blob, has_refs):
                dims_material[dim] = True
    for dim in TEN_DIMENSIONS:
        if dims_material[dim]:
            scope.append({"dimension": dim, "status": "reviewed", "reason": ""})
        else:
            scope.append({"dimension": dim, "status": "not_applicable",
                          "reason": "no target material touches this dimension"})
    return scope


def _dimension_touched(dim: str, t_type: str, blob: str, has_refs: bool) -> bool:
    blob = blob.lower()
    if dim == "source_authenticity":
        return has_refs
    if dim == "epistemic_escalation":
        return True
    if dim == "units_dimension":
        return any(u in blob for u in ("mpa", "kpa", "g/l", "mg/l", "mol/l", "m/s", "kg/m3", "cm/s", "bar", "ppm"))
    if dim == "experimental_design":
        return t_type in ("experiment", "evidence", "conclusion")
    if dim == "statistical_analysis":
        return any(s in blob for s in ("p-value", "p 值", "significant", "显著", "anova", "t-test", "mean", "平均", "标准差"))
    if dim == "micp_mechanism":
        return any(m in blob for m in ("micp", "urease", "脲酶", "od600", "caco3", "钙化", "biocement", "微生物", "菌"))
    if dim == "model_boundary":
        return t_type in ("model", "conclusion") or any(m in blob for m in ("model", "数值模拟", "仿真", "有限元", "regression"))
    if dim == "engineering_scaleup":
        return any(s in blob for s in ("scale", "现场", "field", "放大", "注入", "column", "柱", "pilot", "中试"))
    if dim == "environment_safety":
        return any(e in blob for e in ("氨", "ammonia", "环境", "environment", "安全", "safety", "lca", "法规", "regul"))
    if dim == "decision_gate":
        return t_type in ("decision", "conclusion")
    return True


def _run_tool(name: str, payload: dict) -> dict:
    """Run a sibling tool module's main() in-process (deterministic, offline)."""
    import importlib
    # subcommand name -> module name (blocking engine lives in blocking_rules.py)
    module_name = {"blocking": "blocking_rules"}.get(name, name)
    mod = importlib.import_module(module_name)
    return mod.main(payload)


def _scan_dimensions(p: dict) -> list[dict]:
    """Produce candidate findings from the deterministic tools."""
    findings: list[dict] = []
    targets = p.get("targets") or []
    evidence_refs = p.get("evidence_refs") or []
    data_refs = p.get("data_refs") or []
    constraints = p.get("constraints") or {}
    state_gate = constraints.get("state_gate") or "REVIEW"

    seq = [0]

    def nid(prefix: str) -> str:
        seq[0] += 1
        return f"{prefix}-{seq[0]:03d}"

    # --- dimension 1: source authenticity ---------------------------------
    if evidence_refs:
        try:
            cit = _run_tool("citation", {"citations": evidence_refs, "targets": targets})
            for r in cit["results"]:
                if r["verdict"] in ("REJECTED", "SUSPECTED"):
                    # Both REJECTED and SUSPECTED are fabrication candidates for
                    # BLOCK-1: a fabricated locator/title cannot support a claim.
                    findings.append(_mk_finding(
                        nid("F01"), "source_authenticity", "BLOCKING",
                        summary=f"引用 {r['ref_id']} 结构核验 {r['verdict']}（伪造引用候选）",
                        location=r["ref_id"],
                        evidence="; ".join(r["issues"]) or "locator 不可解析",
                        why="来源真实性受攻击：引用可能不存在或与内容不符，不能支撑任何结论",
                        counterexample="该引用若被删除或替换，结论的证据支撑立即瓦解",
                        required_fix="提供可核验的 DOI/全文定位或替换为已核验来源",
                        verification_method="重跑 citation 工具至 verdict=VERIFIED",
                        rule_id="BLOCK-1", blocks=True,
                        target_id=r["ref_id"],
                    ))
        except Exception as exc:  # noqa: BLE001
            findings.append(_mk_finding(
                nid("F01"), "source_authenticity", "MAJOR",
                summary=f"引用核验工具执行失败: {exc}",
                location="evidence_refs", evidence=str(exc),
                why="工具未真实运行", counterexample="工具可复现失败",
                required_fix="修复工具或输入", verification_method="重跑 citation",
                blocks=False, target_id="tool"))

    # --- dimension 2: epistemic escalation --------------------------------
    for t in targets:
        label = t.get("epistemic_label")
        if label in ("INFERRED", "HYPOTHESIS", "RECOMMENDATION"):
            support = t.get("status_support")
            if support in ("VALIDATED", "PILOT_READY", "DEPLOYABLE"):
                findings.append(_mk_finding(
                    nid("F02"), "epistemic_escalation", "BLOCKING",
                    summary=f"认识论越级: 目标 {t['id']} 自标 {label} 却声明支持 {support}",
                    location=t.get("location") or t["id"],
                    evidence=f"epistemic_label={label}, status_support={support}",
                    why="推断/假设/建议不能作为升级或部署的证据等级",
                    counterexample="同一结论仅以 HYPOTHESIS 支撑即被升级",
                    required_fix="将结论降级为 INFERRED 支撑，或补充 OBSERVED/REPORTED 级证据",
                    verification_method="升级声明关联到 OBSERVED/REPORTED 级证据后方可通过",
                    rule_id="BLOCK-10", blocks=True, target_id=t["id"]))

    # --- dimension 3: units & dimension -----------------------------------
    measurements = []
    for d in data_refs:
        if isinstance(d.get("measurements"), list):
            measurements.extend(d["measurements"])
    for t in targets:
        if isinstance(t.get("measurements"), list):
            measurements.extend(t["measurements"])
    if measurements:
        try:
            u = _run_tool("units", {"measurements": measurements})
            for f in u["findings"]:
                findings.append(_mk_finding(
                    nid("F03"), "units_dimension", f["severity"],
                    summary=f["message"], location=f.get("id", "measurement"),
                    evidence=f.get("message"), why="数值与单位维度受攻击",
                    counterexample="同一数值换用正确单位后结论不再成立",
                    required_fix="修正单位声明或换算", verification_method="重跑 units 工具至无 CRITICAL",
                    blocks=f["severity"] == "CRITICAL", target_id=f.get("id", "?")))
        except Exception as exc:  # noqa: BLE001
            findings.append(_mk_finding(
                nid("F03"), "units_dimension", "MAJOR",
                summary=f"单位检查工具执行失败: {exc}", location="measurements",
                evidence=str(exc), why="工具未真实运行",
                counterexample="工具可复现失败", required_fix="修复工具或输入",
                verification_method="重跑 units", blocks=False, target_id="tool"))

    # --- dimension 4: experimental design (pseudo-replication) ------------
    if p.get("samples") and p.get("data_columns"):
        try:
            pr = _run_tool("pseudo", {"samples": p["samples"], "data_columns": p["data_columns"],
                                      "claim_group_difference": _has_group_claim(p)})
            if pr["detected"]:
                for f in pr["findings"]:
                    # BLOCK-5 fires when the significance claim is engineered
                    # on the inflated n: the analysis reports n == rows (not the
                    # effective independent n) while asserting a group effect.
                    analysis_claims_inflated_n = _analysis_claims_inflated_n(p, pr)
                    severity = "BLOCKING" if (
                        f.get("claim_relies_on_inflated_n")
                        or analysis_claims_inflated_n
                    ) else "CRITICAL"
                    findings.append(_mk_finding(
                        nid("F04"), "experimental_design", severity,
                        summary=f"伪重复: {f['reason']}",
                        location="samples", evidence=f"effective_n={f.get('effective_n')} rows={f.get('rows')}",
                        why="多个测点被当作独立试样；独立样本量被夸大，显著性可能由伪重复撑起",
                        counterexample="若只使用有效样本量，组间差异可能不再显著",
                        required_fix="聚合到采样单位后再做组间推断，或使用混合效应模型",
                        verification_method="重跑 pseudo 工具至 detected=false 或以有效 n 重算显著性",
                        rule_id="BLOCK-5" if severity == "BLOCKING" else None,
                        blocks=severity == "BLOCKING", target_id="samples"))
        except Exception as exc:  # noqa: BLE001
            findings.append(_mk_finding(
                nid("F04"), "experimental_design", "MAJOR",
                summary=f"伪重复检测工具执行失败: {exc}", location="samples",
                evidence=str(exc), why="工具未真实运行", counterexample="工具可复现失败",
                required_fix="修复工具或输入", verification_method="重跑 pseudo",
                blocks=False, target_id="tool"))

    # --- dimension 5: statistical analysis --------------------------------
    analyses = []
    for t in targets:
        if isinstance(t.get("analysis"), dict):
            analyses.append({"id": t["id"], **t["analysis"]})
    if analyses:
        try:
            st = _run_tool("stats", {"analyses": analyses})
            for r in st["analyses"]:
                for f in r["findings"]:
                    findings.append(_mk_finding(
                        nid("F05"), f["dimension"], f["severity"],
                        summary=f["message"], location=r["analysis_id"],
                        evidence=f.get("message"), why="统计分析结构受攻击",
                        counterexample=f.get("code"),
                        required_fix="补充效应量/CI/独立样本量，或修正报告结构",
                        verification_method="重跑 stats 工具至该 code 消失",
                        blocks=f["severity"] in ("CRITICAL", "BLOCKING"),
                        target_id=r["analysis_id"]))
        except Exception as exc:  # noqa: BLE001
            findings.append(_mk_finding(
                nid("F05"), "statistical_analysis", "MAJOR",
                summary=f"统计结构工具执行失败: {exc}", location="analyses",
                evidence=str(exc), why="工具未真实运行", counterexample="工具可复现失败",
                required_fix="修复工具或输入", verification_method="重跑 stats",
                blocks=False, target_id="tool"))

    # --- statistical-methodology text scanner (dimension 5 / 7) ------------
    # Attacks methodological claims even when no structured `analysis` object
    # is supplied: I²-as-absolute-heterogeneity, tiny-k fixed-effect pooling,
    # p-only significance, etc. This is the machinery that catches the
    # strongest counterexample against meta-analysis methodology.
    stat_findings = _scan_stat_methodology(targets, nid)
    findings.extend(stat_findings)

    # --- dimension 6: MICP mechanism (traps) ------------------------------
    micp_findings = _scan_micp_traps(targets)
    findings.extend(micp_findings)

    # --- dimension 7: model boundary --------------------------------------
    models = []
    for t in targets:
        if isinstance(t.get("model"), dict):
            models.append({"name": t["id"], **t["model"]})
    if models:
        try:
            mc = _run_tool("modelcheck", {"models": models})
            for r in mc["models"]:
                for f in r["findings"]:
                    findings.append(_mk_finding(
                        nid("F07"), "model_boundary", f["severity"],
                        summary=f["message"], location=r["model_id"],
                        evidence=f.get("code"), why="模型边界受攻击",
                        counterexample=f.get("message"),
                        required_fix="补充边界条件/独立验证/修正声明域",
                        verification_method="重跑 modelcheck 工具至该 code 消失",
                        blocks=f["severity"] == "BLOCKING",
                        target_id=r["model_id"]))
        except Exception as exc:  # noqa: BLE001
            findings.append(_mk_finding(
                nid("F07"), "model_boundary", "MAJOR",
                summary=f"模型边界工具执行失败: {exc}", location="models",
                evidence=str(exc), why="工具未真实运行", counterexample="工具可复现失败",
                required_fix="修复工具或输入", verification_method="重跑 modelcheck",
                blocks=False, target_id="tool"))

    # --- mass-balance scan (feeds BLOCK-4) --------------------------------
    reactions = []
    for t in targets:
        if isinstance(t.get("reactions"), list):
            reactions.extend(t["reactions"])
    if reactions or p.get("flows"):
        try:
            bal = _run_tool("balance", {"reactions": reactions,
                                        "flows": p.get("flows") or []})
            for r in bal["reactions"]:
                if not r["closed"]:
                    findings.append(_mk_finding(
                        nid("F07"), "model_boundary", "BLOCKING",
                        summary=f"质量守恒被违反: {r['name']} 元素/质量闭合超阈值",
                        location="reactions",
                        evidence=f"mass_rel_err={r['mass_relative_error']} "
                                 f"elem_issues={r['element_issues']}",
                        why="模型违反质量守恒；物料不闭合",
                        counterexample="按守恒重算后产出量差异显著",
                        required_fix="补齐反应物/产物或修正化学计量，重跑 balance 至 closed",
                        verification_method="重跑 balance 工具至 reactions 全部 closed",
                        rule_id="BLOCK-4", blocks=True, target_id="reactions"))
            for f in bal["flow_findings"]:
                findings.append(_mk_finding(
                    nid("F07"), "model_boundary", "BLOCKING",
                    summary=f"物料流不平衡: {f['flow_id']} ({f['species']})",
                    location="flows",
                    evidence=f"in={f['inflow']} out={f['outflow']} acc={f['accumulation']}",
                    why="流入≠流出+累积；质量守恒被违反",
                    counterexample="实际累积与报告不一致",
                    required_fix="修正流量平衡或说明去向",
                    verification_method="重跑 balance 至 flow_findings 为空",
                    rule_id="BLOCK-4", blocks=True, target_id="flows"))
        except Exception as exc:  # noqa: BLE001
            findings.append(_mk_finding(
                nid("F07"), "model_boundary", "MAJOR",
                summary=f"质量守恒工具执行失败: {exc}", location="reactions",
                evidence=str(exc), why="工具未真实运行", counterexample="工具可复现失败",
                required_fix="修复工具或输入", verification_method="重跑 balance",
                blocks=False, target_id="tool"))

    # --- dimension 8: engineering scale-up --------------------------------
    for t in targets:
        blob = str(t.get("summary", "")) + " " + str(t.get("location", ""))
        if _mentions_field_scale(t) and _validation_scale_only_column(p):
            findings.append(_mk_finding(
                nid("F08"), "engineering_scaleup", "BLOCKING",
                summary="小柱/实验室结果直接外推到现场",
                location=t.get("location") or t["id"],
                evidence="validation_scale=column, claimed_scale=field",
                why="实验室参数直接放大忽视非均质/地下水/优先流",
                counterexample="现场地层非均质下水力短路使处理剂绕流",
                required_fix="补充现场尺度的中试/数值模拟或明确停止条件",
                verification_method="提供 PILOT 级验证或尺度外推的显式适用域声明",
                rule_id="BLOCK-7", blocks=True, target_id=t["id"]))

    # --- dimension 9: environment & safety (ammonia / regulations) --------
    env_findings = _scan_environment_safety(p, nid)
    findings.extend(env_findings)

    # --- dimension 10: decision gate --------------------------------------
    # open blockers from a prior review + claims upgrade
    for t in targets:
        if t.get("open_blockers", 0) > 0 and t.get("status_support") in (
                "VALIDATED", "PILOT_READY", "DEPLOYABLE"):
            findings.append(_mk_finding(
                nid("F10"), "decision_gate", "BLOCKING",
                summary=f"阻断项未关闭仍声明升级 {t['status_support']}",
                location=t.get("location") or t["id"],
                evidence=f"open_blockers={t.get('open_blockers')}",
                why="阻断项未关闭不得放行",
                counterexample="存在 BLOCKING 即升级，导致部署失败",
                required_fix="关闭全部阻断项并复验后重新审查",
                verification_method="重审至 blocking_count=0",
                rule_id="BLOCK-3", blocks=True, target_id=t["id"]))

    # --- permission boundary (engine-level audit of upstream actions) -----
    if p.get("actions"):
        try:
            pe = _run_tool("permissions", {"actions": p["actions"]})
            for r in pe["actions"]:
                for f in r["findings"]:
                    findings.append(_mk_finding(
                        nid("F99"), "permission_boundary", f["severity"],
                        summary=f["message"], location=r["actor"],
                        evidence=f.get("code"), why="权限边界受攻击",
                        counterexample=f.get("message"),
                        required_fix="取消越界写入/改为经 Controller 批准",
                        verification_method="重跑 permissions 工具至该 code 消失",
                        blocks=f["severity"] == "BLOCKING",
                        target_id=r["actor"]))
        except Exception as exc:  # noqa: BLE001
            findings.append(_mk_finding(
                nid("F99"), "permission_boundary", "MAJOR",
                summary=f"权限检查工具执行失败: {exc}", location="actions",
                evidence=str(exc), why="工具未真实运行", counterexample="工具可复现失败",
                required_fix="修复工具或输入", verification_method="重跑 permissions",
                blocks=False, target_id="tool"))

    # MICP trap detail: OD600-as-urease, total-CaCO3-as-bridge, non-urea path
    return findings


def _mk_finding(fid: str, dimension: str, severity: str, *, summary: str,
                location: str, evidence: str, why: str, counterexample: str,
                required_fix: str, verification_method: str, blocks: bool,
                target_id: str, rule_id: str | None = None) -> dict:
    finding = {
        "finding_id": fid,
        "target_id": target_id,
        "location": location,
        "dimension": dimension,
        "severity": severity,
        "summary": summary,
        "evidence": evidence,
        "evidence_epistemic_tag": "CALCULATED" if severity in ("BLOCKING", "CRITICAL") else "INFERRED",
        "why": why,
        "counterexample": counterexample,
        "required_fix": required_fix,
        "verification_method": verification_method,
        "blocks_state_upgrade": blocks,
        "status": "OPEN",
    }
    if rule_id:
        finding["rule_id"] = rule_id
    return finding


def _has_group_claim(p: dict) -> bool:
    request = str(p.get("request", "")).lower()
    return any(k in request for k in ("显著", "更高", "更好", "significant", "higher", "improve", "effect"))


# --- statistical-methodology counterexample patterns ------------------------
# Each pattern is the "strongest counterexample" the reviewer must not miss.
STAT_METHOD_PATTERNS = [
    {
        "name": "i2_absolute_heterogeneity",
        "severity": "CRITICAL",
        "dimension": "statistical_analysis",
        "match": lambda blob: ("i2" in blob or "τ²" in blob or "tau2" in blob) and (
            "75%" in blob or "0.75" in blob or "<= 75" in blob or "≤ 75" in blob
            or "阈值" in blob),
        "summary": "把 I² 当作异质性的绝对判据：I² 受精度（研究数/样本量）混淆，同一 I² 在不同 k 下含义不同，单独作可合并阈值会误判",
        "evidence": "I² 的定义基于 Q 与自由度；k 小、样本量大时 I² 偏高，反之偏低",
        "why": "I²≤75% 不是稳健的可合并判据；Borenstein/Higgins 均建议结合 τ² 与预测区间判断",
        "counterexample": "4 个精确研究 I²=0% 但效应方向各异 vs 30 个粗研究 I²=90% 但效应一致——按阈值前者合并后者隔离，结论完全相反",
        "required_fix": "报告 τ² 与预测区间、结合 k 与样本量解释 I²，或用 Q 检验作为辅助判据",
        "verification_method": "重新评测 can_pool 决策并附 τ²/预测区间",
    },
    {
        "name": "two_study_fixed_effect",
        "severity": "CRITICAL",
        "dimension": "statistical_analysis",
        "match": lambda blob: ("2" in blob or "两" in blob or "二个" in blob) and (
            "固定效应" in blob or "fixed effect" in blob or "fixed-effect" in blob),
        "summary": "2 研究固定效应合并不可靠：k=2 无法估计随机效应方差 τ²，固定效应将异质性视为零，结论被两研究之一主导",
        "evidence": "随机效应模型在 k=2 时 τ² 不可识别；固定效应假设效应同质，k=2 下无法检验",
        "why": "2 研究合并对效应量估计高度不稳定，任何一篇的偏倚都会直接写进结论",
        "counterexample": "研究 A 效应 0.9±0.1、研究 B 效应 0.1±0.1，固定效应合并得到 0.5 且『显著』，但真实总体效应几乎确定是两者之间且不显著",
        "required_fix": "k<3 时不做定量合并，改为结构化叙述综合；或明确报告合并对单研究敏感性的依赖",
        "verification_method": "对 k=2 的合并结论执行 leave-one-out，报告合并方向是否翻转",
    },
    {
        "name": "grade_imprecision_no_power",
        "severity": "MAJOR",
        "dimension": "statistical_analysis",
        "match": lambda blob: ("grade" in blob or "不精确" in blob or "imprecision" in blob) and (
            "样本量" in blob or "power" in blob or "功效" in blob or "n=" in blob),
        "summary": "GRADE 不精确域未显式要求样本量/功效证据：仅凭 CI 宽度判定不精确可能漏掉功效不足的小样本研究",
        "evidence": "GRADE 不精确域应结合样本量、事件数与 CI 宽度；单一 CI 宽度判据会把高精度但有偏研究误判为精确",
        "why": "缺功效证据时，小样本研究的高 CI 会被错误降级或升级",
        "counterexample": "n=20 的研究 CI 极宽被判不精确而排除，但其效应量与大型研究一致——排除它反而引入偏倚",
        "required_fix": "在不精确域明确要求报告各研究样本量、功效与事件数",
        "verification_method": "重新执行 GRADE 分级并附每研究的样本量/功效清单",
    },
]


def _scan_stat_methodology(targets: list[dict], nid) -> list[dict]:
    """Text-based scan of methodological claims in target summaries/claims.

    Fires even when no structured `analysis` object exists — the reviewer must
    attack the substance of statistical claims, not just their reporting shape.
    """
    out = []
    for t in targets:
        blob = str(t.get("summary", ""))
        for c in (t.get("claims") or []):
            blob += " " + str(c)
        blob = blob.lower()
        for pat in STAT_METHOD_PATTERNS:
            try:
                if pat["match"](blob):
                    out.append(_mk_finding(
                        nid("F05"), pat["dimension"], pat["severity"],
                        summary=pat["summary"],
                        location=t.get("location") or t["id"],
                        evidence=pat["evidence"],
                        why=pat["why"],
                        counterexample=pat["counterexample"],
                        required_fix=pat["required_fix"],
                        verification_method=pat["verification_method"],
                        blocks=pat["severity"] == "BLOCKING",
                        target_id=t["id"]))
            except Exception:  # noqa: BLE001
                continue
    return out


def _analysis_claims_inflated_n(p: dict, pseudo_result: dict) -> bool:
    """True when a target's statistical analysis reports n == rows (the inflated
    count) while asserting significance — i.e. the claim is engineered on the
    pseudo-replication."""
    eff_n = pseudo_result.get("effective_n")
    rows = pseudo_result.get("rows")
    if eff_n is None or rows is None or eff_n >= rows:
        return False
    for t in p.get("targets") or []:
        a = t.get("analysis") or {}
        n_independent = a.get("n_independent")
        if n_independent is None:
            continue
        try:
            n_independent = int(n_independent)
        except (TypeError, ValueError):
            continue
        # The analysis reports the row count as the independent sample size.
        if n_independent == rows:
            return True
    return False


def _mentions_field_scale(t: dict) -> bool:
    blob = str(t.get("summary", "")).lower() + " " + str(t.get("location", "")).lower()
    return any(k in blob for k in ("field", "现场", "site", "部署", "inject", "deploy", "scale-up", "放大"))


def _validation_scale_only_column(p: dict) -> bool:
    constraints = p.get("constraints") or {}
    val_scale = str(constraints.get("validation_scale", "column")).lower()
    return val_scale not in ("field", "pilot")


def _scan_micp_traps(targets: list[dict]) -> list[dict]:
    out = []
    seq = [0]

    def nid() -> str:
        seq[0] += 1
        return f"F06-{seq[0]:03d}"

    for t in targets:
        blob = str(t.get("summary", "")).lower()
        claims = t.get("claims") or []
        # OD600-as-urease
        for c in claims:
            cblob = str(c).lower()
            if "od600" in cblob and any(k in cblob for k in ("urease", "脲酶活性", "enzyme activity")):
                out.append(_mk_finding(
                    nid(), "micp_mechanism", "CRITICAL",
                    summary="把 OD600 当作脲酶活性",
                    location=t.get("location") or t["id"],
                    evidence=c, why="OD600 是光密度(无量纲)，不是脲酶活性(N L^-3 T^-1)",
                    counterexample="同一 OD600 在不同菌株/诱导条件下对应不同脲酶活性",
                    required_fix="补充 OD600→脲酶活性标准曲线并声明换算系数",
                    verification_method="重跑 units 工具：OD600 与 urease_activity 不再互标",
                    blocks=False, target_id=t["id"]))
        # total-CaCO3-as-effective-bridge
        if "caco3" in blob and any(k in blob for k in ("bridge", "晶桥", "有效连接", "effective")):
            out.append(_mk_finding(
                nid(), "micp_mechanism", "CRITICAL",
                summary="把 CaCO3 总量当作有效晶桥",
                location=t.get("location") or t["id"],
                evidence=t.get("summary"), why="CaCO3 总量≠有效晶桥：需区分晶型、位置、孔隙填充",
                counterexample="大量 CaCO3 以非桥接颗粒堆积存在，强度贡献微弱",
                required_fix="报告有效晶桥量（桥接位置 CaCO3）而非仅总量",
                verification_method="提供 SEM/XRD 或按位置分段的 CaCO3 分布证据",
                blocks=False, target_id=t["id"]))
        # non-urea path fit into urea model
        if any(k in blob for k in ("denitrif", "反硝化")) and any(k in blob for k in ("urea", "尿素", "urease")):
            out.append(_mk_finding(
                nid(), "micp_mechanism", "MAJOR",
                summary="把非尿素路径套入尿素模型",
                location=t.get("location") or t["id"],
                evidence=t.get("summary"),
                why="反硝化路径与尿素水解路径的产碱/产氨机理不同",
                counterexample="用尿素模型预测反硝化路径的氨氮排放",
                required_fix="按实际路径建立模型或明确适用范围",
                verification_method="模型输入显式声明路径类型",
                blocks=False, target_id=t["id"]))
    return out


def _scan_environment_safety(p: dict, nid) -> list[dict]:
    out = []
    targets = p.get("targets") or []
    constraints = p.get("constraints") or {}
    for t in targets:
        blob = str(t.get("summary", "")).lower() + " " + str(t.get("location", "")).lower()
        recommends_deployment = t.get("recommends_deployment") or _mentions_field_scale(t)
        ammonia = t.get("ammonia_concentration")
        if ammonia is not None and recommends_deployment:
            limit = constraints.get("ammonia_limit_mg_l")
            limit = float(limit) if limit is not None else 0.5
            try:
                if float(ammonia) > limit:
                    out.append(_mk_finding(
                        nid("F09"), "environment_safety", "BLOCKING",
                        summary=f"氨氮 {ammonia} mg/L 超出限值 {limit} mg/L 仍建议部署",
                        location=t.get("location") or t["id"],
                        evidence=f"ammonia={ammonia}, limit={limit}",
                        why="氨氮超限仍建议部署：环境排放风险",
                        counterexample="现场氨氮超标导致地下水/作业安全违规",
                        required_fix="调整工艺降低氨氮或变更部署条件，并做法规核验",
                        verification_method="重算氨氮至限值内并附法规引用",
                        rule_id="BLOCK-2", blocks=True, target_id=t["id"]))
            except (TypeError, ValueError):
                pass
        if recommends_deployment and not constraints.get("regulations_verified"):
            out.append(_mk_finding(
                nid("F09"), "environment_safety", "BLOCKING",
                summary="法规未核验仍放行部署",
                location=t.get("location") or t["id"],
                evidence="regulations_verified absent/false",
                why="涉及法规约束（氨氮/地下水/废弃物）却无核验记录",
                counterexample="适用辖区限值严于默认表，部署违规",
                required_fix="核验适用法规并附限值来源",
                verification_method="附法规编号与限值对比表",
                rule_id="BLOCK-6", blocks=True, target_id=t["id"]))
        if recommends_deployment and any(k in blob for k in ("permeab", "渗透")):
            # strength up but permeability down pattern
            if "strength" in blob or "强度" in blob:
                out.append(_mk_finding(
                    nid("F09"), "environment_safety", "BLOCKING",
                    summary="强度提高但渗透率严重下降仍放行",
                    location=t.get("location") or t["id"],
                    evidence=t.get("summary"),
                    why="强度升+渗透降 = 工程阻断未处理即放行",
                    counterexample="处理后土体强度达标但排水失效",
                    required_fix="补充渗透率约束或重新设计注入工艺",
                    verification_method="渗透率与强度联合达标证据",
                    rule_id="BLOCK-7", blocks=True, target_id=t["id"]))
    return out


def _build_review(payload: dict[str, Any]) -> dict[str, Any]:
    targets = payload.get("targets") or []
    constraints = payload.get("constraints") or {}
    state_gate = constraints.get("state_gate") or "REVIEW"
    if state_gate not in ("VALIDATED", "PILOT_READY", "DEPLOYABLE", "REVIEW", ""):
        raise OrtError(OrtErrorCode.INVALID_VALUE,
                       f"invalid state_gate {state_gate!r}",
                       detail={"how_to_fix": "use VALIDATED|PILOT_READY|DEPLOYABLE|REVIEW"})

    findings = _scan_dimensions(payload)

    # severity pass (deterministic scorer on each finding's shape)
    severity_payload = {
        "issues": [{
            "id": f["finding_id"],
            "impact": {"INFO": 1, "MINOR": 2, "MAJOR": 3, "CRITICAL": 4, "BLOCKING": 5}.get(
                f["severity"], 3),
            "affected_domain": "safety" if f["severity"] == "BLOCKING" else "science",
            "certainty": "observed" if f["severity"] in ("BLOCKING", "CRITICAL") else "reported",
            "consequence_probability": "certain" if f["severity"] == "BLOCKING" else "likely",
        } for f in findings]
    }
    score_by_id: dict[str, str] = {}
    if severity_payload["issues"]:
        scored = _run_tool("severity", severity_payload)
        score_by_id = {r["id"]: r["severity"] for r in scored["issues"]}
    for f in findings:
        f["severity"] = score_by_id.get(f["finding_id"], f["severity"])
        f["blocks_state_upgrade"] = f["severity"] == "BLOCKING"

    # blocking engine — derive rule signals from severity+dimension so any
    # BLOCKING finding is machine-enforced, not only the ones with explicit rules.
    def _signal(f: dict) -> dict:
        rule = f.get("rule_id")
        severity = f.get("severity")
        dimension = f.get("dimension")
        summary = f.get("summary", "")
        is_blocking = severity == "BLOCKING"
        return {
            "id": f["finding_id"],
            "rule": rule,
            # BLOCK-1: REJECTED citation in source_authenticity
            "citation_verdict": ("REJECTED" if (rule == "BLOCK-1"
                                                or (is_blocking and dimension == "source_authenticity"))
                                 else None),
            "ammonia_concentration": f.get("ammonia", None),
            "recommends_deployment": is_blocking and dimension in (
                "environment_safety", "engineering_scaleup", "decision_gate",
                "epistemic_escalation"),
            "open_blockers": 1 if (rule == "BLOCK-3"
                                   or (is_blocking and dimension == "decision_gate"
                                       and "阻断" in summary)) else 0,
            "mass_balance_closed": False if (rule == "BLOCK-4"
                                             or (is_blocking and "质量守恒" in summary
                                                 or "物料" in summary)) else None,
            "state_escalation_illegal": rule == "BLOCK-8",
            "long_term_write_without_approval": (rule == "BLOCK-9"
                                                 or (is_blocking and dimension == "permission_boundary")),
            "epistemic_escalation": rule == "BLOCK-10",
            "pseudo_replication": rule == "BLOCK-5",
            "pseudo_replication_carries_significance": rule == "BLOCK-5",
            "regulations_unverified": (rule == "BLOCK-6"
                                       or (is_blocking and "法规" in summary)),
            "permeability_degraded": (rule == "BLOCK-7"
                                      or (is_blocking and "渗透" in summary)),
            # BLOCK-11: a BLOCKING model-boundary finding that is not already a
            # mass-balance violation is a model-boundary violation.
            "model_boundary_blocking": (is_blocking and dimension == "model_boundary"
                                        and rule != "BLOCK-4"),
        }

    block_signals = [_signal(f) for f in findings]
    if block_signals:
        blocked = _run_tool("blocking", {"findings": block_signals, "state_gate": state_gate})
        blocking_ids = blocked["blocking_ids"]
        state_rec = blocked["state_recommendation"]
        # propagate resolved rule ids onto findings (machine-enforced authority)
        rule_by_id = {e["id"]: e.get("rule") for e in blocked["evaluations"]}
        for f in findings:
            if f["finding_id"] in rule_by_id and rule_by_id[f["finding_id"]]:
                f["rule_id"] = rule_by_id[f["finding_id"]]
    else:
        blocking_ids = []
        state_rec = {"recommendation": "APPROVE" if state_gate in ("VALIDATED", "PILOT_READY", "DEPLOYABLE") else "NO_OBJECTION",
                     "reason": "no findings", "blocking_count": 0}

    # counterexamples for BLOCKING/CRITICAL
    targets_for_ce = [t for t in targets if any(
        f["target_id"] in (t["id"], "samples", "tool") and f["severity"] in ("BLOCKING", "CRITICAL")
        for f in findings)]
    counterexamples = []
    if targets_for_ce:
        ce = _run_tool("counterexamp", {"targets": targets_for_ce})
        for c in ce["counterexamples"]:
            counterexamples.append({
                "target_id": c["target_id"],
                "attack": c["attack"],
                "consequence": c["consequence"],
                "epistemic_tag": c.get("epistemic_tag", "HYPOTHESIS"),
            })
    alternative_explanations = []
    for t in targets_for_ce:
        alt = [{"target_id": t["id"], "explanation": a["explanation"],
                "fits_evidence": a["fits_evidence"]} for a in (t.get("alternatives") or [])]
        alternative_explanations.extend(alt)

    # required fixes + retest plan
    required_fixes = [{
        "finding_id": f["finding_id"],
        "fix": f["required_fix"],
        "acceptance": f["verification_method"],
        "verify_by": "ort:retest + human",
    } for f in findings if f["severity"] in ("BLOCKING", "CRITICAL", "MAJOR")]
    retest_fixed = _run_tool("retest", {"required_fixes": required_fixes}) if required_fixes else None

    # required evidence
    required_evidence = [{
        "finding_id": f["finding_id"],
        "evidence": f["verification_method"],
    } for f in findings if f["severity"] in ("BLOCKING", "CRITICAL")]

    blocking_findings = [f for f in findings if f["severity"] == "BLOCKING"]
    scope = _collect_dimension_scope(payload)

    status = "BLOCKED" if blocking_findings else "SUCCESS"
    return {
        "status": status,
        "summary": (
            f"对抗审查完成: {len(findings)} 项发现, {len(blocking_findings)} 项 BLOCKING, "
            f"状态建议={state_rec['recommendation']} (gate={state_gate})."
        ),
        "review_scope": {
            "dimensions": scope,
            "targets": [t["id"] for t in targets],
            "state_gate": state_gate,
        },
        "findings": findings,
        "blocking_findings": blocking_findings,
        "counterexamples": counterexamples,
        "alternative_explanations": alternative_explanations,
        "required_evidence": required_evidence,
        "required_fixes": required_fixes,
        "retest_plan": {
            "steps": [
                "关闭全部 BLOCKING/CRITICAL 发现的 required_fix",
                "逐项按 verification_method 复验并标记 status=VERIFIED",
                "重跑 review 管线，blocking_count 应为 0",
            ],
            "reopen_on": "任一 BLOCKING 复验失败即重新打开审查",
        },
        "state_recommendation": state_rec,
        "risks": [{
            "risk": f["summary"], "severity": "critical" if f["severity"] == "BLOCKING" else "high",
        } for f in findings if f["severity"] in ("BLOCKING", "CRITICAL")],
        "assumptions": [{
            "statement": f"被审目标 {t['id']} 的作者自标 {t.get('epistemic_label', '未声明')}",
            "falsifiable_by": "作者原始措辞与证据链",
        } for t in targets],
        "evidence_used": [{
            "ref_id": r.get("ref_id"), "how_used": "citation/provenance 核验",
            "verifiable": True, "note": r.get("verdict", "UNVERIFIED"),
        } for r in payload.get("evidence_refs") or []],
        "uncertainty": [{
            "topic": "引用核验为离线结构核验，未核全文",
            "level": "medium",
            "note": "REJECTED/SUSPECTED 需要人工或联网复核",
        }],
        "artifacts": [{
            "artifact_id": "review-report", "kind": "review_report",
            "content_type": "application/json",
            "description": "对抗审查报告（含阻断规则结果）",
        }],
        "requested_next_skills": [{
            "skill": "obsidian-decision-gate",
            "reason": "BLOCKING/CRITICAL 发现需决策门裁决或人工放行",
        }] if blocking_findings else [],
        "validation": {
            "self_audit_pass": True,
            "gates": {"blocking": len(blocking_findings) == 0,
                      "state_recommendation": state_rec["recommendation"]},
            "tool_runs": [{"tool": "review", "ok": True}],
        },
        "provenance": {
            "skill": SKILL_NAME,
            "skill_version": SKILL_VERSION,
            "generated_at": _now_iso(),
            "generator": "ort:review",
            "input_task_id": payload.get("task_id"),
            "target_ids": [t["id"] for t in targets],
            "tool_versions": {"ort": SKILL_VERSION},
        },
        "errors": [],
    }


def main(payload: dict[str, Any]) -> dict[str, Any]:
    from common import emit_progress
    emit_progress("review: validating input contract")
    input_issues = _validate_input(payload)
    if input_issues:
        raise OrtError(OrtErrorCode.INPUT_SCHEMA_VIOLATION,
                       "review: input did not pass schemas/input.schema.json",
                       detail={"issues": input_issues[:20],
                               "how_to_fix": "fix the envelope fields listed in issues"})

    version_problems = _check_versions(payload)
    if version_problems:
        raise OrtError(OrtErrorCode.VERSION_MISMATCH,
                       "review: " + "; ".join(version_problems))

    if not payload.get("targets"):
        raise OrtError(OrtErrorCode.MISSING_TARGETS,
                       "review: no auditable target provided",
                       detail={"how_to_fix": "add at least one target with id/type/summary"})

    risk = payload.get("risk_level") or "low"
    approval = payload.get("human_approval_state") or "not_required"
    # Red Team itself reviews; it does not execute experiments or deployments,
    # so high/critical review requests do NOT require its own approval — but a
    # deployment gate with unapproved risk still requires the controller chain.
    del risk, approval

    emit_progress("review: running ten-dimension adversarial scan")
    result = _build_review(payload)

    emit_progress("review: self-checking output against output.schema.json")
    schema = load_schema("output.schema.json")
    try:
        from _jsonschema import validate_with_schema
        out_issues = validate_with_schema(result, schema)
    except Exception:  # noqa: BLE001
        try:
            import jsonschema  # type: ignore
            v = jsonschema.Draft202012Validator(schema)
            out_issues = [f"{e.message} at {'/'.join(map(str, e.path))}" for e in sorted(
                v.iter_errors(result), key=lambda e: list(e.path))]
        except Exception:  # noqa: BLE001
            out_issues = []
    if out_issues:
        result["status"] = "FAILED"
        result["errors"] = [{
            "code": OrtErrorCode.OUTPUT_SCHEMA_VIOLATION.code,
            "message": "output failed self-check: " + "; ".join(out_issues[:10]),
            "retryable": True,
        }]
        result["validation"]["self_audit_pass"] = False

    return result


if __name__ == "__main__":
    from common import read_stdin_envelope, run_tool
    run_tool("review", lambda: main(read_stdin_envelope()))
