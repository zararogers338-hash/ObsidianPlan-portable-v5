"""Service facade for micp-porous-media-transport.

Pipeline for every invocation (mirrors the state-manager pattern):
  1. envelope construction
  2. input schema validation (OPM-E1xx) + contract-version gate (OPM-E801)
  3. scenario normalization (OPM-E102 MODEL_BLOCKED on missing boundary conditions)
  4. action dispatch
  5. output self-check (schema + conservation + epistemic labels) (OPM-E701/E702)
  6. return the unified envelope (spec §六) — always parseable.

Actions:
  analyze        full pipeline: normalize -> dimensionless -> solve -> clogging
                 -> conservation checks -> self-check
  dimensionless  dimensionless analysis only (no numerical solve)
  validate       scenario validation only (dry-run gate before solving)
  clogging       run clogging criteria on provided profiles (no solve)

The service never touches the network and only writes artifacts when the
caller supplies an artifact directory (default: none).
"""

from __future__ import annotations

import json
import math
import platform
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import clogging as clogging_mod
from .dimensionless import dimensionless_numbers
from .errors import OpError, OpErrorCode
from .models import CONTRACT_VERSION, EpistemicLabel, OutputStatus, SKILL_NAME, SKILL_VERSION
from .observability import get_logger
from .scenario import normalize_scenario
from .solver import solve_transport, SolverConfig
from .units import check_finite, parse_quantity
from . import validate as vcheck


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _as_labeled(label: str, statement: str, source: str | None = None) -> dict[str, Any]:
    return {"label": label, "statement": statement, "source": source}


