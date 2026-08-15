"""Shared fixtures for the micp-modeling-optimizer pytest suite.

Every test drives the REAL CLI (tools/modeling.py) over stdin JSON -> stdout
JSON, exactly like the evals and the router integration test. This is the
M2-invariant: the suite never mocks the solver.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

TOOLS = Path(__file__).resolve().parent.parent / "tools"
MICPCORE = TOOLS / "micp"
CLI = TOOLS / "modeling.py"

# allow direct imports of the tool modules (kinetics, checks, ...) for the
# unit-level acceptance tests; the module files use flat imports (from _common)
# so micp/ itself must be on sys.path.
sys.path.insert(0, str(MICPCORE))
sys.path.insert(0, str(TOOLS))

BASE_PAYLOAD = {
    "contract_version": "1.0",
    "task_id": "test",
    "project_id": "test-project",
    "request": "test request",
    "action": None,
    "skill_version": "1.0.0",
    "controller_version": "obsidian-ctl-0.1.0",
    "timestamp": "2026-08-07T00:00:00Z",
    "risk_level": "low",
    "human_approval_state": "not_required",
}


def invoke(payload: dict) -> dict:
    """Run the real CLI with a payload; return parsed stdout.

    Exit codes 2/3/4 are legitimate failure outcomes of the envelope design
    (malformed payload / contract violation), so we do NOT assert returncode 0
    here — the returned envelope's `status` carries the semantic outcome.
    """
    proc = subprocess.run(
        [sys.executable, str(CLI)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        timeout=240,
    )
    return json.loads(proc.stdout)


@pytest.fixture
def base() -> dict:
    return dict(BASE_PAYLOAD)


@pytest.fixture
def invoke_cli():
    return invoke
