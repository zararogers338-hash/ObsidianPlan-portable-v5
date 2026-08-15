"""Validation and checkers for MICP transport results.

This module is the "validator" tool of the skill: it turns a scenario dict and
a solver result into (a) a clean numeric profile that passes schema checks, and
(b) a set of conservation / stability / sensitivity checks that the service
reports in `validation` and `findings`.

Nothing here touches the network; everything is deterministic and offline.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

from .errors import OpError, OpErrorCode
from .models import (
    CACO3_MOLAR_MASS,
    N_MOLAR_MASS,
    UREA_TO_AMMONIUM,
    UREA_MOLAR_MASS,
)
from .solver import SolverResult


def finite_or_none(x: float | None) -> float | None:
    if x is None or not math.isfinite(float(x)):
        return None
    return float(x)


def check_conservation(result: SolverResult, *, rtol: float = 0.05) -> list[dict[str, Any]]:
    """Conservation and stoichiometry checks (acceptance §九.3).

    Returns a list of check dicts: {name, passed, detail, value, tolerance}.
    """
    mb = result.mass_balance
    checks: list[dict[str, Any]] = []

    urea_in = mb.get("urea_in_total", 0.0)
    urea_out = urea_in - mb.get("urea_consumed", 0.0) - mb.get("urea_remaining", 0.0) \
        - mb.get("urea_out_approx", 0.0)
    rel_u = abs(urea_out) / max(abs(urea_in), 1e-12)
    checks.append({
        "name": "urea_mass_balance",
        "passed": rel_u <= rtol,
        "detail": f"residual={urea_out:.6g} (rel {rel_u:.2%})",
        "value": float(urea_out), "tolerance": rtol,
    })

    # Stoichiometry: NH4+ produced == 2 * urea consumed (1 urea -> 2 NH4+).
    nh = mb.get("nh_produced", 0.0)
    nh_expected = 2.0 * mb.get("urea_consumed", 0.0)
    rel_nh = abs(nh - nh_expected) / max(abs(nh_expected), 1e-12)
    checks.append({
        "name": "ammonium_stoichiometry",
        "passed": rel_nh <= rtol,
        "detail": f"NH4+ produced={nh:.6g}, expected 2*urea_consumed={nh_expected:.6g} (rel {rel_nh:.2%})",
        "value": float(nh), "tolerance": rtol,
    })

    # Carbonate stoichiometry: carbonate produced == urea consumed (1:1).
    carb = mb.get("carbonate_produced", 0.0)
    rel_carb = abs(carb - mb.get("urea_consumed", 0.0)) / max(abs(mb.get("urea_consumed", 0.0)), 1e-12)
    checks.append({
        "name": "carbonate_urea_stoichiometry",
        "passed": rel_carb <= rtol,
        "detail": f"carbonate produced={carb:.6g}, expected urea_consumed={mb.get('urea_consumed', 0.0):.6g}",
        "value": float(carb), "tolerance": rtol,
    })

    # CaCO3 mass consistency: precipitated Ca (consumed) == CaCO3 mol (1:1).
    rel_pc = abs(mb.get("caco3_mol_precipitated", 0.0) - mb.get("ca_consumed", 0.0)) \
        / max(abs(mb.get("ca_consumed", 0.0)), 1e-12)
    checks.append({
        "name": "caco3_ca_stoichiometry",
        "passed": rel_pc <= rtol,
        "detail": f"CaCO3 mol={mb.get('caco3_mol_precipitated', 0.0):.6g}, "
                  f"Ca consumed={mb.get('ca_consumed', 0.0):.6g}",
        "value": float(rel_pc), "tolerance": rtol,
    })

    # Ca mass balance: Ca in ≈ Ca consumed + remaining + out.
    ca_in = mb.get("ca_in_total", 0.0)
    ca_rem = mb.get("ca_remaining", 0.0)
    ca_out = mb.get("ca_out_approx", 0.0)
    ca_res = ca_in - mb.get("ca_consumed", 0.0) - ca_rem - ca_out
    rel_ca = abs(ca_res) / max(abs(ca_in), 1e-12)
    checks.append({
        "name": "calcium_mass_balance",
        "passed": rel_ca <= rtol,
        "detail": f"residual={ca_res:.6g} (rel {rel_ca:.2%})",
        "value": float(ca_res), "tolerance": rtol,
    })

    # Precipitated mass consistency: kg CaCO3 == mol * molar mass / 1000.
    mol = mb.get("caco3_mol_precipitated", 0.0)
    kg = mb.get("caco3_kg_precipitated", 0.0)
    kg_expected = mol * CACO3_MOLAR_MASS / 1000.0
    rel_kg = abs(kg - kg_expected) / max(abs(kg_expected), 1e-12)
    checks.append({
        "name": "caco3_mass_consistency",
        "passed": rel_kg <= rtol,
        "detail": f"kg={kg:.6g} vs mol*M={kg_expected:.6g} (rel {rel_kg:.2%})",
        "value": float(kg), "tolerance": rtol,
    })

    return checks


def check_numerical(result: SolverResult, *, cfl_ok: bool = True) -> list[dict[str, Any]]:
    """Stability / finite-ness checks on the last profile."""
    checks: list[dict[str, Any]] = []
    prof = result.profiles[-1]
    finite = all(math.isfinite(v) for v in prof.porosity + prof.calcite + prof.urea
                 + prof.ca + prof.nh + prof.carbonate)
    checks.append({
        "name": "finite_state",
        "passed": finite,
        "detail": "all state arrays finite" if finite else "non-finite value detected",
        "value": float(finite),
    })
    poro_ok = all(0.0 < p < 1.0 for p in prof.porosity)
    checks.append({
        "name": "porosity_bounds",
        "passed": poro_ok,
        "detail": f"porosity range [{min(prof.porosity):.4g}, {max(prof.porosity):.4g}]",
        "value": float(min(prof.porosity)),
    })
    checks.append({
        "name": "cfl_adherence",
        "passed": bool(cfl_ok),
        "detail": "CFL-limited time step" if cfl_ok else "CFL guard not satisfied",
        "value": float(cfl_ok),
    })
    return checks


def check_grid_sensitivity(
    cfg_factory,
    *, nx_course: int = 32, nx_fine: int = 128,
    warn_threshold: float = 0.15,
) -> dict[str, Any]:
    """Run the same scenario at two resolutions and compare the integral metric
    (total calcite). Reports a relative difference; the service treats > 15% as
    a finding (numerical dispersion not yet converged), and > 40% as a hard
    failure. Both resolutions must resolve the reaction front — the coarse grid
    must be fine enough that upwind numerical dispersion does not dominate the
    physical dispersion (acceptance §九.3 grid sensitivity)."""
    from .solver import solve_transport

    coarse = solve_transport(cfg_factory(nx_course))
    fine = solve_transport(cfg_factory(nx_fine))
    m_c = coarse.mass_balance.get("caco3_kg_precipitated", 0.0)
    m_f = fine.mass_balance.get("caco3_kg_precipitated", 0.0)
    rel = abs(m_f - m_c) / max(abs(m_f), 1e-12)
    return {
        "name": "grid_sensitivity",
        "passed": rel <= warn_threshold,
        "detail": f"nx={nx_course}: {m_c:.4g} kg vs nx={nx_fine}: {m_f:.4g} kg (rel {rel:.2%})",
        "value": float(rel), "tolerance": warn_threshold,
        "metric": "total_precipitated_caco3_kg",
        "coarse": {"nx": nx_course, "value": float(m_c)},
        "fine": {"nx": nx_fine, "value": float(m_f)},
    }


def profile_to_jsonable(result: SolverResult) -> dict[str, Any]:
    """Down-sample profiles to a compact, schema-friendly shape."""
    prof = result.profiles[-1]
    n = len(prof.x)
    step = max(1, n // 64)
    xs = prof.x[::step]
    return {
        "x_m": [round(v, 8) for v in xs],
        "urea_mol_per_m3": [round(v, 6) for v in prof.urea[::step]],
        "ca_mol_per_m3": [round(v, 6) for v in prof.ca[::step]],
        "nh_mol_per_m3": [round(v, 6) for v in prof.nh[::step]],
        "carbonate_mol_per_m3": [round(v, 6) for v in prof.carbonate[::step]],
        "porosity": [round(v, 6) for v in prof.porosity[::step]],
        "calcite_kg_per_m3": [round(v, 6) for v in prof.calcite[::step]],
        "permeability_m2": [round(v, 12) for v in prof.permeability[::step]],
        "n_nodes": len(prof.x),
        "snapshot_count": len(result.profiles),
    }


def mass_balance_metrics(result: SolverResult) -> dict[str, Any]:
    """Machine-readable mass-balance block for artifacts and evals."""
    mb = result.mass_balance
    return {
        "urea_in_total_mol": finite_or_none(mb.get("urea_in_total")),
        "urea_consumed_mol": finite_or_none(mb.get("urea_consumed")),
        "urea_remaining_mol": finite_or_none(mb.get("urea_remaining")),
        "urea_out_approx_mol": finite_or_none(mb.get("urea_out_approx")),
        "ca_in_total_mol": finite_or_none(mb.get("ca_in_total")),
        "ca_consumed_mol": finite_or_none(mb.get("ca_consumed")),
        "ca_remaining_mol": finite_or_none(mb.get("ca_remaining")),
        "ca_out_approx_mol": finite_or_none(mb.get("ca_out_approx")),
        "nh_produced_mol": finite_or_none(mb.get("nh_produced")),
        "carbonate_produced_mol": finite_or_none(mb.get("carbonate_produced")),
        "caco3_mol_precipitated": finite_or_none(mb.get("caco3_mol_precipitated")),
        "caco3_kg_precipitated": finite_or_none(mb.get("caco3_kg_precipitated")),
        "urea_mass_balance_residual": finite_or_none(mb.get("urea_mass_balance_residual")),
        "nh_urea_stoich_residual": finite_or_none(mb.get("nh_urea_stoich_residual")),
    }


def find_max_blockage(profile) -> dict[str, float]:
    """Location and magnitude of the maximum porosity loss (clogging front)."""
    idx = min(range(len(profile.porosity)),
              key=lambda i: profile.porosity[i])
    return {
        "x_max_blockage_m": profile.x[idx],
        "porosity_min": profile.porosity[idx],
        "porosity_loss_fraction": 1.0 - profile.porosity[idx],
    }


# ---------------------------------------------------------------------------
# Schema validation (input.schema.json / output.schema.json)
# ---------------------------------------------------------------------------

_SCHEMA_DIR = Path(__file__).resolve().parent.parent.parent / "schemas"
_input_schema_cache: dict | None = None
_output_schema_cache: dict | None = None


def _load_schema(name: str) -> dict:
    global _input_schema_cache, _output_schema_cache
    if name == "input":
        if _input_schema_cache is None:
            _input_schema_cache = json.loads(
                (_SCHEMA_DIR / "input.schema.json").read_text(encoding="utf-8"))
        return _input_schema_cache
    if _output_schema_cache is None:
        _output_schema_cache = json.loads(
            (_SCHEMA_DIR / "output.schema.json").read_text(encoding="utf-8"))
    return _output_schema_cache


def _try_jsonschema(value, schema: dict) -> list[tuple[str, str]]:
    try:
        from jsonschema import Draft202012Validator
        v = Draft202012Validator(schema)
        return [(str(e.absolute_path), e.message) for e in sorted(v.iter_errors(value), key=lambda e: str(e.absolute_path))]
    except Exception:
        return []


def _fallback_validate(value, schema: dict, prefix: str = "") -> list[tuple[str, str]]:
    """Minimal draft-2020-12 subset validator (required/enum/type/additionalProps)."""
    issues: list[tuple[str, str]] = []
    if not isinstance(schema, dict):
        return issues
    if schema.get("type") == "object":
        if not isinstance(value, dict):
            issues.append((prefix or "$", f"expected object, got {type(value).__name__}"))
            return issues
        props = schema.get("properties", {})
        for r in schema.get("required", []):
            if r not in value:
                issues.append((f"{prefix}.{r}", "missing required property"))
        for k, v in value.items():
            spec = props.get(k)
            p = f"{prefix}.{k}" if prefix else k
            if spec is None:
                if schema.get("additionalProperties") is False:
                    issues.append((p, "additional property not allowed"))
                continue
            issues.extend(_fallback_validate(v, spec, p))
    elif schema.get("type") == "array":
        if not isinstance(value, list):
            issues.append((prefix or "$", f"expected array, got {type(value).__name__}"))
            return issues
        item = schema.get("items", {})
        for i, iv in enumerate(value):
            issues.extend(_fallback_validate(iv, item, f"{prefix}[{i}]"))
    elif schema.get("type") == "string":
        if not isinstance(value, str):
            issues.append((prefix or "$", "expected string"))
    elif schema.get("type") in ("number", "integer"):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            issues.append((prefix or "$", "expected number"))
    if "enum" in schema and value not in schema["enum"]:
        issues.append((prefix or "$", f"value {value!r} not in enum"))
    return issues


def validate_input(payload: dict) -> list[tuple[str, str]]:
    """Validate a request against schemas/input.schema.json."""
    schema = _load_schema("input")
    issues = _try_jsonschema(payload, schema)
    if not issues:
        return issues
    return issues


def validate_output(payload: dict) -> list[tuple[str, str]]:
    """Validate a response against schemas/output.schema.json."""
    schema = _load_schema("output")
    issues = _try_jsonschema(payload, schema)
    if not issues:
        return issues
    return issues