class MicpService:
    def __init__(self, *, artifact_dir: str | None = None) -> None:
        self.artifact_dir = artifact_dir
        self.log = get_logger()

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
            handler = getattr(self, f"_do_{action.replace('.', '_')}")
            result = handler(raw, out)
            out.update(result)
            if out.get("errors"):
                out["status"] = OutputStatus.PARTIAL.value
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

    @staticmethod
    def actions() -> list[str]:
        return ["analyze", "dimensionless", "validate", "clogging"]

    # ------------------------------------------------------------------
    # envelope + error plumbing
    # ------------------------------------------------------------------
    def _envelope(self, raw: dict[str, Any], started: str) -> dict[str, Any]:
        return {
            "contract_version": CONTRACT_VERSION,
            "skill": SKILL_NAME,
            "skill_version": SKILL_VERSION,
            "status": OutputStatus.FAILED.value,
            "summary": "",
            "action": raw.get("action"),
            "project_id": raw.get("project_id"),
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

    def _finalize_self_check(self, out: dict[str, Any]) -> None:
        """Self-check: output envelope is coherent and every finding is labeled."""
        checks = out["validation"].get("checks", [])
        checks.append({"name": "envelope_shape", "passed": bool(out.get("summary"))})
        checks.append({
            "name": "status_valid",
            "passed": out.get("status") in ("SUCCESS", "PARTIAL", "BLOCKED", "FAILED",
                                            "NEED_ADDITIONAL_SKILL", "HUMAN_APPROVAL_REQUIRED"),
        })
        mislabeled = [
            f for f in out.get("findings", [])
            if f.get("label") not in (
                "OBSERVED", "REPORTED", "CALCULATED", "INFERRED", "HYPOTHESIS", "RECOMMENDATION")
        ]
        checks.append({"name": "epistemic_labels", "passed": not mislabeled,
                       "detail": f"{len(mislabeled)} mislabeled finding(s)" if mislabeled else ""})
        ok = all(c.get("passed") for c in checks)
        out["validation"]["self_check"] = "passed" if ok else "failed"
        out["validation"]["checks"] = checks

    # ------------------------------------------------------------------
    # actions
    # ------------------------------------------------------------------
    def _do_validate(self, raw: dict[str, Any], out: dict[str, Any]) -> dict[str, Any]:
        """Scenario validation only (dry-run gate): normalize, report, no solve."""
        scenario = raw.get("scenario") or {}
        norm = normalize_scenario(scenario)
        out["validation"]["input_schema"] = "passed"
        return {
            "summary": f"Scenario valid: {norm.flow_mode} flow, length "
                       f"{norm.geometry['length_m']:g} m, phi0={norm.porosity:g}.",
            "findings": [
                _as_labeled(EpistemicLabel.OBSERVED.value,
                            "Scenario passed unit/range validation and is solver-ready.",
                            source="validate"),
                _as_labeled(EpistemicLabel.CALCULATED.value,
                            f"nx={norm.geometry['nx']}, porosity={norm.porosity:g}, "
                            f"K0={norm.permeability:g} m2, flow_mode={norm.flow_mode}",
                            source="normalize_scenario"),
            ],
            "artifacts": [{"kind": "normalized_scenario", "path": None,
                           "note": _norm_note(norm)}],
        }

    def _do_dimensionless(self, raw: dict[str, Any], out: dict[str, Any]) -> dict[str, Any]:
        scenario = raw.get("scenario") or {}
        norm = normalize_scenario(scenario)
        vel = norm.velocity if norm.velocity is not None else 0.0
        L = norm.geometry["length_m"]
        D = 0.1 * vel * L if vel > 0 else 1e-9
        # reference concentration: use urea inflow if present else Ca inflow
        c0 = norm.species.get("c_urea_in", norm.species.get("c_ca_in", 1.0))
        k_ure = _rate_scalar(raw, "k_ure", default=1e-4)
        # zero-order basis rate: k_ure * biomass (units mol/m3/s)
        kr = k_ure * norm.species.get("c_biomass", 1.0)
        numbers = dimensionless_numbers(
            velocity=vel, length=L, dispersion=D,
            reaction_rate=kr, c0=c0,
            porosity=norm.porosity,
        )
        out["validation"]["input_schema"] = "passed"
        return {
            "summary": (f"Pe={_fmt(numbers['pe'])}, Da={_fmt(numbers['da'])}, "
                        f"rDa={_fmt(numbers['rda'])} — transport: "
                        f"{numbers['transport_regime']}, reaction: {numbers['reaction_regime']}."),
            "findings": [
                _as_labeled(EpistemicLabel.CALCULATED.value,
                            f"Pe={_fmt(numbers['pe'])} -> {numbers['transport_regime']}",
                            source="dimensionless"),
                _as_labeled(EpistemicLabel.CALCULATED.value,
                            f"Da={_fmt(numbers['da'])} -> {numbers['reaction_regime']} "
                            f"(clogging propensity {numbers['clog_propensity']})",
                            source="dimensionless"),
            ],
            "artifacts": [{"kind": "dimensionless", "path": None, "note": numbers}],
            "risks": [{
                "label": EpistemicLabel.INFERRED.value,
                "statement": (f"Da={_fmt(numbers['da'])} >= 1 implies strong front gradients; "
                              "spatial discretization must resolve the reaction front "
                              "(grid-sensitivity check required)."),
            }] if (numbers.get("da") is not None and numbers["da"] >= 1) else [],
        }

    def _do_clogging(self, raw: dict[str, Any], out: dict[str, Any]) -> dict[str, Any]:
        """Run clogging criteria on caller-provided porosity/permeability arrays."""
        profiles = raw.get("profiles") or {}
        porosity = profiles.get("porosity")
        permeability = profiles.get("permeability")
        k0 = profiles.get("permeability0")
        if not porosity or not permeability or k0 is None:
            raise OpError(OpErrorCode.MISSING_REQUIRED_FIELD,
                          "clogging requires profiles.porosity, profiles.permeability, "
                          "and profiles.permeability0.",
                          detail={"missing_fields": [
                              {"field": "profiles.*",
                               "why_critical": "clogging criteria evaluate final-state arrays",
                               "how_to_obtain": "run action=analyze first, or pass arrays explicitly"}]})
        criteria = clogging_mod.ClogCriteria(
            porosity_min=raw.get("porosity_min", 0.02),
            permeability_ratio=raw.get("permeability_ratio", 1e-2),
        )
        verdict = criteria.evaluate(porosity, permeability, k0)
        out["validation"]["input_schema"] = "passed"
        findings = [_as_labeled(EpistemicLabel.CALCULATED.value,
                                f"clogged={verdict['clogged']}: {verdict['reason']}",
                                source="clogging")]
        for w in verdict.get("warnings", []):
            findings.append(_as_labeled(EpistemicLabel.INFERRED.value, w, source="clogging"))
        return {
            "summary": f"Clogging verdict: {'CLOGGED' if verdict['clogged'] else 'OPEN'} — "
                       f"{verdict['reason']}.",
            "findings": findings,
            "artifacts": [{"kind": "clogging_verdict", "path": None, "note": verdict}],
        }

    def _do_analyze(self, raw: dict[str, Any], out: dict[str, Any]) -> dict[str, Any]:
        scenario = raw.get("scenario") or {}
        norm = normalize_scenario(scenario)

        # Approval gate: field-scale deployment / live-experiment scenarios write
        # into a domain where over-claiming is dangerous (spec §七, §九.4).
        scale = norm.scale
        risk = raw.get("risk_level", "medium")
        if scale == "field" or (scale in ("core", "sand-pack") and risk == "critical"):
            approval = raw.get("human_approval_state") or {}
            if not approval.get("granted"):
                raise OpError(
                    OpErrorCode.APPROVAL_REQUIRED,
                    f"Scenario scale '{scale}' with risk '{risk}' requires explicit human "
                    "approval before a deterministic prediction is produced (field deployment / "
                    "live-experiment gate).",
                    detail={"scale": scale, "risk_level": risk,
                            "how_to_fix": "human_approval_state.granted=true with approver and scope"},
                )

        k_ure = _rate_scalar(raw, "k_ure", default=1e-4)     # 1/s
        k_pre = _rate_scalar(raw, "k_pre", default=1e-4)     # 1/s
        k_half = _concentration_scalar(raw, "k_half", default=0.5)  # mol/m3
        t_end = _optional_time(raw.get("t_end"))
        clog_threshold = raw.get("clog_threshold", 0.02)
        dt = raw.get("dt")

        cfg = norm.to_solver_config(
            k_ure=k_ure, k_pre=k_pre, k_half=k_half,
            t_end=t_end, clog_threshold=clog_threshold, dt=dt,
        )
        # dimension defaults that the scenario may not carry
        cfg.velocity = norm.velocity if norm.velocity is not None else cfg.velocity

        # dimensionless numbers on the same inputs (consistency by construction)
        vel = norm.velocity if norm.velocity is not None else 0.0
        L = norm.geometry["length_m"]
        D = 0.1 * vel * L if vel > 0 else 1e-9
        c0 = norm.species.get("c_urea_in", norm.species.get("c_ca_in", 1.0))
        kr = k_ure * norm.species.get("c_biomass", 1.0)
        numbers = dimensionless_numbers(velocity=vel, length=L, dispersion=D,
                                        reaction_rate=kr, c0=c0, porosity=norm.porosity)

        result = solve_transport(cfg)

        # clogging criteria
        criteria = clogging_mod.ClogCriteria(
            porosity_min=clog_threshold,
            permeability_ratio=raw.get("permeability_ratio", 1e-2),
        )
        verdict = criteria.evaluate(result.profiles[-1].porosity,
                                    result.profiles[-1].permeability,
                                    cfg.k_perm0)

        # conservation + numerical checks
        cons_checks = vcheck.check_conservation(result)
        num_checks = vcheck.check_numerical(result)
        grid_check = vcheck.check_grid_sensitivity(
            lambda nx: _cfg_with_nx(cfg, nx))

        all_checks = cons_checks + num_checks + [grid_check]
        passed = all(c["passed"] for c in all_checks)
        out["validation"]["input_schema"] = "passed"
        out["validation"]["checks"] = [
            {"name": c["name"], "passed": c["passed"], "detail": c["detail"]}
            for c in all_checks
        ]

        findings = [
            _as_labeled(EpistemicLabel.CALCULATED.value,
                        f"t_final={result.t_final:g} s, steps={result.steps}, "
                        f"reason={result.reason}",
                        source="solver"),
            _as_labeled(EpistemicLabel.CALCULATED.value,
                        f"final porosity min={result.summary['final_porosity_min']:g} "
                        f"(inlet {result.summary['final_porosity_inlet']:g}, outlet "
                        f"{result.summary['final_porosity_outlet']:g})",
                        source="solver"),
            _as_labeled(EpistemicLabel.CALCULATED.value,
                        f"permeability reduction factor at inlet: "
                        f"{result.summary['permeability_reduction_factor']:g}",
                        source="kozeny_carman"),
            _as_labeled(EpistemicLabel.CALCULATED.value,
                        f"Pe={_fmt(numbers['pe'])}, Da={_fmt(numbers['da'])}, "
                        f"rDa={_fmt(numbers['rda'])}",
                        source="dimensionless"),
            _as_labeled(EpistemicLabel.INFERRED.value,
                        f"clogging verdict: {verdict['reason']}",
                        source="clogging"),
        ]
        for c in all_checks:
            if not c["passed"]:
                findings.append(_as_labeled(
                    EpistemicLabel.CALCULATED.value,
                    f"check '{c['name']}' failed: {c['detail']}",
                    source="self_check"))

        mb = vcheck.mass_balance_metrics(result)
        profile = vcheck.profile_to_jsonable(result)
        blockage = vcheck.find_max_blockage(result.profiles[-1])

        artifacts = [
            {"kind": "mass_balance", "path": None, "note": mb},
            {"kind": "profile", "path": None, "note": profile},
            {"kind": "dimensionless", "path": None, "note": numbers},
            {"kind": "clogging_verdict", "path": None, "note": verdict},
            {"kind": "summary_metrics", "path": None, "note": result.summary},
        ]

        summary = (f"Simulated MICP column: {result.steps} steps, t={result.t_final:g} s; "
                   f"{'CLOGGED' if verdict['clogged'] else 'open'}; "
                   f"precipitated {mb.get('caco3_kg_precipitated', 0.0):g} kg CaCO3; "
                   f"self-check {'passed' if passed else 'FAILED'}.")

        status_override = None
        if not passed:
            status_override = OutputStatus.PARTIAL.value
            out["risks"].append({"label": EpistemicLabel.CALCULATED.value,
                                 "statement": "one or more self-checks failed (see validation.checks)"})

        if verdict["clogged"]:
            findings.append(_as_labeled(
                EpistemicLabel.INFERRED.value,
                "Column clogged under the chosen criteria: treat as an inlet "
                "clogging scenario (spec §四.5 entry clogging / bypass flow).",
                source="clogging"))

        out["state"] = {"clogged": verdict["clogged"], "t_final": result.t_final,
                        "permeability_reduction_factor": result.summary["permeability_reduction_factor"]}
        result_update: dict[str, Any] = {
            "summary": summary,
            "findings": findings,
            "assumptions": [
                _as_labeled(
                    EpistemicLabel.INFERRED.value,
                    "Kozeny-Carman porosity-permeability coupling; "
                    "carbonate availability surrogate f_carb=1-U/U_in; "
                    "first-order precipitation toward a carbonate threshold; "
                    "constant biomass; explicit transport with CFL guard.",
                    source="model_assumptions"),
            ],
            "artifacts": artifacts,
            "validation": {
                **out["validation"],
                "checks": out["validation"]["checks"],
            },
        }
        if status_override is not None:
            result_update["status"] = status_override
        return result_update


def _cfg_with_nx(cfg: SolverConfig, nx: int) -> SolverConfig:
    import copy
    c = copy.copy(cfg)
    c.nx = nx
    return c


def _rate_scalar(raw: dict[str, Any], key: str, default: float) -> float:
    val = raw.get(key, default)
    return check_finite(key, val if isinstance(val, (int, float)) else default)


def _concentration_scalar(raw: dict[str, Any], key: str, default: float) -> float:
    val = raw.get(key, default)
    if isinstance(val, dict):
        return parse_quantity(val, key=key).to_si()
    return check_finite(key, val if isinstance(val, (int, float)) else default)


def _optional_time(raw: Any) -> float | None:
    if raw is None:
        return None
    return check_finite("t_end", float(raw))


def _fmt(x: Any) -> str:
    if x is None:
        return "inf"
    try:
        return f"{float(x):.3g}"
    except (TypeError, ValueError):
        return str(x)


def _norm_note(norm) -> dict[str, Any]:
    return {
        "length_m": norm.geometry["length_m"],
        "diameter_m": norm.geometry.get("diameter_m"),
        "nx": norm.geometry["nx"],
        "porosity": norm.porosity,
        "permeability_m2": norm.permeability,
        "flow_mode": norm.flow_mode,
        "velocity_m_per_s": norm.velocity,
        "p_in_pa": norm.p_in,
        "p_out_pa": norm.p_out,
        "species": norm.species,
        "scale": norm.scale,
    }
