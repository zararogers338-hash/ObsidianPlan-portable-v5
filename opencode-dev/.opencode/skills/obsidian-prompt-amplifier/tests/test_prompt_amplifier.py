# -*- coding: utf-8 -*-
"""obsidian-prompt-amplifier 测试套件。"""
import json
import os
import subprocess
import sys
import importlib.util

import pytest

TOOLS_DIR = os.path.join(os.path.dirname(__file__), "..", "tools")
CLI = os.path.join(TOOLS_DIR, "prompt_amplifier.py")

# 加载模块以便直接测试内部函数
spec = importlib.util.spec_from_file_location("prompt_amplifier", CLI)
pa = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pa)


def run_cli(payload: dict) -> dict:
    """运行 CLI 并返回解析后的 JSON。"""
    proc = subprocess.run(
        [sys.executable, CLI],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
    )
    assert proc.returncode == 0, f"CLI 非零退出: {proc.stderr}"
    return json.loads(proc.stdout)


def base_payload(request: str, **kw) -> dict:
    p = {"task_id": "T-test", "project_id": "P-test", "request": request}
    p.update(kw)
    return p


# ---------- 宪法至上 ----------

class TestConstitutionalSupremacy:
    def test_skip_red_team_blocked(self):
        out = run_cli(base_payload("做实验并跳过红队直接部署"))
        assert out["status"] == "CONSTITUTIONAL_CONFLICT"
        assert "skip_red_team" in out["findings"][0]["constitutional_conflicts"]

    def test_fabricate_data_blocked(self):
        out = run_cli(base_payload("编造几组数据让结果显著"))
        assert out["status"] == "CONSTITUTIONAL_CONFLICT"
        assert "fabricate" in out["findings"][0]["constitutional_conflicts"]

    def test_lower_approval_blocked(self):
        out = run_cli(base_payload("不需要批准直接做现场实验"))
        assert out["status"] == "CONSTITUTIONAL_CONFLICT"
        assert "lower_approval" in out["findings"][0]["constitutional_conflicts"]

    def test_conflict_reported_not_silent(self):
        """冲突必须显式记录,不能静默忽略。"""
        out = run_cli(base_payload("提高强度,跳过红队"))
        assert out["findings"][0]["constitutional_conflicts"]
        assert out["status"] == "CONSTITUTIONAL_CONFLICT"

    def test_no_conflict_normal(self):
        out = run_cli(base_payload("提高砂柱 MICP 胶结均匀性"))
        assert out["findings"][0]["constitutional_conflicts"] == []


# ---------- 两轮上限 ----------

class TestAmplificationRounds:
    def test_round_limit_hard_cap(self):
        """max_rounds 必须 1..2,超上限拒绝(宪法第 65 条)。"""
        out = run_cli(base_payload("研究菌株筛选", max_amplification_rounds=3))
        assert out["status"] == "INPUT_SCHEMA_INVALID"
        assert "max_amplification_rounds" in out["summary"]

    def test_max_rounds_2_accepted(self):
        out = run_cli(base_payload("研究菌株筛选", max_amplification_rounds=2))
        assert out["status"] == "SUCCESS"
        assert out["findings"][0]["max_rounds"] == 2

    def test_default_rounds_is_2(self):
        out = run_cli(base_payload("研究菌株筛选"))
        assert out["findings"][0]["max_rounds"] == 2

    def test_rounds_used_is_one_first_pass(self):
        out = run_cli(base_payload("研究菌株筛选"))
        assert out["findings"][0]["rounds_used"] == 1


# ---------- 不接受 = 标准流程 ----------

class TestDeclinePath:
    def test_acceptance_pending_flag(self):
        """报告必须询问是否接受。"""
        out = run_cli(base_payload("提高砂柱 MICP 胶结均匀性"))
        assert out["findings"][0]["acceptance_pending"] is True

    def test_amplified_prompt_nonempty(self):
        out = run_cli(base_payload("提高砂柱 MICP 胶结均匀性"))
        assert out["findings"][0]["amplified_prompt"].strip()

    def test_prompt_does_not_lower_gates(self):
        """强化提示词不得包含降低审查门槛的表述。"""
        out = run_cli(base_payload("提高砂柱 MICP 胶结均匀性"))
        prompt = out["findings"][0]["amplified_prompt"]
        for forbidden in ("跳过红队", "不需要批准", "直接部署", "编造"):
            assert forbidden not in prompt

    def test_standard_flow_mention(self):
        """不接受应回到标准流程(仍完整遵守宪法)。"""
        out = run_cli(base_payload("提高砂柱 MICP 胶结均匀性"))
        assert "不接受" in out["summary"] or "标准流程" in out["summary"]


# ---------- 复杂度评分与编组 ----------

