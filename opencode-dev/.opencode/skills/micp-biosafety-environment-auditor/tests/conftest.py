"""Shared pytest fixtures for micp-biosafety-environment-auditor tests."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

TOOLS = Path(__file__).resolve().parent.parent / "tools"
CLI = TOOLS / "mbs_auditor.py"

BASE_PAYLOAD = {
    "contract_version": "1.0",
    "task_id": "test",
    "project_id": "test-project",
    "request": "test request",
    "action": None,
    "skill_version": "1.0.0",
    "timestamp": "2026-08-07T00:00:00Z",
}


def invoke(payload: dict, env: dict | None = None) -> dict:
    """Run the real CLI with a payload; return parsed stdout."""
    proc = subprocess.run(
        [sys.executable, str(CLI)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        timeout=60,
        env=env,
    )
    assert proc.returncode == 0, f"CLI crashed: {proc.stderr}"
    return json.loads(proc.stdout)


def audit_payload(**overrides) -> dict:
    """A realistic, mostly-clean audit payload that can be mutated per test."""
    payload = dict(BASE_PAYLOAD)
    payload["action"] = "audit"
    payload["request"] = "审查 MICP 砂柱/现场方案的生物安全与环境风险"
    payload["risk_level"] = "medium"
    payload["site"] = {
        "name": "实验室砂柱试点",
        "release_type": "sand_column",
        "waste_treatment_capacity": True,
        "groundwater_injection": False,
        "site_sensitive_ecology": False,
        "aerosol_potential": False,
        "confined_space": False,
        "pH": 8.0,
        "temperature_c": 25.0,
        "strain": {"name": "Sporosarcina pasteurii", "culture_collection_id": "ATCC 11859"},
        # Clean-lab realism: the site's biosafety committee has already assessed
        # S. pasteurii against the in-force CN pathogen list (国卫科教发〔2023〕24号).
        "pathogen_list_ref": "国卫科教发〔2023〕24号",
    }
    payload["plan"] = {
        "name": "柱-01 尿素注浆",
        "nitrogen": {
            "urea_input_g": 120.0,
            "pH": 8.0,
            "temperature_c": 25.0,
            "liquid_residual_g": 20.0,
            "sorbed_retained_g": 35.0,
            "discharged_treated_g": 1.0,
        },
        "waste": {
            "volume_l": 5.0,
            "nh4_n_conc_mgL": 800.0,
            "total_n_load_g": 4.0,
            "discharge_to_environment": False,
        },
    }
    payload.update(overrides)
    return payload


@pytest.fixture
def base() -> dict:
    return dict(BASE_PAYLOAD)


@pytest.fixture
def invoke_cli():
    return invoke


@pytest.fixture
def audit() -> dict:
    return audit_payload()
