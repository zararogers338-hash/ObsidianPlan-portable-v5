"""Model-specification validation and the unified report builder for
micp-modeling-optimizer.

The skill's core discipline (spec §三): every model must declare its purpose,
state variables, parameters with sources, governing equations, initial /
boundary conditions, observation equation, error model, scales, numerical
method, assumptions, applicability, validation data and failure conditions.
A spec missing a key boundary condition / unit / parameter source returns
MODEL_BLOCKED (MMO-E102) with per-field guidance — never a generic
"information insufficient".

validate_model_spec() returns either a valid, normalized spec or raises
MmoError(MMO-E102) with detail.missing_fields = [{field, why_critical,
how_to_obtain}].
"""

from __future__ import annotations

import math
from typing import Any

from _common import ToolError
from errors import MmoError, MmoErrorCode

# The canonical model-purpose enum (spec §二).
PURPOSES = (
    "EXPLANATION",
    "PREDICTION",
    "CONTROL",
    "OPTIMIZATION",
    "SCALE_UP",
    "PARAMETER_INFERENCE",
)

# Roles a parameter may carry (spec §四).
PARAM_ROLES = (
    "fixed",
    "literature_prior",
    "calibration",
    "identifiable",
    "weakly_identifiable",
    "non_identifiable",
)

# Fields that, when missing, block model construction.
REQUIRED_MODEL_FIELDS = [
    "purpose",
    "state_variables",
    "parameters",
    "equations",
    "initial_conditions",
    "observations",
    "error_model",
    "space_scale",
    "time_scale",
]

# Boundary conditions are required when the model is spatial (advection /
# diffusion / reactive transport).
SPATIAL_MODEL_KINDS = {"advection", "diffusion", "reactive_transport", "advection_diffusion", "pde"}

_FIELD_GUIDANCE = {
    "purpose": ("which of EXPLANATION/PREDICTION/CONTROL/OPTIMIZATION/SCALE_UP/PARAMETER_INFERENCE",
                "purpose governs what the model may legitimately be used for; a model fitted to explain "
                "must not be sold as predictive",
                "state the intended use in the task request or model-spec block"),
    "state_variables": ("list of state variables with units",
                        "the ODE/PDE cannot be assembled without a closed state vector",
                        "enumerate species/biomass/solid variables and their units"),
    "parameters": ("list of {name, value or source, role, unit}",
                   "parameter provenance distinguishes fixed / literature-prior / calibration "
                   "and is mandatory before fitting",
                   "provide parameter names, values or literature citations, and units"),
    "equations": ("governing equations (differential + algebraic) in text/LaTeX",
                  "the tool needs the rate expressions to assemble the solver",
                  "paste the equations or reference a model family implemented in tools"),
    "initial_conditions": ("state at t0 for every variable",
                           "without initial conditions the initial-value problem is undefined",
                           "give numeric values or a documented default per variable"),
    "boundary_conditions": ("inlet/outlet/edge conditions for spatial models",
                            "reaction-transport problems are ill-posed without boundary conditions",
                            "provide flux or Dirichlet conditions on each domain boundary"),
    "observations": ("observation equation mapping state to measured outputs",
                     "parameter fitting requires an observation model (which outputs are measured, "
                     "at which times, with what noise)",
                     "describe the measured quantities and their sampling times"),
    "error_model": ("error/measurement-noise model (additive Gaussian, multiplicative, ...)",
                    "uncertainty quantification and identifiability require an error model",
                    "state the noise distribution and its scale"),
    "space_scale": ("spatial scale (lab column / field pilot / ...)",
                    "validity of the calibrated parameters is scale-bound",
                    "name the scale; parameters from a different scale must be flagged"),
    "time_scale": ("time scale (hours / days / weeks)",
                   "kinetic parameters are only valid over the observed time horizon",
                   "state the experimental duration the model is validated over"),
}

_BOUNDARY_GUIDANCE = [
    {
        "field": "boundary_conditions",
        "why_critical": "reaction-transport problems are ill-posed without boundary conditions",
        "how_to_obtain": "provide inlet/outlet Dirichlet (concentration) or flux conditions on each boundary",
    },
]


