"""Integration tests: full CLI pipelines across the actions, output-schema
self-check, and router-integration verification.

The router test requires bun + obsidian-skill-router; it is skipped
automatically when either is missing so the offline core suite stays green.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

SKILL_ROOT = Path(__file__).resolve().parent.parent
REPO_SKILLS = SKILL_ROOT.parent
ROUTER = REPO_SKILLS / "obsidian-skill-router"


def _model_spec(purpose: str = "EXPLANATION", **overrides) -> dict:
    spec = {
        "purpose": purpose,
        "model_kind": "ode",
        "state_variables": ["urea", "ca", "nh4", "biomass", "calcite"],
        "parameters": [
            {"name": "k_ure", "role": "literature_prior", "value": 1e-4, "unit": "1/s"},
            {"name": "k_pre", "role": "literature_prior", "value": 1e-4, "unit": "1/s"},
        ],
        "equations": {"kind": "ode", "ureolysis": "michaelis_menten", "precipitation": "first_order_min"},
        "initial_conditions": {"urea0": 500, "ca0": 500, "biomass0": 1.0, "phi0": 0.4},
        "observations": ["urea", "nh4", "caco3"],
        "error_model": "additive_gaussian",
        "space_scale": "lab_column",
        "time_scale": "days",
    }
    spec.update(overrides)
    return spec


class TestActions:
    def test_validate_action(self, base, invoke_cli) -> None:
        p = dict(base)
        p["action"] = "validate"
        p["model_specification"] = _model_spec()
        out = invoke_cli(p)
        assert out["status"] == "SUCCESS"
        assert out["validation"]["output_schema"] is True

    def test_solve_action_envelope(self, base, invoke_cli) -> None:
        p = dict(base)
        p["action"] = "solve"
        spec = _model_spec()
        spec["initial_conditions"] = {"urea0": 500, "ca0": 500, "biomass0": 1.0,
                                      "phi0": 0.4, "t_end": 86400}
        p["model_specification"] = spec
        out = invoke_cli(p)
        assert out["status"] == "SUCCESS", out["errors"]
        assert out["model_output"]["times"][-1] > 0
        assert out["conservation"]["ok"] is True
        assert out["numerical"]["ok"] is True

    def test_sensitivity_action_sobol(self, base, invoke_cli) -> None:
        p = dict(base)
        p["action"] = "sensitivity"
        p["model_specification"] = _model_spec()
        p["sensitivity"] = {
            "parameters": ["k_ure", "k_pre"],
            "bounds": [[1e-5, 3e-4], [1e-5, 3e-4]],
            "target": "caco3_kg",
            "method": "sobol",
            "n_base": 100,
        }
        p["constraints"] = {"random_seed": 1}
        out = invoke_cli(p)
        assert out["status"] == "SUCCESS", out["errors"]
        assert len(out["sensitivity"]["first_order"]) == 2
        assert len(out["sensitivity"]["total_order"]) == 2

    def test_sensitivity_action_morris(self, base, invoke_cli) -> None:
        p = dict(base)
        p["action"] = "sensitivity"
        p["model_specification"] = _model_spec()
        p["sensitivity"] = {
            "parameters": ["k_ure", "k_pre", "k_half"],
            "bounds": [[1e-5, 3e-4], [1e-5, 3e-4], [100, 500]],
            "target": "caco3_kg",
            "method": "morris",
            "r": 6,
            "p": 4,
        }
        p["constraints"] = {"random_seed": 1}
        out = invoke_cli(p)
        assert out["status"] == "SUCCESS", out["errors"]
        assert len(out["sensitivity"]["mu_star"]) == 3

    def test_uq_action(self, base, invoke_cli) -> None:
        p = dict(base)
        p["action"] = "uq"
        p["model_specification"] = _model_spec()
        p["uncertainty"] = {
            "parameters": [
                {"name": "k_ure", "dist": "uniform", "low": 5e-5, "high": 3e-4},
                {"name": "k_pre", "dist": "uniform", "low": 5e-5, "high": 3e-4},
            ],
            "target": "caco3_kg",
            "n_samples": 50,
        }
        p["constraints"] = {"random_seed": 2}
        out = invoke_cli(p)
        assert out["status"] == "SUCCESS", out["errors"]
        uq = out["uncertainty_analysis"]
        assert uq["outputs"][0]["p5"] <= uq["outputs"][0]["p95"]

    def test_doe_generate(self, base, invoke_cli) -> None:
        p = dict(base)
        p["action"] = "doe"
        p["doe"] = {
            "factors": [{"name": "urea", "low": 200, "high": 800},
                        {"name": "ca", "low": 200, "high": 800},
                        {"name": "k_ure", "low": 1e-5, "high": 1e-3}],
            "kind": "box_behnken",
        }
        p["constraints"] = {"random_seed": 3}
        out = invoke_cli(p)
        assert out["status"] == "SUCCESS", out["errors"]
        # BBD for 3 factors: 12 edge midpoints + 3 center = 15 runs
        assert out["doe_report"]["n_runs"] == 15

    def test_schema_subcommand(self) -> None:
        proc = subprocess.run(
            [sys.executable, str(SKILL_ROOT / "tools" / "modeling.py"), "schema"],
            capture_output=True, text=True, timeout=30,
        )
        assert proc.returncode == 0
        schema = json.loads(proc.stdout)
        assert schema["$id"].endswith("micp-modeling-optimizer.input.json")

    def test_selfcheck_subcommand(self) -> None:
        # a valid envelope must pass selfcheck (exit 0)
        envelope = {
            "contract_version": "1.0", "skill": "micp-modeling-optimizer",
            "skill_version": "1.0.0", "status": "SUCCESS", "summary": "x",
            "findings": [], "assumptions": [], "evidence_used": [], "uncertainty": [],
            "risks": [], "artifacts": [], "requested_next_skills": [],
            "validation": {"input_schema": True, "output_schema": True, "self_check": True,
                           "checks": []},
            "provenance": {"skill": "micp-modeling-optimizer", "skill_version": "1.0.0"},
            "errors": [],
        }
        tmp = SKILL_ROOT / "tests" / "_env.json"
        tmp.write_text(json.dumps(envelope), encoding="utf-8")
        try:
            proc = subprocess.run(
                [sys.executable, str(SKILL_ROOT / "tools" / "modeling.py"), "selfcheck", str(tmp)],
                capture_output=True, text=True, timeout=30,
            )
            assert proc.returncode == 0, proc.stdout
        finally:
            tmp.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# Router integration (bun + real obsidian-skill-router)
# ---------------------------------------------------------------------------


def _bun_available() -> bool:
    return shutil.which("bun") is not None


def _has_router() -> bool:
    return (ROUTER / "tools" / "osr" / "registry.ts").is_file()


pytestmark_router = pytest.mark.skipif(
    not (_bun_available() and _has_router()),
    reason="router integration test requires bun + obsidian-skill-router present",
)


@pytestmark_router
def test_router_indexes_skill_as_usable() -> None:
    script = r"""
