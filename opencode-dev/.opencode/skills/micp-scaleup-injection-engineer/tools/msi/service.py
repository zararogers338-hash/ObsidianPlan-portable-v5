"""Service facade for micp-scaleup-injection-engineer.

Pipeline for every invocation:
  1. envelope construction (unified §八 shape)
  2. input schema validation + contract-version gate (MSI-E801)
  3. scenario normalization (MSI-E102 BLOCKED on missing site permeability)
  4. approval gate for field scale (MSI-E502 -> HUMAN_APPROVAL_REQUIRED)
  5. action dispatch
  6. output self-check (schema + epistemic labels + mass balance)
  7. return the unified envelope — always parseable.

Actions:
  scaleup           full pipeline
  similarity        similarity matrix only
  material_balance  mass/volume balance only
  boundary_check    constant-flux vs constant-head + pressure
  pressure_risk     pressure vs allowable
  injection_layout  well array + zones
  injection_schedule schedule phases/rounds/pulse/flush
  monitoring_plan   monitoring + real-time alarms
  clogging_risk     inlet clogging / preferential flow / uniformity
  tracer            tracer breakthrough analysis
  stage_gate        gate decision + stop + fallback
  validate          input validation only (dry-run)
  generate_tables   construction parameter + monitoring tables

The service never touches the network and only writes artifacts when the
caller supplies an artifact directory.
"""

from __future__ import annotations

import json
import platform
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .clogging import clogging_risk
from .errors import OpError, OpErrorCode
from .layout import build_layout
from .material import material_balance
from .models import CONTRACT_VERSION, EpistemicLabel, OutputStatus, SKILL_NAME, SKILL_VERSION
from .monitoring import build_monitoring_plan, evaluate_monitoring
from .observability import get_logger
from .pressure import boundary_check
from .scenario import normalize_scenario
from .schedule import build_schedule
from .similarity import build_similarity
from .stage_gate import stage_gate
from .tracer import tracer_analysis
from .units import safe_project_id
from . import validate as vcheck

# JSON Schema validation (optional third-party): use jsonschema when present,
# else the builtin structural checks. Never fail the pipeline for the absence
# of jsonschema — only for an actual schema violation.
try:
    import jsonschema  # type: ignore
    _HAS_JSONSCHEMA = True
except Exception:  # pragma: no cover - optional dep
    _HAS_JSONSCHEMA = False


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _as_labeled(label: str, statement: str, source: str | None = None) -> dict[str, Any]:
    return {"label": label, "statement": statement, "source": source}


