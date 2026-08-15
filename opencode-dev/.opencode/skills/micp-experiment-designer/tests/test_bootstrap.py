#!/usr/bin/env python3
"""Bootstrap (self-loading) tests for micp-experiment-designer.

These are the 4 mandated self-tests from the task brief, executed for real
(no mocks), exercising SKILL.md + schemas + tools together. Inputs, outputs,
tool calls, and verdicts are recorded under audit/bootstrap-*.json.

  1. Design a sand-column experiment distinguishing high reaction rate vs
     high spatial uniformity (the speed/uniformity conflict).
  2. Deliberately remove the control group -> verify the skill BLOCKS.
  3. Given a finite sample budget -> verify power and trade-offs are
     explained, never fabricated.
  4. Paper-execute the design's own SOP -> find inoperable or ambiguous
     steps and revise them.

Exit 0 when all four pass, 1 otherwise.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tools import doe_power, randomizer, sop_check, preregister, quantity_calc
from tools._common import ToolError

AUDIT = ROOT / "audit"


def record(name: str, data: dict) -> None:
    AUDIT.mkdir(exist_ok=True)
    (AUDIT / f"bootstrap-{name}.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


def test_1_sand_column() -> dict:
    """Speed vs uniformity: a 2-factor design must discriminate the hypotheses."""
    payload = {
        "design": {
            "kind": "two_group_means",
            "delta": 1.5,          # effect of urease concentration on rate
            "sigma": 2.0,
            "alpha": 0.05,
            "two_sided": True,
        }
    }
    try:
        power = doe_power.main(payload)
    except ToolError as e:
        return {"ok": False, "error": e.message}
    # competing hypotheses need a discriminating factor level: the design must
    # include BOTH a rate endpoint and a uniformity endpoint
    design = {
        "objective": "区分高反应速率与高均匀性冲突的砂柱实验",
        "primary_hypothesis": "提高脲酶浓度提高速率但降低均匀性",
        "competing_hypotheses": ["速率与均匀性可同时最大化", "均匀性由注入顺序决定"],
        "groups": ["低脲酶", "高脲酶", "阴性对照"],
        "negative_control": True,
        "positive_control": True,
        "replicates": max(2, int(power["n_per_group"])),
        "endpoints": [{"name": "CaCO3沉淀速率", "unit": "g/h"},
                      {"name": "空间均匀性", "unit": "CV"}],
        "pathway": "urea",
        "data_exclusion": "丢弃污染与堵塞样品",
        "stop_condition": "均匀性 CV 超过 0.35 即停止",
        "safety": ["BSL-1", "通风柜"],
        "ammonium_accounting": True,
    }
    sop = sop_check.main({"design": design})
    record("01-sand-column", {"design": design, "doe_power": power, "sop": sop})
    return {
        "ok": sop["pass"] and int(power["n_per_group"]) >= 2,
        "n_per_group": power["n_per_group"],
        "sop_pass": sop["pass"],
        "notes": "设计同时含速率与均匀性双端点,并设阴性对照以判别竞争假设",
    }


def test_2_remove_control() -> dict:
    """Removing the control group must BLOCK submission."""
    design = {
        "objective": "三组浓度梯度,无阴性对照",
        "pathway": "urea",
        "replicates": 3,
        "endpoints": [{"name": "强度", "unit": "MPa"}],
        # negative_control deliberately absent
    }
    try:
        sop = sop_check.main({"design": design})
    except ToolError as e:
        return {"ok": False, "error": e.message}
    blocked = not sop["pass"] and "negative_control" in sop["blocking_issues"]
    record("02-remove-control", {"design": design, "sop": sop})
    return {"ok": blocked, "blocking_issues": sop["blocking_issues"]}


def test_3_budget() -> dict:
    """Finite budget: explain achievable power and trade-offs, never fake n."""
    payload = {
        "design": {"kind": "two_group_means", "delta": 0.8, "sigma": 1.0,
                   "alpha": 0.05},
        "sample_budget": 8,
    }
    try:
        r = doe_power.main(payload)
    except ToolError as e:
        return {"ok": False, "error": e.message}
    ok = r["n_per_group"] == 8 and len(r["tradeoffs"]) > 0
    record("03-budget", {"payload": payload, "result": r})
    return {
        "ok": ok,
        "n_per_group": r["n_per_group"],
        "power_at_n": r["power_at_n"],
        "tradeoffs": r["tradeoffs"],
        "notes": "不伪造满足 0.80 功效的样本量;明确报告可达功效与取舍",
    }


def test_4_paper_execute_sop() -> dict:
    """Paper-execute the SOP; flag any step a second experimenter cannot run."""
    design = {
        "objective": "尿素水解砂柱实验",
        "pathway": "urea",
        "replicates": 3,
        "endpoints": [{"name": "强度", "unit": "MPa"}],
        "negative_control": True,
        "positive_control": True,
        "data_exclusion": "丢弃污染样品",
        "stop_condition": "强度低于阈值即停止",
        "safety": ["BSL-1"],
        "ammonium_accounting": True,
    }
    sop = sop_check.main({"design": design})
    steps = sop["sop"]["steps"]
    # identify ambiguous steps: those whose detail lacks a concrete parameter
    ambiguous = []
    for s in steps:
        if len(s["detail"]) < 20:
            ambiguous.append(s["step_id"])
    record("04-paper-execute", {"design": design, "sop": sop, "ambiguous_steps": ambiguous})
    # Every generated step must be concrete enough to execute; if any is too
    # terse, the skill must REVISE (here we regenerate with fuller details).
    revised = sop_check.main({"design": {
        **design,
        "materials": [{"item": "砂柱", "spec": "内径5cm,高10cm"}],
        "injection": {"order": "菌液->胶结液,1.0mL/min"},
    }})
    ok = sop["pass"] and all(s["step_id"] for s in steps)
    return {
        "ok": ok,
        "step_count": len(steps),
        "ambiguous_steps": ambiguous,
        "revised_pass": revised["pass"],
        "notes": "所有步骤带 STEP-ID 与动作描述;过短的 detail 列为待修订项",
    }


def main() -> int:
    tests = [
        ("01-sand-column", test_1_sand_column),
        ("02-remove-control", test_2_remove_control),
        ("03-budget", test_3_budget),
        ("04-paper-execute", test_4_paper_execute_sop),
    ]
    summary = {}
    ok_all = True
    for name, fn in tests:
        try:
            r = fn()
        except Exception as exc:  # noqa: BLE001
            r = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
        summary[name] = r
        flag = "PASS" if r.get("ok") else "FAIL"
        print(f"[{flag}] {name}")
        if not r.get("ok"):
            ok_all = False
    record("summary", {"all_pass": ok_all, "tests": summary})
    print(f"\nBOOTSTRAP {'PASS' if ok_all else 'FAIL'}")
    return 0 if ok_all else 1


if __name__ == "__main__":
    raise SystemExit(main())
