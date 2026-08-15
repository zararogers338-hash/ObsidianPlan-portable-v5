"""Service layer for micp-modeling-optimizer: action dispatch, envelope
assembly, self-checks, and status mapping.

Actions (subcommands):
  * solve        — assemble a kinetic/reactive-transport ODE model from a model
                   spec, solve it, run conservation + numerical + grid/step
                   sensitivity checks, and emit the unified report.
  * fit          — parameter estimation (multi-start least squares) with
                   identifiability analysis and hold-out validation.
  * analyze      — full pipeline: solve + fit + identifiability + sensitivity +
                   optimization (single and multi-objective) + robustness.
  * optimize     — single-objective (Bayesian) optimization only.
  * multiobjective — NSGA-II multi-objective optimization only.
  * sensitivity  — global sensitivity (Sobol') / Morris screening only.
  * uq           — Monte-Carlo uncertainty propagation only.
  * doe          — DOE generation and response-surface fitting only.
  * validate     — schema-only dry-run gate (validates input, no computation).

Envelope: unified (contract_version / skill / skill_version / status / summary
/ ... / errors), identical in shape to the sibling OPM skill.
"""

from __future__ import annotations

import json
import math
import time
from typing import Any

from _common import (
    SKILL_NAME,
    SKILL_VERSION,
    CONTRACT_VERSION,
    EpistemicLabel,
    OutputStatus,
    emit_progress,
)
from errors import MmoError, MmoErrorCode
from validate import check_output_schema, validate_input
from modelspec import (
    validate_model_spec,
    check_parameter_free_fit_policy,
    build_unified_report,
)

# ---------------------------------------------------------------------------
# Envelope assembly
# ---------------------------------------------------------------------------

def _envelope(payload: dict, action: str) -> dict:
    return {
        "contract_version": CONTRACT_VERSION,
        "skill": SKILL_NAME,
        "skill_version": SKILL_VERSION,
        "status": OutputStatus.FAILED.value,
        "summary": "",
        "action": action,
        "project_id": payload.get("project_id"),
        "task_id": payload.get("task_id"),
        "findings": [],
        "assumptions": [],
        "evidence_used": [],
        "uncertainty": [],
        "risks": [],
        "artifacts": [],
        "requested_next_skills": [],
        "validation": {
            "input_schema": False,
            "output_schema": False,
            "self_check": None,
            "checks": [],
        },
        "provenance": {
            "skill": SKILL_NAME,
            "skill_version": SKILL_VERSION,
            "started_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "completed_at": None,
            "generator": "micp-modeling-optimizer/cli.py",
            "seed": payload.get("constraints", {}).get("random_seed", 0)
            if isinstance(payload.get("constraints"), dict)
            else 0,
        },
        "errors": [],
    }


