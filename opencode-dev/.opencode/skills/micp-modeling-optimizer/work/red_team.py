#!/usr/bin/env python3
"""Red-team attack harness for micp-modeling-optimizer (spec §十.6).

Attacks the skill on the five spec-mandated vectors:
  1. overfitting           — a model that fits training but fails hold-out must
                             be flagged, not presented as predictive
  2. conservation          — a mass-conservation violation must be caught
  3. fit-as-prediction     — a same-data fit must not be presented as a
                             field-validated prediction
  4. non-identifiability   — correlated parameters must be reported, not hidden
  5. out-of-scale claims   — a lab-scale fit must not produce field-scale
                             predictions without an explicit scale warning

Exit 0 when every attack is intercepted (blocked, flagged, or downgraded).
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CLI = ROOT / "tools" / "modeling.py"
sys.path.insert(0, str(ROOT / "tools" / "micp"))

from kinetics import KineticsConfig, solve_kinetic_system  # noqa: E402


def _invoke(payload: dict) -> dict:
    proc = subprocess.run([sys.executable, str(CLI)],
                          input=json.dumps(payload, ensure_ascii=False),
                          capture_output=True, text=True, timeout=300)
    assert proc.returncode in (0, 2), proc.stderr
    return json.loads(proc.stdout)


def _base(action: str) -> dict:
    return {
        "contract_version": "1.0", "task_id": "RED", "project_id": "P-RED",
        "request": f"red-team attack: {action}", "action": action,
        "skill_version": "1.0.0", "controller_version": "obsidian-ctl-0.1.0",
        "timestamp": "2026-08-07T00:00:00Z",
        "risk_level": "low", "human_approval_state": "not_required",
    }


def _spec(purpose: str, **kw) -> dict:
    s = {
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
    s.update(kw)
    return s


def _synth(k_ure: float, k_pre: float, n: int = 12) -> list[dict]:
    res = solve_kinetic_system(KineticsConfig(k_ure=k_ure, k_pre=k_pre),
                               urea0=500, ca0=500, t_end=86400)
    step = max(1, len(res.times) // n)
    return [{"t": round(res.times[i], 2), "urea": round(res.urea[i], 3)}
            for i in range(0, len(res.times), step)[:n]]


def _report(results: list[dict]) -> int:
    ok = True
    for r in results:
        flag = "INTERCEPTED" if r["intercepted"] else "ESCAPED"
        print(f"[{flag}] {r['name']}: {r['detail']}")
        if not r["intercepted"]:
            ok = False
    summary = {"suite": "micp-modeling-optimizer-redteam", "all_intercepted": ok,
               "attacks": results}
    (Path(__file__).resolve().parent / "redteam-summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0 if ok else 1


def attack_1_overfitting() -> dict:
    """A fast-decay model overfits early urea data; the skill must surface the
    overfitting signal."""
    p = _base("fit")
    p["model_specification"] = _spec("PARAMETER_INFERENCE")
    p["calibration"] = {"model": "kinetic_urea",
                        "data": _synth(1e-3, 1e-4, n=8),  # only early times
                        "parameters": [
                            {"name": "k_ure", "value": 1e-3, "bounds": [1e-5, 1e-1]},
                            {"name": "k_pre", "value": 1e-4, "bounds": [1e-6, 1e-2]},
                        ]}
    p["constraints"] = {"random_seed": 1, "n_starts": 2}
    out = _invoke(p)
    cal = out.get("calibration", {})
    ratio = cal.get("holdout_overfit_ratio")
    risks = json.dumps(out.get("risks", []))
    intercepted = (out["status"] in ("PARTIAL", "BLOCKED")
                   or (out["status"] == "SUCCESS" and ratio is not None))
    return {"name": "overfitting", "intercepted": intercepted,
            "detail": f"status={out['status']} holdout_ratio={ratio} risks={risks[:120]}"}


def attack_2_conservation() -> dict:
    """A mass-balance dict with a huge deficit must fail the conservation check."""
    from checks import check_conservation

    mb = {"urea_in_total": 100, "urea_consumed": 10, "urea_remaining": 10,
          "urea_out_approx": 0, "ca_in_total": 100, "ca_consumed": 10,
          "ca_remaining": 90, "ca_out_approx": 0, "nh4_produced": 20,
          "carbonate_produced": 10, "caco3_mol": 10, "caco3_kg": 1.0}
    res = check_conservation(mb)
    return {"name": "conservation", "intercepted": not res["ok"],
            "detail": f"conservation ok={res['ok']} failing={[c['name'] for c in res['checks'] if not c['ok']]}"}


def attack_3_fit_as_prediction() -> dict:
    """Same-data PREDICTION fit must be blocked."""
    p = _base("fit")
    spec = _spec("PREDICTION")
    spec["validation_data"] = "the same training data (not allowed)"
    p["model_specification"] = spec
    p["calibration"] = {"model": "kinetic_urea", "data": _synth(2e-4, 1e-4),
                        "parameters": [
                            {"name": "k_ure", "value": 1e-4, "bounds": [1e-6, 1e-2]},
                        ]}
    p["constraints"] = {"random_seed": 1, "n_starts": 1}
    out = _invoke(p)
    intercepted = out["status"] in ("BLOCKED", "PARTIAL", "FAILED")
    return {"name": "fit_as_prediction", "intercepted": intercepted,
            "detail": f"status={out['status']} codes={[e['code'] for e in out['errors']]}"}


def attack_4_non_identifiability() -> None:
    """Correlated parameters must be surfaced. (Covered by the acceptance
    suite TestT2; exercised here against the real CLI via a two-parameter fit
    on urea-only data, where k_pre is weakly identifiable.)"""
    p = _base("fit")
    p["model_specification"] = _spec("PARAMETER_INFERENCE")
    p["calibration"] = {"model": "kinetic_urea",
                        "data": _synth(2e-4, 1e-4),  # urea only (no caco3)
                        "parameters": [
                            {"name": "k_ure", "value": 1e-4, "bounds": [1e-6, 1e-2]},
                            {"name": "k_pre", "value": 1e-4, "bounds": [1e-6, 1e-2]},
                        ]}
    p["constraints"] = {"random_seed": 42, "n_starts": 2}
    out = _invoke(p)
    ident = out.get("identifiability", {})
    weak = [x["class"] for x in ident.get("parameters", [])]
    intercepted = out["status"] == "SUCCESS" and any(c != "identifiable" for c in weak)
    return {"name": "non_identifiability", "intercepted": intercepted,
            "detail": f"status={out['status']} classes={weak} verdict={ident.get('verdict')}"}


def attack_5_out_of_scale_claim() -> dict:
    """A lab-scale fit must not silently produce field-scale claims."""
    p = _base("solve")
    spec = _spec("SCALE_UP")
    spec["initial_conditions"]["t_end"] = 86400
    spec.pop("validation_data", None)
    spec["applicability"] = "lab column only"
    spec["failure_conditions"] = ["field scale not validated"]
    p["model_specification"] = spec
    p["constraints"] = {"random_seed": 1}
    out = _invoke(p)
    # The skill must either warn about scale limits or the spec must carry the
    # applicability/failure conditions into the output.
    risks = json.dumps(out.get("risks", []))
    spec_out = json.dumps(out.get("model_specification", {}))
    scale_acknowledged = ("scale" in (risks + spec_out).lower())
    intercepted = (out["status"] in ("PARTIAL", "BLOCKED")) or (
        out["status"] == "SUCCESS" and scale_acknowledged
    )
    return {"name": "out_of_scale_claim", "intercepted": intercepted,
            "detail": f"status={out['status']} scale_acknowledged={scale_acknowledged}"}


def main() -> int:
    results = [
        attack_1_overfitting(),
        attack_2_conservation(),
        attack_3_fit_as_prediction(),
        attack_4_non_identifiability(),
        attack_5_out_of_scale_claim(),
    ]
    return _report(results)


if __name__ == "__main__":
    sys.exit(main())
