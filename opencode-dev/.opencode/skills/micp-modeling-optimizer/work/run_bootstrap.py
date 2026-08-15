#!/usr/bin/env python3
"""Bootstrap self-test for micp-modeling-optimizer (spec §十).

Drives the REAL CLI through the full workflow on synthetic MICP data:
  model definition -> parameter inversion -> identifiability check ->
  hold-out validation -> sensitivity analysis -> multi-objective optimization
  -> Pareto output -> self-review.

Writes per-case JSON artifacts to work/bootstrap-cases/ and a summary to
work/bootstrap-summary.json. Exit 0 when every case SUCCEEDs and passes its
self-review gate.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CLI = ROOT / "tools" / "modeling.py"
OUT = Path(__file__).resolve().parent / "bootstrap-cases"
sys.path.insert(0, str(ROOT / "tools" / "micp"))

from kinetics import KineticsConfig, solve_kinetic_system  # noqa: E402


def _invoke(payload: dict) -> dict:
    proc = subprocess.run(
        [sys.executable, str(CLI)],
        input=json.dumps(payload, ensure_ascii=False),
        capture_output=True, text=True, timeout=300,
    )
    assert proc.returncode in (0, 2), proc.stderr
    return json.loads(proc.stdout)


def _synth_data(k_ure: float, k_pre: float, n: int = 12) -> list[dict]:
    res = solve_kinetic_system(KineticsConfig(k_ure=k_ure, k_pre=k_pre),
                               urea0=500, ca0=500, t_end=86400)
    step = max(1, len(res.times) // n)
    rows = []
    for i in range(0, len(res.times), step)[:n]:
        rows.append({"t": round(res.times[i], 2),
                     "urea": round(res.urea[i], 3),
                     "caco3": round(res.calcite_kg[i], 5)})
    return rows


def _base(action: str) -> dict:
    return {
        "contract_version": "1.0", "task_id": "BOOT", "project_id": "P-BOOT",
        "request": f"bootstrap case: {action}",
        "action": action, "skill_version": "1.0.0",
        "controller_version": "obsidian-ctl-0.1.0",
        "timestamp": "2026-08-07T00:00:00Z",
        "risk_level": "low", "human_approval_state": "not_required",
    }


def _model_spec(purpose: str = "PARAMETER_INFERENCE") -> dict:
    return {
        "purpose": purpose, "model_kind": "ode",
        "state_variables": ["urea", "ca", "nh4", "biomass", "calcite"],
        "parameters": [
            {"name": "k_ure", "role": "calibration", "value": 1e-4, "unit": "1/s",
             "bounds": [1e-6, 1e-2]},
            {"name": "k_pre", "role": "calibration", "value": 1e-4, "unit": "1/s",
             "bounds": [1e-6, 1e-2]},
        ],
        "equations": {"kind": "ode", "ureolysis": "michaelis_menten",
                      "precipitation": "first_order_min"},
        "initial_conditions": {"urea0": 500, "ca0": 500, "biomass0": 1.0, "phi0": 0.4},
        "observations": ["urea", "nh4", "caco3"],
        "error_model": "additive_gaussian", "space_scale": "lab_column",
        "time_scale": "days",
    }


def run_all() -> dict:
    OUT.mkdir(exist_ok=True)
    cases: list[dict] = []

    # case 1: model definition + solve
    p = _base("solve")
    spec = _model_spec("EXPLANATION")
    spec["initial_conditions"]["t_end"] = 86400
    p["model_specification"] = spec
    p["constraints"] = {"random_seed": 1}
    out = _invoke(p)
    cases.append({"name": "model_definition_solve", "status": out["status"],
                  "conservation_ok": out.get("conservation", {}).get("ok"),
                  "numerical_ok": out.get("numerical", {}).get("ok"),
                  "caco3_kg": out.get("model_output", {}).get("calcite_kg", [None])[-1]})
    (OUT / "case1-solve.json").write_text(json.dumps(out, ensure_ascii=False, indent=2),
                                          encoding="utf-8")

    # case 2: parameter inversion + identifiability + hold-out
    p = _base("fit")
    p["model_specification"] = _model_spec("PARAMETER_INFERENCE")
    p["calibration"] = {
        "model": "kinetic_urea",
        "data": _synth_data(2e-4, 1e-4),
        "parameters": [
            {"name": "k_ure", "value": 1e-4, "bounds": [1e-6, 1e-2]},
            {"name": "k_pre", "value": 1e-4, "bounds": [1e-6, 1e-2]},
        ],
    }
    p["constraints"] = {"random_seed": 42, "n_starts": 3}
    out = _invoke(p)
    cal = out.get("calibration", {})
    ident = out.get("identifiability", {})
    cases.append({"name": "inversion_identifiability", "status": out["status"],
                  "theta": cal.get("theta"),
                  "holdout_ratio": cal.get("holdout_overfit_ratio"),
                  "verdict": ident.get("verdict"),
                  "classes": [x["class"] for x in ident.get("parameters", [])]})
    (OUT / "case2-fit.json").write_text(json.dumps(out, ensure_ascii=False, indent=2),
                                        encoding="utf-8")

    # case 3: sensitivity + UQ
    p = _base("sensitivity")
    p["model_specification"] = _model_spec("PARAMETER_INFERENCE")
    p["sensitivity"] = {"parameters": ["k_ure", "k_pre"],
                        "bounds": [[1e-5, 3e-4], [1e-5, 3e-4]],
                        "target": "caco3_kg", "method": "sobol", "n_base": 150}
    p["constraints"] = {"random_seed": 7}
    out = _invoke(p)
    cases.append({"name": "sensitivity_sobol", "status": out["status"],
                  "s1": out.get("sensitivity", {}).get("first_order")})
    (OUT / "case3-sensitivity.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")

    # case 4: multi-objective optimization + Pareto + robustness
    p = _base("multiobjective")
    p["model_specification"] = _model_spec("OPTIMIZATION")
    p["optimization"] = {
        "mode": "multi",
        "variables": [{"name": "k_ure"}, {"name": "k_pre"}],
        "bounds": [[1e-5, 5e-4], [1e-5, 5e-4]],
        "objectives": [
            {"name": "max_caco3", "target": {"output": "caco3_kg"}, "maximize": True},
            {"name": "min_ammonia", "target": {"output": "ammonia_release"}, "maximize": False},
        ],
    }
    p["constraints"] = {"random_seed": 7, "pop_size": 20, "n_gen": 15,
                        "robustness_samples": 10}
    out = _invoke(p)
    opt = out.get("optimization_results", {})
    cases.append({"name": "multiobjective_pareto", "status": out["status"],
                  "n_front": opt.get("n_front_solutions"),
                  "knee": opt.get("knee_point"),
                  "robustness_n": len(opt.get("robustness", {}).get("solutions", []))})
    (OUT / "case4-multiobjective.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")

    # case 5: full pipeline analyze
    p = _base("analyze")
    p["model_specification"] = _model_spec("OPTIMIZATION")
    p["calibration"] = {
        "model": "kinetic_urea",
        "data": _synth_data(1e-4, 1e-4),
        "parameters": [
            {"name": "k_ure", "value": 1e-4, "bounds": [1e-6, 1e-2]},
            {"name": "k_pre", "value": 1e-4, "bounds": [1e-6, 1e-2]},
        ],
    }
    p["sensitivity"] = {"parameters": ["k_ure", "k_pre"],
                        "bounds": [[1e-5, 3e-4], [1e-5, 3e-4]],
                        "target": "caco3_kg", "method": "sobol", "n_base": 100}
    p["optimization"] = {
        "mode": "multi",
        "variables": [{"name": "k_ure"}, {"name": "k_pre"}],
        "bounds": [[1e-5, 5e-4], [1e-5, 5e-4]],
        "objectives": [
            {"name": "max_caco3", "target": {"output": "caco3_kg"}, "maximize": True},
            {"name": "min_ammonia", "target": {"output": "ammonia_release"}, "maximize": False},
        ],
    }
    p["uncertainty"] = {"parameters": [
        {"name": "k_ure", "dist": "uniform", "low": 5e-5, "high": 3e-4},
        {"name": "k_pre", "dist": "uniform", "low": 5e-5, "high": 3e-4}],
        "target": "caco3_kg", "n_samples": 50}
    p["constraints"] = {"random_seed": 7, "pop_size": 16, "n_gen": 10,
                        "robustness_samples": 8}
    out = _invoke(p)
    cases.append({"name": "full_pipeline_analyze", "status": out["status"],
                  "n_front": out.get("optimization_results", {}).get("n_front_solutions"),
                  "has_identifiability": "identifiability" in out,
                  "has_sensitivity": "sensitivity" in out,
                  "has_uq": "uncertainty_analysis" in out})
    (OUT / "case5-analyze.json").write_text(json.dumps(out, ensure_ascii=False, indent=2),
                                            encoding="utf-8")

    # self-review
    ok = all(c["status"] == "SUCCESS" for c in cases)
    summary = {
        "suite": "micp-modeling-optimizer-bootstrap",
        "all_pass": ok,
        "cases": cases,
    }
    (Path(__file__).resolve().parent / "bootstrap-summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    for c in cases:
        flag = "OK " if c["status"] == "SUCCESS" else "!! "
        print(f"{flag}{c['name']}: {c['status']}")
    return summary


if __name__ == "__main__":
    summary = run_all()
    sys.exit(0 if summary["all_pass"] else 1)