def _finalize(out: dict, *, ok: bool = True) -> dict:
    out["provenance"]["completed_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    # self-check the envelope shape
    checks = out["validation"].setdefault("checks", [])
    checks.append({"name": "envelope_shape", "ok": ok and "summary" in out})
    checks.append({"name": "status_valid", "ok": out["status"] in (
        "SUCCESS", "PARTIAL", "BLOCKED", "FAILED",
        "NEED_ADDITIONAL_SKILL", "HUMAN_APPROVAL_REQUIRED")})
    # epistemic-label audit on findings
    bad_labels = [
        f["statement"][:40] for f in out.get("findings", [])
        if f.get("epistemic_tag") not in (
            "OBSERVED", "REPORTED", "CALCULATED", "INFERRED", "HYPOTHESIS", "RECOMMENDATION")
    ]
    checks.append({"name": "epistemic_labels", "ok": not bad_labels})
    out["validation"]["self_check"] = all(c["ok"] for c in checks)
    return out


def _validate_output_or_flag(out: dict) -> None:
    """Run the mandatory output-schema self-check and record the result. The
    output document is always structurally complete (even for BLOCKED/FAILED),
    so this should pass; a failure is reported as MMO-E701."""
    try:
        check_output_schema(out)
        out["validation"]["output_schema"] = True
    except MmoError as err:
        out["validation"]["output_schema"] = False
        # do not overwrite a more specific existing error
        if not any(e["code"] == "MMO-E701" for e in out["errors"]):
            out["errors"].append({
                "code": "MMO-E701",
                "message": err.message,
                "retryable": True,
                "details": err.details,
            })


def _apply_error(out: dict, err: MmoError) -> None:
    code = err.code
    if code == "MMO-E502":
        out["status"] = OutputStatus.HUMAN_APPROVAL_REQUIRED.value
    elif code == "MMO-E601":
        out["status"] = OutputStatus.NEED_ADDITIONAL_SKILL.value
    elif code in (
        "MMO-E102", "MMO-E101", "MMO-E103", "MMO-E104", "MMO-E105", "MMO-E106",
        "MMO-E201", "MMO-E202", "MMO-E203", "MMO-E204", "MMO-E801",
    ):
        out["status"] = OutputStatus.BLOCKED.value
        if code == "MMO-E102" and err.details.get("missing_fields"):
            out["missing_inputs"] = err.details["missing_fields"]
        elif code == "MMO-E101" and err.details.get("issues"):
            out["missing_inputs"] = [
                {"field": str(i), "why_critical": "input contract violation",
                 "how_to_obtain": "see errors[].message"}
                for i in err.details["issues"][:10]
            ]
        else:
            # the output schema requires `missing_inputs` on every BLOCKED
            # envelope; synthesize a per-field entry from the error message
            out["missing_inputs"] = [{
                "field": "request/action/contract",
                "why_critical": err.message,
                "how_to_obtain": "see errors[].message for the failing field and correction",
            }]
    elif code in ("MMO-E403", "MMO-E404"):
        out["status"] = OutputStatus.PARTIAL.value
    elif code == "MMO-E701":
        out["status"] = OutputStatus.FAILED.value
    else:
        out["status"] = OutputStatus.FAILED.value
    out["errors"].append({
        "code": err.code,
        "message": err.message,
        "retryable": err.retryable,
        "details": err.details,
    })


# ---------------------------------------------------------------------------
# Action handlers
# ---------------------------------------------------------------------------

def _build_solver_from_spec(payload: dict) -> tuple[dict, dict]:
    """Assemble a solve configuration from the model_specification block."""
    spec_block = payload.get("model_specification")
    if not isinstance(spec_block, dict):
        raise MmoError(MmoErrorCode.INVALID_MODEL_SPEC, "model_specification is required for action=solve")
    # validate: this raises MMO-E102 MODEL_BLOCKED with per-field guidance
    spec = validate_model_spec(spec_block)

    kinetics_block = spec_block.get("kinetics", {}) or {}
    ureolysis = kinetics_block.get("ureolysis", "michaelis_menten")
    precip = kinetics_block.get("precipitation", "first_order_min")
    kp = kinetics_block.get("porosity_permeability", "kozeny_carman")

    params = {}
    for p in spec_block.get("parameters", []):
        if isinstance(p, dict) and p.get("name"):
            v = p.get("value")
            if isinstance(v, (int, float)):
                params[p["name"]] = float(v)

    def g(name: str, default: float) -> float:
        return params.get(name, default)

    cfg = {
        "k_ure": g("k_ure", 1e-5),
        "k_pre": g("k_pre", 1e-5),
        "k_half": g("k_half", 305.0),
        "kd": g("kd", 1e-7),
        "c_biomass": g("c_biomass", 1.0),
        "urea0": g("urea0", 500.0),
        "ca0": g("ca0", 500.0),
        "biomass0": g("biomass0", 1.0),
        "phi0": g("phi0", 0.4),
        "t_end": g("t_end", 86400.0 * 3),
        "ureolysis": ureolysis,
        "precipitation": precip,
        "porosity_permeability": kp,
    }
    # initial conditions may come from spec
    ic = spec_block.get("initial_conditions", {})
    if isinstance(ic, dict):
        for key, value in ic.items():
            if isinstance(value, (int, float)):
                cfg[key] = float(value)
    return cfg, spec


def _solve_handler(payload: dict) -> dict:
    from kinetics import KineticsConfig, parse_kinetics_config, solve_kinetic_system

    spec_block = payload.get("model_specification")
    if not isinstance(spec_block, dict):
        raise MmoError(MmoErrorCode.INVALID_MODEL_SPEC, "model_specification is required")
    spec = validate_model_spec(spec_block)
    cfg, spec = _build_solver_from_spec(payload)
    kcfg = parse_kinetics_config(spec_block)

    constraints = payload.get("constraints", {}) or {}
    dt = constraints.get("dt")
    t_end = cfg["t_end"]
    result = solve_kinetic_system(
        kcfg,
        urea0=cfg["urea0"],
        ca0=cfg["ca0"],
        biomass0=cfg["biomass0"],
        phi0=cfg["phi0"],
        t_end=t_end,
        dt=dt,
    )
    # conservation check
    cons = _check_conservation(result.mass_balance)
    num = _check_numerical_stability({
        "urea": result.urea,
        "ca": result.ca,
        "nh4": result.nh4,
        "carbonate": result.carbonate,
        "porosity": result.phi,
    })
    return {
        "model_output": {
            "times": result.times,
            "urea": result.urea,
            "ca": result.ca,
            "nh4": result.nh4,
            "carbonate": result.carbonate,
            "biomass": result.biomass,
            "calcite_kg": result.calcite_kg,
            "phi": result.phi,
            "permeability_ratio": result.permeability_ratio,
            "mass_balance": result.mass_balance,
            "summary": result.summary,
        },
        "conservation": cons,
        "numerical": num,
        "steps": result.steps,
        "mass_balance": result.mass_balance,
    }


def _check_conservation(mb: dict) -> dict:
    from checks import check_conservation
    return check_conservation(mb)


def _check_numerical_stability(state: dict) -> dict:
    from checks import check_numerical_stability
    return check_numerical_stability(state)


def _fit_handler(payload: dict) -> dict:
    """Parameter estimation + identifiability + hold-out validation."""
    from optimizer import fit_parameters, identifiability_report, FitSpec
    from modelspec import validate_model_spec

    spec_block = payload.get("model_specification")
    if not isinstance(spec_block, dict):
        raise MmoError(MmoErrorCode.INVALID_MODEL_SPEC, "model_specification is required")
    spec = validate_model_spec(spec_block)
    constraints = payload.get("constraints", {}) or {}
    seed = int(constraints.get("random_seed", 0))

    calib = payload.get("calibration")
    if not isinstance(calib, dict):
        raise MmoError(MmoErrorCode.INVALID_MODEL_SPEC,
                       "calibration block {data, parameters, model} required for action=fit")
    data = calib.get("data")
    if not isinstance(data, list) or not data:
        raise MmoError(MmoErrorCode.INVALID_MODEL_SPEC, "calibration.data must be a non-empty array")
    params = calib.get("parameters")
    if not isinstance(params, list) or not params:
        raise MmoError(MmoErrorCode.INVALID_PARAM_DEF, "calibration.parameters must list the fitting parameters")

    # free-fit policy gate (spec §四)
    policy = check_parameter_free_fit_policy(params)
    policy_warnings = [p for p in policy if p.get("severity") in ("warning", "error")]

    names = [p["name"] for p in params if isinstance(p, dict)]
    theta0 = []
    bounds = []
    for p in params:
        if not isinstance(p, dict) or "name" not in p:
            raise MmoError(MmoErrorCode.INVALID_PARAM_DEF, "each calibration parameter needs a name")
        theta0.append(float(p.get("value", p.get("guess", 1.0))))
        b = p.get("bounds")
        if b is None:
            v = theta0[-1]
            bounds.append((v * 0.5, v * 2.0))
        else:
            bounds.append((float(b[0]), float(b[1])))

    # model: name of a built-in kinetic model or a callable path
    model_name = calib.get("model", "kinetic_urea")
    extras = {"payload": payload, "params": params, "spec": spec}

    if model_name == "kinetic_urea":
        # k_half / c_biomass / initial conditions pulled once from the spec
        k_half_val = float(spec.get("kinetics", {}).get("k_half", 305.0)) \
            if isinstance(spec.get("kinetics"), dict) else 305.0
        c_bio_val = float(spec.get("kinetics", {}).get("c_biomass", 1.0)) \
            if isinstance(spec.get("kinetics"), dict) else 1.0
        init = payload.get("model_specification", {}).get("initial_conditions", {}) or {}
        u0 = float(init.get("urea0", 500.0))
        c0 = float(init.get("ca0", 500.0))

        def model_full(theta, t, ex):
            # theta = [k_ure, k_pre, ...] (order = calibration.parameters)
            k_ure = theta[0]
            k_pre = theta[1] if len(theta) > 1 else 1e-5
            kd = theta[2] if len(theta) > 2 else 1e-7
            from kinetics import KineticsConfig, solve_kinetic_system
            kcfg = KineticsConfig(k_ure=k_ure, k_pre=k_pre, kd=kd,
                                   k_half=k_half_val, c_biomass=c_bio_val)
            res = solve_kinetic_system(kcfg, urea0=u0, ca0=c0, t_end=float(t))
            idx = min(range(len(res.times)), key=lambda q: abs(res.times[q] - t))
            return [res.urea[idx], res.nh4[idx], res.calcite_kg[idx]]
    else:
        raise MmoError(MmoErrorCode.INVALID_MODEL_SPEC, f"unknown calibration model '{model_name}'")

    # data: list of {t, urea?, nh4?, caco3?} observations. The set of
    # measurement keys is inferred from the first row and must be consistent
    # across rows; the model always returns [urea, nh4, caco3] and the adapter
    # below selects the measured subset so residuals are compared on matching
    # quantities.
    obs_keys: list[str] = []
    obs_rows: list[tuple[float, list[float], None]] = []
    for d in data:
        if not isinstance(d, dict) or "t" not in d:
            raise MmoError(MmoErrorCode.INVALID_MODEL_SPEC, "each data row needs 't'")
        t = float(d["t"])
        if t <= 0:
            continue  # t=0 carries no kinetic information and the solver needs t>0
        keys = [k for k in ("urea", "nh4", "caco3") if k in d]
        if not keys:
            raise MmoError(MmoErrorCode.INVALID_MODEL_SPEC,
                           "data row needs urea/nh4/caco3 observation")
        if not obs_keys:
            obs_keys = keys
        elif keys != obs_keys:
            raise MmoError(
                MmoErrorCode.INVALID_MODEL_SPEC,
                "all data rows must carry the same measurement columns "
                f"(found {keys}, first row had {obs_keys})",
            )
        obs_rows.append((t, [float(d[k]) for k in obs_keys], None))
    if len(obs_rows) < 2:
        raise MmoError(MmoErrorCode.INVALID_MODEL_SPEC,
                       "need >= 2 observations with t>0 for fitting")
    obs_keys_tup = tuple(obs_keys)

    def model_masked(theta, t, ex):
        """model -> [urea, nh4, caco3] -> select measured keys in order."""
        full = model_full(theta, t, ex)
        return [full[("urea", "nh4", "caco3").index(k)] for k in obs_keys_tup]

    # hold-out split (sequential: later times are the validation set)
    times = [r[0] for r in obs_rows]
    k_split = max(1, int(round(len(times) * 0.7)))
    train = obs_rows[:k_split]
    valid = obs_rows[k_split:]
    if not valid:
        raise MmoError(MmoErrorCode.INVALID_MODEL_SPEC,
                       "need at least one held-out observation; increase data length")

    spec_fit = FitSpec(model=model_masked, data=train, theta0=theta0, bounds=bounds,
                       n_starts=int(constraints.get("n_starts", 3)), seed=seed)
    res = fit_parameters(spec_fit, {"payload": payload, "params": params, "spec": spec},
                         max_iter=int(constraints.get("max_iter", 20000)))

    # validate on held-out
    def rss_valid(theta):
        s = 0.0
        for (t, obs, _) in valid:
            pred = model_masked(theta, t, {"payload": payload, "params": params, "spec": spec})
            for i, o in enumerate(obs):
                s += (pred[i] - o) ** 2
        return s

    train_rss = res.cost
    valid_rss = rss_valid(res.theta)
    overfit_ratio = valid_rss / max(train_rss, 1e-12)

    ident = identifiability_report(spec_fit, res.theta,
                                   {"payload": payload, "params": params, "spec": spec})

    # T3 gate (spec §九.3): a PREDICTION-purpose fit must never present the
    # training data as its own validation. We always split internally, so any
    # declared validation_data that resolves to the training set is refused;
    # otherwise the limitation is surfaced as an explicit risk.
    validation_blocked = None
    purpose = spec.get("purpose")
    vdata = spec.get("validation_data")
    if purpose == "PREDICTION":
        if vdata and any(tok in str(vdata).lower()
                         for tok in ("same", "training", "identical", "self")):
            validation_blocked = (
                "PREDICTION model declared validation_data as the training data "
                "itself; same-data fit cannot be presented as validation"
            )
        elif not vdata:
            validation_blocked = (
                "PREDICTION model has no external validation_data; only an internal "
                "hold-out split was used — do not present the fit as field-validated"
            )
    if validation_blocked:
        raise MmoError(
            MmoErrorCode.INVALID_MODEL_SPEC,
            validation_blocked,
            detail={"policy": "spec_9_3_same_data_fit_validate"},
        )

    return {
        "status": OutputStatus.SUCCESS.value,
        "theta": res.theta,
        "cost": res.cost,
        "backend": res.backend,
        "train_rss": train_rss,
        "holdout_rss": valid_rss,
        "holdout_overfit_ratio": overfit_ratio,
        "holdout_warning": "held-out performance much worse than training — overfitting signal"
            if overfit_ratio > 2.0 else None,
        "identifiability": ident,
        "policy_warnings": policy_warnings,
        "starts": res.starts,
    }


def _optimize_handler(payload: dict) -> dict:
    """Single-objective Bayesian optimization over decision variables."""
    from bayesopt import bayesian_optimize

    opt = payload.get("optimization")
    if not isinstance(opt, dict):
        raise MmoError(MmoErrorCode.INVALID_OBJECTIVE, "optimization block required")
    bounds = opt.get("bounds")
    if not isinstance(bounds, list) or not bounds:
        raise MmoError(MmoErrorCode.INVALID_OBJECTIVE, "optimization.bounds required")
    vars_ = opt.get("variables")
    if not isinstance(vars_, list) or len(vars_) != len(bounds):
        raise MmoError(MmoErrorCode.INVALID_OBJECTIVE, "optimization.variables must match bounds length")
    constraints = payload.get("constraints", {}) or {}
    seed = int(constraints.get("random_seed", 0))
    maximize = bool(opt.get("maximize", False))

    # objective: reference a model output + which scalar to minimize
    target = opt.get("target")
    if not isinstance(target, dict) or "output" not in target:
        raise MmoError(MmoErrorCode.INVALID_OBJECTIVE, "optimization.target.output required")

    def objective(x, ex):
        # build a kinetics config from the decision vector mapped onto
        # optimization.variables (which carry 'name')
        vmap = {vars_[i]["name"]: x[i] for i in range(len(x))}
        base = payload.get("model_specification", {}).get("kinetics", {}) or {}
        merged = dict(base)
        for k, v in vmap.items():
            merged[k] = v
        spec = dict(payload.get("model_specification", {}))
        spec["kinetics"] = merged
        from kinetics import parse_kinetics_config, solve_kinetic_system
        kcfg = parse_kinetics_config(spec)
        init = payload.get("model_specification", {}).get("initial_conditions", {}) or {}
        t_end = float(target.get("t_end", 86400.0))
        res = solve_kinetic_system(kcfg, urea0=float(init.get("urea0", 500.0)),
                                   ca0=float(init.get("ca0", 500.0)),
                                   t_end=t_end)
        out = target["output"]
        if out == "caco3_kg":
            return res.calcite_kg[-1]
        if out == "ammonia_release":
            # molar NH4 produced (mol/m3) as a proxy for ammonia emission load
            return res.nh4[-1]
        if out == "processing_time":
            return t_end
        if out == "permeability_ratio":
            return res.permeability_ratio[-1]
        if out == "urea_remaining":
            return res.urea[-1]
        raise MmoError(MmoErrorCode.INVALID_OBJECTIVE, f"unknown target output '{out}'")

    res = bayesian_optimize(objective, [(float(b[0]), float(b[1])) for b in bounds],
                            n_init=int(constraints.get("n_init", 6)),
                            n_iter=int(constraints.get("n_iter", 20)),
                            seed=seed,
                            maximize=maximize,
                            extras={})
    return {"optimization": res}


def _multiobjective_handler(payload: dict) -> dict:
    """NSGA-II multi-objective optimization."""
    from multiobjective import nsga2, robustness_analysis

    opt = payload.get("optimization")
    if not isinstance(opt, dict):
        raise MmoError(MmoErrorCode.INVALID_OBJECTIVE, "optimization block required")
    bounds = opt.get("bounds")
    if not isinstance(bounds, list) or not bounds:
        raise MmoError(MmoErrorCode.INVALID_OBJECTIVE, "optimization.bounds required")
    vars_ = opt.get("variables")
    objectives = opt.get("objectives")
    if not isinstance(objectives, list) or len(objectives) < 2:
        raise MmoError(MmoErrorCode.INVALID_OBJECTIVE, "need >= 2 objectives")
    constraints = payload.get("constraints", {}) or {}
    seed = int(constraints.get("random_seed", 0))
    names = [o.get("name", f"obj{i}") for i, o in enumerate(objectives)]
    maximize = [bool(o.get("maximize", False)) for o in objectives]

    def make_objective(o):
        target = o.get("target")
        if not isinstance(target, dict) or "output" not in target:
            raise MmoError(MmoErrorCode.INVALID_OBJECTIVE, "each objective needs target.output")

        def obj_fn(x, ex):
            vmap = {vars_[i]["name"]: x[i] for i in range(len(x))}
            spec = dict(payload.get("model_specification", {}))
            merged = dict(spec.get("kinetics", {}) or {})
            for k, v in vmap.items():
                merged[k] = v
            spec["kinetics"] = merged
            from kinetics import parse_kinetics_config, solve_kinetic_system
            kcfg = parse_kinetics_config(spec)
            init = spec.get("initial_conditions", {}) or {}
            t_end = float(target.get("t_end", 86400.0))
            res = solve_kinetic_system(kcfg, urea0=float(init.get("urea0", 500.0)),
                                       ca0=float(init.get("ca0", 500.0)),
                                       t_end=t_end)
            out = target["output"]
            table = {
                "caco3_kg": res.calcite_kg[-1],
                "ammonia_release": res.nh4[-1],
                "urea_remaining": res.urea[-1],
                "permeability_ratio": res.permeability_ratio[-1],
                "processing_time": t_end,
                "cost": vmap.get("urea_cost_per_mol", 0.0) * res.urea[-1] + vmap.get("ca_cost_per_mol", 0.0) * res.ca[-1],
            }
            if out not in table:
                raise MmoError(MmoErrorCode.INVALID_OBJECTIVE, f"unknown objective output '{out}'")
            return table[out]
        return obj_fn

    objs = [make_objective(o) for o in objectives]
    res = nsga2(objs, [(float(b[0]), float(b[1])) for b in bounds],
                pop_size=int(constraints.get("pop_size", 40)),
                n_gen=int(constraints.get("n_gen", 100)),
                seed=seed,
                constraints=opt.get("constraints"),
                names=names,
                maximize=maximize,
                extras={})
    # robustness on the front
    front = [f["x"] for f in res["front"]]
    if front and constraints.get("robustness_samples", 0) or opt.get("robustness"):
        rob = robustness_analysis(objs, front, [(float(b[0]), float(b[1])) for b in bounds],
                                  n_samples=int(constraints.get("robustness_samples", 50)),
                                  seed=seed + 1,
                                  constraints=opt.get("constraints"),
                                  maximize=maximize,
                                  extras={})
        res["robustness"] = rob
    return {"optimization": res}


def _sensitivity_handler(payload: dict) -> dict:
    from sensitivity import sobol_indices, morris_screening

    sens = payload.get("sensitivity")
    if not isinstance(sens, dict):
        raise MmoError(MmoErrorCode.INVALID_MODEL_SPEC, "sensitivity block required")
    names = sens.get("parameters")
    bounds = sens.get("bounds")
    if not isinstance(names, list) or not isinstance(bounds, list) or len(names) != len(bounds):
        raise MmoError(MmoErrorCode.INVALID_PARAM_DEF, "sensitivity.parameters and bounds must align")
    constraints = payload.get("constraints", {}) or {}
    seed = int(constraints.get("random_seed", 0))
    target = sens.get("target", "caco3_kg")

    def g(x, ex):
        vmap = {names[i]: x[i] for i in range(len(x))}
        spec = dict(payload.get("model_specification", {}))
        merged = dict(spec.get("kinetics", {}) or {})
        for k, v in vmap.items():
            merged[k] = v
        spec["kinetics"] = merged
        from kinetics import parse_kinetics_config, solve_kinetic_system
        kcfg = parse_kinetics_config(spec)
        init = spec.get("initial_conditions", {}) or {}
        t_end = float(sens.get("t_end", 86400.0))
        res = solve_kinetic_system(kcfg, urea0=float(init.get("urea0", 500.0)),
                                   ca0=float(init.get("ca0", 500.0)),
                                   t_end=t_end)
        if target == "caco3_kg":
            return res.calcite_kg[-1]
        if target == "ammonia_release":
            return res.nh4[-1]
        if target == "permeability_ratio":
            return res.permeability_ratio[-1]
        return res.urea[-1]

    method = sens.get("method", "sobol")
    n_base = int(sens.get("n_base", 500))
    b = [(float(lo), float(hi)) for lo, hi in bounds]
    if method == "morris":
        return {"sensitivity": morris_screening(g, len(names), int(sens.get("r", 10)),
                                                int(sens.get("p", 4)), seed, bounds=b)}
    return {"sensitivity": sobol_indices(g, len(names), n_base, seed, bounds=b)}


def _uq_handler(payload: dict) -> dict:
    from uncertainty import monte_carlo_uq

    uq = payload.get("uncertainty")
    if not isinstance(uq, dict):
        raise MmoError(MmoErrorCode.INVALID_MODEL_SPEC, "uncertainty block required")
    dists = uq.get("parameters")
    if not isinstance(dists, list) or not dists:
        raise MmoError(MmoErrorCode.INVALID_PARAM_DEF, "uncertainty.parameters required")
    constraints = payload.get("constraints", {}) or {}
    seed = int(constraints.get("random_seed", 0))
    target = uq.get("target", "caco3_kg")

    def g(x, ex):
        vmap = {d["name"]: x[i] for i, d in enumerate(dists)}
        spec = dict(payload.get("model_specification", {}))
        merged = dict(spec.get("kinetics", {}) or {})
        for k, v in vmap.items():
            merged[k] = v
        spec["kinetics"] = merged
        from kinetics import parse_kinetics_config, solve_kinetic_system
        kcfg = parse_kinetics_config(spec)
        init = spec.get("initial_conditions", {}) or {}
        t_end = float(uq.get("t_end", 86400.0))
        res = solve_kinetic_system(kcfg, urea0=float(init.get("urea0", 500.0)),
                                   ca0=float(init.get("ca0", 500.0)),
                                   t_end=t_end)
        table = {
            "caco3_kg": res.calcite_kg[-1],
            "ammonia_release": res.nh4[-1],
            "permeability_ratio": res.permeability_ratio[-1],
            "urea_remaining": res.urea[-1],
        }
        if target not in table:
            raise MmoError(MmoErrorCode.INVALID_MODEL_SPEC, f"unknown uncertainty target '{target}'")
        return [table[target]]

    res = monte_carlo_uq(g, dists, int(uq.get("n_samples", 200)), seed)
    return {"uncertainty": res}


def _doe_handler(payload: dict) -> dict:
    from doe import doe_generate, response_surface

    doe = payload.get("doe")
    if not isinstance(doe, dict):
        raise MmoError(MmoErrorCode.INVALID_MODEL_SPEC, "doe block required")
    if "factors" in doe and "kind" in doe:
        seed = int(payload.get("constraints", {}).get("random_seed", 0) or 0)
        res = doe_generate(doe["factors"], kind=doe["kind"], seed=seed,
                           center_points=doe.get("center_points"),
                           alpha=doe.get("alpha"),
                           n_lhs=int(doe.get("n_lhs", 20)))
        return {"doe": res}
    if "coded_points" in doe and "responses" in doe:
        res = response_surface(doe["factors"], doe["coded_points"], doe["responses"])
        return {"response_surface": res}
    raise MmoError(MmoErrorCode.INVALID_MODEL_SPEC,
                   "doe block needs {factors, kind} or {factors, coded_points, responses}")


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------

def _analyze_handler(payload: dict) -> dict:
    """Full pipeline: solve -> calibrate (if data) -> identifiability ->
    sensitivity -> single-objective (Bayesian) and multi-objective (NSGA-II)
    optimization -> robustness -> UQ (if blocks present)."""
    out: dict = {}
    # 1. solve
    solved = _solve_handler(payload)
    out.update({k: solved[k] for k in ("model_output", "conservation", "numerical",
                                       "mass_balance") if k in solved})
    out["steps"] = solved.get("steps")

    # 2. fit + identifiability when calibration data is provided
    if isinstance(payload.get("calibration"), dict):
        fit = _fit_handler(payload)
        for k in ("identifiability", "theta", "cost", "train_rss", "holdout_rss",
                  "holdout_overfit_ratio", "backend", "holdout_warning",
                  "policy_warnings", "starts"):
            if k in fit:
                out[k] = fit[k]
        # record calibration targets from the payload for the report
        out["_calib_target"] = payload["calibration"].get("target")

    # 3. sensitivity (Sobol') on the calibrated/fit parameters or spec params
    sens_block = payload.get("sensitivity")
    if isinstance(sens_block, dict):
        sens = _sensitivity_handler(payload)
        out["sensitivity"] = sens["sensitivity"]

    # 4. single-objective Bayesian optimization
    opt_block = payload.get("optimization")
    if isinstance(opt_block, dict) and opt_block.get("mode") == "single":
        single = _optimize_handler(payload)
        out["optimization"] = single["optimization"]

    # 5. multi-objective NSGA-II + robustness
    if isinstance(opt_block, dict) and opt_block.get("mode") == "multi":
        multi = _multiobjective_handler(payload)
        out["optimization"] = multi["optimization"]

    # 6. UQ
    if isinstance(payload.get("uncertainty"), dict):
        uq = _uq_handler(payload)
        out["uncertainty"] = uq["uncertainty"]

    out["status"] = OutputStatus.SUCCESS.value
    return out


HANDLERS = {
    "solve": _solve_handler,
    "fit": _fit_handler,
    "analyze": _analyze_handler,
    "optimize": _optimize_handler,
    "multiobjective": _multiobjective_handler,
    "sensitivity": _sensitivity_handler,
    "uq": _uq_handler,
    "doe": _doe_handler,
}


def handle(payload: dict) -> dict:
    """Entry point: validate input contract, version gate, dispatch, self-check."""
    # build the envelope first so contract failures carry a BLOCKED status
    # instead of crashing into a FAILED minimal envelope.
    action = payload.get("action")
    out = _envelope(payload, action or "unknown")

    # semantic gates first: action enum, contract_version, skill_version.
    # these are validated semantically BEFORE strict schema validation so a
    # wrong action reports MMO-E103 rather than an opaque MMO-E101.
    if action not in HANDLERS and action != "validate":
        _apply_error(out, MmoError(MmoErrorCode.INVALID_ACTION,
                                   f"unknown action '{action}'; supported: {', '.join(HANDLERS)} + validate"))
        out["summary"] = out["errors"][-1]["message"]
        _validate_output_or_flag(out)
        return _finalize(out)
    contract = payload.get("contract_version", "1.0")
    if not str(contract).startswith("1."):
        _apply_error(out, MmoError(MmoErrorCode.UNSUPPORTED_SCHEMA_VERSION,
                                   f"unsupported contract_version '{contract}'"))
        out["summary"] = out["errors"][-1]["message"]
        _validate_output_or_flag(out)
        return _finalize(out)

    sv = payload.get("skill_version")
    if sv and not str(sv).startswith("1."):
        _apply_error(out, MmoError(MmoErrorCode.UNSUPPORTED_SCHEMA_VERSION,
                                   f"skill_version '{sv}' major != 1"))
        out["summary"] = out["errors"][-1]["message"]
        _validate_output_or_flag(out)
        return _finalize(out)

    try:
        validate_input(payload)
    except MmoError as err:
        _apply_error(out, err)
        out["summary"] = err.message
        out["validation"]["input_schema"] = False
        _validate_output_or_flag(out)
        return _finalize(out)
    out["validation"]["input_schema"] = True

    if action == "validate":
        out["status"] = OutputStatus.SUCCESS.value
        out["summary"] = "Input contract valid."
        try:
            check_output_schema(out)
            out["validation"]["output_schema"] = True
        except MmoError as err:
            _apply_error(out, err)
            out["summary"] = err.message
            out["validation"]["output_schema"] = False
        return _finalize(out)

    try:
        result = HANDLERS[action](payload)
        out.update(result)
        # assemble the unified report fields
        _populate_report(out, payload, action)
        # hard self-checks
        conservation = out.get("conservation")
        numerical = out.get("numerical")
        if conservation is not None and not conservation.get("ok"):
            out["status"] = OutputStatus.PARTIAL.value
            out["errors"].append({
                "code": "MMO-E403",
                "message": "conservation self-check failed",
                "retryable": False,
                "details": {"failing": [c["name"] for c in conservation.get("checks", []) if not c["ok"]]},
            })
        if numerical is not None and not numerical.get("ok"):
            out["status"] = OutputStatus.PARTIAL.value
            out["errors"].append({
                "code": "MMO-E404",
                "message": "numerical stability self-check failed",
                "retryable": False,
                "details": {"failing": [c["name"] for c in numerical.get("checks", []) if not c["ok"]]},
            })
        if out["status"] == OutputStatus.FAILED.value:
            out["status"] = OutputStatus.SUCCESS.value
        if not out.get("summary"):
            out["summary"] = f"action={action} completed with status {out['status']}."
        _validate_output_or_flag(out)
    except MmoError as err:
        _apply_error(out, err)
        out["summary"] = err.message
        _validate_output_or_flag(out)
    return _finalize(out)


def _populate_report(out: dict, payload: dict, action: str) -> None:
    """Fill the unified-report fields from the handler result and strip the
    raw handler keys that are not part of the output contract."""
    spec_block = payload.get("model_specification") or {}
    purpose = spec_block.get("purpose")
    if purpose:
        out["model_purpose"] = purpose
    if isinstance(spec_block, dict) and spec_block:
        out["model_specification"] = spec_block
    out["equations"] = _equations_artifacts(spec_block)

    # solve result keys that ARE part of the contract
    for key in ("model_output", "conservation", "numerical", "mass_balance"):
        if key in out:
            pass  # keep as-is

    # fit result -> calibration block, keep identifiability
    if out.get("theta") is not None:
        out["calibration"] = {
            "theta": out["theta"],
            "cost": out.get("cost"),
            "train_rss": out.get("train_rss"),
            "holdout_rss": out.get("holdout_rss"),
            "holdout_overfit_ratio": out.get("holdout_overfit_ratio"),
            "backend": out.get("backend"),
        }
    # optimization result -> optimization_results + pareto_candidates
    if isinstance(out.get("optimization"), dict):
        opt = out["optimization"]
        out["optimization_results"] = opt
        if opt.get("front"):
            out["pareto_candidates"] = opt["front"]
    # uq result -> uncertainty_analysis (NOT the envelope's `uncertainty` list)
    if isinstance(out.get("uncertainty"), dict):
        out["uncertainty_analysis"] = out.pop("uncertainty")
        out.setdefault("uncertainty", [])  # envelope field stays a list
    # doe result
    if isinstance(out.get("doe"), dict):
        out["doe_report"] = out.pop("doe")
    if isinstance(out.get("response_surface"), dict):
        out["response_surface_report"] = out.pop("response_surface")

    # strip raw handler keys that are not part of the output contract
    RAW_KEYS = (
        "steps", "theta", "cost", "backend", "train_rss", "holdout_rss",
        "holdout_overfit_ratio", "policy_warnings", "starts", "optimization",
        "_calib_target",
    )
    for key in RAW_KEYS:
        out.pop(key, None)

    # risks and findings
    out.setdefault("risks", [])
    if out.get("holdout_warning"):
        out["risks"].append({
            "risk": out["holdout_warning"],
            "severity": "high",
            "mitigation": "do not use the model for extrapolation beyond the training scale",
        })
    out.pop("holdout_warning", None)
    if out.get("policy_warnings"):
        for w in out["policy_warnings"]:
            out["risks"].append({"risk": w["message"], "severity": "medium",
                                 "mitigation": "run identifiability analysis and fix correlated parameters"})
    findings = out.setdefault("findings", [])
    findings.append({
        "statement": f"action={action} completed with status {out['status']}",
        "epistemic_tag": "CALCULATED",
    })
    if out.get("identifiability"):
        v = out["identifiability"].get("verdict")
        findings.append({
            "statement": f"identifiability verdict: {v}",
            "epistemic_tag": "CALCULATED",
        })
    # assumptions from the model spec
    assumptions = out.setdefault("assumptions", [])
    for a in spec_block.get("assumptions", []) if isinstance(spec_block, dict) else []:
        assumptions.append({"statement": a})


def _equations_artifacts(spec_block: dict) -> list[dict]:
    if not isinstance(spec_block, dict) or not spec_block.get("equations"):
        return []
    eqs = spec_block["equations"]
    if isinstance(eqs, list):
        return eqs
    if isinstance(eqs, dict):
        return [{"name": k, "expression": str(v)} for k, v in eqs.items()]
    return [{"expression": str(eqs)}]
