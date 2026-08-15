"""Shared fixtures for micp-scaleup-injection-engineer tests."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
TOOLS = HERE.parent / "tools"
sys.path.insert(0, str(TOOLS))

from msi.service import ScaleUpService  # noqa: E402


def make_payload(**overrides) -> dict:
    base = {
        "contract_version": "1.0",
        "task_id": "T-TEST",
        "project_id": "PRJ-TEST",
        "request": "MICP scale-up injection design",
        "action": "scaleup",
        "skill_version": "1.0.0",
        "controller_version": "1.4.2",
        "timestamp": "2026-08-07T00:00:00Z",
        "risk_level": "medium",
        "lab": {
            "recipe": {
                "urea_conc": {"value": 500, "unit": "mol/m3"},
                "ca_conc": {"value": 500, "unit": "mol/m3"},
                "pore_volumes_per_treatment": 1.0,
                "rounds": 5,
                "flow_mode": "constant_flux",
                "flow_rate": {"value": 0.0005, "unit": "m3/s"},
                "treatment_length": {"value": 0.05, "unit": "m"},
            }
        },
        "target": {
            "scale_level": "metre",
            "geometry": {"volume": {"value": 0.05, "unit": "m3"},
                         "length": {"value": 1.0, "unit": "m"},
                         "radius": {"value": 0.13, "unit": "m"}},
        },
        "site": {
            "layers": [
                {"name": "A", "thickness": {"value": 1.0, "unit": "m"},
                 "porosity": 0.4, "permeability": {"value": 1e-11, "unit": "m2"}},
            ]
        },
        "constraints": {
            "allowed_injection_pressure": {"value": 500000, "unit": "Pa"},
            "target_caco3_content_kg_m3": 60,
            "ammonia_limit_mg_L": 50,
            "conversion_efficiency": 0.5,
        },
    }
    base.update(overrides)
    return base


def run(payload: dict) -> dict:
    svc = ScaleUpService()
    return svc.handle(payload)


@pytest.fixture
def service() -> ScaleUpService:
    return ScaleUpService()


@pytest.fixture
def payload() -> dict:
    return make_payload()
