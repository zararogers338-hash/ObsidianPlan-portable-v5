"""Shared pytest fixtures for MES tests and evals."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

from mes import jsonschema as _js  # noqa: E402


def load_schema(name: str) -> dict:
    return json.loads((ROOT / "schemas" / name).read_text(encoding="utf-8"))


@pytest.fixture(scope="session")
def input_schema() -> dict:
    return load_schema("input.schema.json")


@pytest.fixture(scope="session")
def output_schema() -> dict:
    return load_schema("output.schema.json")


def make_card(**overrides) -> dict:
    """A valid, poolable evidence card with two arms."""
    card = {
        "ref_id": "doi:10.1000/example",
        "study_id": "chen2024",
        "study_type": "lab_experiment",
        "layer": "engineering_performance",
        "evidence_level": "L1_direct_observation",
        "strain": ["Sporosarcina pasteurii"],
        "material": {"soil_type": "Ottawa sand", "grain_size_d50_mm": 0.4},
        "treatment": {
            "cementation_solution_concentration": {"value": 1.0, "unit": "mol/L"},
            "injection_protocol": "5 injections, 1 pore volume each",
        },
        "context": {"scale": "column", "saturation": "100%"},
        "sample": {"diameter_mm": 50, "height_mm": 100, "curing_days": 7,
                   "loading_rate_mm_min": 1.0},
        "measurement": {"method": "unconfined compression", "endpoint_timing": "7 d"},
        "outcome": {"name": "UCS", "value": 3.2, "unit": "MPa",
                    "direction": "higher_is_better",
                    "spread": {"sd": 0.4}},
        "reported_effect": {
            "effect_type": "mean_difference",
            "arms": [
                {"name": "MICP", "n": 6, "mean": 3.2, "sd": 0.4, "unit": "MPa"},
                {"name": "control", "n": 6, "mean": 0.4, "sd": 0.1, "unit": "MPa"},
            ],
        },
        "risk_of_bias": {"overall": "low"},
        "claims": [{"statement": "MICP raised UCS", "label": "REPORTED"}],
    }
    card.update(overrides)
    return card


def make_base_input(**overrides) -> dict:
    base = {
        "contract_version": "1.0",
        "task_id": "task-001",
        "project_id": "proj-001",
        "request": "synthesize UCS evidence for MICP-treated sand",
        "action": "evidence.synthesize",
        "skill_version": "1.0.0",
        "controller_version": "1.0.0",
        "timestamp": "2026-08-06T00:00:00Z",
        "pico": {
            "population": "Ottawa sand, D50=0.4mm, Dr=60%",
            "intervention": "MICP, 1M cementation solution, 5 injections",
            "outcome": "UCS at 7 d, MPa",
            "unit": "MPa",
        },
        "evidence_cards": [make_card()],
    }
    base.update(overrides)
    return base
