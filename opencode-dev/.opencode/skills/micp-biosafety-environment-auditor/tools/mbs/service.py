"""Service layer: dispatch an input payload to the correct handler and build
the unified output envelope (Obsidian Plan spec §六).

The auditor's core action `audit` runs a full environmental & biosafety audit
of an MICP sand-column or field plan and produces every section the task brief
requires: hazards, exposure_pathways, nitrogen_balance, waste_streams,
regulatory_context, monitoring_requirements, control_measures, residual_risk,
approval_requirements, stop_conditions, emergency_actions, etc.

Approval gates are hard: the nine trigger conditions from the brief map to
HUMAN_APPROVAL_REQUIRED. Bypass requests are refused (MBS-E205).
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any, Callable

from .chemistry import (
    nh3_concentration,
    nh3_fraction,
    urea_molar_mass,
    urea_to_nitrogen_balance,
    ureolysis_ammonium,
    waste_loading,
)
from .errors import MbsError, MbsErrorCode
from .regulatory import (
    all_regulatory_context,
    evaluate_against_limits,
    lookup_regulation,
    regulatory_gaps_for_site,
)
from .risk import (
    HAZARD_CATALOG,
    RISK_LEVELS,
    alarm_rules,
    any_alarm,
    emergency_actions,
    exposure_pathways,
    identify_hazards,
    monitoring_plan,
    rank_risk,
    residual_risk,
    risk_level,
    risk_matrix,
)
from .strain import classify_biosafety, verify_strain_identity
from .treatment import compare_treatment_options, permit_status, sampling_plan
from .validate import check_output_schema, validate_input

SKILL_NAME = "micp-biosafety-environment-auditor"
SKILL_VERSION = "1.0.0"
CONTRACT_MAJOR = "1"

APPROVAL_GATE_ACTIONS = {
    "strain_verify", "regulatory_lookup", "mass_balance", "nh3_speciation",
    "waste_loading", "risk_matrix", "monitoring", "treatment_compare",
    "sampling_plan", "emergency", "permit_check",
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _clock_from_env() -> Callable[[], str] | None:
    fixed = os.environ.get("MBS_TEST_CLOCK")
    return (lambda: fixed) if fixed else None


class BiosafetyAuditorService:
    def __init__(self) -> None:
        self._clock = _clock_from_env()

    def _timestamp(self) -> str:
        return self._clock() if self._clock else _now()

    # ------------------------------------------------------------------ #
    def handle(self, payload: dict[str, Any]) -> dict[str, Any]:
        started = self._timestamp()
        # 1. contract version gate
        cv = payload.get("contract_version", "1.0")
        major = str(cv).split(".")[0]
        if major != CONTRACT_MAJOR:
            return self._envelope(
                payload, started,
                status="FAILED",
                summary=f"contract_version major {major} is not supported (expected {CONTRACT_MAJOR}).",
                errors=[MbsError(MbsErrorCode.UNSUPPORTED_SCHEMA_VERSION,
                                 detail={"got": cv, "expected_major": CONTRACT_MAJOR})],
            )
        # 2. input schema validation
        violations = validate_input(payload)
        if violations:
            return self._envelope(
                payload, started,
                status="BLOCKED",
                summary="Input does not conform to schemas/input.schema.json; see errors for missing/invalid fields.",
                errors=[MbsError(MbsErrorCode.INPUT_SCHEMA_VIOLATION,
                                 detail={"violations": violations,
                                         "missing_fields": self._extract_missing(violations)})],
            )
        # 3. dispatch
        action = payload.get("action")
        try:
            result = self._dispatch(action, payload)
        except MbsError as exc:
            return self._envelope(payload, started, status="FAILED", summary=str(exc.message), errors=[exc])
        except Exception as exc:
            return self._envelope(
                payload, started,
                status="FAILED",
                summary=f"Unexpected internal error: {exc}",
                errors=[MbsError(MbsErrorCode.CONTEXT_CORRUPT, detail={"error": str(exc)})],
            )

        # 4. stamp + self-check
        out = self._envelope(payload, started, status=result["status"], summary=result["summary"], extra=result)
        try:
            self._self_check(out)
            out["validation"]["self_check"] = "passed"
        except MbsError as exc:
            out["status"] = "FAILED"
            out["validation"]["self_check"] = "failed"
            out["errors"] = [exc.to_dict()]

        # 5. output schema validation
        try:
            check_output_schema(out)
            out["validation"]["output_schema"] = "passed"
        except MbsError as exc:
            out["validation"]["output_schema"] = "failed"
            out["status"] = "FAILED"
            out["errors"] = [exc.to_dict()]
        return out

    # ------------------------------------------------------------------ #
    def _dispatch(self, action: str, payload: dict[str, Any]) -> dict[str, Any]:
        handlers: dict[str, Callable[[dict[str, Any]], dict[str, Any]]] = {
            "audit": self._handle_audit,
            "mass_balance": self._handle_mass_balance,
            "nh3_speciation": self._handle_nh3_speciation,
            "waste_loading": self._handle_waste_loading,
            "strain_verify": self._handle_strain_verify,
            "regulatory_lookup": self._handle_regulatory_lookup,
            "risk_matrix": self._handle_risk_matrix,
            "monitoring": self._handle_monitoring,
            "treatment_compare": self._handle_treatment_compare,
            "sampling_plan": self._handle_sampling_plan,
            "emergency": self._handle_emergency,
            "permit_check": self._handle_permit_check,
        }
        fn = handlers.get(action)
        if fn is None:
            raise MbsError(
                MbsErrorCode.INPUT_SCHEMA_VIOLATION,
                f"Unknown action '{action}'. Supported: {', '.join(sorted(handlers))}.",
                detail={"action": action},
            )
        return fn(payload)

    # ------------------------------------------------------------------ #
    # Core audit pipeline
    # ------------------------------------------------------------------ #
    def _handle_audit(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Full environmental & biosafety audit of a sand-column or field plan.

        Returns the complete result dict that the envelope carries in `extra`.
        """
        site = payload.get("site") or payload.get("context") or {}
        plan = payload.get("plan") or {}
        strain_input = site.get("strain") or payload.get("strain")

        # --- 1. strain identity & biosafety ---
        strain_cls = classify_biosafety(strain_input or {}, site_pathogen_list_ref=site.get("pathogen_list_ref"))
        strain_identity = verify_strain_identity(strain_input)

        # --- 2. nitrogen balance ---
        nitrogen = plan.get("nitrogen") or {}
        n_balance = urea_to_nitrogen_balance(
            urea_input_g=nitrogen.get("urea_input_g", 0.0),
            theoretical_total_n_g=nitrogen.get("theoretical_total_n_g"),
            nh4_upper_bound_g=nitrogen.get("nh4_upper_bound_g"),
            nh3_potential_g=nitrogen.get("nh3_potential_g"),
            liquid_residual_g=nitrogen.get("liquid_residual_g"),
            sorbed_retained_g=nitrogen.get("sorbed_retained_g"),
            discharged_treated_g=nitrogen.get("discharged_treated_g"),
        )

        # --- 3. NH3 speciation from pH/temp ---
        pH = nitrogen.get("pH") or site.get("pH")
        temp_c = nitrogen.get("temperature_c") or site.get("temperature_c")
        nh4_n_conc_mgL = nitrogen.get("nh4_n_conc_mgL", 0.0)
        speciation = None
        if pH is not None and temp_c is not None:
            speciation = nh3_concentration(nh4_n_conc_mgL, float(pH), float(temp_c))

        # --- 4. waste streams ---
        waste_streams: list[dict[str, Any]] = []
        waste = plan.get("waste") or {}
        if waste.get("volume_l") is not None:
            # Waste-stream concentration: prefer the waste block's own value,
            # fall back to the process/column concentration.
            waste_nh4_n = waste.get("nh4_n_conc_mgL", nh4_n_conc_mgL)
            wl = waste_loading(
                waste_volume_l=waste.get("volume_l", 0.0),
                nh4_n_conc_mgL=waste_nh4_n,
                urea_conc_mgL=waste.get("urea_conc_mgL", 0.0),
                temperature_c=float(temp_c) if temp_c is not None else 20.0,
                pH=float(pH) if pH is not None else None,
            )
            waste_streams.append({"stream": "primary_effluent", **wl})

        # --- 5. regulatory context ---
        reg_context = all_regulatory_context()
        reg_verified = reg_context.get("fully_verified", False)
        # Plan-folded site view: declared discharge/injection in the plan is as
        # authoritative as the optional site flags (never downgrade to contained).
        site_with_plan = dict(site)
        site_with_plan["plan"] = plan
        computed_nh3 = None
        if speciation is not None:
            computed_nh3 = speciation["nh3_n_mgL"]
        hazards = identify_hazards(
            site_with_plan,
            computed_nh3_n_mgL=computed_nh3,
            strain_biosafety=strain_cls,
        )
        pathways = exposure_pathways(site_with_plan)

        # --- 7. monitoring ---
        monitoring = monitoring_plan(site)
        measurements = plan.get("measurements") or {}
        alarms = alarm_rules(monitoring, measurements)
        triggered = [a for a in alarms if a["triggered"]]

        # --- 8. treatment comparison (if waste exists) ---
        treatment = None
        if waste.get("volume_l") is not None and waste.get("total_n_load_g"):
            treatment = compare_treatment_options(
                total_n_load_g=waste["total_n_load_g"],
                volume_l=waste["volume_l"],
                available_options=waste.get("available_options"),
            )

        # --- 9. sampling plan ---
        sampling = sampling_plan(site)

        # --- 10. emergency actions ---
        emergencies = emergency_actions(site, triggered)

        # --- 11. approval gates ---
        approval = self._compute_approval_gates(
            site_with_plan, strain_cls, strain_identity, n_balance, reg_context,
            hazards, triggered, treatment, plan,
        )

        # --- 12. stop conditions ---
        stop_conditions = self._compute_stop_conditions(approval, n_balance, triggered, alarms)

        # --- 13. residual risk summary ---
        residual = self._residual_risk_summary(hazards, site, approval)
        max_residual = max(
            (rank_risk(r.get("residual", "LOW")) for r in residual),
            default=0,
        )
        max_residual_level = RISK_LEVELS[max_residual] if residual else "UNKNOWN"

        status = "HUMAN_APPROVAL_REQUIRED" if not approval["all_clear"] else "SUCCESS"
        requested = self._requested_next_skills(site, approval)

        summary = (
            f"Audit of plan '{plan.get('name') or 'unnamed'}' at site "
            f"'{site.get('name') or 'unspecified'}' — {len(hazards)} hazard(s) identified, "
            f"nitrogen balance {n_balance['balance_error_fraction']:.1%} closed, "
            f"{'approval gated' if not approval['all_clear'] else 'clear to proceed'}, "
            f"regulatory {('verified' if reg_verified else 'VERIFICATION REQUIRED')}."
        )

        return {
            "status": status,
            "summary": summary,
            "hazards": hazards,
            "exposure_pathways": pathways,
            "nitrogen_balance": n_balance,
            "waste_streams": waste_streams,
            "regulatory_context": reg_context,
            "monitoring_requirements": monitoring,
            "control_measures": self._control_measures(approval, treatment),
            "residual_risk": residual,
            "approval_requirements": approval["requirements"],
            "stop_conditions": stop_conditions,
            "emergency_actions": emergencies,
            "findings": self._audit_findings(hazards, n_balance, reg_context, approval),
            "assumptions": [
                "Theoretical nitrogen from urea stoichiometry unless a measured path is supplied.",
                "NH3 speciation assumes the Davies activity correction and validated pKa correlation.",
                "Monitoring bands are engineering defaults until verified regulatory limits override them.",
            ],
            "evidence_used": payload.get("evidence_refs") or [],
            "uncertainty": [
                f"Strain biosafety confidence: {strain_cls.get('classification_confidence')}.",
                "Regulatory conclusions depend on verified records; see regulatory_context.verification_required.",
                "Biological hazard screens flag triggers, they do not measure exposure concentration.",
            ],
            "risks": [
                {"label": "INFERRED", "statement": f"Residual risk for identified hazards ranges up to {max_residual_level}."},
            ],
            "artifacts": [
                {"kind": "nitrogen_balance", "path": None, "note": n_balance},
                {"kind": "risk_matrix", "path": None, "note": risk_matrix()},
                {"kind": "monitoring_plan", "path": None, "note": monitoring},
                {"kind": "sampling_plan", "path": None, "note": sampling},
                {"kind": "approval_gates", "path": None, "note": approval},
            ],
            "requested_next_skills": requested,
        }

    # ------------------------------------------------------------------ #
    def _compute_approval_gates(self, site, strain_cls, strain_identity, n_balance,
                                reg_context, hazards, triggered, treatment, plan) -> dict[str, Any]:
        """Nine hard approval gates from the task brief."""
        gates: list[dict[str, str]] = []

        def add(code: str, detail: str, risk: str = "HIGH") -> None:
            gates.append({"code": code, "detail": detail, "risk": risk})

        # G1 — unknown strain
        if not strain_identity.get("verified"):
            add("UNVERIFIED_STRAIN", "使用身份不明菌株", "HIGH")
        # G1b — strain biosafety not confirmed against site pathogen list.
        #     Provisional BSL-1 is NOT a safety verdict: any strain that still
        #     needs regulatory confirmation must be gated until a site
        #     pathogen_list_ref confirms it (never default a common MICP strain
        #     to safe).
        if strain_cls.get("needs_regulatory_confirmation"):
            add("STRAIN_BIOSAFETY_UNCONFIRMED",
                f"菌株生物安全未获场地病原名录确认（分级={strain_cls.get('biosafety_level')}，"
                f"置信={strain_cls.get('classification_confidence')}）",
                "HIGH")
        # G1c — pathogenic-genus marker never defaulted to safe even with an accession.
        if strain_cls.get("pathogenic_marker"):
            add("PATHOGENIC_STRAIN_UNCERTIFIED",
                "菌株属致病性风险属，必须提供场地病原名录核验与 BSL 分级证据",
                "CRITICAL")
        # G1d — any identified hazard at HIGH/CRITICAL forces human approval
        #     (risk model: hazard severity is not waived by passing raw gates).
        for h in hazards:
            if h.get("base_level") in ("HIGH", "CRITICAL"):
                add("HAZARD_{}".format(h.get("id", "UNKNOWN").upper()),
                    f"识别危害 {h.get('label', h.get('id'))} 基准等级 {h.get('base_level')}",
                    h.get("base_level", "HIGH"))
        # G2 — live-cell environmental release
        if str(site.get("release_type") or "contained").lower() in ("open_environment", "injection"):
            add("LIVE_CELL_RELEASE", "环境释放活菌", "CRITICAL")
        # G3 — on-site groundwater injection
        if site.get("groundwater_injection"):
            add("GROUNDWATER_INJECTION", "现场地下水注入", "CRITICAL")
        # G4 — high-concentration urea / N-bearing waste discharge
        nh4 = plan.get("nitrogen", {}).get("nh4_n_conc_mgL", 0.0)
        if float(nh4) > 0 or plan.get("waste", {}).get("volume_l"):
            if plan.get("waste", {}).get("discharge_to_environment", False):
                add("HIGH_N_DISCHARGE", "高浓度尿素或含氮废液排放", "HIGH")
        # G5 — regulation unverifiable for the categories RELEVANT to this site.
        #     The plan is folded into the site view so a declared discharge
        #     (plan.waste.discharge_to_environment) triggers water/groundwater/
        #     emissions verification even when the optional site flags are absent.
        site_with_plan = dict(site)
        site_with_plan["plan"] = plan
        reg_gaps = regulatory_gaps_for_site(site_with_plan, reg_context)
        if reg_gaps:
            add("REGULATORY_UNVERIFIED",
                f"法规无法核验 (REGULATORY_VERIFICATION_REQUIRED): {', '.join(reg_gaps)}", "HIGH")
        # G6 — no waste-treatment capacity
        if not site.get("waste_treatment_capacity"):
            if plan.get("waste", {}).get("volume_l") or float(nh4) > 0:
                add("NO_WASTE_TREATMENT", "缺少废液处理能力", "HIGH")
        # G7 — NH4+/NH3 risk over limit
        if triggered:
            add("MONITORING_EXCEEDED", "NH4+ 或 NH3 监测超限", "CRITICAL")
        # G8 — personnel exposure or confined space
        if site.get("confined_space") or site.get("personnel_exposure"):
            add("PERSONNEL_EXPOSURE", "涉及人员暴露或密闭空间", "HIGH")
        # G9 — sensitive ecological receptors
        if site.get("site_sensitive_ecology"):
            add("SENSITIVE_ECOLOGY", "试验场地存在敏感生态受体", "CRITICAL")
        # G10 — nitrogen balance is theory-only (no measured paths supplied):
        #     environmental conclusions cannot be drawn from an unclosed balance.
        if n_balance.get("uses_only_theory"):
            add("NITROGEN_BALANCE_UNVERIFIED",
                "氮质量平衡仅有理论上限，未提供实测路径(liquid/sorbed/discharged)核验闭合", "HIGH")

        # Treatment recommendation blocked (HIGH residual risk route)
        if treatment and treatment.get("recommendation_blocked"):
            add("TREATMENT_RECOMMENDATION_BLOCKED", treatment["reason"], "HIGH")

        all_clear = len(gates) == 0
        return {
            "all_clear": all_clear,
            "requirements": gates,
            "summary": "全部审批门通过，可继续" if all_clear else f"{len(gates)} 项审批门未通过，需人工批准",
        }

    def _compute_stop_conditions(self, approval, n_balance, triggered, alarms) -> list[dict[str, Any]]:
        stops: list[dict[str, Any]] = []
        if not n_balance.get("mass_balance_closed"):
            stops.append({"condition": "质量守恒不闭合", "action": "STOP 环境结论；重新核算氮平衡 (MBS-E301)"})
        if triggered:
            for a in triggered:
                stops.append({
                    "condition": f"监测超限 {a['parameter']}={a['value']:g} (阈值 {a['threshold'].get('max')})",
                    "action": "STOP 注入/排放；启动应急响应",
                })
        if any(a["level"] == "warning" for a in alarms):
            stops.append({"condition": "监测进入预警带", "action": "降低注入速率并加密监测"})
        if not approval.get("all_clear"):
            stops.append({"condition": "审批门未全部通过", "action": "STOP 直至人工批准 (HUMAN_APPROVAL_REQUIRED)"})
        return stops

    def _residual_risk_summary(self, hazards, site, approval) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for h in hazards:
            base = h.get("base_level", "MODERATE")
            # Control effectiveness must derive from ACTUAL implemented/verified
            # controls, never from passing approval gates. Without control
            # evidence, effectiveness is 'none' (conservative).
            effectiveness = "none"
            if site.get("waste_treatment_capacity") and any(
                m.get("measure") == "废液处理" for m in self._control_measures(approval, None)
            ):
                effectiveness = "moderate"
            if site.get("containment") or site.get("enclosure"):
                effectiveness = "moderate"
            resid = residual_risk(base, effectiveness)
            out.append({
                "hazard": h.get("id"),
                "hazard_level": base,
                "control_effectiveness": effectiveness,
                "residual": resid,
            })
        return out

    def _control_measures(self, approval, treatment) -> list[dict[str, str]]:
        measures = [
            {"measure": "工程控制", "detail": "密闭收集、通风、防渗衬垫、含氨废液密封储罐"},
            {"measure": "行政控制", "detail": "仅经授权人员操作；受限空间作业许可；双人监护"},
            {"measure": "监测", "detail": "按监测计划执行；超阈值立即停止并上报"},
        ]
        if treatment and not treatment.get("recommendation_blocked"):
            measures.append({"measure": "废液处理", "detail": f"推荐方案 {treatment['best_option']} ({treatment['reason']})"})
        return measures

    def _audit_findings(self, hazards, n_balance, reg_context, approval) -> list[dict[str, Any]]:
        findings: list[dict[str, Any]] = []
        for h in hazards:
            findings.append({
                "label": "INFERRED",
                "statement": f"{h['label']}: {h['evidence']} (基准 {h['base_level']})",
            })
        findings.append({
            "label": "CALCULATED",
            "statement": f"氮质量平衡闭合误差 {n_balance['balance_error_fraction']:.2%}；"
                        f"理论总氮 {n_balance['theoretical_total_n_g']:.3g} g",
        })
        if not reg_context.get("fully_verified", False):
            findings.append({
                "label": "RECOMMENDATION",
                "statement": "法规无法完全核验：标记 REGULATORY_VERIFICATION_REQUIRED，批准前必须补齐核验记录。",
            })
        if not approval.get("all_clear"):
            findings.append({
                "label": "RECOMMENDATION",
                "statement": f"审批门未通过：{approval['summary']}",
            })
        return findings

    def _requested_next_skills(self, site, approval) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        if str(site.get("release_type") or "").lower() == "injection" or site.get("groundwater_injection"):
            out.append({
                "skill": "micp-porous-media-transport",
                "reason": "现场注入/地下水路径需要运移模拟校核污染物与菌体运移。",
                "inputs_needed": ["site_hydraulics", "injection_schedule"],
            })
        if site.get("soil_performance") or site.get("geotechnical_check"):
            out.append({
                "skill": "micp-geotechnical-performance",
                "reason": "砂柱/固化体力学性能校核。",
                "inputs_needed": ["specimen_results"],
            })
        if approval.get("all_clear") and site.get("risk_level") == "high":
            out.append({
                "skill": "obsidian-red-team",
                "reason": "高风险方案需对抗审查后方可实施。",
                "inputs_needed": ["approval_evidence"],
            })
        return out

    # ------------------------------------------------------------------ #
    # Individual tool handlers
    # ------------------------------------------------------------------ #
    def _handle_mass_balance(self, payload: dict[str, Any]) -> dict[str, Any]:
        nb = payload.get("nitrogen") or {}
        res = urea_to_nitrogen_balance(
            urea_input_g=nb.get("urea_input_g", 0.0),
            theoretical_total_n_g=nb.get("theoretical_total_n_g"),
            nh4_upper_bound_g=nb.get("nh4_upper_bound_g"),
            nh3_potential_g=nb.get("nh3_potential_g"),
            liquid_residual_g=nb.get("liquid_residual_g"),
            sorbed_retained_g=nb.get("sorbed_retained_g"),
            discharged_treated_g=nb.get("discharged_treated_g"),
        )
        return {
            "status": "SUCCESS",
            "summary": f"尿素 {res['urea_input_g']:g} g → 理论总氮 {res['theoretical_total_n_g']:.3g} g；"
                       f"平衡误差 {res['balance_error_fraction']:.2%}，闭合={res['mass_balance_closed']}",
            "nitrogen_balance": res,
            "findings": [{"label": "CALCULATED", "statement": f"NH4+ 理论上限 {res['nh4_upper_bound_g']:.3g} g；NH3 潜在 {res['nh3_potential_g']:.3g} g N。"}],
            "assumptions": ["基于尿素化学计量；未提供实测路径时仅为理论上限。"],
            "evidence_used": payload.get("evidence_refs") or [],
            "uncertainty": ["未实测路径时无质量闭合判定。"],
            "risks": [],
            "artifacts": [{"kind": "nitrogen_balance", "path": None, "note": res}],
            "requested_next_skills": [],
        }

    def _handle_nh3_speciation(self, payload: dict[str, Any]) -> dict[str, Any]:
        s = payload.get("conditions") or {}
        total = payload.get("total_ammonia_n_mgL")
        if total is None:
            total = s.get("nh4_n_mgL")
        if total is None:
            raise MbsError(MbsErrorCode.MISSING_REQUIRED_FIELD,
                           "nh3_speciation requires total_ammonia_n_mgL (or conditions.nh4_n_mgL).",
                           detail={"fields": ["total_ammonia_n_mgL", "conditions.nh4_n_mgL"]})
        ph = s.get("pH")
        temp = s.get("temperature_c", 20.0)
        if ph is None:
            raise MbsError(MbsErrorCode.MISSING_REQUIRED_FIELD,
                           "nh3_speciation requires conditions.pH.",
                           detail={"fields": ["conditions.pH"]})
        res = nh3_concentration(float(total), float(ph), float(temp))
        return {
            "status": "SUCCESS",
            "summary": f"总氨 {res['total_ammonia_n_mgL']:g} mg/L (as N) 在 pH={ph}、{temp}°C 下 "
                       f"NH3-N={res['nh3_n_mgL']:.3g} mg/L ({res['nh3_fraction']:.1%})",
            "findings": [{"label": "CALCULATED", "statement": f"游离 NH3 占比 {res['nh3_fraction']:.1%} (pKa={res['pka']:.2f})。"}],
            "assumptions": ["Davies 活度校正；pKa 关联 Bates & Pinching (1949)。"],
            "evidence_used": payload.get("evidence_refs") or [],
            "uncertainty": ["高离子强度或非水基质时活度校正误差增大。"],
            "risks": [],
            "artifacts": [{"kind": "nh3_speciation", "path": None, "note": res}],
            "requested_next_skills": [],
        }

    def _handle_waste_loading(self, payload: dict[str, Any]) -> dict[str, Any]:
        w = payload.get("waste") or {}
        res = waste_loading(
            waste_volume_l=w.get("volume_l", 0.0),
            nh4_n_conc_mgL=w.get("nh4_n_conc_mgL", 0.0),
            urea_conc_mgL=w.get("urea_conc_mgL", 0.0),
            temperature_c=w.get("temperature_c", 20.0),
            pH=w.get("pH"),
        )
        return {
            "status": "SUCCESS",
            "summary": f"废液 {res['waste_volume_l']:g} L，NH4-N 负荷 {res['nh4_n_load_g']:.3g} g，"
                       f"总氮负荷 {res['total_n_load_g']:.3g} g",
            "findings": [{"label": "CALCULATED", "statement": f"总氮负荷 {res['total_n_load_g']:.3g} g"
                        + (f"，NH3-N 负荷 {res['nh3_n_load_g']:.3g} g (pH={res['pH']})" if "nh3_n_load_g" in res else "")}],
            "assumptions": ["浓度基于提供值；未提供 pH 时不估算 NH3。"],
            "evidence_used": payload.get("evidence_refs") or [],
            "uncertainty": [],
            "risks": [],
            "artifacts": [{"kind": "waste_loading", "path": None, "note": res}],
            "requested_next_skills": [],
        }

    def _handle_strain_verify(self, payload: dict[str, Any]) -> dict[str, Any]:
        strain = payload.get("strain")
        cls = classify_biosafety(strain or {}, site_pathogen_list_ref=payload.get("pathogen_list_ref"))
        identity = verify_strain_identity(strain)
        status = "HUMAN_APPROVAL_REQUIRED" if not identity.get("verified") else "SUCCESS"
        return {
            "status": status,
            "summary": f"菌株 '{identity['name']}' 身份核验={'已验证' if identity['verified'] else '未验证'}；"
                       f"安全等级 {cls.get('biosafety_level')}（{cls.get('classification_confidence')}）",
            "findings": [
                {"label": "REPORTED", "statement": f"菌株身份：{identity['name']}，保藏号/来源：{identity.get('accession') or identity.get('source') or '无'}。"},
                {"label": "INFERRED", "statement": f"生物安全分级 {cls.get('biosafety_level')}，置信 {cls.get('classification_confidence')}；"
                                                   f"{'需现场法规确认' if cls.get('needs_regulatory_confirmation') else '已确认'}。"},
            ],
            "assumptions": ["分类须与国家病原微生物名录现场核验一致。"],
            "evidence_used": payload.get("evidence_refs") or [],
            "uncertainty": ["未提供国家名录引用时仅为临时分级。"],
            "risks": [],
            "artifacts": [{"kind": "strain_biosafety", "path": None, "note": cls},
                          {"kind": "strain_identity", "path": None, "note": identity}],
            "requested_next_skills": [],
        }

    def _handle_regulatory_lookup(self, payload: dict[str, Any]) -> dict[str, Any]:
        query = payload.get("regulatory_query") or payload.get("query")
        category = payload.get("regulatory_category")
        record_id = payload.get("regulatory_record_id")
        try:
            res = lookup_regulation(query=query, record_id=record_id, category=category, allow_stale=True)
        except MbsError as exc:
            # Propagate as MBS-E201 so the envelope carries the code and the
            # REGULATORY_VERIFICATION_REQUIRED marker. Never fabricate a limit.
            raise MbsError(
                MbsErrorCode.REGULATION_UNVERIFIABLE,
                f"{exc.message} 标记 REGULATORY_VERIFICATION_REQUIRED；不得凭记忆断言限值。",
                detail=exc.detail,
            ) from exc
        verified = res.get("verified")
        n_pending = len(res.get("verification_required", []))
        status = "SUCCESS" if verified else "HUMAN_APPROVAL_REQUIRED"
        detail_text = "全部已核验" if verified else f"待核验 {n_pending} 条 (REGULATORY_VERIFICATION_REQUIRED)"
        return {
            "status": status,
            "summary": f"法规检索：{len(res['records'])} 条记录，{detail_text}",
            "findings": [
                {"label": "REPORTED", "statement": f"匹配记录：{', '.join(r.get('doc_id', r.get('id', '?')) for r in res['records'])}。"}
            ],
            "assumptions": ["本地核验库中的记录即当前核验基线。"],
            "evidence_used": payload.get("evidence_refs") or [],
            "uncertainty": ["记录须在核验期限内；过期视为未核验。"],
            "risks": [],
            "artifacts": [{"kind": "regulatory_lookup", "path": None, "note": res}],
            "requested_next_skills": [],
        }

    def _handle_risk_matrix(self, payload: dict[str, Any]) -> dict[str, Any]:
        matrix = risk_matrix()
        return {
            "status": "SUCCESS",
            "summary": "风险矩阵已生成 (5x5，LOW/CRITICAL)。",
            "findings": [{"label": "CALCULATED", "statement": "25 个风险单元格；按 likelihood×severity 查表。"}],
            "assumptions": ["矩阵为工程默认；组织可采用自定义矩阵。"],
            "evidence_used": [], "uncertainty": [], "risks": [],
            "artifacts": [{"kind": "risk_matrix", "path": None, "note": matrix}],
            "requested_next_skills": [],
        }

    def _handle_monitoring(self, payload: dict[str, Any]) -> dict[str, Any]:
        site = payload.get("site") or {}
        monitoring = monitoring_plan(site)
        measurements = payload.get("measurements") or {}
        alarms = alarm_rules(monitoring, measurements)
        return {
            "status": "SUCCESS",
            "summary": f"监测计划生成；{len(alarms)} 项告警规则，"
                       f"{'有触发' if any_alarm(alarms) else '全部在限内'}",
            "findings": [{"label": "CALCULATED", "statement": f"触发告警：{sum(1 for a in alarms if a['triggered'])} 项。"}],
            "assumptions": ["默认阈值带为工程占位；法规核验限值覆盖时以法规为准。"],
            "evidence_used": payload.get("evidence_refs") or [],
            "uncertainty": ["监测频率为默认；需现场确认。"],
            "risks": [],
            "artifacts": [{"kind": "monitoring_plan", "path": None, "note": monitoring},
                          {"kind": "alarms", "path": None, "note": alarms}],
            "requested_next_skills": [],
        }

    def _handle_treatment_compare(self, payload: dict[str, Any]) -> dict[str, Any]:
        w = payload.get("waste") or {}
        res = compare_treatment_options(
            total_n_load_g=w.get("total_n_load_g", 0.0),
            volume_l=w.get("volume_l", 0.0),
            available_options=w.get("available_options"),
        )
        status = "SUCCESS" if not res["recommendation_blocked"] else "HUMAN_APPROVAL_REQUIRED"
        return {
            "status": status,
            "summary": res["reason"],
            "findings": [{"label": "CALCULATED", "statement": f"最优方案 {res['best_option']}；残余 NH3 风险 {res['best_residual_nh3_risk']}。"}],
            "assumptions": ["处置性能为工程默认带；应替换为场地/厂商实测数据。"],
            "evidence_used": payload.get("evidence_refs") or [],
            "uncertainty": ["未考虑运费、法规路径差异。"],
            "risks": [],
            "artifacts": [{"kind": "treatment_comparison", "path": None, "note": res}],
            "requested_next_skills": [],
        }

    def _handle_sampling_plan(self, payload: dict[str, Any]) -> dict[str, Any]:
        site = payload.get("site") or {}
        plan = sampling_plan(site)
        return {
            "status": "SUCCESS",
            "summary": f"采样计划生成（{len(plan['sampling_stations'])} 个点位）。",
            "findings": [{"label": "RECOMMENDATION", "statement": "点位/频率为模板，需主管部门确认后执行。"}],
            "assumptions": ["QA/QC 要求见计划。"],
            "evidence_used": payload.get("evidence_refs") or [],
            "uncertainty": ["受纳体特征决定最终点位。"],
            "risks": [],
            "artifacts": [{"kind": "sampling_plan", "path": None, "note": plan}],
            "requested_next_skills": [],
        }

    def _handle_emergency(self, payload: dict[str, Any]) -> dict[str, Any]:
        site = payload.get("site") or {}
        monitoring = monitoring_plan(site)
        measurements = payload.get("measurements") or {}
        alarms = alarm_rules(monitoring, measurements)
        triggered = [a for a in alarms if a["triggered"]]
        actions = emergency_actions(site, triggered)
        return {
            "status": "SUCCESS",
            "summary": f"应急响应清单生成（{len(actions)} 类场景）。",
            "findings": [{"label": "RECOMMENDATION", "statement": "应急行动须纳入现场应急预案并演练。"}],
            "assumptions": ["触发场景来自监测告警与场地特征。"],
            "evidence_used": payload.get("evidence_refs") or [],
            "uncertainty": [], "risks": [],
            "artifacts": [{"kind": "emergency_actions", "path": None, "note": actions}],
            "requested_next_skills": [],
        }

    def _handle_permit_check(self, payload: dict[str, Any]) -> dict[str, Any]:
        permits = payload.get("permits") or []
        requested = payload.get("requested_actions") or []
        res = permit_status(permits=permits, requested_actions=requested)
        status = "SUCCESS" if res["all_approved"] else "HUMAN_APPROVAL_REQUIRED"
        return {
            "status": status,
            "summary": res["verdict"],
            "findings": [{"label": "REPORTED", "statement": "; ".join(
                f"{c['action']}={c['status']}" for c in res["checks"]) or "无审批记录。"}],
            "assumptions": ["到期日未提供时按未核验处理。"],
            "evidence_used": payload.get("evidence_refs") or [],
            "uncertainty": [], "risks": [],
            "artifacts": [{"kind": "permit_status", "path": None, "note": res}],
            "requested_next_skills": [],
        }

    # ------------------------------------------------------------------ #
    def _self_check(self, out: dict[str, Any]) -> None:
        valid_labels = {"OBSERVED", "REPORTED", "CALCULATED", "INFERRED", "HYPOTHESIS", "RECOMMENDATION"}
        for f in out.get("findings", []):
            label = f.get("label")
            if label not in valid_labels:
                raise MbsError(MbsErrorCode.SELF_CHECK_FAILED, f"Finding has invalid epistemic label '{label}'.", detail={"statement": f.get("statement")})
        # status coherence: HUMAN_APPROVAL_REQUIRED / BLOCKED must not assert OBSERVED findings
        if out.get("status") in ("HUMAN_APPROVAL_REQUIRED", "BLOCKED"):
            for f in out.get("findings", []):
                if f.get("label") == "OBSERVED":
                    raise MbsError(MbsErrorCode.SELF_CHECK_FAILED,
                                   f"{out.get('status')} envelope cannot assert OBSERVED findings.",
                                   detail={"statement": f.get("statement")})
        # mass-balance gate surfaces in the summary of audits: when the caller
        # supplied measured paths they must close; a theory-only balance is
        # gated upstream by the NITROGEN_BALANCE_UNVERIFIED approval gate.
        if out.get("action") == "audit" and out.get("status") not in ("FAILED", "BLOCKED"):
            nb = out.get("nitrogen_balance") or {}
            if not nb.get("uses_only_theory") and not nb.get("mass_balance_closed"):
                raise MbsError(MbsErrorCode.SELF_CHECK_FAILED,
                               "audit output claims a status but the supplied nitrogen balance does not close.",
                               detail={"balance_error_fraction": nb.get("balance_error_fraction")})

    def _extract_missing(self, violations: list[str]) -> list[str]:
        missing: list[str] = []
        for v in violations:
            if "required" in v and "property" in v:
                field = v.split("'")[1]
                missing.append(field)
        return missing

    # ------------------------------------------------------------------ #
    def _envelope(self, payload: dict[str, Any], started: str, *, status: str, summary: str,
                  errors: list[MbsError] | None = None, extra: dict[str, Any] | None = None) -> dict[str, Any]:
        extra = extra or {}
        completed = self._timestamp()
        out: dict[str, Any] = {
            "contract_version": "1.0",
            "skill": SKILL_NAME,
            "skill_version": SKILL_VERSION,
            "status": status,
            "summary": summary,
            "action": payload.get("action"),
            "project_id": payload.get("project_id"),
            "task_id": payload.get("task_id"),
            # Unified envelope (spec §六, 12 fields)
            "findings": extra.get("findings", []),
            "assumptions": extra.get("assumptions", []),
            "evidence_used": extra.get("evidence_used", []),
            "uncertainty": extra.get("uncertainty", []),
            "risks": extra.get("risks", []),
            "artifacts": extra.get("artifacts", []),
            "requested_next_skills": extra.get("requested_next_skills", []),
            "state": None,
            "validation": {
                "input_schema": "passed" if status != "BLOCKED" else "failed",
                "output_schema": "pending",
                "self_check": "not_run",
            },
            "provenance": {"started_at": started, "completed_at": completed, "host": None},
            "errors": [e.to_dict() for e in (errors or [])],
            # Domain sections (task brief §七) — present on audit and, for the
            # single-tool actions, filled from `extra` where available.
            "hazards": extra.get("hazards", []),
            "exposure_pathways": extra.get("exposure_pathways", []),
            "nitrogen_balance": extra.get("nitrogen_balance"),
            "waste_streams": extra.get("waste_streams", []),
            "regulatory_context": extra.get("regulatory_context"),
            "monitoring_requirements": extra.get("monitoring_requirements"),
            "control_measures": extra.get("control_measures", []),
            "residual_risk": extra.get("residual_risk", []),
            "approval_requirements": extra.get("approval_requirements", []),
            "stop_conditions": extra.get("stop_conditions", []),
            "emergency_actions": extra.get("emergency_actions", []),
        }
        return out