class ScaleUpService:
    def __init__(self, *, artifact_dir: str | None = None) -> None:
        self.artifact_dir = artifact_dir
        self.log = get_logger()

    def actions(self) -> list[str]:
        return ["scaleup", "similarity", "material_balance", "boundary_check",
                "pressure_risk", "injection_layout", "injection_schedule",
                "monitoring_plan", "clogging_risk", "tracer", "stage_gate",
                "validate", "generate_tables"]

    # ------------------------------------------------------------------
    # public entry
    # ------------------------------------------------------------------
    def handle(self, raw: dict[str, Any]) -> dict[str, Any]:
        started = _now_iso()
        out = self._envelope(raw, started)
        try:
            self._check_contract_version(raw)
            action = raw.get("action")
            if action not in self.actions():
                raise OpError(OpErrorCode.INVALID_ACTION,
                              f"Unknown action '{action}'.",
                              detail={"known_actions": sorted(self.actions())})
            # Central field-approval gate: EVERY action that could emit field
            # construction values requires the six approvals + granted flag.
            # This closes the bypass where non-scaleup actions produced field
            # plans with no human approval (red-team/auditor blocker).
            self._require_field_approval(raw)
            handler = getattr(self, f"_do_{action.replace('.', '_')}")
            result = handler(raw, out)
            out.update(result)
            if out.get("errors"):
                out["status"] = OutputStatus.PARTIAL.value
            elif out.get("_force_partial"):
                out["status"] = OutputStatus.PARTIAL.value
                out.pop("_force_partial", None)
            else:
                out["status"] = OutputStatus.SUCCESS.value
        except OpError as exc:
            self._apply_error(raw, out, exc)
        except Exception as exc:  # last-resort: never emit unparseable output
            self._apply_error(raw, out, OpError(
                OpErrorCode.TOOL_UNAVAILABLE,
                f"Unhandled internal error: {type(exc).__name__}: {exc}",
                detail={"exception_type": type(exc).__name__},
            ))

        out["provenance"]["completed_at"] = _now_iso()
        self._finalize_self_check(out)
        return out

    # ------------------------------------------------------------------
    # envelope + error plumbing
    # ------------------------------------------------------------------
    def _envelope(self, raw: dict[str, Any], started: str) -> dict[str, Any]:
        try:
            pid = safe_project_id(str(raw.get("project_id", "")))
        except OpError:
            pid = None
        return {
            "contract_version": CONTRACT_VERSION,
            "skill": SKILL_NAME,
            "skill_version": SKILL_VERSION,
            "status": OutputStatus.FAILED.value,
            "summary": "",
            "action": raw.get("action"),
            "project_id": pid,
            "task_id": raw.get("task_id"),
            "findings": [],
            "assumptions": [],
            "evidence_used": [],
            "uncertainty": [],
            "risks": [],
            "artifacts": [],
            "requested_next_skills": [],
            "state": None,
            "validation": {
                "input_schema": "pending",
                "output_schema": "pending",
                "self_check": "not_run",
                "checks": [],
            },
            "provenance": {
                "started_at": started,
                "completed_at": None,
                "skill": SKILL_NAME,
                "skill_version": SKILL_VERSION,
                "host": platform.node(),
                "log_tail": [],
                "artifacts_written": [],
            },
            "errors": [],
            # §八 domain fields
            "scale_level": None,
            "site_assumptions": [],
            "similarity_matrix": None,
            "non_scalable_factors": [],
            "injection_layout": None,
            "injection_schedule": None,
            "material_balance": None,
            "pressure_constraints": None,
            "monitoring_plan": None,
            "stop_conditions": [],
            "fallback_plan": None,
            "environmental_requirements": None,
        }

    def _apply_error(self, raw: dict[str, Any], out: dict[str, Any], exc: OpError) -> None:
        status_map = {
            OpErrorCode.APPROVAL_REQUIRED: OutputStatus.HUMAN_APPROVAL_REQUIRED,
            OpErrorCode.DOWNSTREAM_CAPABILITY_MISSING: OutputStatus.NEED_ADDITIONAL_SKILL,
            OpErrorCode.MISSING_REQUIRED_FIELD: OutputStatus.BLOCKED,
            OpErrorCode.INPUT_SCHEMA_VIOLATION: OutputStatus.BLOCKED,
            OpErrorCode.INVALID_ACTION: OutputStatus.BLOCKED,
            OpErrorCode.INVALID_SCENARIO: OutputStatus.BLOCKED,
            OpErrorCode.EVIDENCE_UNVERIFIABLE: OutputStatus.BLOCKED,
            OpErrorCode.UNIT_INCONSISTENT: OutputStatus.BLOCKED,
            OpErrorCode.UNIT_PARSE_ERROR: OutputStatus.BLOCKED,
            OpErrorCode.RANGE_OUT_OF_BOUNDS: OutputStatus.BLOCKED,
            OpErrorCode.UNSUPPORTED_SCHEMA_VERSION: OutputStatus.BLOCKED,
        }
        out["status"] = status_map.get(exc.code, OutputStatus.FAILED).value
        out["errors"].append(exc.to_dict())
        out["summary"] = f"{exc.code.code}: {exc.message}"
        self.log.warn("error", code=exc.code.code, message=exc.message)

    def _check_contract_version(self, raw: dict[str, Any]) -> None:
        declared = raw.get("contract_version", "")
        if not declared.startswith("1."):
            raise OpError(
                OpErrorCode.UNSUPPORTED_SCHEMA_VERSION,
                f"contract_version {declared!r} is not consumable by this build (supports 1.x).",
                detail={"declared": declared, "supported": "1.x"},
            )

    def _validate_input_schema(self, raw: dict[str, Any]) -> None:
        """Strict JSON-Schema validation when jsonschema is available; always
        enforces the required-field list regardless."""
        required = ["task_id", "project_id", "request", "action",
                    "skill_version", "controller_version", "timestamp"]
        missing = [f for f in required if f not in raw]
        if missing:
            raise OpError(
                OpErrorCode.INPUT_SCHEMA_VIOLATION,
                f"Missing required input fields: {missing}.",
                detail={"missing_fields": [
                    {"field": f, "why_critical": "required by input.schema.json",
                     "how_to_obtain": "controller supplies it"} for f in missing]},
            )
        if _HAS_JSONSCHEMA:
            schema = vcheck._load_schema("input.schema.json")
            if schema is not None:
                try:
                    jsonschema.validate(instance=raw, schema=schema)
                except jsonschema.ValidationError as exc:
                    raise OpError(
                        OpErrorCode.INPUT_SCHEMA_VIOLATION,
                        f"Input schema violation: {exc.message}",
                        detail={"json_path": list(exc.absolute_path)})

    def _finalize_self_check(self, out: dict[str, Any]) -> None:
        checks = out["validation"].get("checks", [])
        checks.append({"name": "envelope_shape", "passed": bool(out.get("summary"))})
        checks.append({
            "name": "status_valid",
            "passed": out.get("status") in ("SUCCESS", "PARTIAL", "BLOCKED", "FAILED",
                                            "NEED_ADDITIONAL_SKILL", "HUMAN_APPROVAL_REQUIRED"),
        })
        checks.append(vcheck.check_epistemic_labels(out))
        # output schema check
        issues = vcheck.validate_output(out)
        checks.append({"name": "output_schema", "passed": len(issues) == 0,
                       "detail": f"{len(issues)} issue(s)" if issues else ""})
        ok = all(c.get("passed") for c in checks)
        out["validation"]["self_check"] = "passed" if ok else "failed"
        out["validation"]["checks"] = checks

    # ------------------------------------------------------------------
    # approval gate helper
    # ------------------------------------------------------------------
    def _require_field_approval(self, raw: dict[str, Any]) -> None:
        target = raw.get("target") or {}
        if target.get("scale_level") == "field":
            approval = raw.get("human_approval_state") or {}
            if not approval.get("granted"):
                raise OpError(
                    OpErrorCode.APPROVAL_REQUIRED,
                    "scale_level 'field' requires explicit human approval with six items: "
                    "geotechnical approval, biosafety review, regulatory verification, "
                    "construction risk assessment, waste/ammonia plan, emergency plan.",
                    detail={"how_to_fix": "set human_approval_state.granted=true with approver, "
                            "revision, scope AND provide all six site approvals"})
            six = ["geotechnical_approval", "biosafety_review", "regulatory_verification",
                   "construction_risk_assessment", "waste_ammonia_plan", "emergency_plan"]
            site = raw.get("site") or {}
            missing = [k for k in six if not (site.get(k) or {}).get("approved")]
            if missing:
                raise OpError(
                    OpErrorCode.APPROVAL_REQUIRED,
                    f"field scale requires all six approvals; missing: {missing}.",
                    detail={"missing_approvals": missing})

    # ------------------------------------------------------------------
    # actions
    # ------------------------------------------------------------------
    def _do_validate(self, raw: dict[str, Any], out: dict[str, Any]) -> dict[str, Any]:
        self._validate_input_schema(raw)
        s = normalize_scenario(raw)
        out["validation"]["input_schema"] = "passed"
        bc = boundary_check(s)
        mb = material_balance(s, flow_override_m3_s=bc.injection_flow_m3_s)
        out["material_balance"] = mb.to_dict()
        # A dry-run gate must not green-light an unbuildable scenario
        # (missing porosity -> no pore volume -> no NH4-N/volumes).
        if s.effective_porosity is None:
            out["_force_partial"] = True
        return {
            "summary": (f"Scenario validation: scale={s.scale_level}, target volume "
                        f"{s.target_volume_m3 if s.target_volume_m3 is not None else 'n/a'} m3, "
                        f"pore volume {s.pore_volume_m3 if s.pore_volume_m3 is not None else 'n/a'} m3"
                        + ("; WARNING: porosity missing — pore volume/NH4-N cannot be sized"
                           if s.effective_porosity is None else "")),
            "findings": [
                _as_labeled("OBSERVED", "Scenario passed unit/range validation; plan not built "
                                        "(dry-run gate).", source="validate"),
            ] + ([_as_labeled("INFERRED", "porosity missing — supply site.layers porosity to "
                              "size pore volume and NH4-N", source="validate")]
                 if s.effective_porosity is None else []),
            "assumptions": [_as_labeled("INFERRED", "validation only; no plan built")],
        }

    def _do_similarity(self, raw: dict[str, Any], out: dict[str, Any]) -> dict[str, Any]:
        self._validate_input_schema(raw)
        s = normalize_scenario(raw)
        out["validation"]["input_schema"] = "passed"
        sim = build_similarity(s)
        out["similarity_matrix"] = sim["rows"]
        out["non_scalable_factors"] = sim["non_scalable_factors"]
        out["scale_level"] = s.scale_level
        return {
            "summary": f"Similarity matrix for {s.scale_level}: "
                       f"{len(sim['non_scalable_factors'])} non-scalable factors identified.",
            "findings": [
                _as_labeled("CALCULATED", f"similarity rows: {len(sim['rows'])}"),
                _as_labeled("CALCULATED",
                            f"non-scalable: {', '.join(f['factor'] for f in sim['non_scalable_factors'])}"),
            ],
            "artifacts": [{"kind": "similarity_matrix", "path": None, "note": sim}],
        }

    def _do_material_balance(self, raw: dict[str, Any], out: dict[str, Any]) -> dict[str, Any]:
        self._validate_input_schema(raw)
        s = normalize_scenario(raw)
        out["validation"]["input_schema"] = "passed"
        mb = material_balance(s)
        out["material_balance"] = mb.to_dict()
        findings = [
            _as_labeled("CALCULATED",
                        f"pore volume {mb.pore_volume_m3:.3f} m3; CaCO3 required "
                        f"{mb.caco3_required_kg:.1f} kg ({mb.target_caco3_content_kg_m3:.0f} kg/m3)"
                        if mb.pore_volume_m3 is not None else
                        f"CaCO3 required {mb.caco3_required_kg:.1f} kg "
                        f"({mb.target_caco3_content_kg_m3:.0f} kg/m3); pore volume n/a "
                        "(porosity missing)",
                        source="material_balance"),
            _as_labeled("CALCULATED",
                        f"urea {mb.urea_mol:.0f} mol, Ca {mb.ca_mol:.0f} mol; cementation "
                        f"{mb.cementation_volume_m3:.1f} m3, bacteria {mb.bacteria_volume_m3:.1f} m3"
                        if mb.cementation_volume_m3 is not None and mb.bacteria_volume_m3 is not None
                        else "reagent balance requires lab concentrations",
                        source="material_balance"),
            _as_labeled("CALCULATED",
                        f"NH4-N produced {mb.nh4_n_kg:.0f} kg; porewater NH4-N "
                        f"{mb.nh4_n_conc_mg_L:.0f} mg/L"
                        if mb.nh4_n_conc_mg_L is not None else "NH4-N balance requires pore volume",
                        source="material_balance"),
        ]
        for w in mb.warnings:
            findings.append(_as_labeled("INFERRED", w, source="material_balance"))
        return {"summary": f"Material balance: {mb.caco3_required_kg:.1f} kg CaCO3 for "
                           f"{mb.treatment_volume_m3:.2f} m3.", "findings": findings,
                "artifacts": [{"kind": "material_balance", "path": None, "note": mb.to_dict()}]}

    def _do_boundary_check(self, raw: dict[str, Any], out: dict[str, Any]) -> dict[str, Any]:
        self._validate_input_schema(raw)
        s = normalize_scenario(raw)
        out["validation"]["input_schema"] = "passed"
        bc = boundary_check(s)
        out["pressure_constraints"] = bc.to_dict()
        return {
            "summary": f"Boundary {bc.flow_mode}: verdict {bc.verdict}; dP "
                       f"{bc.pressure_drop_bar:.2f} bar vs allowable "
                       f"{bc.allowable_pressure_pa / 1e5:.2f} bar"
                       if bc.pressure_drop_bar is not None and bc.allowable_pressure_pa is not None
                       else f"Boundary {bc.flow_mode}: incomplete (need permeability/allowable).",
            "findings": [_as_labeled("CALCULATED", f"pressure verdict: {bc.verdict}",
                                     source="boundary_check")]
            + [_as_labeled("INFERRED", n, source="boundary_check") for n in bc.notes],
            "artifacts": [{"kind": "boundary_check", "path": None, "note": bc.to_dict()}],
        }

    def _do_pressure_risk(self, raw: dict[str, Any], out: dict[str, Any]) -> dict[str, Any]:
        self._validate_input_schema(raw)
        s = normalize_scenario(raw)
        out["validation"]["input_schema"] = "passed"
        bc = boundary_check(s)
        out["pressure_constraints"] = bc.to_dict()
        return {
            "summary": f"Pressure risk: {bc.verdict} (dP {bc.pressure_drop_bar:.2f} bar, "
                       f"allowable {bc.allowable_pressure_pa / 1e5:.2f} bar)."
                       if bc.pressure_drop_bar is not None else "Pressure risk: incomplete.",
            "findings": [_as_labeled("CALCULATED", f"margin ratio {bc.margin_ratio:.2f}"
                          if bc.margin_ratio is not None else "margin n/a", source="pressure_risk")],
            "artifacts": [{"kind": "pressure_constraints", "path": None, "note": bc.to_dict()}],
        }

    def _do_injection_layout(self, raw: dict[str, Any], out: dict[str, Any]) -> dict[str, Any]:
        self._validate_input_schema(raw)
        s = normalize_scenario(raw)
        s._wells_raw = raw.get("wells") or {}  # layout reads the raw wells spec
        out["validation"]["input_schema"] = "passed"
        layout = build_layout(s)
        out["injection_layout"] = layout
        return {
            "summary": f"Injection layout: pattern {layout['pattern']}, "
                       f"{len([w for w in layout['wells'] if w['type'] == 'injection'])} injection wells.",
            "findings": [_as_labeled("CALCULATED",
                                     f"wells: {len(layout['wells'])} total "
                                     f"({sum(1 for w in layout['wells'] if w['type'] == 'injection')} inj, "
                                     f"{sum(1 for w in layout['wells'] if w['type'] == 'extraction')} ext, "
                                     f"{sum(1 for w in layout['wells'] if w['type'] == 'monitoring')} mon)",
                                     source="injection_layout")],
            "artifacts": [{"kind": "injection_layout", "path": None, "note": layout}],
        }

    def _do_injection_schedule(self, raw: dict[str, Any], out: dict[str, Any]) -> dict[str, Any]:
        self._validate_input_schema(raw)
        s = normalize_scenario(raw)
        out["validation"]["input_schema"] = "passed"
        bc = boundary_check(s)
        mb = material_balance(s, flow_override_m3_s=bc.injection_flow_m3_s)
        sched = build_schedule(s, mb)
        out["injection_schedule"] = sched
        return {
            "summary": f"Schedule: {sched['rounds']} cementation rounds, "
                       f"{sched['total_duration_days']} d total, pulse {sched['pulse_strategy']}.",
            "findings": [_as_labeled("CALCULATED",
                                     f"sequence: {' -> '.join(sched['sequence'])}",
                                     source="injection_schedule")],
            "artifacts": [{"kind": "injection_schedule", "path": None, "note": sched}],
        }

    def _do_monitoring_plan(self, raw: dict[str, Any], out: dict[str, Any]) -> dict[str, Any]:
        self._validate_input_schema(raw)
        s = normalize_scenario(raw)
        out["validation"]["input_schema"] = "passed"
        bc = boundary_check(s)
        plan = build_monitoring_plan(s, bc.allowable_pressure_pa, s.ammonia_limit_mg_L)
        out["monitoring_plan"] = plan
        # real-time evaluation if readings provided
        readings = raw.get("monitoring")
        mon_result = evaluate_monitoring(s, plan, readings or {})
        if mon_result["stop_signals"]:
            out["stop_conditions"] = [{"id": f"STOP-{i}", "condition": c, "action": "halt + fallback"}
                                      for i, c in enumerate(mon_result["stop_signals"])]
            # A fired stop rule must surface in status (red-team blocker):
            out["_force_partial"] = True
        return {
            "summary": (f"Monitoring plan: {len(plan['parameters'])} parameters; "
                        f"{len(mon_result['alerts'])} alerts, {len(mon_result['stop_signals'])} "
                        "stop signals."),
            "findings": [_as_labeled("CALCULATED",
                                     f"alerts: {mon_result['alerts']}", source="monitoring")
                         if mon_result["alerts"] else _as_labeled("OBSERVED",
                         "no alerts in current readings", source="monitoring")]
                        + [_as_labeled("CALCULATED", f"STOP: {c}", source="monitoring")
                           for c in mon_result["stop_signals"]],
            "artifacts": [{"kind": "monitoring_plan", "path": None, "note": plan},
                          {"kind": "monitoring_result", "path": None, "note": mon_result}],
        }

    def _do_clogging_risk(self, raw: dict[str, Any], out: dict[str, Any]) -> dict[str, Any]:
        self._validate_input_schema(raw)
        s = normalize_scenario(raw)
        out["validation"]["input_schema"] = "passed"
        cr = clogging_risk(s)
        return {
            "summary": f"Clogging risk: inlet {cr.inlet_clogging_risk}, preferential "
                       f"{cr.preferential_flow_risk}, uniformity {cr.uniformity_score:.2f} "
                       f"({cr.uniformity_verdict}).",
            "findings": [_as_labeled("CALCULATED",
                                     f"inlet clogging {cr.inlet_clogging_risk}; preferential "
                                     f"flow {cr.preferential_flow_risk}; uniformity "
                                     f"{cr.uniformity_score:.2f}", source="clogging_risk")]
            + [_as_labeled("INFERRED", d, source="clogging_risk") for d in cr.drivers],
            "artifacts": [{"kind": "clogging_risk", "path": None, "note": cr.to_dict()}],
        }

    def _do_tracer(self, raw: dict[str, Any], out: dict[str, Any]) -> dict[str, Any]:
        self._validate_input_schema(raw)
        raw_tracer = raw.get("tracer")
        ta = tracer_analysis(raw_tracer or {})
        rec = f"{ta.recovered_fraction:.2f}" if ta.recovered_fraction is not None else "n/a"
        mrt = f"{ta.mean_residence_time_s:.1f}" if ta.mean_residence_time_s is not None else "n/a"
        return {
            "summary": f"Tracer: recovery {rec}, MRT {mrt} s, "
                       f"Pe {ta.peclet_number if ta.peclet_number is not None else 'n/a'}.",
            "findings": [_as_labeled("CALCULATED", ta.verdict, source="tracer")],
            "artifacts": [{"kind": "tracer_analysis", "path": None, "note": ta.to_dict()}],
        }

    def _do_stage_gate(self, raw: dict[str, Any], out: dict[str, Any]) -> dict[str, Any]:
        self._validate_input_schema(raw)
        s = normalize_scenario(raw)
        out["validation"]["input_schema"] = "passed"
        # approval gate enforced centrally in handle(); recompute here so the
        # gate reflects the true approval state.
        approval = raw.get("human_approval_state") or {}
        bc = boundary_check(s)
        cr = clogging_risk(s)
        # nh4_over must be the actual exceedance (production > limit), not
        # merely "a limit exists" (consistency with _do_scaleup).
        mb = material_balance(s, flow_override_m3_s=bc.injection_flow_m3_s)
        nh4_over = (s.ammonia_limit_mg_L is not None and mb.nh4_n_conc_mg_L is not None
                    and mb.nh4_n_conc_mg_L > s.ammonia_limit_mg_L)
        sg = stage_gate(s, bc.verdict, cr.to_dict(), cr.uniformity_score,
                        nh4_over, bool(approval.get("granted")))
        out["stop_conditions"] = sg["stop_conditions"]
        out["fallback_plan"] = sg["fallback_plan"]
        return {
            "summary": sg["summary"],
            "findings": [_as_labeled("CALCULATED", sg["summary"], source="stage_gate")]
            + [_as_labeled("INFERRED", b, source="stage_gate")
               for g in sg["gates"] for b in g["blocked_reasons"]],
            "artifacts": [{"kind": "stage_gate", "path": None, "note": sg}],
        }

    def _do_generate_tables(self, raw: dict[str, Any], out: dict[str, Any]) -> dict[str, Any]:
        self._validate_input_schema(raw)
        s = normalize_scenario(raw)
        out["validation"]["input_schema"] = "passed"
        bc = boundary_check(s)
        mb = material_balance(s, flow_override_m3_s=bc.injection_flow_m3_s)
        sched = build_schedule(s, mb)
        tables = {
            "construction_parameters": [
                {"parameter": "scale_level", "value": s.scale_level},
                {"parameter": "treatment_volume_m3", "value": mb.treatment_volume_m3},
                {"parameter": "pore_volume_m3", "value": mb.pore_volume_m3},
                {"parameter": "effective_porosity", "value": mb.effective_porosity},
                {"parameter": "target_caco3_kg_m3", "value": mb.target_caco3_content_kg_m3},
                {"parameter": "caco3_required_kg", "value": mb.caco3_required_kg},
                {"parameter": "urea_mol", "value": mb.urea_mol},
                {"parameter": "ca_mol", "value": mb.ca_mol},
                {"parameter": "cementation_volume_m3", "value": mb.cementation_volume_m3},
                {"parameter": "bacteria_volume_m3", "value": mb.bacteria_volume_m3},
                {"parameter": "total_injection_volume_m3", "value": mb.total_injection_volume_m3},
                {"parameter": "nh4_n_kg", "value": mb.nh4_n_kg},
                {"parameter": "nh4_n_porewater_mg_L", "value": mb.nh4_n_conc_mg_L},
                {"parameter": "injection_flow_L_min", "value": (mb.injection_flow_m3_s * 60e3)
                 if mb.injection_flow_m3_s else None},
                {"parameter": "injection_pressure_limit_bar",
                 "value": (bc.allowable_pressure_pa / 1e5) if bc.allowable_pressure_pa else None},
                {"parameter": "rounds", "value": sched["rounds"]},
                {"parameter": "total_duration_days", "value": sched["total_duration_days"]},
                {"parameter": "flushing_pv", "value": sched["flushing_pv"]},
            ],
            "monitoring_table": [
                {"name": p["name"], "frequency": p["frequency"],
                 "alarm_high": p["thresholds"]["alarm_high"],
                 "stop_high": p["thresholds"]["stop_high"]}
                for p in build_monitoring_plan(s, bc.allowable_pressure_pa,
                                               s.ammonia_limit_mg_L)["parameters"]
            ],
        }
        return {
            "summary": f"Construction parameter table ({len(tables['construction_parameters'])} "
                       f"rows) and monitoring table ({len(tables['monitoring_table'])} rows).",
            "findings": [_as_labeled("CALCULATED",
                                     "tables generated for construction + monitoring",
                                     source="generate_tables")],
            "artifacts": [{"kind": "tables", "path": None, "note": tables}],
        }

    def _do_scaleup(self, raw: dict[str, Any], out: dict[str, Any]) -> dict[str, Any]:
        self._validate_input_schema(raw)
        s = normalize_scenario(raw)
        out["validation"]["input_schema"] = "passed"
        # Field approval gate is enforced centrally in handle() before this
        # handler runs (closes the 11-action bypass).

        # similarity
        sim = build_similarity(s)
        out["similarity_matrix"] = sim["rows"]
        out["non_scalable_factors"] = sim["non_scalable_factors"]

        # boundary + pressure (FIRST: back-calculates flow when none given,
        # which material_balance and schedule consume)
        bc = boundary_check(s)

        # material balance
        mb = material_balance(s, flow_override_m3_s=bc.injection_flow_m3_s)
        out["material_balance"] = mb.to_dict()
        out["pressure_constraints"] = bc.to_dict()

        # layout + schedule
        s._wells_raw = raw.get("wells") or {}
        layout = build_layout(s)
        out["injection_layout"] = layout
        sched = build_schedule(s, mb)
        out["injection_schedule"] = sched

        # monitoring
        mon_plan = build_monitoring_plan(s, bc.allowable_pressure_pa, s.ammonia_limit_mg_L)
        out["monitoring_plan"] = mon_plan

        # clogging
        cr = clogging_risk(s)
        cr_dict = cr.to_dict()

        # stage gate
        approval = raw.get("human_approval_state") or {}
        nh4_over = (s.ammonia_limit_mg_L is not None and mb.nh4_n_conc_mg_L is not None
                    and mb.nh4_n_conc_mg_L > s.ammonia_limit_mg_L)
        sg = stage_gate(s, bc.verdict, cr_dict, cr.uniformity_score,
                        nh4_over, bool(approval.get("granted")))
        out["stop_conditions"] = sg["stop_conditions"]
        out["fallback_plan"] = sg["fallback_plan"]

        # environmental requirements
        out["environmental_requirements"] = self._environmental(s, mb)

        # real-time monitoring evaluation if readings provided
        readings = raw.get("monitoring")
        mon_result = evaluate_monitoring(s, mon_plan, readings or {})
        if mon_result["stop_signals"]:
            out["stop_conditions"] = (out["stop_conditions"] or []) + [
                {"id": f"RT-{i}", "condition": c, "action": "halt + fallback"}
                for i, c in enumerate(mon_result["stop_signals"])
            ]

        # site assumptions
        out["site_assumptions"] = self._site_assumptions(s, mb, bc, cr_dict)
        out["scale_level"] = s.scale_level

        # tracer if provided
        if raw.get("tracer"):
            try:
                ta = tracer_analysis(raw["tracer"])
                out["artifacts"].append({"kind": "tracer_analysis", "path": None, "note": ta.to_dict()})
            except OpError as exc:
                out["errors"].append(exc.to_dict())

        # self-check of material balance
        mb_checks = vcheck.check_material_balance(out["material_balance"])
        out["validation"]["checks"] = mb_checks

        findings = [
            _as_labeled("CALCULATED",
                        f"scale {s.scale_level}: volume {mb.treatment_volume_m3:.2f} m3, "
                        f"pore {mb.pore_volume_m3:.3f} m3, CaCO3 {mb.caco3_required_kg:.1f} kg"
                        if mb.pore_volume_m3 is not None else
                        f"scale {s.scale_level}: volume {mb.treatment_volume_m3:.2f} m3, "
                        f"CaCO3 {mb.caco3_required_kg:.1f} kg",
                        source="scaleup"),
            _as_labeled("CALCULATED",
                        f"pressure {bc.verdict}: dP {bc.pressure_drop_bar:.2f} bar vs "
                        f"allowable {bc.allowable_pressure_pa / 1e5:.2f} bar"
                        if bc.pressure_drop_bar is not None and bc.allowable_pressure_pa is not None
                        else "pressure: incomplete (missing permeability/allowable)",
                        source="scaleup"),
            _as_labeled("CALCULATED",
                        f"uniformity {cr.uniformity_score:.2f} ({cr.uniformity_verdict}); "
                        f"inlet clogging {cr.inlet_clogging_risk}",
                        source="scaleup"),
            _as_labeled("CALCULATED",
                        f"NH4-N {mb.nh4_n_kg:.1f} kg "
                        f"({mb.nh4_n_conc_mg_L:.0f} mg/L porewater)"
                        if mb.nh4_n_conc_mg_L is not None else
                        f"NH4-N {mb.nh4_n_kg:.1f} kg",
                        source="scaleup"),
        ]
        if mb.warnings:
            for w in mb.warnings:
                findings.append(_as_labeled("INFERRED", w, source="material_balance"))
        if cr.drivers:
            for d in cr.drivers:
                findings.append(_as_labeled("INFERRED", d, source="clogging_risk"))
        if sg["human_approval_required"]:
            findings.append(_as_labeled("INFERRED",
                                        "field deployment awaits HUMAN approval (six items)",
                                        source="stage_gate"))
        if not sg["gate_ok"]:
            blocked = [b for g in sg["gates"] for b in g["blocked_reasons"]]
            for b in blocked:
                findings.append(_as_labeled("INFERRED", f"gate block: {b}", source="stage_gate"))
            # A blocked gate must NOT report a clean SUCCESS (red-team blocker).
            out["_force_partial"] = True
        if mon_result["stop_signals"]:
            for c in mon_result["stop_signals"]:
                findings.append(_as_labeled("CALCULATED",
                                            f"RT stop: {c}", source="monitoring"))

        assumptions = [
            _as_labeled("INFERRED",
                        "conversion_efficiency design default 0.5 unless provided; VP2010 "
                        "reports ~0.12 in a 1 m3 box — pilot must verify", source="assumptions"),
            _as_labeled("INFERRED",
                        "overburden assumed saturated bulk density 2000 kg/m3; fracture "
                        "pressure = 2x overburden (classic borehole criterion); safe limit "
                        "= 80% of fracture (OEGG 2017)", source="assumptions"),
            _as_labeled("INFERRED",
                        "bacteria suspension volume assumed 0.5 PV (Gomez 2017 used 0.5 PV "
                        "injection)", source="assumptions"),
            _as_labeled("REPORTED",
                        "uniformity degrades with scale; lab uniformity is NOT representative "
                        "(VP2010 m3 box)", source="assumptions"),
        ]
        out["assumptions"] = assumptions

        evidence_used = [
            "AS2013 Al Qabany & Soga 2013 (concentration window)",
            "VP2010 van Paassen 2010 (scale-up data, conversion, gradient<1)",
            "OEGG2017 (pressure ~80% fracture, 5-15 L/min)",
            "GA2017/GA2018 Gomez et al. (0.5 PV, Vs detection)",
        ]
        out["evidence_used"] = evidence_used

        summary = (f"Scale-up plan {s.scale_level}: {mb.caco3_required_kg:.0f} kg CaCO3 over "
                   f"{mb.treatment_volume_m3:.2f} m3; pressure {bc.verdict}; uniformity "
                   f"{cr.uniformity_score:.2f}; NH4-N {mb.nh4_n_conc_mg_L:.0f} mg/L"
                   if mb.nh4_n_conc_mg_L is not None else
                   f"Scale-up plan {s.scale_level}: {mb.caco3_required_kg:.0f} kg CaCO3 over "
                   f"{mb.treatment_volume_m3:.2f} m3; pressure {bc.verdict}.")
        if s.scale_level == "field":
            if sg["human_approval_required"]:
                summary += " [field construction BLOCKED: awaits HUMAN approval (six items)]"
            elif sg["gate_ok"]:
                summary += " [approved and gate-pass — construction plan may be finalized]"
            else:
                summary += " [approved but gate NOT passed — resolve blocked reasons first]"
        else:
            summary += (" [preliminary plan; stage gate "
                        f"{'PASS' if sg['gate_ok'] else 'BLOCKED'}]")

        return {
            "summary": summary,
            "findings": findings,
            "assumptions": assumptions,
            "evidence_used": evidence_used,
            "artifacts": out["artifacts"] + [
                {"kind": "similarity_matrix", "path": None, "note": sim},
                {"kind": "material_balance", "path": None, "note": mb.to_dict()},
                {"kind": "pressure_constraints", "path": None, "note": bc.to_dict()},
                {"kind": "injection_layout", "path": None, "note": layout},
                {"kind": "injection_schedule", "path": None, "note": sched},
                {"kind": "monitoring_plan", "path": None, "note": mon_plan},
                {"kind": "clogging_risk", "path": None, "note": cr_dict},
                {"kind": "stage_gate", "path": None, "note": sg},
            ],
        }

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _site_assumptions(s, mb, bc, cr) -> list[str]:
        out = []
        if s.layers:
            for lyr in s.layers:
                out.append(f"layer {lyr.name}: h={lyr.thickness_m:.2f} m, "
                           f"k={lyr.permeability_m2:.2e} m2"
                           if lyr.permeability_m2 is not None else f"layer {lyr.name}: h={lyr.thickness_m:.2f} m")
        if s.effective_permeability_m2 is not None:
            out.append(f"effective permeability (harmonic) = {s.effective_permeability_m2:.2e} m2")
        if s.effective_porosity is not None:
            out.append(f"effective porosity = {s.effective_porosity:.3f}")
        if s.preferential_flow_notes:
            out.append(f"preferential flow: {s.preferential_flow_notes}")
        return out

    @staticmethod
    def _environmental(s, mb) -> dict[str, Any]:
        over_limit = (s.ammonia_limit_mg_L is not None and mb.nh4_n_conc_mg_L is not None
                      and mb.nh4_n_conc_mg_L > s.ammonia_limit_mg_L)
        limit_missing = s.ammonia_limit_mg_L is None
        return {
            "ammonia_n_produced_kg": mb.nh4_n_kg,
            "ammonia_n_porewater_mg_L": mb.nh4_n_conc_mg_L,
            "site_limit_mg_L": s.ammonia_limit_mg_L,
            "over_limit": over_limit,
            "limit_missing": limit_missing,
            "limit_status": ("missing — discharge limit NOT established; effluent must "
                             "not be discharged until a limit is set"
                             if limit_missing else
                             f"{'EXCEEDS' if over_limit else 'within'} limit "
                             f"{s.ammonia_limit_mg_L:.0f} mg/L"),
            "treatment_options": [
                "struvite (NH4MgPO4·6H2O) recovery: ~90% NH4-N removal (Gowthaman 2022)",
                "anaerobic ammonium oxidation (Anammox) for concentrated effluent",
                "zeolite amendment reduces ammonia release (Su et al. 2022)",
                "flushing (N pore volumes) to dilute + recover residual ammonium",
            ],
            "discharge_requirement": "effluent NH4-N must be below site limit before discharge; "
                                     "treat or recover (never discharge untreated)",
        }
