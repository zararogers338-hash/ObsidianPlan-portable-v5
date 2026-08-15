"""Router-integration verification for micp-scaleup-injection-engineer.

Proves the new skill is (a) indexable as `usable` by the real
obsidian-skill-router registry, and (b) routable for a scale-up request, using
the router's own planner against the real on-disk skill directory.

Requires bun + the router package to be present (repo dev toolchain). Skipped
automatically when bun or the router is unavailable, so the core pytest suite
stays green offline without the router.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

SKILL_ROOT = Path(__file__).resolve().parent.parent
REPO_SKILLS = SKILL_ROOT.parent  # <repo>/skills
ROUTER = REPO_SKILLS / "obsidian-skill-router"


def _bun_path() -> str | None:
    """Resolve the real bun binary. On this Windows box bun is installed as a
    POSIX shell shim (no bun.exe on disk), so it must be launched via `sh`."""
    raw = shutil.which("bun")
    if not raw:
        return None
    cand = Path(raw)
    if cand.suffix.lower() in (".cmd", ".bat", ".ps1", ""):
        return raw  # caller will launch via `sh`
    return raw


def _has_router() -> bool:
    return (ROUTER / "tools" / "osr" / "registry.ts").is_file()


pytestmark = pytest.mark.skipif(
    not (_bun_path() and _has_router()),
    reason="router integration test requires bun + obsidian-skill-router present",
)


def _run_router_check(script: str) -> subprocess.CompletedProcess:
    # Write the check script inside the router directory and use relative
    # imports — absolute Windows paths with drive letters get mangled by bun.
    tmp = ROUTER / "_router_check.ts"
    tmp.write_text(script, encoding="utf-8")
    bun = _bun_path()
    assert bun, "bun must be discoverable when the router test runs"
    try:
        if os.name == "nt":
            # bun is a POSIX shim on this box; launch via Git Bash `sh`.
            proc = subprocess.run(
                ["sh", "-c", f'cd "{ROUTER}" && "{bun}" run _router_check.ts'],
                capture_output=True, timeout=120)
        else:
            proc = subprocess.run([bun, "run", str(tmp)],
                                  capture_output=True, timeout=120, cwd=str(ROUTER))
        out = proc.stdout.decode("utf-8", errors="replace")
        err = proc.stderr.decode("utf-8", errors="replace")
        return subprocess.CompletedProcess(proc.args, proc.returncode, out, err)
    finally:
        tmp.unlink(missing_ok=True)


def test_registry_indexes_skill_as_usable():
    script = r'''
import { indexRegistry } from "./tools/osr/registry.ts"
const root = "../"   // skills/ (parent of the router dir where this script lives)
const { snapshot } = await indexRegistry([root])
const entry = snapshot.entries.find((e) => e.name === "micp-scaleup-injection-engineer")
if (!entry) { console.log(JSON.stringify({ ok: false, reason: "not found" })); process.exit(1) }
console.log(JSON.stringify({ ok: entry.usable, issues: entry.issues, manifest_valid: entry.manifest_valid }))
process.exit(entry.usable ? 0 : 1)
'''
    res = _run_router_check(script)
    assert res.returncode == 0, f"router check failed: {res.stderr}\n{res.stdout}"
    parsed = json.loads(res.stdout.strip().splitlines()[-1])
    assert parsed["ok"] is True
    assert parsed["issues"] == [] or parsed["manifest_valid"] is True


def test_planner_routes_scaleup_request():
    script = r'''
import { indexRegistry } from "./tools/osr/registry.ts"
import { buildPlan } from "./tools/osr/planner.ts"
const root = "../"
const { snapshot } = await indexRegistry([root])
const req = {
  task_id: "T-SU-1", project_id: "P-SU-1",
  request: "把 5cm 砂柱放大到米级试验，设计现场注入方案与监测计划",
  context: {}, evidence_refs: [], data_refs: [], upstream_outputs: [],
  skill_version: "1.0.0", controller_version: "1.4.2",
  timestamp: "2026-08-07T00:00:00Z", risk_level: "medium",
}
const plan = buildPlan(req, snapshot)
const steps = plan.plan?.steps ?? []
const routed = steps.some((s) => s.skill === "micp-scaleup-injection-engineer")
console.log(JSON.stringify({ ok: routed, status: plan.status, steps: steps.map((s) => s.skill) }))
process.exit(routed ? 0 : 1)
'''
    res = _run_router_check(script)
    assert res.returncode == 0, f"planner check failed: {res.stderr}\n{res.stdout}"
    parsed = json.loads(res.stdout.strip().splitlines()[-1])
    assert parsed["ok"] is True
    assert "micp-scaleup-injection-engineer" in parsed["steps"]
