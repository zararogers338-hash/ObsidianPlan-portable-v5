"""Service layer: dispatch a validated input envelope to an action handler and
assemble the unified output envelope (contract_version 1.0).

Pipeline per invocation:
  1. contract_version major gate (2.x -> OMM-E501)
  2. input schema validation (missing fields -> BLOCKED + guidance)
  3. evidence/data ref resolution gate (verify_refs)
  4. action dispatch to a pure handler
  5. output schema validation + self-check (audit_envelope)
  6. envelope downgrade: self-check failure on SUCCESS -> FAILED

All handlers are pure (no I/O) except optional audit-log persistence, which is
guarded by dry_run + human_approval_state (spec §七: field deployment / long-
term knowledge write requires approval).
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any

from .errors import OmError, make_error
from .models import CONTRACT_VERSION, SKILL_NAME, SKILL_VERSION
from .validate import ValidationIssue, load_schema, validate

# action -> handler table (kept here so SKILL.md and code stay in sync)
from . import xrd, sem, spectra, fuse, hashcheck, report as report_mod
from . import audit as audit_mod


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _minimal_failure_envelope(message: str) -> dict[str, Any]:
    """A BLOCKED/FAILED envelope that still passes the output schema."""
    return {
        "contract_version": CONTRACT_VERSION,
        "skill": SKILL_NAME,
        "skill_version": SKILL_VERSION,
        "status": "BLOCKED",
        "summary": message,
        "action": None,
        "project_id": None,
        "task_id": None,
        "findings": [],
        "assumptions": [],
        "evidence_used": [],
        "uncertainty": [],
        "risks": [],
        "artifacts": [],
        "requested_next_skills": [],
        "results": {},
        "candidate_phases": [],
        "confirmed_phases": [],
        "rejected_phases": [],
        "unexplained_features": [],
        "morphology": {},
        "spatial_distribution": {},
        "bridge_evidence": {},
        "validation": {
            "input_schema": "failed",
            "output_schema": "pending",
            "self_check": "not_run",
            "checks": [],
        },
        "provenance": {
            "started_at": None,
            "completed_at": None,
            "skill_version": SKILL_VERSION,
            "sources": ["references/sources.md"],
            "audit_log": None,
        },
        "errors": [
            make_error("OMM-E101", message).to_dict(),
        ],
    }


class MissingFieldGuidance:
    """Guidance for each required input field (spec §十一: 不得以"信息不足"结束)."""

    REQUIRED = {
        "contract_version": "输入契约版本;由控制器注入,与本 Skill 主版本匹配",
        "task_id": "任务节点标识;由 Task Decomposer 分配,用于决策日志锚点与预算记账",
        "project_id": "项目/实验标识;来自项目注册,用于审计与版本隔离",
        "request": "表征任务的自然语言描述;由 Mission Lock 产生的任务合同提供",
        "action": "要执行的动作(interpret.phases / tools.*);由控制器或本 Skill 解析",
        "skill_version": "本 Skill 版本;由 SKILL.md frontmatter 声明,控制器注入",
        "timestamp": "ISO 8601 时间戳;由控制器调用时注入",
    }


def _build_blocked(envelope: dict[str, Any], errors: list[dict[str, Any]], summary: str) -> dict[str, Any]:
    envelope["status"] = "BLOCKED"
    envelope["errors"] = errors
    envelope["summary"] = summary
    return envelope


def handle(payload: Any, *, schema_dir: str | None = None) -> dict[str, Any]:
    """Main entry point: takes a JSON object, returns the output envelope."""
    started = _now_iso()

    # --- 1. contract_version gate ------------------------------------------
    if not isinstance(payload, dict):
        return _finalize(_minimal_failure_envelope("stdin JSON 必须是对象"), started, schema_dir)
    cv = payload.get("contract_version")
    # Contract major gate: only 1.x is supported (spec §十一 version compat).
    if isinstance(cv, str) and cv.split(".")[0] not in ("1",):
        return _finalize(_fail_contract(payload), started, schema_dir)

    # --- 2. input schema -----------------------------------------------------
    issues: list[ValidationIssue] = validate(payload, load_schema("input", schema_dir))
    if issues:
        missing = _missing_fields(issues)
        guidance = {f: MissingFieldGuidance.REQUIRED.get(f, "由控制器按统一输入契约提供") for f in missing}
        err = make_error("OMM-E101",
                         "输入未通过 input.schema.json 校验",
                         {"issues": [i.to_dict() for i in issues[:20]],
                          "missing_fields": sorted(missing),
                          "field_guidance": guidance}).to_dict()
        env = _base_envelope(payload, status="BLOCKED",
                             summary=f"输入缺少必需字段: {', '.join(sorted(missing)) or '若干字段'};"
                                     f"获取方式见 errors[0].detail.field_guidance")
        env["errors"] = [err]
        return _finalize(env, started, schema_dir)

    # --- 3. evidence/data ref gate ------------------------------------------
    env = _base_envelope(payload, status="SUCCESS", summary="")
    ref_issue = _check_refs(payload, env)
    if ref_issue:
        return _finalize(ref_issue, started, schema_dir)

    # --- 4. action dispatch --------------------------------------------------
    action = payload.get("action")
    try:
        if action == "interpret.phases":
            env = _action_interpret(payload, env)
        elif action == "tools.xrd_match":
            env = _action_xrd_match(payload, env)
        elif action == "tools.sem_stats":
            env = _action_sem_stats(payload, env)
        elif action == "tools.spectra_parse":
            env = _action_spectra_parse(payload, env)
        elif action == "tools.fuse":
            env = _action_fuse(payload, env)
        elif action == "tools.audit_image":
            env = _action_audit_image(payload, env)
        elif action == "tools.image_hash":
            env = _action_image_hash(payload, env)
        elif action == "tools.report":
            env = _action_report(payload, env)
        elif action == "tools.validate":
            env = _action_validate(payload, env)
        elif action == "tools.self_check":
            env = _action_self_check(payload, env)
        else:
            raise make_error("OMM-E101", f"未知 action: {action!r}",
                             {"allowed": ["interpret.phases", "tools.xrd_match", "tools.sem_stats",
                                          "tools.spectra_parse", "tools.fuse", "tools.audit_image",
                                          "tools.image_hash", "tools.report", "tools.validate",
                                          "tools.self_check"]})
    except OmError as exc:
        env["status"] = "FAILED"
        env["errors"] = [exc.to_dict()]
        env["summary"] = f"{exc.code}: {exc.message}"

    return _finalize(env, started, schema_dir)


def _fail_contract(payload: dict[str, Any]) -> dict[str, Any]:
    env = _base_envelope(payload, status="FAILED",
                         summary=f"contract_version {payload.get('contract_version')} 不受支持;"
                                 f"本 Skill 契约主版本为 1,旧版本输出需迁移或明确拒绝")
    env["errors"] = [make_error("OMM-E501", "不支持的 contract_version(主版本 2)", {
        "received": payload.get("contract_version"), "supported_major": 1,
    }).to_dict()]
    return env


def _missing_fields(issues: list[ValidationIssue]) -> set[str]:
    import re
    missing: set[str] = set()
    for i in issues:
        m = re.search(r'missing required property "([^"]+)"', i.message)
        if m:
            missing.add(m.group(1))
    return missing


def _check_refs(payload: dict[str, Any], env: dict[str, Any]) -> dict[str, Any] | None:
    """When verify_refs is true, evidence_refs/data_refs must point to readable
    files or resolve to inline samples. Returns an error envelope or None."""
    if payload.get("verify_refs") is False:
        return None
    missing: list[str] = []
    for ref in payload.get("evidence_refs", []) or []:
        if not os.path.isfile(ref):
            missing.append(f"evidence:{ref}")
    for ref in payload.get("data_refs", []) or []:
        if not os.path.isfile(ref):
            missing.append(f"data:{ref}")
    if missing:
        err = make_error("OMM-E102", "证据或数据引用不可读", {"unresolvable": missing[:20]}).to_dict()
        env["status"] = "BLOCKED"
        env["errors"] = [err]
        env["summary"] = f"引用不可读: {', '.join(missing[:8])};需提供可读文件或设置 verify_refs=false 以内联样本工作"
        return env
    return None


def _base_envelope(payload: dict[str, Any], *, status: str, summary: str) -> dict[str, Any]:
    return {
        "contract_version": CONTRACT_VERSION,
        "skill": SKILL_NAME,
        "skill_version": SKILL_VERSION,
        "status": status,
        "summary": summary,
        "action": payload.get("action"),
        "project_id": payload.get("project_id"),
        "task_id": payload.get("task_id"),
        "findings": [],
        "assumptions": [f"输入请求: {payload.get('request', '')[:120]}"],
        "evidence_used": [{"ref_id": r, "uri": r} for r in (payload.get("evidence_refs") or [])],
        "uncertainty": [],
        "risks": [],
        "artifacts": [],
        "requested_next_skills": [],
        "results": {},
        "candidate_phases": [],
        "confirmed_phases": [],
        "rejected_phases": [],
        "unexplained_features": [],
        "morphology": {},
        "spatial_distribution": {},
        "bridge_evidence": {},
        "validation": {"input_schema": "passed", "output_schema": "pending",
                       "self_check": "not_run", "checks": []},
        "provenance": {
            "started_at": None,
            "completed_at": None,
            "skill_version": SKILL_VERSION,
            "sources": ["references/sources.md"],
            "audit_log": None,
        },
        "errors": [],
    }


def _samples_or_none(payload: dict[str, Any]) -> list[dict[str, Any]]:
    return payload.get("samples") or []


def _thresholds(payload: dict[str, Any]) -> dict[str, Any]:
    defaults = {
        "xrd_d_spacing_tol_A": 0.03,
        "xrd_min_relative_intensity": 10.0,
        "xrd_min_peaks": 2,
        "spectra_wavenumber_tol_cm1": 8.0,
        "sem_min_particles": 30,
        "sem_contact_threshold_um": 1.0,
        "eds_ca_kev_tol": 0.15,
        "fuse_min_evidence": 2,
    }
    given = payload.get("thresholds") or {}
    return {**defaults, **given}


# ---------------------------------------------------------------------------
# action handlers
# ---------------------------------------------------------------------------

def _first_sample(payload: dict[str, Any], kind: str) -> dict[str, Any]:
    samples = _samples_or_none(payload)
    if not samples:
        raise make_error("OMM-E101", f"action 需要至少一个 samples 条目(类型 {kind})", {})
    for s in samples:
        if s.get("data_type") == kind:
            return s
    raise make_error("OMM-E101", f"未找到 {kind} 类型的样本", {"available": [s.get("data_type") for s in samples]})


def _load_xrd_series(sample: dict[str, Any]) -> tuple[Any, Any]:
    if sample.get("path"):
        raise make_error("OMM-E204", "XRD 文件路径解析未启用(本版本仅内联 values)", {"path": sample.get("path")})
    values = sample.get("values")
    if not values:
        raise make_error("OMM-E104", "XRD 样本缺少 values", {})
    two_theta, intensity = xrd.parse_twotheta_intensity(values)
    return two_theta, intensity


def _action_interpret(payload: dict[str, Any], env: dict[str, Any]) -> dict[str, Any]:
    """interpret.phases: run the full multi-modal interpretation across all
    provided samples, then fuse into per-phase confidence."""
    th = _thresholds(payload)
    samples = _samples_or_none(payload)
    if not samples:
        raise make_error("OMM-E101", "interpret.phases 需要至少一个 samples 条目", {})

    xrd_results: list[dict[str, Any]] = []
    xrd_detected_peaks: list[dict[str, float]] = []
    sem_morph: dict[str, str] = {}
    sem_stats_acc: dict[str, Any] | None = None
    spectra_evidence: dict[str, dict[str, Any]] = {}
    eds_ca: bool | None = None
    tga_co2_likely: bool | None = None

    for s in samples:
        dt = s.get("data_type")
        if dt == "xrd_twotheta_intensity" or dt == "xrd_dspacing_intensity":
            two_theta, intensity = _load_xrd_series(s)
            results = xrd.match_profile(
                two_theta, intensity,
                d_tol_A=th["xrd_d_spacing_tol_A"],
                min_relative_intensity=th["xrd_min_relative_intensity"],
                min_peaks=th["xrd_min_peaks"],
                wavelength_A=s.get("wavelength_A") or 1.540598,
            )
            xrd_results = [xrd.result_to_dict(r) for r in results]
            xrd_detected_peaks = [
                {"d_A": p.d_A, "two_theta": round(p.two_theta, 2), "intensity": round(p.intensity, 1)}
                for p in xrd.detect_peaks(two_theta, intensity)
            ]
        elif dt == "sem_image":
            # lightweight: parse any provided particles; real segmentation is
            # the audit_image action.
            if s.get("particles"):
                stats = sem.particle_stats(s["particles"],
                                           unit_scale_um_per_px=s.get("unit_scale"),
                                           particle_units=s.get("particle_units", "um"),
                                           min_particles=th["sem_min_particles"])
                env["uncertainty"].append(
                    f"SEM 形态判定基于 {stats.n} 个颗粒,样本有限;未做整体均匀性外推")
            elif s.get("sem_morphology_note"):
                pass
        elif dt == "sem_particle_list":
            stats = sem.particle_stats(s.get("particles") or [],
                                       unit_scale_um_per_px=s.get("unit_scale"),
                                       particle_units=s.get("particle_units", "um"),
                                       min_particles=th["sem_min_particles"])
            sem_stats_acc = _stats_to_dict(stats)
            if stats.n < th["sem_min_particles"]:
                env["uncertainty"].append(f"SEM 颗粒样本量 {stats.n} < 阈值 {th['sem_min_particles']},"
                                          "不宜据此外推整体均匀性")
        elif dt in ("eds_spectrum", "ftir_spectrum", "raman_spectrum", "tga_curve"):
            parsed = spectra.parse_spectrum(s)
            if parsed["modality"] == "eds":
                eds_ca = parsed.get("ca_present")
            elif parsed["modality"] == "ftir":
                for phase, ev in parsed.get("phase_evidence", {}).items():
                    spectra_evidence.setdefault(phase, {})["ftir"] = ev["matched_bands_cm1"]
            elif parsed["modality"] == "raman":
                for phase, ev in parsed.get("phase_evidence", {}).items():
                    spectra_evidence.setdefault(phase, {})["raman"] = ev["matched_bands_cm1"]
            elif parsed["modality"] == "tga":
                tga_co2_likely = parsed.get("total_mass_loss_wt_pct", 0) >= th.get("tga_co2_threshold", 40.0)

    fused = fuse.fuse_all(xrd_results=xrd_results, sem_morphology=sem_morph,
                          spectra=spectra_evidence, eds_ca=eds_ca,
                          tga_co2_likely=tga_co2_likely)
    # Flag when a single SEM image (or particle list from one image) was the
    # sole spatial evidence — the auditor's single_sem_no_homogeneity hard rule
    # reads this signal (spec §四.3, §九: 单张 SEM 不得外推整体均匀).
    single_sem = any(s.get("data_type") in ("sem_image", "sem_particle_list") for s in samples)
    env["results"] = {
        "xrd": xrd_results,
        "sem_morphology": sem_morph,
        "spectra": spectra_evidence,
        "eds_ca_present": eds_ca,
        "tga_co2_likely": tga_co2_likely,
        "fusion": fused,
        "single_sem_image_used": single_sem,
        "_has_samples": bool(samples),
    }
    # sem_stats is accumulated in the sample loop as a local; merge it into the
    # results block here (a prior setdefault-then-overwrite bug dropped it and
    # left bridge_evidence empty even with adequate particle counts).
    if sem_stats_acc is not None:
        env["results"]["sem_stats"] = sem_stats_acc

    # --- 扁平业务字段(规格 §八):四级结论严格区分 -------------------------
    # level1 含钙/碳酸盐信号 < level2 CaCO3 < level3 具体矿物相 < level4 晶桥工程贡献。
    # 只有 fused.confidence == "confirmed" 才进入 confirmed_phases;其余一律 candidate/rejected。
    phases_by_confidence = {p["phase"]: p for p in fused.get("phases", [])}

    # 跨模态冲突检测(规格 §五):当两个候选相由不同模态独立支持且置信度接近时,
    # 冲突必须显式记录,不得静默偏向其中一个。
    _record_modal_conflicts(env, fused, spectra_evidence, xrd_results)

    confirmed = [p for p in phases_by_confidence.values() if p.get("confidence") == "confirmed"]
    candidates = [p for p in phases_by_confidence.values() if p.get("confidence") in ("likely", "candidate")]
    rejected = [p for p in phases_by_confidence.values() if p.get("confidence") in ("weak",) or p.get("score", 0) <= 0.0]

    env["candidate_phases"] = [p["phase"] for p in candidates]
    env["confirmed_phases"] = [p["phase"] for p in confirmed]
    env["rejected_phases"] = [p["phase"] for p in rejected]

    # level1/level2 信号边界:EDS 检出 Ca 只到 level1,总 CaCO3 质量只到 level2。
    if eds_ca is True:
        env["findings"].append({
            "statement": "EDS 检出 Ca 信号(level1):只证明存在含钙相,不证明 CaCO3 或特定晶型",
            "label": "OBSERVED",
            "source": "EDS 谱",
        })
    if tga_co2_likely:
        env["findings"].append({
            "statement": "TGA 质量损失与碳酸盐化学计量一致(level2):支持 CaCO3 存在,不区分晶型",
            "label": "CALCULATED",
        })

    # 未解释特征:来自 XRD 未匹配峰(等级1/2之外的残余特征)。
    unexplained = _collect_unexplained(xrd_results, xrd_detected_peaks)
    if unexplained:
        env["unexplained_features"] = unexplained
        env["findings"].append({
            "statement": f"存在 {len(unexplained)} 处未归属矿物相的特征,需补充表征确认",
            "label": "INFERRED",
        })

    # 峰重叠冲突证据(spec §四.2,§边界案例#3):当同一观测峰落在两个不同
    # 晶型参考反射的容差窗内时,该反射不能判别晶型——必须显式列出,否则
    # 用户只能从候选列表自行推断冲突(对抗审查缺陷 7)。
    overlaps = _detect_reflection_overlaps(xrd_results, th["xrd_d_spacing_tol_A"])
    if overlaps:
        env["reflection_overlaps"] = overlaps
        env["findings"].append({
            "statement": f"检测到 {len(overlaps)} 处晶型参考峰重叠,相关反射不能单独判别晶型",
            "label": "HYPOTHESIS",
        })

    # 空间分布与形貌:仅当有 SEM 颗粒统计时给出,且绝不外推整体。
    sem_stats = env["results"].get("sem_stats")
    if sem_stats:
        env["spatial_distribution"] = {
            "n_particles": sem_stats["n"],
            "note": "仅覆盖观测视野内的颗粒;不得外推整个试样均匀性",
        }
        env["morphology"] = {
            "source": "sem_particle_list",
            "note": "SEM 形貌为支持性证据,晶型鉴定需 XRD/FTIR/Raman 交叉确认",
        }
        # 颗粒接触处晶桥(规格核心使命第 4 层):几何上相邻的颗粒是晶桥的
        # 候选位置。晶桥的观测与"工程贡献"是两件事:
        #   1) geometric_contacts_observed = 颗粒间距小于接触阈值(候选,INFERRED);
        #   2) engineering_contribution_claimed 恒为 False —— 矿物证据绝不替代
        #      力学验证,需要上游 micp-geotechnical-performance。
        if sem_stats["n"] < th["sem_min_particles"]:
            env["bridge_evidence"] = {
                "geometric_contacts_observed": False,
                "engineering_contribution_claimed": False,
                "note": "颗粒样本量不足,未评估接触处晶桥;晶桥→工程性能必须由力学验证(上游 geotechnical 能力)支持",
            }
        else:
            contact_ratio = _estimate_contact_ratio(samples, th.get("sem_contact_threshold_um", 1.0))
            env["bridge_evidence"] = {
                "geometric_contacts_observed": contact_ratio > 0.0,
                "contact_ratio": contact_ratio,
                "engineering_contribution_claimed": False,
                "note": (
                    "几何接触候选(INFERRED):仅说明颗粒间距接近,不代表已形成有效晶桥;"
                    "晶桥→工程性能贡献必须由力学验证(上游 geotechnical 能力)支持,矿物证据不可替代"
                ),
            }
            env["findings"].append({
                "statement": f"SEM 颗粒中约 {contact_ratio:.0%} 处于接触候选距离;晶桥有效性与工程贡献需力学验证",
                "label": "INFERRED",
            })

    winner = fused.get("winner")
    if winner:
        env["findings"].append({
            "statement": f"综合多模态证据,主导相为 {winner['phase']}(置信度 {winner['confidence']},"
                         f"score {winner['score']})",
            "label": "INFERRED" if winner["confidence"] in ("likely", "candidate") else "CALCULATED",
        })
        env["summary"] = f"主导相: {winner['phase']} ({winner['confidence']})"
        env["status"] = "SUCCESS"
    else:
        env["findings"].append({
            "statement": "多模态证据不足以确定主导相;输出候选相列表而非武断结论",
            "label": "INFERRED",
        })
        env["summary"] = "未确定主导相;详见候选相列表"
        env["status"] = "PARTIAL"
    return env


def _estimate_contact_ratio(
    samples: list[dict[str, Any]],
    contact_threshold_um: float = 1.0,
) -> float:
    """Estimate the fraction of SEM particles that have a near neighbour within
    ``contact_threshold_um`` (geometric bridge *candidate*, never proof).

    Particles are read from the first sem_particle_list sample (rows are
    [x_um, y_um, area_um2, ...] in the particle_units frame). A particle counts
    as "contact candidate" when another particle's centroid lies within
    ``contact_threshold_um``. Pure O(n^2) over the inline list — no image, no
    watershed. Returns 0.0 when no usable particle list exists.
    """
    try:
        sample = next(s for s in samples if s.get("data_type") == "sem_particle_list")
    except StopIteration:
        return 0.0
    rows = sample.get("particles") or []
    if len(rows) < 2:
        return 0.0
    pts = []
    for r in rows:
        try:
            pts.append((float(r[0]), float(r[1])))
        except (TypeError, ValueError, IndexError):
            continue
    if len(pts) < 2:
        return 0.0
    scale = sample.get("unit_scale")
    thresh = contact_threshold_um
    # convert pixel-space thresholds when the list is in px without a scale —
    # without a scale we cannot map px->um, so fall back to the raw threshold
    if sample.get("particle_units") == "px" and isinstance(scale, (int, float)) and scale > 0:
        thresh = contact_threshold_um / float(scale)
    contact = 0
    for i in range(len(pts)):
        x0, y0 = pts[i]
        for j in range(i + 1, len(pts)):
            dx = x0 - pts[j][0]
            dy = y0 - pts[j][1]
            if (dx * dx + dy * dy) ** 0.5 <= thresh:
                contact += 1
                break
    return contact / len(pts)


def _record_modal_conflicts(
    env: dict[str, Any],
    fused: dict[str, Any],
    spectra_evidence: dict[str, dict[str, Any]],
    xrd_results: list[dict[str, Any]],
) -> None:
    """Detect and surface cross-modal conflicts (spec §五).

    A conflict exists when at least two candidate phases are each supported by
    different modalities (e.g. XRD strongly calcite, FTIR diagnostic bands for
    aragonite). The tension must be written to ``uncertainty`` — never silently
    resolved in favour of one phase.
    """
    scored = [p for p in (fused.get("phases") or []) if p.get("score", 0) >= 0.3]
    if len(scored) < 2:
        return
    by_phase = {p["phase"]: p for p in scored}
    # For each phase: which modality gave it its strongest support?
    #   xrd_verdict -> the phase's XRD verdict (identified / candidate / ...)
    #   ftir_diag   -> True when the phase's FTIR match includes a polymorph-DIAGNOSTIC
    #                  band (shared carbonate bands like ~875/~1090 do NOT count —
    #                  they confirm carbonate presence but not a specific polymorph).
    xrd_by_phase = {r.get("phase"): r.get("verdict") for r in xrd_results}
    diag_by_phase: dict[str, bool] = {}
    for p in scored:
        ev = p.get("evidence") or {}
        diag_by_phase[p["phase"]] = bool(ev.get("ftir_diagnostic") or ev.get("raman_diagnostic"))

    conflicting_pairs: list[tuple[str, str]] = []
    for a in by_phase:
        for b in by_phase:
            if a >= b:
                continue
            a_xrd = xrd_by_phase.get(a) == "identified"
            b_xrd = xrd_by_phase.get(b) == "identified"
            a_diag = diag_by_phase.get(a, False)
            b_diag = diag_by_phase.get(b, False)
            # Conflict: one phase is XRD-identified while the OTHER has a
            # polymorph-diagnostic spectral band that XRD does not confirm.
            # Shared carbonate bands are ignored (a genuine two-phase mixture
            # where both are XRD-identified must NOT be flagged as conflict).
            if (a_xrd and b_diag and not b_xrd) or (b_xrd and a_diag and not a_xrd):
                conflicting_pairs.append((a, b))
    if conflicting_pairs:
        pair = conflicting_pairs[0]
        env["uncertainty"].append(
            f"跨模态证据冲突:XRD 支持 {pair[0]},FTIR/Raman 支持 {pair[1]};"
            "两种晶型无法同时由当前证据确认,需补充表征或人工裁决"
        )
        env["findings"].append({
            "statement": f"跨模态证据冲突({pair[0]} vs {pair[1]}):不静默偏向任一方",
            "label": "INFERRED",
        })


def _collect_unexplained(
    xrd_results: list[dict[str, Any]],
    detected_peaks: list[dict[str, float]] | None = None,
) -> list[dict[str, Any]]:
    """Identify XRD peaks that matched no phase's reference reflections.

    `detected_peaks` (from the raw profile) is the authoritative source: every
    observed peak not accepted by ANY phase is unexplained and must be surfaced
    (spec §四.5: 未解释峰必须列出), not silently dropped. Falls back to the
    matched-only heuristic when the raw peak list is unavailable.
    """
    if detected_peaks:
        matched_d: set[float] = set()
        for r in xrd_results:
            for p in (r.get("peaks") or []):
                od = p.get("obs_d_A")
                if isinstance(od, (int, float)):
                    matched_d.add(round(float(od), 3))
        out: list[dict[str, Any]] = []
        for pk in detected_peaks:
            d = round(float(pk.get("d_A", 0.0)), 3)
            if d not in matched_d:
                out.append({
                    "kind": "xrd_unexplained_peak",
                    "value": d,
                    "detail": f"观测峰 d={d} Å(2θ≈{pk.get('two_theta', '?')})未被任何参考相接受,"
                              "可能为杂质相、未识别晶型或仪器伪峰",
                })
        return out
    # Fallback (no raw peak list): conservative note only when every phase is
    # absent/weak (unresolved mixture signal).
    matched_d = set()
    for r in xrd_results:
        for p in (r.get("peaks") or []):
            od = p.get("obs_d_A")
            if isinstance(od, (int, float)):
                matched_d.add(round(float(od), 3))
    if xrd_results and matched_d:
        all_unmatched = sum(1 for r in xrd_results if r.get("verdict") in ("absent", "weak"))
        if all_unmatched == len(xrd_results):
            return [{
                "kind": "xrd_unmatched_reflections",
                "value": len(matched_d),
                "detail": "所有参考相均为 absent/weak,观测峰未能归属任何已知碳酸钙晶型",
            }]
    return []


def _detect_reflection_overlaps(
    xrd_results: list[dict[str, Any]],
    d_tol_A: float,
) -> list[dict[str, Any]]:
    """Find reference reflections from different phases whose d-windows overlap.

    When aragonite 3.273 Å and vaterite 3.29 Å (for example) both fall within
    tolerance of the same observed peak, that reflection cannot discriminate
    the polymorphs — this is conflict evidence the skill must surface (spec
    §四.2 peak overlap; SKILL.md §边界案例#3). Returns one entry per
    overlapping (phase_a, phase_b, d_ref_a, d_ref_b) pair.
    """
    overlaps: list[dict[str, Any]] = []
    by_phase: dict[str, set[float]] = {}
    for r in xrd_results:
        phase = r.get("phase", "")
        d_refs: set[float] = set()
        for p in (r.get("peaks") or []):
            rd = p.get("ref_d_A")
            if isinstance(rd, (int, float)):
                d_refs.add(round(float(rd), 4))
        if d_refs:
            by_phase[phase] = d_refs
    phases_list = sorted(by_phase)
    for i in range(len(phases_list)):
        for j in range(i + 1, len(phases_list)):
            pa, pb = phases_list[i], phases_list[j]
            for da in by_phase[pa]:
                for db in by_phase[pb]:
                    if abs(da - db) <= d_tol_A:
                        overlaps.append({
                            "phases": [pa, pb],
                            "ref_d_A": [da, db],
                            "note": f"d={da} Å({pa})与 d={db} Å({pb})在容差 {d_tol_A} Å 内重叠,"
                                    "该反射不能单独判别这两个晶型",
                        })
    return overlaps


def _action_xrd_match(payload: dict[str, Any], env: dict[str, Any]) -> dict[str, Any]:
    sample = _first_sample(payload, "xrd_twotheta_intensity")
    two_theta, intensity = _load_xrd_series(sample)
    th = _thresholds(payload)
    results = xrd.match_profile(
        two_theta, intensity,
        d_tol_A=th["xrd_d_spacing_tol_A"],
        min_relative_intensity=th["xrd_min_relative_intensity"],
        min_peaks=th["xrd_min_peaks"],
        wavelength_A=sample.get("wavelength_A") or 1.540598,
    )
    dicts = [xrd.result_to_dict(r) for r in results]
    env["results"] = {"matches": dicts, "_has_samples": True}
    env["summary"] = "XRD 峰匹配完成"
    env["status"] = "SUCCESS"
    for r in dicts[:3]:
        env["findings"].append({
            "statement": f"{r['phase']}: {r['verdict']}(score {r['score']},"
                         f"匹配峰 {r['matched_peak_count']})",
            "label": "CALCULATED",
        })
    return env


def _action_sem_stats(payload: dict[str, Any], env: dict[str, Any]) -> dict[str, Any]:
    sample = _first_sample(payload, "sem_particle_list")
    rows = sample.get("particles")
    if not rows:
        raise make_error("OMM-E104", "sem_particle_list 样本缺少 particles 行", {})
    th = _thresholds(payload)
    stats = sem.particle_stats(rows,
                               unit_scale_um_per_px=sample.get("unit_scale"),
                               particle_units=sample.get("particle_units", "um"),
                               min_particles=th["sem_min_particles"])
    env["results"] = {"stats": _stats_to_dict(stats), "_has_samples": True}
    env["summary"] = f"SEM 颗粒统计完成(n={stats.n})"
    env["status"] = "SUCCESS"
    env["findings"].append({
        "statement": f"SEM 颗粒统计: n={stats.n},平均面积 {stats.mean_area_um2} µm²,"
                     f"平均 Feret {stats.mean_feret_um} µm",
        "label": "CALCULATED",
    })
    if stats.n < th["sem_min_particles"]:
        env["uncertainty"].append(f"颗粒样本量 {stats.n} 不足,统计代表性受限;"
                                  "不得据此外推整体均匀性")
    return env


def _action_spectra_parse(payload: dict[str, Any], env: dict[str, Any]) -> dict[str, Any]:
    sample = _first_sample(payload, "eds_spectrum")
    parsed = spectra.parse_spectrum(sample)
    env["results"] = {"spectrum": parsed, "_has_samples": True}
    env["summary"] = f"{parsed['modality']} 谱解析完成"
    env["status"] = "SUCCESS"
    source = f"{parsed['modality'].upper()} 谱(sample_id={sample.get('id', '?')})"
    for st in parsed.get("statements", []):
        env["findings"].append({"statement": st, "label": "OBSERVED", "source": source})
    return env


def _action_fuse(payload: dict[str, Any], env: dict[str, Any]) -> dict[str, Any]:
    results_in = payload.get("results") or {}
    xrd_results = results_in.get("xrd")
    sem_morph = results_in.get("sem_morphology")
    spectra_evidence = results_in.get("spectra")
    eds_ca = results_in.get("eds_ca_present")
    tga_co2 = results_in.get("tga_co2_likely")
    fused = fuse.fuse_all(xrd_results=xrd_results, sem_morphology=sem_morph,
                          spectra=spectra_evidence, eds_ca=eds_ca, tga_co2_likely=tga_co2)
    env["results"] = {"fusion": fused}
    env["summary"] = "多模态证据融合完成"
    env["status"] = "SUCCESS"
    return env


def _action_audit_image(payload: dict[str, Any], env: dict[str, Any]) -> dict[str, Any]:
    """Segment an SEM image with a full audit log.

    Persisting the audit log requires human approval unless dry_run. If no
    image bytes are supplied inline, this action only validates parameters and
    reports the audit contract (offline-safe; real segmentation needs a path).
    """
    sample = _first_sample(payload, "sem_image")
    if not sample.get("path") and not sample.get("px_width"):
        raise make_error("OMM-E101",
                         "audit_image 需要图像文件 path(本版本离线不支持内联位图)",
                         {"sample_id": sample.get("id")})
    th = _thresholds(payload)
    audit = sem.ImageAuditLog()
    audit.record("contract_check", {
        "unit_scale_um_per_px": sample.get("unit_scale"),
        "scale_bar_um": sample.get("scale_bar_um"),
        "scale_bar_px": sample.get("scale_bar_px"),
    }, {"ok": True})

    env["results"] = {
        "audit_contract": {
            "required": ["unit_scale_um_per_px", "scale_bar_um", "scale_bar_px"],
            "provided": {k: sample.get(k) for k in ("unit_scale", "scale_bar_um", "scale_bar_px")},
            "note": "轻量分割不分离接触晶体;结果估计,经审计记录",
        },
        "audit_log": audit.close(),
        "_has_samples": True,
    }
    env["artifacts"].append({"kind": "audit_log", "path": None, "note": "dry_run 未落盘"})
    env["summary"] = "图像处理审计契约已记录(未执行分割)"
    env["status"] = "SUCCESS"
    if not payload.get("dry_run"):
        # Persisting the audit log (or actually segmenting) requires approval.
        env["risks"].append({
            "label": "RECOMMENDATION",
            "statement": "audit_image 落盘需人工批准;当前未获得批准,仅记录契约",
        })
    return env


def _action_image_hash(payload: dict[str, Any], env: dict[str, Any]) -> dict[str, Any]:
    """tools.image_hash — SHA-256 image integrity + append-only hash chain.

    Verifies an image file's SHA-256 against a claimed/expected hash and/or
    appends a tamper-evident entry to a JSONL hash chain (dry-run by default;
    persistence requires approval). Mismatch raises OMM-E501 and the envelope
    reports FAILED — the skill will not analyse a file whose integrity cannot
    be established (spec §九 test #8: 原始图像不可覆盖,处理前后哈希可核对).
    """
    sample = _first_sample(payload, "sem_image")
    path = sample.get("path")
    if not path:
        raise make_error("OMM-E101",
                         "image_hash 需要 sem_image 样本的 path(文件字节的 SHA-256)",
                         {"sample_id": sample.get("id")})

    report = hashcheck.verify_file_hash(path, sample.get("expected_sha256"))
    result: dict[str, Any] = {"verify": report, "chain": None, "_has_samples": True}

    chain_path = payload.get("save_audit_to")
    if chain_path:
        chain_result = hashcheck.append_chain(
            chain_path,
            {"path": path, "sha256": report["sha256"], "label": sample.get("label", "raw")},
            dry_run=bool(payload.get("dry_run", True)),
            approval_granted=bool((payload.get("human_approval_state") or {}).get("granted", False)),
        )
        result["chain"] = chain_result
        env["artifacts"].append({
            "kind": "hash_chain",
            "path": chain_path,
            "note": "dry_run 未落盘" if chain_result.get("dry_run") else "已追加哈希链",
        })

    env["results"] = result
    env["summary"] = f"图像 SHA-256 校验完成: {'匹配' if report['match'] else '不匹配'}"
    env["status"] = "SUCCESS"
    env["findings"].append({
        "statement": f"图像 {path} SHA-256={report['sha256'][:16]}… 与期望哈希{'一致' if report['match'] else '不一致'}",
        "label": "CALCULATED",
    })
    return env


def _action_report(payload: dict[str, Any], env: dict[str, Any]) -> dict[str, Any]:
    """tools.report — generate a structured analysis report from a candidate
    envelope (passed via candidate_output/output) or from a completed prior
    result. Pure reshaping; never adds data."""
    candidate = payload.get("candidate_output") or payload.get("output")
    if not isinstance(candidate, dict):
        raise make_error("OMM-E101",
                         "tools.report 需要 candidate_output(一个已完成的分析封套)", {})
    if candidate.get("status") not in ("SUCCESS", "PARTIAL", "FAILED", "BLOCKED"):
        raise make_error("OMM-E101",
                         "tools.report 的 candidate_output 缺少合法 status", {})

    report = report_mod.build_report(
        candidate,
        title=payload.get("requested_output_format") == "summary" and "MICP 矿物相解释报告(摘要)" or None,
        include_chart=True,
    )
    env["results"] = {"report": report, "report_text": report_mod.render_text(report), "_has_samples": bool(payload.get("samples"))}
    env["summary"] = "分析报告已生成"
    env["status"] = "SUCCESS"
    env["artifacts"].append({"kind": "report", "path": None, "note": "结构化报告在 results.report;文本视图在 results.report_text"})
    return env


def _action_validate(payload: dict[str, Any], env: dict[str, Any]) -> dict[str, Any]:
    """Validate a candidate output envelope against the output schema."""
    candidate = payload.get("candidate_output") or payload.get("output")
    if not isinstance(candidate, dict):
        raise make_error("OMM-E101", "tools.validate 需要 candidate_output 对象", {})
    issues = validate(candidate, load_schema("output", None))
    env["results"] = {"valid": len(issues) == 0, "issues": [i.to_dict() for i in issues]}
    env["summary"] = "输出 schema 校验: " + ("通过" if len(issues) == 0 else f"{len(issues)} 处问题")
    env["status"] = "SUCCESS" if len(issues) == 0 else "FAILED"
    return env


def _action_self_check(payload: dict[str, Any], env: dict[str, Any]) -> dict[str, Any]:
    """Run the full self-check on a candidate envelope (used by bootstrapping).

    The audit context must be derived from the candidate envelope the same way
    _finalize derives it for the live path, otherwise the same envelope passes
    on the live path but fails here (regression found during bootstrap: the
    no_fabrication hard rule flagged an inline-sample envelope because context
    was empty)."""
    candidate = payload.get("candidate_output") or payload.get("output")
    if not isinstance(candidate, dict):
        raise make_error("OMM-E101", "tools.self_check 需要 candidate_output 对象", {})
    results = candidate.get("results") if isinstance(candidate.get("results"), dict) else {}
    context = {
        "single_sem_image_used": bool(results.get("single_sem_image_used")),
        "has_inline_samples": bool(results.get("_has_samples")),
    }
    result = audit_mod.audit_envelope(candidate, context=context)
    env["results"] = result
    env["summary"] = "自检: " + ("通过" if result["passed"] else f"{len(result['issues'])} 处问题")
    env["status"] = "SUCCESS" if result["passed"] else "FAILED"
    return env


def _stats_to_dict(stats: sem.ParticleStats) -> dict[str, Any]:
    return {
        "n": stats.n,
        "min_area_um2": stats.min_area_um2,
        "max_area_um2": stats.max_area_um2,
        "mean_area_um2": stats.mean_area_um2,
        "median_area_um2": stats.median_area_um2,
        "std_area_um2": stats.std_area_um2,
        "min_feret_um": stats.min_feret_um,
        "max_feret_um": stats.max_feret_um,
        "mean_feret_um": stats.mean_feret_um,
        "circularity_mean": stats.circularity_mean,
        "calibration": stats.calibration,
        "unit_scale_um_per_px": stats.unit_scale_um_per_px,
        "notes": stats.notes,
    }


def _finalize(env: dict[str, Any], started: str, schema_dir: str | None) -> dict[str, Any]:
    """Validate output schema + self-check; downgrade SUCCESS on self-check failure."""
    env["provenance"]["started_at"] = started
    env["provenance"]["completed_at"] = _now_iso()
    out_issues = validate(env, load_schema("output", schema_dir))
    env["validation"]["output_schema"] = "passed" if len(out_issues) == 0 else "failed"

    context = {
        "single_sem_image_used": bool(env.get("results", {}).get("single_sem_image_used")),
        "has_inline_samples": bool(env.get("results", {}).get("_has_samples")),
    }
    result = audit_mod.audit_envelope(env, context=context, schema_dir=schema_dir)
    env["validation"]["self_check"] = "passed" if result["passed"] else "failed"
    env["validation"]["checks"] = [{"name": f"issue_{i}", "passed": False,
                                    "detail": iss} for i, iss in enumerate(result["issues"][:20])]
    if not result["passed"] and env["status"] == "SUCCESS":
        env["status"] = "FAILED"
        env["summary"] = "输出未通过自身自检,状态降级为 FAILED"
        if not env["errors"]:
            env["errors"] = [make_error("OMM-E601", "输出未通过自检",
                                        {"issues": result["issues"][:10]}).to_dict()]
    return env
