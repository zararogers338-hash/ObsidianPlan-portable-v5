"""Shared pytest fixtures for micp-biology-reasoner tests."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

TOOLS = Path(__file__).resolve().parent.parent / "tools"
CLI = TOOLS / "micp_bio_reasoner.py"

BASE_PAYLOAD = {
    "contract_version": "1.0",
    "task_id": "test",
    "project_id": "test-project",
    "request": "test request",
    "action": None,
    "skill_version": "0.1.0",
    "timestamp": "2026-08-06T00:00:00Z",
}


def invoke(payload: dict) -> dict:
    """Run the real CLI with a payload; return parsed stdout."""
    proc = subprocess.run(
        [sys.executable, str(CLI)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert proc.returncode == 0, f"CLI crashed: {proc.stderr}"
    return json.loads(proc.stdout)


@pytest.fixture
def base() -> dict:
    return dict(BASE_PAYLOAD)


@pytest.fixture
def invoke_cli():
    return invoke
