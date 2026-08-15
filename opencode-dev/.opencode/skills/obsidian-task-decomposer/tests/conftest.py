"""Shared test fixtures for obsidian-task-decomposer tools.

All fixtures are offline and deterministic.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys

TOOLS_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__))) + os.sep + "tools"
SKILL_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

CYCLE_NODES = [
    {"id": "a", "depends_on": ["b"]},
    {"id": "b", "depends_on": ["a"]},
]

VALID_MICP_NODES = [
    {
        "id": "lit_review",
        "title": "Survey MICP ureolysis literature",
        "kind": "evidence_retrieval",
        "primary_skill": "micp-literature-scout",
        "depends_on": [],
        "inputs": ["request", "evidence_refs:whiffin2007"],
        "outputs": ["evidence_shortlist"],
        "definition_of_done": {
            "artifact": "evidence_shortlist.json",
            "acceptance_criteria": [
                {"metric": "sources_shortlisted", "comparator": ">=", "threshold": 10},
                {"metric": "has_dedup", "comparator": "==", "threshold": True},
            ],
        },
        "failure_modes": ["no sources found", "duplicate sources"],
        "retry_policy": {"max_attempts": 2, "backoff": "linear", "on_exhaustion": "replan_local"},
        "risk_level": "low",
        "data_sensitivity": "public",
        "est_effort_hours": 2.0,
        "est_context_tokens": 20000,
        "max_cost_budget": {"amount": 10, "currency": "USD"},
        "human_approval_gate": False,
    },
    {
        "id": "ureolysis_chem",
        "title": "Model ureolysis chemistry and ammonium balance",
        "kind": "mechanism_reasoning",
        "primary_skill": "micp-ureolysis-chemistry",
        "depends_on": ["lit_review"],
        "inputs": ["lit_review:evidence_shortlist", "context"],
        "outputs": ["ammonium_mass_balance"],
        "definition_of_done": {
            "artifact": "ammonium_mass_balance.md",
            "acceptance_criteria": [
                {"metric": "n_balance_closed", "comparator": ">=", "threshold": 0.95, "unit": "-"},
            ],
        },
        "failure_modes": ["pathway is not ureolytic", "data inconsistency"],
        "retry_policy": {"max_attempts": 2, "backoff": "none", "on_exhaustion": "escalate_human"},
        "risk_level": "medium",
        "data_sensitivity": "internal",
        "est_effort_hours": 6.0,
        "est_context_tokens": 30000,
        "max_cost_budget": {"amount": 20, "currency": "USD"},
        "human_approval_gate": False,
    },
]

MICP_DAG = {
    "dag": {"nodes": VALID_MICP_NODES},
    "execution_limits": {"max_call_depth": 8, "max_iterations": 50, "max_parallel_skills": 4},
    "findings": [
        {"statement": "ureolysis produces 2 mol NH4+ per mol CaCO3",
         "epistemic_tag": "CALCULATED", "source": "stoichiometry"},
    ],
}


def run_tool(name: str, payload: dict, expect_exit: int = 0) -> dict:
    """Run a tool over stdin, return its envelope dict, assert the exit code."""
    script = os.path.join(TOOLS_DIR, f"{name}.py")
    proc = subprocess.run(
        [sys.executable, script],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        cwd=TOOLS_DIR,
    )
    assert proc.returncode == expect_exit, (
        f"{name} exited {proc.returncode}, expected {expect_exit}\n"
        f"stderr: {proc.stderr}\nstdout: {proc.stdout}"
    )
    return json.loads(proc.stdout)
