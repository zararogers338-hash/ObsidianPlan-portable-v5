"""Shared pytest fixtures for obsidian-red-team tests.

Puts tools/ort on sys.path so tests can import tool modules directly, and
provides a helper that runs the CLI as a subprocess (the way evals do).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys

import pytest

TOOLS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                         "tools", "ort")
sys.path.insert(0, TOOLS_DIR)

CLI = os.path.join(TOOLS_DIR, "cli.py")


def run_cli(subcommand: str, payload: dict) -> dict:
    """Run `python tools/ort/cli.py <subcommand>` with the payload on stdin.

    Returns the parsed stdout envelope ({ok, tool, version, result|error}).
    """
    proc = subprocess.run(
        [sys.executable, CLI, subcommand],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        cwd=os.path.dirname(TOOLS_DIR),
    )
    out = json.loads(proc.stdout or "{}")
    out["_exit"] = proc.returncode
    return out


@pytest.fixture
def cli():
    return run_cli


@pytest.fixture
def review_blocked_payload() -> dict:
    return {
        "task_id": "test-blocked-01",
        "project_id": "panshi-test",
        "request": "审查 MICP 部署结论（氨氮超限、伪重复、伪造引用）",
        "skill_version": "1.0.0",
        "controller_version": "obsidian-ctl-0.1.0",
        "timestamp": "2026-08-07T09:00:00Z",
        "risk_level": "high",
        "human_approval_state": "not_required",
        "constraints": {"state_gate": "DEPLOYABLE"},
        "targets": [
            {
                "id": "T1",
                "type": "decision",
                "summary": "MICP 处理后强度提高但渗透率下降，仍建议现场注入部署。氨氮 12 mg/L。",
                "location": "report.pdf §4.2",
                "epistemic_label": "INFERRED",
                "status_support": "DEPLOYABLE",
                "ammonia_concentration": 12,
                "recommends_deployment": True,
            }
        ],
        "evidence_refs": [
            {"ref_id": "R1", "locator": "fake-paper-xyz", "title": "Nonexistent Paper", "year": 2026}
        ],
    }


@pytest.fixture
def review_clean_payload() -> dict:
    return {
        "task_id": "test-clean-01",
        "project_id": "panshi-test",
        "request": "审查一条实验室 UCS 观测结论",
        "skill_version": "1.0.0",
        "controller_version": "obsidian-ctl-0.1.0",
        "timestamp": "2026-08-07T10:00:00Z",
        "constraints": {"state_gate": "VALIDATED"},
        "targets": [
            {
                "id": "T1",
                "type": "conclusion",
                "summary": "砂柱 UCS 均值 3.5 MPa, 标准差 0.4 MPa, n=8",
                "location": "lab-report §3",
                "epistemic_label": "OBSERVED",
                "status_support": "SUPPORTED",
            }
        ],
    }
