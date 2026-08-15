"""Service layer: dispatch an input payload to the correct handler and build
the unified output envelope (Obsidian Plan spec §六).

Handlers are pure functions in the sibling modules; this module owns the
envelope shape, the epistemic-label stamping, and the self-check.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any, Callable

from .analysis import (
    analyze_contradictory_data,
    assess_treatment_strategy,
    compare_batches,
    salinity_assessment,
    urease_yield_urea_to_ammonia,
)
from .errors import MbrError, MbrErrorCode
from .kinetics import (
    fit_first_order_decay,
    fit_logistic_growth,
    sensitivity_elasticity,
)
from .units import activity_to_u_per_ml, cell_concentration_from_od, specific_urease_activity
from .validate import check_output_schema, validate_input

SKILL_NAME = "micp-biology-reasoner"
SKILL_VERSION = "0.1.0"
CONTRACT_MAJOR = "1"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _clock_from_env() -> Callable[[], str] | None:
    fixed = os.environ.get("MBR_TEST_CLOCK")
    return (lambda: fixed) if fixed else None


class BiologyReasonerService:
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
                payload,
                started,
                status="FAILED",
                summary=f"contract_version major {major} is not supported (expected {CONTRACT_MAJOR}).",
                errors=[MbrError(
                    MbrErrorCode.UNSUPPORTED_SCHEMA_VERSION,
                    detail={"got": cv, "expected_major": CONTRACT_MAJOR},
                )],
            )
        # 2. input schema validation
        violations = validate_input(payload)
        if violations:
            detail = {"violations": violations, "missing_fields": self._extract_missing(violations, payload)}
            return self._envelope(
                payload,
                started,
                status="BLOCKED",
                summary="Input does not conform to schemas/input.schema.json; see errors for missing/invalid fields.",
                errors=[MbrError(
                    MbrErrorCode.INPUT_SCHEMA_VIOLATION,
                    detail=detail,
                )],
            )
        # 3. dispatch
        action = payload.get("action")
        try:
            result = self._dispatch(action, payload)
        except MbrError as exc:
            return self._envelope(payload, started, status="FAILED", summary=str(exc.message), errors=[exc])
        except Exception as exc:  # unexpected: wrap, do not crash
            return self._envelope(
                payload,
                started,
                status="FAILED",
                summary=f"Unexpected internal error: {exc}",
                errors=[MbrError(MbrErrorCode.CONTEXT_CORRUPT, detail={"error": str(exc)})],
            )

        # 4. stamp + self-check
        out = self._envelope(payload, started, status="SUCCESS", summary=result["summary"], extra=result)
        try:
            self._self_check(out)
            out["validation"]["self_check"] = "passed"
        except MbrError as exc:
            out["status"] = "FAILED"
            out["validation"]["self_check"] = "failed"
            out["errors"] = [exc.to_dict()]

        # 5. output schema validation
        try:
            check_output_schema(out)
            out["validation"]["output_schema"] = "passed"
        except MbrError as exc:
            out["validation"]["output_schema"] = "failed"
            out["status"] = "FAILED"
            out["errors"] = [exc.to_dict()]
        return out

    # ------------------------------------------------------------------ #
    def _dispatch(self, action: str, payload: dict[str, Any]) -> dict[str, Any]:
        handlers: dict[str, Callable[[dict[str, Any]], dict[str, Any]]] = {
            "analyze": self._handle_analyze,
            "compare": self._handle_compare,
            "assess": self._handle_assess,
            "convert": self._handle_convert,
            "evaluate": self._handle_evaluate,
        }
        fn = handlers.get(action)
        if fn is None:
            raise MbrError(
                MbrErrorCode.INPUT_SCHEMA_VIOLATION,
                f"Unknown action '{action}'. Supported: {', '.join(handlers)}.",
                detail={"action": action},
            )
        return fn(payload)

    def _handle_analyze(self, payload: dict[str, Any]) -> dict[str, Any]:
        request = (payload.get("request") or "").lower()
        records = payload.get("records")
        # contradictory-data analysis
        if records is not None:
            res = analyze_contradictory_data(records)
            return {
                "summary": "Contradictory biological records analyzed for metric conflation.",
                "findings": res["findings"],
                "artifacts": [{"kind": "metric_scan", "path": None, "note": {"metrics_seen": res["metrics_seen"]}}],
                "assumptions": [],
                "evidence_used": [],
                "uncertainty": ["Metric-seen set is derived from provided records only."],
                "risks": [],
            }
        # growth-curve / retention / inactivation fitting
        culture = payload.get("culture") or {}
        attachments = payload.get("attachments") or {}
        findings: list[dict[str, Any]] = []
        artifacts: list[dict[str, Any]] = []
        if culture.get("od600") is not None and request and any(k in request for k in ("growth", "曲线", "生长", "logistic")):
            res = fit_logistic_growth(culture.get("time_points_h") or [], culture.get("od600_series") or [])
            findings.append({"label": "CALCULATED", "statement": f"Logistic growth fit: K={res['K']:.4g}, r={res['r_per_h']:.4g} 1/h, doubling={res['doubling_h']:.3g} h, R2={res['r2']:.3f}."})
            artifacts.append({"kind": "fit", "path": None, "note": res})
        ret = attachments.get("retention") or {}
        if ret.get("time_points_h") and ret.get("retained_fraction"):
            res = fit_first_order_decay(ret["time_points_h"], ret["retained_fraction"], y_name="retained_fraction")
            findings.append({"label": "CALCULATED", "statement": f"Retention first-order fit: k={res['k_per_h']:.4g} 1/h, half-life={res['halflife_h']:.3g} h, R2={res['r2']:.3f}."})
            artifacts.append({"kind": "fit_retention", "path": None, "note": res})
        inactivation = attachments.get("inactivation") or {}
        if inactivation.get("time_points_h") and inactivation.get("viable_fraction"):
            res = fit_first_order_decay(inactivation["time_points_h"], inactivation["viable_fraction"], y_name="viable_fraction")
            findings.append({"label": "CALCULATED", "statement": f"Inactivation first-order fit: k={res['k_per_h']:.4g} 1/h, half-life={res['halflife_h']:.3g} h, R2={res['r2']:.3f}."})
            artifacts.append({"kind": "fit_inactivation", "path": None, "note": res})
        if not findings:
            raise MbrError(
                MbrErrorCode.MISSING_REQUIRED_FIELD,
                "analyze requires a 'records' array for metric-conflation analysis, OR culture/attachments "
                "with time-series for kinetic fitting. None were present.",
                detail={"available": ["records", "culture.time_points_h+od600_series", "attachments.retention", "attachments.inactivation"]},
            )
        return {
            "summary": "Analysis produced findings from the provided biological data.",
            "findings": findings,
            "artifacts": artifacts,
            "assumptions": [],
            "evidence_used": payload.get("evidence_refs") or [],
            "uncertainty": ["Fit validity limited to the provided time range."],
            "risks": [],
        }

    def _handle_compare(self, payload: dict[str, Any]) -> dict[str, Any]:
        batch_a = payload.get("culture") or {}
        batch_b = (payload.get("baseline") or {}).get("culture") or {}
        if not batch_a or not batch_b:
            raise MbrError(
                MbrErrorCode.MISSING_REQUIRED_FIELD,
                "compare requires both 'culture' (batch A) and 'baseline.culture' (batch B).",
                detail={"fields": ["culture", "baseline.culture"]},
            )
        res = compare_batches(batch_a, batch_b)
        return {
            "summary": f"Batches compared: same OD600={res['same_od600']}, activity identical={res['activity_identical']}.",
            "findings": res["findings"],
            "artifacts": [{"kind": "comparison", "path": None, "note": {
                "same_od600": res["same_od600"],
                "activity_identical": res["activity_identical"],
                "activity_ratio_a_over_b": res["activity_ratio_a_over_b"],
            }}],
            "assumptions": ["OD600 compared only as biomass; activity normalized to U/mL when both units given."],
            "evidence_used": payload.get("evidence_refs") or [],
            "uncertainty": [] if res["activity_ratio_a_over_b"] is not None else ["One or both batches lack activity data; ratio not computed."],
            "risks": [],
        }

    def _handle_assess(self, payload: dict[str, Any]) -> dict[str, Any]:
        # salinity assessment (spec §八.2)
        culture = payload.get("culture") or {}
        conditions = payload.get("conditions") or {}
        salinity = conditions.get("salinity")
        if salinity is not None:
            res = salinity_assessment(
                culture.get("name") or "unknown strain",
                salinity=salinity,
                observed_evidence=bool(conditions.get("measured_at_salinity", False)),
            )
            findings = [{"label": res["evidence_label"], "statement": res["statement"]}]
            if res["insufficient_evidence"]:
                findings.append({
                    "label": "RECOMMENDATION",
                    "statement": "Evidence insufficient for this strain at this salinity. Obtain growth (OD600 series) and urease activity measurements at the target salinity before any OBSERVED claim.",
                })
            return {
                "summary": f"Salinity assessment at {salinity} g/L completed with evidence label {res['evidence_label']}.",
                "findings": findings,
                "artifacts": [{"kind": "salinity_assessment", "path": None, "note": res}],
                "assumptions": ["Salinity expressed as g/L NaCl-equivalent."],
                "evidence_used": payload.get("evidence_refs") or [],
                "uncertainty": [] if not res["insufficient_evidence"] else ["No strain-specific high-salt data."],
                "risks": [{"label": "INFERRED", "statement": "High-salt conclusions without direct data risk over-claiming (MBR-E206)."}],
            }
        # treatment-strategy assessment (spec §四.4, §八.3)
        treatment = payload.get("treatment")
        if treatment is not None:
            res = assess_treatment_strategy(treatment, context=payload.get("context"))
            return {
                "summary": f"Treatment strategy '{treatment}' assessed.",
                "findings": res["findings"],
                "artifacts": [{"kind": "treatment_strategy", "path": None, "note": {
                    "treatment": treatment,
                    "rationale": "Mechanistic evaluation grounded in Graddy 2021 / Dhami 2017 / Babaeizad 2025.",
                }}],
                "assumptions": ["Community dynamics inferred from literature; site-specific data would upgrade confidence."],
                "evidence_used": payload.get("evidence_refs") or [],
                "uncertainty": ["Spatial uniformity claims depend on site hydraulic/geochemical context."],
                "risks": [],
            }
        raise MbrError(
            MbrErrorCode.MISSING_REQUIRED_FIELD,
            "assess requires either 'conditions.salinity' (salinity assessment) or 'treatment' (strategy assessment).",
            detail={"fields": ["conditions.salinity", "treatment"]},
        )

    def _handle_convert(self, payload: dict[str, Any]) -> dict[str, Any]:
        culture = payload.get("culture") or {}
        mq = payload.get("metric_query") or {}
        kind = mq.get("kind")
        artifacts: list[dict[str, Any]] = []
        findings: list[dict[str, Any]] = []
        if kind == "activity_normalization":
            activity = culture.get("urease_activity")
            unit = culture.get("urease_activity_unit")
            if activity is None:
                raise MbrError(
                    MbrErrorCode.MISSING_REQUIRED_FIELD,
                    "activity_normalization requires culture.urease_activity.",
                    detail={"fields": ["urease_activity"]},
                )
            if unit is None or str(unit).strip() == "":
                # domain-coded: activity without a unit is a unit-consistency
                # failure, not a generic missing-field failure.
                raise MbrError(
                    MbrErrorCode.UNIT_INCONSISTENT,
                    "activity_normalization requires culture.urease_activity_unit "
                    "(total activity has no meaning without a unit). Obtain the "
                    "unit from the assay method/experimental record.",
                    detail={"fields": ["urease_activity_unit"]},
                )
            # total -> U/mL
            res = activity_to_u_per_ml(float(activity), unit)
            findings.append({"label": "CALCULATED", "statement": f"Activity {activity} {unit} -> {res['u_per_ml']:.4g} U/mL ({res['interpretation']})."})
            artifacts.append({"kind": "unit_conversion", "path": None, "note": res})
            # specific, if a denominator is present
            denom = mq.get("denominator") or {}
            if denom.get("value") is not None:
                sp = specific_urease_activity(float(activity), unit, float(denom["value"]), denom.get("kind", "od600"))
                findings.append({"label": "CALCULATED", "statement": f"Specific activity: {sp['specific']:.4g} {sp['unit']}."})
                artifacts.append({"kind": "specific_activity", "path": None, "note": sp})
        elif kind == "cell_concentration":
            od = culture.get("od600")
            if od is None:
                raise MbrError(MbrErrorCode.MISSING_REQUIRED_FIELD, "cell_concentration requires culture.od600.", detail={"fields": ["od600"]})
            res = cell_concentration_from_od(float(od), calibration=mq.get("calibration"))
            findings.append({"label": "CALCULATED", "statement": f"OD600={od} -> {res['cfu_per_ml']:.3e} CFU/mL via explicit calibration."})
            artifacts.append({"kind": "cell_concentration", "path": None, "note": res})
        else:
            raise MbrError(
                MbrErrorCode.INPUT_SCHEMA_VIOLATION,
                f"convert does not support metric_query.kind '{kind}'. Supported: activity_normalization, cell_concentration.",
                detail={"kind": kind},
            )
        return {
            "summary": "Conversion/normalization completed.",
            "findings": findings,
            "artifacts": artifacts,
            "assumptions": ["Unit conversions follow the curated unit grammar in tools/micp_bio/units.py."],
            "evidence_used": payload.get("evidence_refs") or [],
            "uncertainty": [],
            "risks": [],
        }

    def _handle_evaluate(self, payload: dict[str, Any]) -> dict[str, Any]:
        mq = payload.get("metric_query") or {}
        kind = mq.get("kind")
        if kind == "retention_rate":
            att = (payload.get("attachments") or {}).get("retention") or {}
            if att.get("time_points_h") and att.get("retained_fraction"):
                res = fit_first_order_decay(att["time_points_h"], att["retained_fraction"], y_name="retained_fraction")
                return {
                    "summary": f"Retention rate k={res['k_per_h']:.4g} 1/h.",
                    "findings": [{"label": "CALCULATED", "statement": f"First-order retention k={res['k_per_h']:.4g} 1/h, half-life {res['halflife_h']:.3g} h, R2={res['r2']:.3f}."}],
                    "artifacts": [{"kind": "retention_fit", "path": None, "note": res}],
                    "assumptions": [], "evidence_used": payload.get("evidence_refs") or [],
                    "uncertainty": [], "risks": [],
                }
            raise MbrError(MbrErrorCode.MISSING_REQUIRED_FIELD, "retention_rate requires attachments.retention.time_points_h + retained_fraction.")
        if kind == "inactivation_rate":
            att = (payload.get("attachments") or {}).get("inactivation") or {}
            if att.get("time_points_h") and att.get("viable_fraction"):
                res = fit_first_order_decay(att["time_points_h"], att["viable_fraction"], y_name="viable_fraction")
                return {
                    "summary": f"Inactivation rate k={res['k_per_h']:.4g} 1/h.",
                    "findings": [{"label": "CALCULATED", "statement": f"First-order inactivation k={res['k_per_h']:.4g} 1/h, half-life {res['halflife_h']:.3g} h, R2={res['r2']:.3f}."}],
                    "artifacts": [{"kind": "inactivation_fit", "path": None, "note": res}],
                    "assumptions": [], "evidence_used": payload.get("evidence_refs") or [],
                    "uncertainty": [], "risks": [],
                }
            raise MbrError(MbrErrorCode.MISSING_REQUIRED_FIELD, "inactivation_rate requires attachments.inactivation.time_points_h + viable_fraction.")
        if kind == "sensitivity":
            sens = mq.get("sensitivity") or {}
            parameter = sens.get("parameter")
            base = sens.get("base_value")
            pct = sens.get("range_pct")
            if parameter is None or base is None or pct is None:
                raise MbrError(MbrErrorCode.MISSING_REQUIRED_FIELD, "sensitivity requires metric_query.sensitivity.parameter/base_value/range_pct.")
            # Build a model: if an explicit fn is provided (JSON can't carry it),
            # fall back to a documented heuristic: output proportional to k for
            # first-order decay half-life... Use caller-provided fn via exec-free
            # lambda factory: sensitivity.linear_scale can be set.
            linear = sens.get("linear_scale", 1.0)
            res = sensitivity_elasticity(lambda p: linear * p, float(base), float(pct))
            # interpret elasticity
            return {
                "summary": f"Local sensitivity elasticity = {res['elasticity']:.4g}.",
                "findings": [{"label": "CALCULATED", "statement": f"Elasticity {res['elasticity']:.4g} wrt parameter '{parameter}' (±{pct}%). {res['interpretation']}"}],
                "artifacts": [{"kind": "sensitivity", "path": None, "note": res}],
                "assumptions": ["Sensitivity uses a linear placeholder model unless a real model function is supplied (see tools)."],
                "evidence_used": payload.get("evidence_refs") or [],
                "uncertainty": ["Elasticity is local; not valid far from the base point."],
                "risks": [],
            }
        if kind == "urease_mass_balance":
            urea_mM = mq.get("urea_consumed_mM")
            if urea_mM is None:
                raise MbrError(MbrErrorCode.MISSING_REQUIRED_FIELD, "urease_mass_balance requires metric_query.urea_consumed_mM.")
            res = urease_yield_urea_to_ammonia(float(urea_mM))
            return {
                "summary": f"{res['urea_consumed_mM']:g} mM urea -> {res['ammonium_produced_mM']:g} mM NH4+.",
                "findings": [{"label": "CALCULATED", "statement": f"Urea consumed {res['urea_consumed_mM']:g} mM yields {res['ammonium_produced_mM']:g} mM NH4+ ({res['stoichiometry']})."}],
                "artifacts": [{"kind": "mass_balance", "path": None, "note": res}],
                "assumptions": ["Complete ureolysis stoichiometry; no NH3 volatilization loss."],
                "evidence_used": payload.get("evidence_refs") or [],
                "uncertainty": ["Real systems lose some NH3 to volatilization; this is an upper bound."],
                "risks": [],
            }
        raise MbrError(
            MbrErrorCode.INPUT_SCHEMA_VIOLATION,
            f"evaluate does not support metric_query.kind '{kind}'. Supported: retention_rate, inactivation_rate, sensitivity, urease_mass_balance.",
            detail={"kind": kind},
        )

    # ------------------------------------------------------------------ #
    def _self_check(self, out: dict[str, Any]) -> None:
        """Re-run cheap invariants; raise MbrError on failure (MBR-E702)."""
        # Every finding must carry a valid epistemic label.
        valid_labels = {"OBSERVED", "REPORTED", "CALCULATED", "INFERRED", "HYPOTHESIS", "RECOMMENDATION"}
        for f in out.get("findings", []):
            label = f.get("label")
            if label not in valid_labels:
                raise MbrError(MbrErrorCode.SELF_CHECK_FAILED, f"Finding has invalid epistemic label '{label}'.", detail={"statement": f.get("statement")})
            if label in ("INFERRED", "HYPOTHESIS", "RECOMMENDATION"):
                if f.get("statement", "").lower().startswith("observed"):
                    raise MbrError(MbrErrorCode.SELF_CHECK_FAILED, "A non-OBSERVED label claims observation.", detail={"statement": f.get("statement")})
        # status coherence: BLOCKED must not carry findings of label OBSERVED
        if out.get("status") == "BLOCKED" and any(f.get("label") == "OBSERVED" for f in out.get("findings", [])):
            raise MbrError(MbrErrorCode.SELF_CHECK_FAILED, "BLOCKED envelope cannot assert OBSERVED findings.")

    def _extract_missing(self, violations: list[str], payload: dict[str, Any]) -> list[str]:
        missing: list[str] = []
        for v in violations:
            if "required" in v and "property" in v:
                # jsonschema style: "'task_id' is a required property"
                field = v.split("'")[1]
                missing.append(field)
        return missing

    # ------------------------------------------------------------------ #
    def _envelope(
        self,
        payload: dict[str, Any],
        started: str,
        *,
        status: str,
        summary: str,
        errors: list[MbrError] | None = None,
        extra: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
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
            "provenance": {
                "started_at": started,
                "completed_at": completed,
                "host": None,
            },
            "errors": [e.to_dict() for e in (errors or [])],
        }
        # requested_next_skills default: bio-safety audit for field deployment
        if status == "SUCCESS" and not out["requested_next_skills"] and payload.get("risk_level") == "high":
            out["requested_next_skills"] = [{
                "skill": "obsidian-env-biosafety-audit",
                "reason": "High-risk biological deployment; biosafety conclusions must be audited by the dedicated skill.",
                "inputs_needed": ["evidence_refs", "conditions", "treatment"],
            }]
        return out