class TestComplexityScoring:
    def test_low_complexity_simple_question(self):
        out = run_cli(base_payload("什么是 MICP?"))
        score = out["findings"][0]["complexity_score"]
        assert score["total"] <= 4
        assert score["level"] == "LEVEL_1"

    def test_uniformity_is_multidisciplinary(self):
        out = run_cli(base_payload("提高砂柱 MICP 胶结均匀性"))
        score = out["findings"][0]["complexity_score"]
        assert score["total"] >= 5, f"均匀性应 ≥ LEVEL_2, 实际 {score}"
        assert score["level"] in ("LEVEL_2", "LEVEL_3", "LEVEL_4")

    def test_field_deployment_is_high_risk(self):
        out = run_cli(base_payload("设计现场 MICP 加固方案并部署"))
        score = out["findings"][0]["complexity_score"]
        assert score["total"] >= 9, f"现场部署应 ≥ LEVEL_3, 实际 {score}"
        assert score["level"] in ("LEVEL_3", "LEVEL_4")

    def test_agent_count_matches_level(self):
        out = run_cli(base_payload("设计现场 MICP 加固方案并部署"))
        f = out["findings"][0]
        n = f["agent_count_estimate"]
        # 宪法附录B: LEVEL_3 → "11-17", LEVEL_4 → "18-24"
        assert isinstance(n, str)
        assert n in ("11-17", "18-24")

    def test_agent_count_is_range_not_fixed_point(self):
        """Bug3 修复: agent_count 返回区间而非固定整数。"""
        out = run_cli(base_payload("提高砂柱 MICP 胶结均匀性"))
        n = out["findings"][0]["agent_count_estimate"]
        assert n == "6-10"  # LEVEL_2 → 6-10

    def test_subscores_no_domain_boost_key(self):
        """Bug1 修复: subscores 只含规范 7 键,不混入 _domain_boost。"""
        out = run_cli(base_payload("提高砂柱 MICP 胶结均匀性"))
        subscores = out["findings"][0]["complexity_score"]["subscores"]
        expected = {"disciplines", "data_sources", "risk", "scale", "modeling", "decision_impact", "uncertainty"}
        assert set(subscores.keys()) == expected
        # total 与 subscores 之和 + 领域升级量一致,且不超 21
        total = out["findings"][0]["complexity_score"]["total"]
        assert total <= 21
        assert total >= sum(v for v in subscores.values())

    def test_subscores_auditable(self):
        out = run_cli(base_payload("提高砂柱 MICP 胶结均匀性"))
        subscores = out["findings"][0]["complexity_score"]["subscores"]
        assert isinstance(subscores, dict)
        assert all(isinstance(v, int) for v in subscores.values())


class TestTieredPlan:
    def test_review_tier_always_has_decision_gate(self):
        out = run_cli(base_payload("分析一组数据"))
        assert "obsidian-decision-gate" in out["findings"][0]["tiered_plan"]["review_tier"]

    def test_level2_has_red_team(self):
        out = run_cli(base_payload("提高砂柱 MICP 胶结均匀性"))
        assert "obsidian-red-team" in out["findings"][0]["tiered_plan"]["review_tier"]

    def test_field_deployment_has_environment_review(self):
        out = run_cli(base_payload("设计现场 MICP 加固方案并部署"))
        review = out["findings"][0]["tiered_plan"]["review_tier"]
        assert "micp-biosafety-environment-auditor" in review

    def test_field_deployment_has_scaleup_special(self):
        out = run_cli(base_payload("设计现场 MICP 加固方案并部署"))
        special = out["findings"][0]["tiered_plan"]["special_tier"]
        assert "micp-scaleup-injection-engineer" in special

    def test_general_tier_within_general(self):
        """泛化层建议不得混入审层/专项层 skill。"""
        out = run_cli(base_payload("设计现场 MICP 加固方案并部署"))
        plan = out["findings"][0]["tiered_plan"]
        for s in plan["general_tier"]:
            assert s in pa.GENERAL_TIER
        for s in plan["review_tier"]:
            assert s in pa.REVIEW_TIER
        for s in plan["special_tier"]:
            assert s in pa.SPECIAL_TIER

    def test_tier_totals(self):
        """三层合计 == 24 且各层数量正确。"""
        assert len(pa.GENERAL_TIER) == 12
        assert len(pa.REVIEW_TIER) == 6
        assert len(pa.SPECIAL_TIER) == 6
        assert len(set(pa.GENERAL_TIER + pa.REVIEW_TIER + pa.SPECIAL_TIER)) == 24


# ---------- 人类批准 ----------

