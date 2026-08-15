"""Shared fixtures for micp-data-analyst tests.

All fixtures are offline and deterministic. `run_tool` executes the real CLI
over stdin and asserts the exit code, proving the tools run for real.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys

TOOLS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                         "tools", "micp")
SKILL_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def run_tool(name: str, payload: dict, expect_exit: int = 0) -> dict:
    """Run a tool over stdin, return its envelope dict, assert the exit code."""
    script = os.path.join(TOOLS_DIR, "cli.py")
    proc = subprocess.run(
        [sys.executable, script, name],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        cwd=TOOLS_DIR,
        timeout=60,
    )
    assert proc.returncode == expect_exit, (
        f"{name} exited {proc.returncode}, expected {expect_exit}\n"
        f"stderr: {proc.stderr}\nstdout: {proc.stdout}")
    return json.loads(proc.stdout)


# A realistic pseudo-replicated UCS dataset (2 columns × 3 heights per treatment)
PSEUDO_INPUT = {
    "task_id": "test-01", "project_id": "panshi-demo",
    "request": "Analyze UCS strength across treatments, detect pseudo-replication, report statistics.",
    "skill_version": "1.0.0", "controller_version": "obsidian-ctl-0.1.0",
    "timestamp": "2026-08-06T12:00:00Z", "risk_level": "medium",
    "human_approval_state": "not_required", "requested_output_format": "json",
    "data_columns": [
        {"name": "specimen", "role": "id", "data_type": "string", "sampling_unit": "column"},
        {"name": "treatment", "role": "treatment", "data_type": "string"},
        {"name": "position", "role": "position", "data_type": "string"},
        {"name": "ucs", "role": "response", "data_type": "number", "unit": "MPa"},
    ],
    "samples": [
        {"specimen": "A1", "treatment": "ctrl", "position": "top", "ucs": 1.0},
        {"specimen": "A1", "treatment": "ctrl", "position": "mid", "ucs": 1.1},
        {"specimen": "A1", "treatment": "ctrl", "position": "bot", "ucs": 1.2},
        {"specimen": "A2", "treatment": "ctrl", "position": "top", "ucs": 1.3},
        {"specimen": "A2", "treatment": "ctrl", "position": "mid", "ucs": 1.4},
        {"specimen": "A2", "treatment": "ctrl", "position": "bot", "ucs": 1.5},
        {"specimen": "B1", "treatment": "micp", "position": "top", "ucs": 3.0},
        {"specimen": "B1", "treatment": "micp", "position": "mid", "ucs": 3.4},
        {"specimen": "B1", "treatment": "micp", "position": "bot", "ucs": 3.8},
        {"specimen": "B2", "treatment": "micp", "position": "top", "ucs": 3.2},
        {"specimen": "B2", "treatment": "micp", "position": "mid", "ucs": 3.5},
        {"specimen": "B2", "treatment": "micp", "position": "bot", "ucs": 3.9},
    ],
}

VALID_ENVELOPE = {
    "task_id": "t1", "project_id": "p", "request": "Analyze this MICP strength data.",
    "skill_version": "1.0.0", "controller_version": "obsidian-ctl-0.1.0",
    "timestamp": "2026-08-06T12:00:00Z", "risk_level": "low",
    "human_approval_state": "not_required", "requested_output_format": "json",
}
