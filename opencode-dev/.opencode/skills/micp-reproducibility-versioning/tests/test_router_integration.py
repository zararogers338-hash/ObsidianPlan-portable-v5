"""Router-integration verification for micp-reproducibility-versioning.

Proves the new skill is (a) indexable as `usable` by the real
obsidian-skill-router registry, and (b) routable for a reproducibility request,
using the router's own planner against the real on-disk skill directory.

Requires bun + the router package to be present (repo dev toolchain). Skipped
automatically when bun or the router is unavailable, so the core pytest suite
stays green offline without the router.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

SKILL_ROOT = Path(__file__).resolve().parent.parent
REPO_SKILLS = SKILL_ROOT.parent  # <repo>/skills
ROUTER = REPO_SKILLS / "obsidian-skill-router"

SKILL_NAME = "micp-reproducibility-versioning"


def _bun_available() -> bool:
    return shutil.which("bun") is not None


def _has_router() -> bool:
    return (ROUTER / "tools" / "osr" / "registry.ts").is_file()


pytestmark = pytest.mark.skipif(
    not (_bun_available() and _has_router()),
    reason="router integration test requires bun + obsidian-skill-router present",
)


def _run_router_check() -> subprocess.CompletedProcess:
    script = r"""
import { indexRegistry } from "ROUTER/tools/osr/registry.ts"
import { buildPlan } from "ROUTER/tools/osr/planner.ts"
const root = "REPO_SKILLS"
const { snapshot } = await indexRegistry([root])
const entry = snapshot.entries.find((e) => e.name === "SKILL_NAME")
if (!entry || !entry.usable) { console.log(JSON.stringify({ ok: false, reason: "not usable", issues: entry?.issues })); process.exit(1) }
const req = {
  task_id: "T-1", project_id: "P-1",
  request: "对这批 MICP 实验做完整复现并归档：创建 reproduction manifest、锁定依赖环境、校验数据溯源与版本",
  context: {}, evidence_refs: [], data_refs: [], upstream_outputs: [],
  skill_version: "1.0.0", controller_version: "obsidian-ctl-0.1.0", timestamp: "2026-08-07T00:00:00Z",
  risk_level: "low",
}
const plan = buildPlan(req, snapshot)
const steps = plan.plan?.steps ?? []
const routed = steps.some((s) => s.skill === "SKILL_NAME")
console.log(JSON.stringify({ ok: routed, status: plan.status, steps: steps.map((s) => s.skill) }))
process.exit(routed ? 0 : 1)
"""
    script = (
        script.replace("ROUTER", str(ROUTER).replace("\\", "/"))
        .replace("REPO_SKILLS", str(REPO_SKILLS).replace("\\", "/"))
        .replace("SKILL_NAME", SKILL_NAME)
    )
    tmp = Path(__file__).resolve().parent / "_router_check_mrv.ts"
    tmp.write_text(script, encoding="utf-8")
    bun = shutil.which("bun")
    assert bun is not None, "bun must be discoverable when the router test runs"
    try:
        return subprocess.run(
            [bun, "run", str(tmp)],
            capture_output=True,
            text=True,
            timeout=120,
        )
    finally:
        tmp.unlink(missing_ok=True)


class TestRouterIntegration:
    def test_registry_indexes_skill_as_usable(self) -> None:
        proc = _run_router_check()
        assert proc.returncode == 0, f"router check failed: {proc.stdout} {proc.stderr}"
        out = json.loads(proc.stdout.strip().splitlines()[-1])
        assert out["ok"] is True
        assert out["status"] == "SUCCESS"
        assert SKILL_NAME in out["steps"]