def validate_model_spec(spec: dict) -> dict:
    """Validate a model specification; raise MMO-E102 (MODEL_BLOCKED) with
    per-field guidance on the first missing/ invalid key block."""
    if not isinstance(spec, dict):
        raise MmoError(MmoErrorCode.INVALID_MODEL_SPEC, "model_specification must be an object")

    missing: list[dict] = []
    for f in REQUIRED_MODEL_FIELDS:
        if f not in spec or spec[f] in (None, "", [], {}):
            g = _FIELD_GUIDANCE[f]
            missing.append({
                "field": f,
                "why_critical": g[1],
                "how_to_obtain": g[2],
            })

    purpose = spec.get("purpose")
    if purpose is not None:
        if isinstance(purpose, str):
            if purpose not in PURPOSES:
                raise MmoError(
                    MmoErrorCode.INVALID_MODEL_SPEC,
                    f"model_specification.purpose '{purpose}' not in {PURPOSES}",
                    detail={"supported": list(PURPOSES)},
                )
        elif isinstance(purpose, (list, tuple)):
            for p in purpose:
                if p not in PURPOSES:
                    raise MmoError(MmoErrorCode.INVALID_MODEL_SPEC,
                                   f"unknown purpose '{p}'", detail={"purpose": p})
        else:
            missing.append({
                "field": "purpose",
                "why_critical": _FIELD_GUIDANCE["purpose"][1],
                "how_to_obtain": _FIELD_GUIDANCE["purpose"][2],
            })

    # spatial models require boundary conditions
    kind = spec.get("model_kind")
    equations = spec.get("equations", {})
    kind_str = str(kind or (equations.get("kind") if isinstance(equations, dict) else "")).lower()
    is_spatial = kind_str in SPATIAL_MODEL_KINDS or any(
        token in str(equations).lower() for token in ("advection", "diffusion", "∂u/∂t", "reactive_transport")
    )
    if is_spatial and not spec.get("boundary_conditions"):
        missing.extend(_BOUNDARY_GUIDANCE)

    # parameter roles must be coherent
    params = spec.get("parameters")
    if isinstance(params, list) and params:
        for p in params:
            if not isinstance(p, dict):
                missing.append({"field": "parameters", "why_critical": "each parameter must be an object",
                                "how_to_obtain": "give {name, role, unit, source/value}"})
                continue
            if "unit" not in p or not p.get("unit"):
                missing.append({
                    "field": f"parameters[].{p.get('name','?')}.unit",
                    "why_critical": "units are mandatory for every parameter",
                    "how_to_obtain": "declare SI or conventional unit",
                })
            role = p.get("role")
            if role is not None and role not in PARAM_ROLES:
                raise MmoError(
                    MmoErrorCode.INVALID_PARAM_DEF,
                    f"parameter role '{role}' not in {PARAM_ROLES}",
                    detail={"parameter": p.get("name"), "supported": list(PARAM_ROLES)},
                )

    if missing:
        raise MmoError(
            MmoErrorCode.MISSING_REQUIRED_FIELD,
            "MODEL_BLOCKED: model specification is missing required fields",
            detail={"missing_fields": missing},
            retryable=True,
        )

    # normalized echo of the spec with defaults
    out = dict(spec)
    out.setdefault("contract_version", "1.0")
    out.setdefault("model_kind", kind or "ode")
    out.setdefault("numerical_method", "unspecified")
    out.setdefault("assumptions", spec.get("assumptions", []))
    out.setdefault("applicability", spec.get("applicability", "not stated"))
    out.setdefault("validation_data", spec.get("validation_data", None))
    out.setdefault("failure_conditions", spec.get("failure_conditions", []))
    return out


def check_parameter_free_fit_policy(params: list[dict]) -> list[dict]:
    """Spec §四: prohibit freely fitting multiple highly-correlated parameters
    without extra evidence. Returns a list of policy warnings; if any are
    severe the caller must block/flag the fit."""
    warnings: list[dict] = []
    calibration = [p for p in params if isinstance(p, dict) and p.get("role") == "calibration"]
    if len(calibration) >= 2:
        names = [p.get("name", "?") for p in calibration]
        warnings.append({
            "code": "MMO-W001",
            "severity": "warning",
            "message": (
                f"{len(calibration)} parameters are marked role='calibration' ({', '.join(names)}). "
                "Fitting several highly-correlated parameters simultaneously without extra evidence "
                "produces non-identifiable estimates. Run identifiability analysis before trusting "
                "the fit, and prefer fixing literature-prior parameters."
            ),
        })
    return warnings


def build_unified_report(
    *,
    status: str,
    summary: str,
    findings: list[dict],
    assumptions: list[dict],
    evidence_used: list[dict],
    uncertainty: list[dict],
    risks: list[dict],
    artifacts: list[dict],
    requested_next_skills: list[dict],
    validation: dict,
    provenance: dict,
    errors: list[dict],
    model_specification: dict | None = None,
    equations: list[dict] | None = None,
    parameters: list[dict] | None = None,
    parameter_sources: list[dict] | None = None,
    identifiability: dict | None = None,
    calibration: dict | None = None,
    sensitivity: dict | None = None,
    optimization_results: dict | None = None,
    pareto_candidates: list[dict] | None = None,
    model_purpose: str | list[str] | None = None,
) -> dict:
    """Assemble the unified output envelope (spec §八)."""
    report: dict = {
        "contract_version": "1.0",
        "skill": "micp-modeling-optimizer",
        "skill_version": "1.0.0",
        "status": status,
        "summary": summary,
        "findings": findings,
        "assumptions": assumptions,
        "evidence_used": evidence_used,
        "uncertainty": uncertainty,
        "risks": risks,
        "artifacts": artifacts,
        "requested_next_skills": requested_next_skills,
        "validation": validation,
        "provenance": provenance,
        "errors": errors,
    }
    optional = {
        "model_purpose": model_purpose,
        "model_specification": model_specification,
        "equations": equations,
        "parameters": parameters,
        "parameter_sources": parameter_sources,
        "identifiability": identifiability,
        "calibration": calibration,
        "sensitivity": sensitivity,
        "optimization_results": optimization_results,
        "pareto_candidates": pareto_candidates,
    }
    for key, value in optional.items():
        if value is not None:
            report[key] = value
    return report