import { indexRegistry } from "ROUTER/tools/osr/registry.ts"
import { buildPlan } from "ROUTER/tools/osr/planner.ts"
const root = "REPO_SKILLS"
const { snapshot } = await indexRegistry([root])
const entry = snapshot.entries.find((e) => e.name === "micp-modeling-optimizer")
if (!entry || !entry.usable) { console.log(JSON.stringify({ ok: false, reason: "not usable", issues: entry?.issues })); process.exit(1) }
const req = {
  task_id: "T-1", project_id: "P-1",
  request: "为 MICP 柱实验建立机理模型并做多目标优化，求 Pareto 前沿，反演参数并做敏感性分析",
  context: {}, evidence_refs: [], data_refs: [], upstream_outputs: [],
  skill_version: "1.0.0", controller_version: "obsidian-ctl-0.1.0", timestamp: "2026-08-07T00:00:00Z",
  risk_level: "low",
}
const plan = buildPlan(req, snapshot)
const steps = plan.plan?.steps ?? []
const routed = steps.some((s) => s.skill === "micp-modeling-optimizer")
console.log(JSON.stringify({ ok: routed, status: plan.status, steps: steps.map((s) => s.skill) }))
process.exit(routed ? 0 : 1)
"""
    script = (
        script.replace("ROUTER", str(ROUTER).replace("\\", "/"))
        .replace("REPO_SKILLS", str(REPO_SKILLS).replace("\\", "/"))
    )
    tmp = Path(__file__).resolve().parent / "_router_check.ts"
    tmp.write_text(script, encoding="utf-8")
    bun = shutil.which("bun")
    assert bun is not None
    try:
        proc = subprocess.run([bun, "run", str(tmp)], capture_output=True, text=True, timeout=90)
    finally:
        tmp.unlink(missing_ok=True)
    assert proc.returncode == 0, f"router check failed: {proc.stdout} {proc.stderr}"
    out = json.loads(proc.stdout.strip().splitlines()[-1])
    assert out["ok"] is True
    assert out["status"] == "SUCCESS"
    assert "micp-modeling-optimizer" in out["steps"]
