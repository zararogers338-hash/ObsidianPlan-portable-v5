"""Shared fixtures for micp-lca-technoeconomic tests."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

TOOLS = Path(__file__).resolve().parent.parent / "tools"
sys.path.insert(0, str(TOOLS))
sys.path.insert(0, str(TOOLS / "micp_lca"))

from factors import FactorDatabase  # noqa: E402
from units import reference_flow_ratio  # noqa: E402


def make_payload(**overrides) -> dict:
    payload = {
        "contract_version": "1.0",
        "task_id": "test-1",
        "project_id": "panshi-test",
        "request": "评估 MICP 处理 1 m3 砂体的碳排与成本, 与水泥基准比较",
        "action": "compare",
        "skill_version": "1.0.0",
        "controller_version": "obsidian-ctl-0.1.0",
        "timestamp": "2026-08-07T00:00:00Z",
        "risk_level": "low",
        "human_approval_state": "not_required",
        "constraints": {"analysis_year": 2026, "random_seed": 42},
        "functional_unit": {
            "description": "处理 1 m3 松散砂体, 目标 UCS >= 1.0 MPa",
            "reference_flow": {"value": 1, "unit": "m3"},
            "performance_target": {"metric": "UCS", "value": 1.0, "unit": "MPa"},
        },
        "scope": {
            "time_boundary": "2026, 一次性施工",
            "geography": "中国华北",
            "energy_mix": "华北电网平均",
            "transport": "材料公路运输 100 km",
            "material_source": "工业级尿素与 CaCl2",
            "waste_route": "nitrification",
            "technology_readiness": "TRL 6 现场中试",
            "analysis_size": {"value": 100, "unit": "m3"},
            "reference_scale": {"value": 100, "unit": "m3"},
        },
        "baseline": {"id": "cement-dsm", "type": "cement",
                     "description": "水泥搅拌桩处理 1 m3 砂体"},
        "scenarios": [
            {
                "id": "micp-a",
                "type": "micp",
                "materials": {"urea_kg": 40.0, "cacl2_kg": 30.0, "media_kg": 2.0,
                              "culture_kg": 1.0, "water_m3": 0.5, "price_tier": "industrial"},
                "energy": {"electricity_kwh": 15.0, "diesel_L": 2.0},
                "transport": {"material_distance_km": 100.0},
                "waste": {"route": "nitrification", "derive_from_urea": True},
                "labour": {"hours": 6.0},
                "capex": {"equipment_cny": 80000, "injection_system_cny": 30000,
                          "site_setup_cny": 20000, "engineering_cny": 15000},
                "opex": {"monitoring_cny": 5000, "maintenance_cny": 3000, "insurance_cny": 1000},
                "contingency": {"risk_reserve_pct": 10.0, "failure_cost_cny": 20000,
                                "downtime_pct": 5.0},
            },
            {
                "id": "cement-dsm",
                "type": "cement",
                "materials": {"cement_kg": 350.0, "water_m3": 0.2},
                "energy": {"electricity_kwh": 8.0, "diesel_L": 3.0},
                "transport": {"material_distance_km": 50.0},
                "waste": {"slurry_m3": 0.1},
                "labour": {"hours": 2.0},
                "capex": {"equipment_cny": 50000, "injection_system_cny": 20000,
                          "site_setup_cny": 15000},
                "opex": {"monitoring_cny": 2000, "maintenance_cny": 1000, "insurance_cny": 500},
                "contingency": {"risk_reserve_pct": 8.0},
            },
        ],
    }
    payload.update(overrides)
    return payload


@pytest.fixture
def db() -> FactorDatabase:
    return FactorDatabase()


@pytest.fixture
def payload() -> dict:
    return make_payload()