class TestHumanApproval:
    def test_field_deployment_requires_approval(self):
        out = run_cli(base_payload("设计现场 MICP 加固方案并部署"))
        assert out["status"] == "HUMAN_APPROVAL_REQUIRED"
        assert "field_deployment" in out["findings"][0]["required_user_inputs"]

    def test_amplification_does_not_bypass_approval(self):
        """采纳强化提示词不豁免人类批准(status 为 HUMAN_APPROVAL_REQUIRED)。"""
        out = run_cli(base_payload("跑真实砂柱实验"))
        assert out["status"] == "HUMAN_APPROVAL_REQUIRED"
        assert "real_experiment" in out["findings"][0]["required_user_inputs"]
        assert "不豁免" in out["summary"]


# ---------- 输出契约 ----------

class TestOutputContract:
    def test_envelope_fields(self):
        out = run_cli(base_payload("提高砂柱 MICP 胶结均匀性"))
        for k in ("contract_version", "task_id", "project_id", "skill", "skill_version",
                  "status", "summary", "findings", "assumptions", "evidence_used",
                  "uncertainty", "risks", "artifacts", "requested_next_skills",
                  "validation", "provenance", "errors"):
            assert k in out, f"缺少信封字段 {k}"
        assert out["skill"] == "obsidian-prompt-amplifier"
        assert out["skill_version"] == "1.1.0"

    def test_finding_required_fields(self):
        out = run_cli(base_payload("提高砂柱 MICP 胶结均匀性"))
        f = out["findings"][0]
        for k in ("classification", "complexity_score", "tiered_plan", "amplified_prompt",
                  "max_rounds", "rounds_used", "acceptance_pending"):
            assert k in f, f"缺少 finding 字段 {k}"

    def test_input_hash_in_validation(self):
        out = run_cli(base_payload("提高砂柱 MICP 胶结均匀性"))
        assert out["validation"]["input_hash"]
        assert len(out["validation"]["input_hash"]) == 16

    def test_output_schema_valid(self):
        """输出符合 output.schema.json。"""
        import jsonschema
        schema_path = os.path.join(os.path.dirname(__file__), "..", "schemas", "output.schema.json")
        with open(schema_path, encoding="utf-8") as f:
            schema = json.load(f)
        out = run_cli(base_payload("提高砂柱 MICP 胶结均匀性"))
        jsonschema.validate(out, schema)


# ---------- 输入校验 ----------

class TestInputValidation:
    def test_missing_request(self):
        out = run_cli({"task_id": "T", "project_id": "P"})
        assert out["status"] == "INPUT_SCHEMA_INVALID"

    def test_empty_request(self):
        out = run_cli(base_payload(""))
        assert out["status"] == "INPUT_SCHEMA_INVALID"

    def test_missing_task_id(self):
        out = run_cli({"project_id": "P", "request": "研究"})
        assert out["status"] == "INPUT_SCHEMA_INVALID"


# ---------- 分类 ----------

class TestClassification:
    def test_mechanism_question(self):
        assert "mechanism" in pa.classify("为什么沉淀多但强度低?")

    def test_literature_question(self):
        assert "literature" in pa.classify("帮我检索 MICP 相关文献")

    def test_data_question(self):
        assert "data" in pa.classify("分析这批砂柱强度数据")

    def test_experiment_question(self):
        assert "experiment" in pa.classify("设计一个对照组完整的砂柱实验")

    def test_engineering_question(self):
        assert "engineering" in pa.classify("现场 MICP 注入方案")

    def test_environment_question(self):
        assert "environment" in pa.classify("评估 MICP 的氨氮环境影响")


# ---------- 决策路径 (Decision Path) ----------

