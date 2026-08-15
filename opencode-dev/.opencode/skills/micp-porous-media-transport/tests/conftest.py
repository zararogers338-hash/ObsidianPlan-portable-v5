"""Shared pytest fixtures. Run with: python -m pytest tests/ -q"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

TOOLS_DIR = Path(__file__).resolve().parent.parent / "tools"
CLI = TOOLS_DIR / "transport.py"

BASE = {
    "contract_version": "1.0",
    "task_id": "t-unit",
    "project_id": "unit-project",
    "request": "unit test invocation",
    "action": "analyze",
    "skill_version": "1.0.0",
    "controller_version": "1.0.0",
    "timestamp": "2026-08-06T00:00:00Z",
}

# A minimal, physically-plausible scenario (moderate rates, no clogging).
SMOKE_SCENARIO = {
    "geometry": {"length": {"value": 0.1, "unit": "m"}, "nx": 32},
    "porosity": {"value": 0.40, "unit": "-"},
    "permeability": {"value": 1e-11, "unit": "m2"},
    "flow": {"mode": "flux", "velocity": {"value": 2.8e-5, "unit": "m/s"}},
    "species": {
        "c_urea_in": {"value": 0.5, "unit": "mol/m3"},
        "c_ca_in": {"value": 0.5, "unit": "mol/m3"},
    },
}

# Reaction / control parameters to pair with SMOKE_SCENARIO (without t_end the
# solver runs until the clog threshold — which never fires at these low rates).
SMOKE_PARAMS = {"k_ure": 2e-3, "k_pre": 1e-3, "k_half": 0.5, "t_end": 3600}


def deep_copy_smoke() -> dict:
    """Independent deep copy of SMOKE_SCENARIO — tests must never mutate the
    module-level template (a shallow dict() copy would share nested dicts and
    poison later tests)."""
    return json.loads(json.dumps(SMOKE_SCENARIO))


def cli_call(payload: dict, *, expect_ok: bool = True) -> dict:
    """Run the real CLI with one payload; return parsed stdout."""
    proc = subprocess.run(
        [sys.executable, str(CLI)],
        input=json.dumps(payload), capture_output=True, text=True, timeout=300,
    )
    assert proc.returncode == 0, f"CLI crashed: {proc.stderr}"
    out = json.loads(proc.stdout)
    if expect_ok:
        assert out["status"] not in ("FAILED", "NEED_ADDITIONAL_SKILL", "HUMAN_APPROVAL_REQUIRED"), (
            f"unexpected status {out['status']} for {payload.get('action')}: "
            f"{out.get('summary')} errors={out.get('errors')}"
        )
    return out


@pytest.fixture
def base() -> dict:
    return dict(BASE)


@pytest.fixture
def smoke_scenario() -> dict:
    return json.loads(json.dumps(SMOKE_SCENARIO))


@pytest.fixture
def cli() -> Path:
    return CLI
