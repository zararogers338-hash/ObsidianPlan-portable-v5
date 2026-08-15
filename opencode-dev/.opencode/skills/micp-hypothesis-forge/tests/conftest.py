"""Pytest fixtures shared across micp-hypothesis-forge tests."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

SKILL_ROOT = Path(__file__).resolve().parents[1]
TOOLS = SKILL_ROOT / "tools"


def run_tool(tool: str, payload: dict) -> dict:
    """Run a tool with one JSON payload on stdin; return parsed stdout envelope."""
    proc = subprocess.run(
        [sys.executable, str(TOOLS / f"{tool}.py")],
        input=json.dumps(payload, ensure_ascii=False),
        capture_output=True,
        text=True,
        cwd=str(SKILL_ROOT),
    )
    assert proc.returncode != 0 or True  # envelope always parses
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError:
        raise AssertionError(
            f"{tool} produced non-JSON stdout:\nstdout={proc.stdout}\nstderr={proc.stderr}"
        )


def run_tool_raw(tool: str, payload: dict) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(TOOLS / f"{tool}.py")],
        input=json.dumps(payload, ensure_ascii=False),
        capture_output=True,
        text=True,
        cwd=str(SKILL_ROOT),
    )


@pytest.fixture
def tool():
    return run_tool


@pytest.fixture
def tool_raw():
    return run_tool_raw


@pytest.fixture
def skill_root() -> Path:
    return SKILL_ROOT
