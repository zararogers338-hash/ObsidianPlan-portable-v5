"""Shared fixtures for micp-evidence-extractor tests.

All fixtures are offline and deterministic. `run_tool` executes the real CLI
over stdin and asserts the exit code, proving the tools run for real.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys

TOOLS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                         "tools", "mee")
SKILL_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCHEMAS_DIR = os.path.join(SKILL_ROOT, "schemas")

# Make the tool modules importable as top-level packages (tools/mee is not a
# package dir with __init__.py by design; tests import modules directly).
if TOOLS_DIR not in sys.path:
    sys.path.insert(0, TOOLS_DIR)


def run_tool(name: str, payload: dict, expect_exit: int = 0) -> dict:
    """Run a tool over stdin, return its envelope dict, assert the exit code."""
    script = os.path.join(TOOLS_DIR, "cli.py")
    proc = subprocess.run(
        [sys.executable, script, name],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        cwd=TOOLS_DIR,
        timeout=90,
    )
    assert proc.returncode == expect_exit, (
        f"{name} exited {proc.returncode}, expected {expect_exit}\n"
        f"stderr: {proc.stderr}\nstdout: {proc.stdout}")
    return json.loads(proc.stdout)


def valid_envelope(**overrides) -> dict:
    base = {
        "task_id": "mee-test", "project_id": "panshi-demo",
        "request": "从这篇 MICP 论文提取结构化证据卡，逐实验组、逐时间点、逐测量方法，不混组。",
        "skill_version": "1.0.0", "controller_version": "obsidian-ctl-0.1.0",
        "timestamp": "2026-08-07T09:00:00Z", "risk_level": "medium",
        "human_approval_state": "not_required", "requested_output_format": "json",
        "constraints": {"offline": True},
    }
    base.update(overrides)
    return base


def sample_document(**overrides) -> dict:
    doc = {
        "source_id": "paper-2023",
        "title": "Microbially induced calcite precipitation in sand columns",
        "year": "2023",
        "journal": "Geotechnical Testing Journal",
        "doi": "10.1002/jctb.280520402",
        "document_type": "original_research",
        "sections": [
            {"kind": "methods", "heading": "Materials and Methods",
             "text": "Sporosarcina pasteurii was cultured in B4 medium at 30 C. "
                     "Urease activity reached 0.8 mM urea/min/OD. Urea concentration "
                     "0.5 M and CaCl2 0.5 M were injected."},
            {"kind": "results", "heading": "Results",
             "text": "UCS reached 3.2 MPa after 14 days of treatment."},
        ],
        "tables": [
            {"table_id": "t1", "caption": "UCS results",
             "header": ["Group", "Day 7 UCS (kPa)", "Day 14 UCS (kPa)"],
             "rows": [["Control", "150", "210"], ["MICP", "1200", "2500"]],
             "source_locator": "Table 1"},
            {"table_id": "t2", "caption": "Biological characterization",
             "header": ["Sample", "OD600", "Urease (mM urea/min/OD)"],
             "rows": [["S. pasteurii", "1.2", "0.8"], ["Blank", "0.05", "0.0"]],
             "source_locator": "Table 2"},
        ],
        "figures": [],
    }
    doc.update(overrides)
    return doc


def run_service(payload: dict) -> dict:
    env = run_tool("service", payload)
    assert env.get("ok"), f"service failed: {env.get('error')}"
    return env["result"]


# Helper to walk every quantity in a card set.
def walk_quantities(cards):
    out = []

    def walk(node, path):
        if isinstance(node, dict):
            if "normalized_unit" in node and "acquisition_mode" in node \
                    and "value" in node and "epistemic_tag" in node:
                out.append((path, node))
                return
            for k, v in node.items():
                walk(v, f"{path}.{k}" if path else k)
        elif isinstance(node, list):
            for i, item in enumerate(node):
                walk(item, f"{path}[{i}]")

    for card in cards:
        walk(card, "")
    return out