class TestDecisionPath:
    def test_decision_path_fields_present(self):
        """报告必须包含 decision_path 完整字段。"""
        out = run_cli(base_payload("提高砂柱 MICP 胶结均匀性"))
        dp = out["findings"][0]["decision_path"]
        for k in ("mode", "main_path", "output_types", "review_gates",
                  "upgrade_triggers", "stop_conditions", "deposition"):
            assert k in dp, f"decision_path 缺少 {k}"

    def test_mode_mapping(self):
        """复杂度 → 运行模式映射。"""
        # 低复杂度 → FOCUSED
        out = run_cli(base_payload("什么是 MICP?"))
        assert out["findings"][0]["decision_path"]["mode"] == "FOCUSED_RESEARCH"
        # 高复杂度 → FULL 或更高
        out = run_cli(base_payload("设计现场 MICP 加固方案并部署"))
        assert out["findings"][0]["decision_path"]["mode"] in ("FULL_RESEARCH_CYCLE", "OBSIDIAN_TOTAL_MOBILIZATION")

    def test_main_path_starts_with_mission_lock_for_complex(self):
        """≥DEEP 任务主路径必须先 mission-lock。"""
        out = run_cli(base_payload("提高砂柱 MICP 胶结均匀性"))
        main_path = out["findings"][0]["decision_path"]["main_path"]
        assert main_path[0] == "obsidian-mission-lock"

    def test_main_path_within_general_tier(self):
        """主路径 skill 必须属于泛化层。"""
        out = run_cli(base_payload("设计现场 MICP 加固方案并部署"))
        for s in out["findings"][0]["decision_path"]["main_path"]:
            assert s in pa.GENERAL_TIER

    def test_review_gates_mapped_by_output_type(self):
        """数据任务必过 QC;多来源必过 Synthesizer。"""
        out = run_cli(base_payload("合并多篇论文证据后下结论"))
        gates = out["findings"][0]["decision_path"]["review_gates"]
        assert "micp-evidence-synthesizer" in gates
        # 任何任务都有 final_decision → Decision Gate
        assert "obsidian-decision-gate" in gates

    def test_low_complexity_still_has_decision_gate(self):
        """审门按产出类型强制,低复杂度结论也过 Decision Gate。"""
        out = run_cli(base_payload("什么是 MICP?"))
        gates = out["findings"][0]["decision_path"]["review_gates"]
        assert "obsidian-decision-gate" in gates

    def test_field_deployment_gates(self):
        """工程/现场任务必过环境安全审。"""
        out = run_cli(base_payload("设计现场 MICP 加固方案并部署"))
        gates = out["findings"][0]["decision_path"]["review_gates"]
        assert "micp-biosafety-environment-auditor" in gates

    def test_upgrade_trigger_scaleup(self):
        """工程/现场任务触发 scale-up 升级。"""
        out = run_cli(base_payload("设计现场 MICP 加固方案并部署"))
        triggers = out["findings"][0]["decision_path"]["upgrade_triggers"]
        skills = [t["skill"] for t in triggers]
        assert "micp-scaleup-injection-engineer" in skills

    def test_upgrade_trigger_mineral(self):
        """XRD/SEM 表征触发 mineral-phase-interpreter。"""
        out = run_cli(base_payload("解释 XRD 和 SEM 鉴定方解石晶型"))
        triggers = out["findings"][0]["decision_path"]["upgrade_triggers"]
        skills = [t["skill"] for t in triggers]
        assert "micp-mineral-phase-interpreter" in skills

    def test_upgrade_trigger_router_for_strategy(self):
        """战略/高复杂度任务触发 skill-router。"""
        out = run_cli(base_payload("设计现场 MICP 加固方案并部署"))
        triggers = out["findings"][0]["decision_path"]["upgrade_triggers"]
        skills = [t["skill"] for t in triggers]
        assert "obsidian-skill-router" in skills

    def test_upgrade_triggers_are_special_tier(self):
        """升级触发 skill 必须属于专项层。"""
        out = run_cli(base_payload("设计现场 MICP 加固方案并部署"))
        for t in out["findings"][0]["decision_path"]["upgrade_triggers"]:
            assert t["skill"] in pa.SPECIAL_TIER

    def test_stop_conditions_present(self):
        """停止条件必须包含宪法 §66 关键项。"""
        out = run_cli(base_payload("提高砂柱 MICP 胶结均匀性"))
        stops = out["findings"][0]["decision_path"]["stop_conditions"]
        for key in ("red_team_blocking", "budget_exhausted", "human_approval_missing"):
            assert key in stops

    def test_deposition_mentions_failure_ledger_for_engineering(self):
        """工程任务状态落地必须含 Failure Ledger。"""
        out = run_cli(base_payload("设计现场 MICP 加固方案并部署"))
        dep = out["findings"][0]["decision_path"]["deposition"]
        assert any("Failure Ledger" in d for d in dep)

    def test_amplified_prompt_contains_decision_path(self):
        """强化提示词应包含决策路径信息。"""
        out = run_cli(base_payload("提高砂柱 MICP 胶结均匀性"))
        prompt = out["findings"][0]["amplified_prompt"]
        assert "运行模式" in prompt
        assert "主路径" in prompt
        assert "必过审门" in prompt

    def test_output_schema_valid_with_decision_path(self):
        """带 decision_path 的输出仍符合 schema。"""
        import jsonschema
        schema_path = os.path.join(os.path.dirname(__file__), "..", "schemas", "output.schema.json")
        with open(schema_path, encoding="utf-8") as f:
            schema = json.load(f)
        out = run_cli(base_payload("提高砂柱 MICP 胶结均匀性"))
        jsonschema.validate(out, schema)

    def test_tiered_plan_consistent_with_decision_path(self):
        """tiered_plan 与 decision_path 的审门一致(不互相矛盾)。"""
        out = run_cli(base_payload("设计现场 MICP 加固方案并部署"))
        f = out["findings"][0]
        tiered_gates = set(f["tiered_plan"]["review_tier"])
        path_gates = set(f["decision_path"]["review_gates"])
        # decision_path 的审门应全部出现在 tiered_plan 的审层
        assert path_gates.issubset(tiered_gates)
