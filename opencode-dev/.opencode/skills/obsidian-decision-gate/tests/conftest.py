"""Shared fixtures for obsidian-decision-gate tests."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

TOOLS_DIR = Path(__file__).resolve().parent.parent / "tools"
sys.path.insert(0, str(TOOLS_DIR))


def make_mission(**overrides) -> dict:
    m = {
        "task_id": "T-MICP-01",
        "contract_version": "1.0.0",
        "title": "MICP 道路加固",
        "mission_type": "engineering",
        "objectives": [
            {"id": "o1", "statement": "验证 MICP 提升砂土强度至工程阈值", "kind": "engineering",
             "depends_on": []}
        ],
        "primary_objective_id": "o1",
        "metrics": [
            {"name": "strength", "direction": "maximize", "unit": "MPa",
             "target": {"value": 5, "unit": "MPa"},
             "threshold": {"value": 1, "unit": "MPa"}},
            {"name": "ammonia_emission", "direction": "minimize", "unit": "mg/m3",
             "target": {"value": 500, "unit": "mg/m3"}},
        ],
        "success_criteria": ["强度≥5MPa", "氨排放≤500 mg/m3"],
        "failure_thresholds": ["强度<1MPa"],
        "stop_conditions": ["氨排放超标即停"],
        "human_approval_gates": ["VALIDATED", "PILOT_READY", "DEPLOYABLE"],
        "stakeholders": ["工程方"],
        "decision_use": "阶段门放行决策",
        "spatial_scale": "lab: 38mm cylinder",
        "temporal_scale": "28 day curing",
    }
    m.update(overrides)
    return m


def evidence_cards(n: int = 3, **overrides) -> list[dict]:
    cards = []
    for i in range(n):
        cards.append({
            "ref_id": f"REF-{i+1}",
            "source": f"https://doi.org/10.1000/ref{i+1}",
            "label": "REPORTED",
            "verifiable": True,
            "evidence_level": "high",
            "scale": "lab",
            "outcome": "MICP 提升砂土强度",
        })
    if "verifiable" in overrides:
        for c in cards:
            c["verifiable"] = overrides["verifiable"]
    return cards


def synthesis(conclusions: list[dict] | None = None, **overrides) -> dict:
    s = {
        "conclusions": conclusions or [
            {"id": "c1", "statement": "MICP 可在砂土中沉积碳酸钙并提升强度",
             "label": "REPORTED", "evidence_level": "moderate", "scope": "lab"}
        ],
        "gaps": [{"gap": "无现场尺度数据", "impact": "medium", "how_to_fill": "开展中试"}],
        "synthesis_method": "structured_narrative",
        "grade": {"certainty": "moderate"},
    }
    s.update(overrides)
    return s


def reproducibility(**overrides) -> dict:
    r = {
        "reproducible": True,
        "evidence": "数据与代码已归档，三次独立重复结果一致",
        "data_archived": True,
        "code_archived": True,
        "versioned": True,
    }
    r.update(overrides)
    return r


def experiment(outcome: dict, *, scale: str = "lab", has_control: bool = True,
               kind: str = "strength_test", status: str = "completed",
               n: int = 6, id: str = "exp-1", **overrides) -> dict:
    e = {
        "id": id,
        "kind": kind,
        "status": status,
        "scale": scale,
        "has_control": has_control,
        "n": n,
        "outcomes": [outcome],
    }
    e.update(overrides)
    return e


def strength_met(value: float = 6.2, threshold: float = 5.0) -> dict:
    return {"name": "strength", "value": value, "unit": "MPa", "threshold": threshold,
            "direction": "maximize", "status": "met"}


def ammonia(value: float, threshold: float = 500.0) -> dict:
    return {"name": "ammonia_emission", "value": value, "unit": "mg/m3", "threshold": threshold,
            "direction": "minimize", "status": "met" if value <= threshold else "not_met"}


def scaleup_plan(**overrides) -> dict:
    p = {
        "stages": [
            {"scale": "pilot", "objective": "受控中试", "duration": "3 months", "capacity": "10 m³",
             "success_criteria": ["强度≥5MPa", "氨≤500mg/m3"]}
        ],
        "monitoring_plan": "强度;氨浓度;地下水pH",
        "shutdown_conditions": ["氨浓度超过 500 mg/m3", "地下水pH 超出 6-9"],
        "rollback_plan": "停止注入并抽排，恢复原状",
        "environmental_controls": ["氨气收集", "地下水监测井"],
    }
    p.update(overrides)
    return p


def make_base_payload(**overrides) -> dict:
    p = {
        "contract_version": "1.0",
        "task_id": "T-MICP-01",
        "project_id": "P-MICP-ROAD-01",
        "request": "评估 MICP 道路加固路线是否可推进至下一阶段",
        "action": "gate.evaluate",
        "skill_version": "1.0.0",
        "timestamp": "2026-08-07T00:00:00Z",
        "current_state": "EVIDENCE_GATHERING",
        "proposed_state": "SUPPORTED",
        "mission_lock": make_mission(),
        "evidence_cards": evidence_cards(3),
        "synthesis": synthesis(),
        "hypothesis_cards": [{
            "id": "H1", "kind": "hypothesis_card",
            "statement": "MICP 通过碳酸钙沉淀提升砂土强度",
            "mechanism_chain": ["尿素水解", "碳酸钙沉积", "颗粒胶结"],
            "prediction_direction": "increase", "observables": ["强度"],
            "refutation": "无强度提升即推翻", "time_scale": "28d",
            "scope": "lab sand", "epistemic_label": "HYPOTHESIS", "status": "SUPPORTED",
        }],
        "experiment_results": [experiment(strength_met())],
        "reproducibility": reproducibility(),
        "red_team_report": {"status": "passed", "findings": []},
    }
    p.update(overrides)
    return p


def approval(granted: bool = True, scope: str = "VALIDATED", revision: int = 1) -> dict:
    return {"granted": granted, "scope": scope, "revision": revision,
            "granted_at": "2026-08-01T00:00:00Z" if granted else None}


@pytest.fixture
def base_payload() -> dict:
    return make_base_payload()
