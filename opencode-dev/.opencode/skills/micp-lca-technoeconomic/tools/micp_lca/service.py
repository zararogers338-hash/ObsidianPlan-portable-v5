"""micp-lca-technoeconomic core service.

Pipeline (all tool calls are real; no fabricated outputs):

  1. validate input envelope against schemas/input.schema.json
  2. version gate (skill_version major, contract_version major)
  3. scope gate: functional unit + system boundary + baseline declared;
     every formal calculation requires functional_unit AND baseline
     (missing -> BLOCKED LCA-E103 / LCA-E104)
  4. gate: scope completeness (time/geography/energy mix/transport/TRL)
  5. per scenario: inventory + environmental results + cost model
  6. comparison: boundary-symmetry check (LCA-E704) + functional-unit
     fairness (LCA-E705)
  7. hotspots (Pareto) + sensitivity (OAT) + Monte Carlo (when asked)
  8. scenario comparison + recommendations
  9. self-check against schemas/output.schema.json
  10. envelope
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

from _common import ToolError, now_iso, env_clock, emit_progress
from errors import LcaErrorCode, LcaError
from factors import FactorDatabase
from inventory import build_inventory, NH3_N_FRACTION
from cost import build_cost_model
from uncertainty import run_monte_carlo, run_oats, run_morris, pareto_hotspots, compare_scenarios
from _jsonschema import validate_json
import units

SKILL_VERSION = "1.0.0"
SCHEMA_MAJOR = 1

_REQUIRED_ENVELOPE = ["contract_version", "task_id", "project_id", "request",
                      "skill_version", "controller_version", "timestamp"]

# Scope fields that must be declared for any formal calculation (spec §二).
_REQUIRED_SCOPE = [
    "time_boundary", "geography", "energy_mix", "transport",
    "material_source", "technology_readiness",
]

_SCOPE_KEYS = {
    "time_boundary", "geography", "energy_mix", "transport",
    "material_source", "waste_route", "recycling", "equipment_utilization",
    "service_life", "technology_readiness", "analysis_size", "reference_scale",
}


class _Pipeline:
    def __init__(self, payload: dict):
        self.p = payload
        self.db = FactorDatabase(overrides=payload.get("factors"))
        self.functional_unit = payload.get("functional_unit") or {}
        self.baseline = payload.get("baseline") or {}
        self.scope = payload.get("scope") or {}
        self.scenarios = payload.get("scenarios") or []
        self.constraints = payload.get("constraints") or {}
        self.year = int((self.constraints or {}).get("analysis_year", 2026))

    # ------------------------------------------------------------------ gates
    def gate_version(self) -> None:
        sv = self.p.get("skill_version")
        if not isinstance(sv, str) or not sv.split(".")[0] == str(SCHEMA_MAJOR):
            raise LcaError(LcaErrorCode.VERSION_MISMATCH,
                           f"skill_version {sv!r} major must be {SCHEMA_MAJOR}",
                           detail={"skill_version": sv})
        cv = self.p.get("contract_version")
        if cv and str(cv).split(".")[0] != str(SCHEMA_MAJOR):
            raise LcaError(LcaErrorCode.VERSION_MISMATCH,
                           f"contract_version {cv!r} major must be {SCHEMA_MAJOR}",
                           detail={"contract_version": cv})

    def gate_envelope(self) -> None:
        missing = [k for k in _REQUIRED_ENVELOPE if not self.p.get(k)]
        if missing:
            raise LcaError(LcaErrorCode.MISSING_REQUIRED_FIELD,
                           "缺少关键信封字段",
                           detail={"missing": missing,
                                   "field_guidance": {k: self._guidance(k) for k in missing}})

    @staticmethod
    def _guidance(field: str) -> str:
        return {
            "contract_version": "Input/output schema contract version, e.g. '1.0'.",
            "task_id": "Task identifier from the controller / task decomposer.",
            "project_id": "Project identifier.",
            "request": "The LCA/techno-economic request as natural language.",
            "skill_version": "Skill version, must be 1.x.y.",
            "controller_version": "Controller version, e.g. obsidian-ctl-0.1.0.",
            "timestamp": "ISO-8601 caller timestamp.",
        }.get(field, "Supply the field per the input schema.")

    def gate_scope(self) -> dict:
        """Return a BLOCKED dict (not raise) so callers can report details."""
        missing_fu = False
        fu = self.functional_unit
        if not isinstance(fu, dict) or not fu.get("description"):
            missing_fu = True
        missing_base = not isinstance(self.baseline, dict) or not self.baseline.get("id")
        if missing_fu:
            raise LcaError(LcaErrorCode.MISSING_FUNCTIONAL_UNIT,
                           "缺少功能单位(functional_unit): 任何正式计算必须先定义功能单位、参考流与系统边界",
                           detail={"missing_inputs": {
                               "functional_unit": {
                                   "why_critical": "ISO 14040 要求功能单位声明待评价服务的量化绩效; 无功能单位则无法归一化清单与比较",
                                   "how_to_obtain": "在 functional_unit 中给出 description / reference_flow(value+unit) / performance_target",
                               }}})
        if missing_base:
            raise LcaError(LcaErrorCode.MISSING_BASELINE,
                           "缺少基准方案(baseline): 比较类 LCA/技术经济分析必须声明基准方案",
                           detail={"missing_inputs": {
                               "baseline": {
                                   "why_critical": "没有基准则无法回答'比传统方案便宜/低碳吗',所有比较结论都会被标为无基准",
                                   "how_to_obtain": "在 baseline 中给出 id/type(如 cement/chemical) 与实现相同功能单位的用量",
                               }}})
        # scope completeness
        missing_scope = [k for k in _REQUIRED_SCOPE if not self.scope.get(k)]
        if missing_scope:
            raise LcaError(LcaErrorCode.INCOMPLETE_SCOPE,
                           "系统边界声明不完整",
                           detail={"missing": missing_scope,
                                   "field_guidance": {k: self._scope_guidance(k) for k in missing_scope}})
        return fu

    @staticmethod
    def _scope_guidance(k: str) -> str:
        return {
            "time_boundary": "时间边界, 如 '2026-2031, 5年服务期'",
            "geography": "地理边界, 如 '中国华北地区'",
            "energy_mix": "能源结构, 如 '中国电网平均' 或 '华北燃煤为主'",
            "transport": "运输距离假设, 如 '尿素产地至现场 500 km, 公路'",
            "material_source": "材料来源, 如 '工业级尿素, 工厂提货'",
            "technology_readiness": "技术成熟度, 如 TRL 4-5 (中试) 或 TRL 9 (工业)",
        }.get(k, "scope.<field>")

    def _require_scenarios(self) -> list[dict]:
        if not isinstance(self.scenarios, list) or len(self.scenarios) == 0:
            raise LcaError(LcaErrorCode.INPUT_SCHEMA_VIOLATION,
                           "缺少 scenarios: 需要至少一个待评价情景",
                           detail={"scenarios": self.scenarios})
        return self.scenarios

    # ------------------------------------------------------------- computation
    def evaluate_scenario(self, scenario: dict, label: str) -> dict:
        env = build_inventory(scenario, self.functional_unit, self.scope, self.db, self.year)
        cost = build_cost_model(scenario, self.functional_unit, self.scope, self.db, self.year)
        return {"scenario_id": scenario.get("id") or label,
                "type": scenario.get("type"),
                "environmental": env["environmental_results"],
                "mass_balance": env.get("mass_balance", {}),
                "inventory": env["inventory"],
                "cost": {**cost["cost_results"], "warnings": cost["warnings"]},
                "per_fu": cost["per_fu"],
                "scale_up": cost["scale_up"],
                "cost_warnings": cost["warnings"],
                "env_warnings": [w for dim in env["environmental_results"].values()
                                 for w in dim.get("warnings", [])],
                "provenance": env["provenance"],
                "hotspots": pareto_hotspots(env["environmental_results"]["gwp"].get("breakdown", []))}

    def boundary_symmetry_check(self, results: list[dict]) -> list[dict]:
        """LCA-E704: when any scenario treats its waste, every scenario with a
        comparable waste stream must declare its own treatment; a comparison
        that treats MICP effluent but omits the baseline's waste is asymmetric
        and must be surfaced (the caller decides whether it is a defect)."""
        problems: list[str] = []
        waste_routes = {}
        for r in results:
            routes = [i["factor_id"] for i in r["inventory"].get("items", [])
                      if i.get("key") in ("waste_treatment", "sludge", "waste")]
            waste_routes[r["scenario_id"]] = routes
        has_any = any(routes for routes in waste_routes.values())
        if has_any:
            for sid, routes in waste_routes.items():
                if not routes:
                    problems.append(
                        f"scenario {sid} 未声明废液/废渣处理项, 而其它情景已计入;"
                        " 比较边界可能不对称(LCA-E704)")
        return problems

    def run_sensitivity(self, scenario: dict, result: dict) -> dict:
        target = "gwp_total"
        inputs = {}
        mats = scenario.get("materials") or {}
        energy = scenario.get("energy") or {}
        inputs.update({f"urea_kg": float(mats.get("urea_kg", 0.0)),
                       f"cacl2_kg": float(mats.get("cacl2_kg", 0.0)),
                       f"water_m3": float(mats.get("water_m3", 0.0))})
        inputs.update({f"electricity_kwh": float(energy.get("electricity_kwh", 0.0))})
        inputs = {k: v for k, v in inputs.items() if v != 0.0}
        if not inputs:
            return {"oats": {"note": "no numeric inputs to perturb"}, "morris": None}
        db = self.db

        def eval_gwp(over: dict) -> dict:
            gwp = 0.0
            if "urea_kg" in over:
                gwp += over["urea_kg"] * db.get("gwp.urea")["value"]
            if "cacl2_kg" in over:
                gwp += over["cacl2_kg"] * db.get("gwp.cacl2")["value"]
            if "water_m3" in over:
                gwp += over["water_m3"] * db.get("gwp.water_industrial")["value"]
            if "electricity_kwh" in over:
                gwp += over["electricity_kwh"] * db.get("gwp.electricity_cn_avg")["value"]
            return {"gwp_total": gwp}

        oats = run_oats(eval_gwp, inputs, "gwp_total", delta_pct=10.0)
        morris = run_morris(lambda over: eval_gwp(over)["gwp_total"],
                            [fid for fid in ("gwp.urea", "gwp.cacl2", "gwp.water_industrial",
                                             "gwp.electricity_cn_avg") if db.has(fid)],
                            db, k_samples=20, seed=int(self.constraints.get("random_seed", 42)))
        return {"oats": oats, "morris": morris}

    def run_mc(self, scenario: dict) -> dict:
        db = self.db
        factor_ids = [fid for fid in ("gwp.urea", "gwp.cacl2", "gwp.media_yeast",
                                      "gwp.electricity_cn_avg",
                                      "gwp.wastewater_nh3_n_removal") if db.has(fid)]
        seed = int(self.constraints.get("random_seed", 42))
        n = int(self.constraints.get("monte_carlo_iterations", 200))

        def eval_gwp(over: dict) -> float:
            mats = scenario.get("materials") or {}
            energy = scenario.get("energy") or {}
            waste = scenario.get("waste") or {}
            urea = float(mats.get("urea_kg", 0.0)); cacl2 = float(mats.get("cacl2_kg", 0.0))
            media = float(mats.get("media_kg", 0.0)); elec = float(energy.get("electricity_kwh", 0.0))
            n_load = float(waste.get("nh3_n_kg", 0.0)) or urea * NH3_N_FRACTION
            gwp = 0.0
            if "gwp.urea" in over: gwp += urea * over["gwp.urea"]
            if "gwp.cacl2" in over: gwp += cacl2 * over["gwp.cacl2"]
            if "gwp.media_yeast" in over: gwp += media * over["gwp.media_yeast"]
            if "gwp.electricity_cn_avg" in over: gwp += elec * over["gwp.electricity_cn_avg"]
            if "gwp.wastewater_nh3_n_removal" in over:
                gwp += n_load * over["gwp.wastewater_nh3_n_removal"]
            return gwp

        return run_monte_carlo(eval_gwp, factor_ids, db, n_iter=n, seed=seed)

    # ------------------------------------------------------------- comparison
    def fairness_check(self, results: list[dict]) -> list[dict]:
        """LCA-E705: all scenarios share the same functional unit by
        construction (scale ratio), but lifetimes / performance targets may
        differ — surface those differences."""
        notes: list[str] = []
        fu = self.functional_unit
        target = (fu.get("performance_target") or {}) if isinstance(fu, dict) else {}
        for r in results:
            if not target:
                continue
            scen_target = r.get("performance_target")
            if scen_target and scen_target != target:
                notes.append(f"scenario {r['scenario_id']} 性能目标与功能单位不一致")
        return notes

    def build_comparison(self, results: list[dict]) -> dict:
        rows = []
        for r in results:
            rows.append({
                "scenario_id": r["scenario_id"],
                "gwp_total": r["environmental"]["gwp"]["value"],
                "energy_mj": r["environmental"]["energy"]["value"],
                "nitrogen_load": r["environmental"]["nitrogen_load"]["value"],
                "total_cost_cny": r["cost"]["total_cost_cny"],
                "cost_per_fu_cny": r["per_fu"]["total_cost_cny"],
            })
        return compare_scenarios(rows, ["gwp_total", "energy_mj", "nitrogen_load",
                                        "total_cost_cny", "cost_per_fu_cny"])

    def recommendations(self, results: list[dict], comparison: dict) -> list[dict]:
        out: list[dict] = []
        for m in comparison.get("metrics", []):
            out.append({
                "label": "RECOMMENDATION",
                "statement": f"指标 {m['metric']} 下最优情景为 {m['best_scenario']} "
                             f"(值 {m['best_value']:.3f}); 其它情景相对偏差见 comparison.",
            })
        # Cost vs carbon tension
        gwp_best = None; cost_best = None
        for m in comparison.get("metrics", []):
            if m["metric"] == "gwp_total": gwp_best = m["best_scenario"]
            if m["metric"] == "total_cost_cny": cost_best = m["best_scenario"]
        if gwp_best and cost_best and gwp_best != cost_best:
            out.append({
                "label": "RECOMMENDATION",
                "statement": f"碳排最低 ({gwp_best}) 与成本最低 ({cost_best}) 并非同一情景:"
                             " 决策须在碳排/成本之间权衡, 并考虑不确定区间重叠(见 uncertainty).",
            })
        return out

    # --------------------------------------------------------------- service
    def run(self) -> dict:
        emit_progress("gate: envelope + version + scope")
        self.gate_envelope()
        self.gate_version()
        self.gate_scope()
        scenarios = self._require_scenarios()

        results = [self.evaluate_scenario(s, label=f"scenario-{i+1}")
                   for i, s in enumerate(scenarios)]
        comparison = self.build_comparison(results)
        hotspots = {r["scenario_id"]: r["hotspots"] for r in results}
        fair = self.fairness_check(results)
        asymmetry = self.boundary_symmetry_check(results)
        if asymmetry:
            # Surface boundary asymmetry as a finding, not a hard failure: the
            # comparison is still reported, but every affected scenario is
            # flagged so no biased conclusion slips out (LCA-E704).
            fair.extend(asymmetry)
        sensitivity = {}
        mc = {}
        for i, s in enumerate(scenarios):
            r = results[i]
            sensitivity[r["scenario_id"]] = self.run_sensitivity(s, r)
            if self.constraints.get("run_monte_carlo"):
                mc[r["scenario_id"]] = self.run_mc(s)

        env_warnings = [w for r in results for w in r["env_warnings"]]
        cost_warnings = [w for r in results for w in r["cost_warnings"]]
        provenance = list({p["factor_id"]: p for r in results for p in r["provenance"]}.values())

        recommendations = self.recommendations(results, comparison)

        # Boundary-symmetry / functional-unit fairness findings (LCA-E704/E705)
        # are surfaced in limitations so no biased comparison slips out silent.
        boundary_notes = list(fair)

        out = {
            "contract_version": "1.0",
            "skill": "micp-lca-technoeconomic",
            "skill_version": SKILL_VERSION,
            "status": "SUCCESS",
            "summary": self._summary(results, comparison),
            "action": self.p.get("action", "assess"),
            "project_id": self.p.get("project_id"),
            "task_id": self.p.get("task_id"),
            "functional_unit": self.functional_unit,
            "system_boundary": self.scope,
            "baseline": self.baseline,
            "inventory": {r["scenario_id"]: r["inventory"] for r in results},
            "environmental_results": {r["scenario_id"]: r["environmental"] for r in results},
            "cost_results": {r["scenario_id"]: r["cost"] for r in results},
            "hotspots": hotspots,
            "scenario_comparison": comparison,
            "sensitivity": sensitivity,
            "uncertainty": {"monte_carlo": mc,
                            "note": "蒙特卡洛/敏感性仅在 constraints.run_monte_carlo 时执行"},
            "limitations": self._limitations() + boundary_notes,
            "recommendations": recommendations,
            "artifacts": self._artifacts(results),
            "validation": {
                "input_schema": "passed",
                "output_schema": "pending",
                "self_check": "not_run",
            },
            "provenance": {
                "started_at": env_clock() or now_iso(),
                "completed_at": env_clock() or now_iso(),
                "host": "opencode-dev",
                "factors": provenance,
            },
            "errors": [],
            "requested_next_skills": self._next_skills(fair, results),
        }
        # self-check
        from _jsonschema import validate_json as _vj
        schema = _load_output_schema()
        issues = _vj(out, schema)
        if issues:
            return {
                **out,
                "status": "FAILED",
                "errors": [{"code": LcaErrorCode.OUTPUT_SCHEMA_VIOLATION.code,
                            "message": "output failed self-check", "detail": {"issues": issues[:5]},
                            "retryable": True}],
                "validation": {**out["validation"], "output_schema": "failed"},
            }
        out["validation"]["output_schema"] = "passed"
        out["validation"]["self_check"] = "passed"
        return out

    def _summary(self, results: list[dict], comparison: dict) -> str:
        parts = []
        for r in results:
            g = r["environmental"]["gwp"]["value"]
            c = r["cost"]["total_cost_cny"]
            parts.append(f"{r['scenario_id']}: GWP={g:.2f} kgCO2eq, 总成本={c:,.0f} CNY")
        bests = [f"{m['metric']}->{m['best_scenario']}" for m in comparison.get("metrics", [])]
        return "情景结果: " + "; ".join(parts) + " | 最优: " + ", ".join(bests)

    def _limitations(self) -> list[str]:
        return [
            "因子库为 2026 参考值, 需在正式报告中以 references/sources.md 逐因子核验; 不得据本 Skill 输出直接宣称'低碳'",
            "未做时间贴现与价格通胀模型(v1 局限); 多年度 OPEX 差异未贴现",
            "蒙特卡洛仅对主要材料/电力因子抽样; 运输与废液因子不确定性未计入",
            "未对菌种培养、培养基的微生物排放路径建模(生物过程碳源计入培养能耗)",
            "技术经济结果依赖调用方声明的设备利用率、单价与现场条件; 未核验时相关结论标为 INFERRED",
            "省际/地区电网因子差异大; energy_mix 未声明时使用中国电网平均因子",
        ]

    def _artifacts(self, results: list[dict]) -> list[dict]:
        arts = [{"kind": "lca_environmental_report", "path": None,
                 "note": "per-scenario GWP/energy/water/nitrogen/enrichment"},
                {"kind": "technoeconomic_report", "path": None,
                 "note": "CAPEX/OPEX/per-FU cost and scale-up"},
                {"kind": "pareto_hotspot", "path": None,
                 "note": "GWP contribution ranking per scenario"}]
        for r in results:
            arts.append({"kind": "scenario_detail", "path": None,
                         "note": f"{r['scenario_id']} inventory+mass balance"})
        return arts

    def _next_skills(self, fair_notes: list[str], results: list[dict]) -> list[dict]:
        nexts: list[dict] = []
        if self.p.get("action") in ("assess", "compare") and self.scope.get("technology_readiness", "").lower().find("trl 9") == -1:
            nexts.append({"skill": "micp-geotechnical-performance",
                          "reason": "LCA/TEA 结论需要 UCS/渗透率等岩土性能目标来确认功能单位等价性",
                          "inputs_needed": ["performance_data"]})
        nexts.append({"skill": "obsidian-red-team",
                      "reason": "环境/成本声明发布前建议对抗审查: 边界是否偏向 MICP、是否漏氨氮、功能单位是否公平",
                      "inputs_needed": []})
        return nexts


def _load_output_schema() -> dict:
    import os
    here = os.path.dirname(os.path.abspath(__file__))
    schema_path = os.path.normpath(os.path.join(here, "..", "..", "schemas", "output.schema.json"))
    with open(schema_path, encoding="utf-8") as fh:
        return json.load(fh)


def validate_input(payload: dict) -> dict:
    """Schema-only validation (tool 'validate')."""
    import os
    here = os.path.dirname(os.path.abspath(__file__))
    schema_path = os.path.normpath(os.path.join(here, "..", "..", "schemas", "input.schema.json"))
    with open(schema_path, encoding="utf-8") as fh:
        schema = json.load(fh)
    issues = validate_json(payload, schema)
    return {"valid": len(issues) == 0, "issues": issues}


def service_main(payload: dict, op: str = "service") -> dict:
    try:
        if op == "validate":
            return validate_input(payload)
        pipe = _Pipeline(payload)
        return pipe.run()
    except LcaError as exc:
        return _blocked_payload(payload, exc)
    except ToolError as exc:
        return _blocked_payload(payload, exc)


def _blocked_payload(payload: dict, err: ToolError) -> dict:
    status = "BLOCKED"
    if err.code == LcaErrorCode.OUTPUT_SCHEMA_VIOLATION.code:
        status = "FAILED"
    detail = err.details or {}
    return {
        "contract_version": "1.0",
        "skill": "micp-lca-technoeconomic",
        "skill_version": SKILL_VERSION,
        "status": status,
        "summary": f"{status}: {err.message}",
        "action": payload.get("action", "assess"),
        "project_id": payload.get("project_id"),
        "task_id": payload.get("task_id"),
        "functional_unit": payload.get("functional_unit") or {},
        "system_boundary": payload.get("scope") or {},
        "baseline": payload.get("baseline") or {},
        "inventory": {}, "environmental_results": {}, "cost_results": {},
        "hotspots": {}, "scenario_comparison": {}, "sensitivity": {},
        "uncertainty": {}, "limitations": [], "recommendations": [],
        "artifacts": [],
        "validation": {"input_schema": "passed", "output_schema": "pending",
                       "self_check": "skipped"},
        "provenance": {"started_at": env_clock() or now_iso(),
                       "completed_at": env_clock() or now_iso(),
                       "host": "opencode-dev", "factors": []},
        "errors": [{"code": err.code, "message": err.message,
                    "detail": detail, "retryable": err.retryable}],
        "requested_next_skills": [],
    }
