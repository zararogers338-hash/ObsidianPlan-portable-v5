#!/usr/bin/env python3
"""obsidian-prompt-amplifier — 提示词扩充机制(任务入口首检)。

Reads one JSON envelope from stdin, classifies the task, scores complexity
per Panshi Constitution Appendix B, suggests a three-tier model grouping,
drafts an amplified prompt, and emits a structured acceptance report.

Constitutional supremacy: this tool and its output sit UNDER the Panshi
Constitution. Conflicts are reported, never silently resolved against the
constitution.

Every tool is offline and deterministic.
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
from typing import Any

CONTRACT_VERSION = "1.0.0"
SKILL_ID = "obsidian-prompt-amplifier"
SKILL_VERSION = "1.1.0"
DEFAULT_MAX_ROUNDS = 2
HARD_MAX_ROUNDS = 2  # Panshi Constitution §65 budget: amplification capped at 2 rounds

# 宪法附录 B 复杂度评分维度
COMPLEXITY_DIMENSIONS = [
    ("disciplines", "学科数量"),
    ("data_sources", "数据来源"),
    ("risk", "风险"),
    ("scale", "尺度"),
    ("modeling", "建模"),
    ("decision_impact", "决策影响"),
    ("uncertainty", "不确定性"),
]

# 三级模型:12 泛化 / 6 审 / 6 专项
GENERAL_TIER = [
    "obsidian-mission-lock",
    "obsidian-task-decomposer",
    "micp-literature-scout",
    "micp-evidence-extractor",
    "micp-hypothesis-forge",
    "micp-biology-reasoner",
    "micp-ureolysis-chemistry",
    "micp-porous-media-transport",
    "micp-experiment-designer",
    "micp-data-analyst",
    "micp-geotechnical-performance",
    "micp-modeling-optimizer",
]
REVIEW_TIER = [
    "micp-evidence-synthesizer",
    "micp-instrumentation-qc",
    "micp-reproducibility-versioning",
    "micp-biosafety-environment-auditor",
    "obsidian-red-team",
    "obsidian-decision-gate",
]
SPECIAL_TIER = [
    "obsidian-skill-router",
    "obsidian-state-manager",
    "micp-knowledge-graph-steward",
    "micp-mineral-phase-interpreter",
    "micp-scaleup-injection-engineer",
    "micp-lca-technoeconomic",
]

# 宪法第 72 条:普通指令不得要求的行为
CONSTITUTIONAL_VIOLATION_PATTERNS = [
    ("skip_red_team", re.compile(r"跳过.*红队|跳过.*red\s*team|skip.*red\s*team", re.I)),
    ("skip_decision_gate", re.compile(r"跳过.*决策门|跳过.*decision\s*gate|直接放行|直接部署", re.I)),
    ("skip_environment", re.compile(r"跳过.*环境|不要管.*环境|忽略.*废液|忽略.*氨", re.I)),
    ("fabricate", re.compile(r"编造|虚构|伪造|当作.*已完成|假设.*已完成|假装.*测试通过", re.I)),
    ("lower_approval", re.compile(r"不需要.*批准|绕过.*批准|跳过.*批准|自动批准", re.I)),
    ("overclaim_epistemics", re.compile(r"把.*写成.*observed|当成.*事实|当作.*已验证", re.I)),
]

# 任务分类关键词
CLASSIFICATION_KEYWORDS: dict[str, list[str]] = {
    "literature": ["文献", "综述", "检索", "查", "论文", "专利", "标准", "literature", "review", "search", "citation", "来源", "研究现状"],
    "mechanism": ["机制", "为什么", "菌株", "脲酶", "化学", "平衡", "晶型", "矿物", "运移", "堵塞", "沉淀", "胶结", "附着", "菌", "成核", "mechanism", "why", "strain", "urease", "nucleation", "precipitat", "attachment"],
    "experiment": ["实验", "设计", "方案", "对照", "重复", "SOP", "砂柱实验", "组", "随机", "样本量", "experiment", "design", "trial", "试验"],
    "data": ["数据", "分析", "统计", "显著性", "效应量", "均匀性", "变异", "方差", "data", "analy", "statistic", "uniformity", "variation"],
    "model": ["模型", "建模", "模拟", "数值", "反演", "优化", "预测", "model", "simulat", "numerical", "optim", "equation"],
    "engineering": ["放大", "现场", "中试", "注入", "强度", "渗透率", "耐久", "scale", "field", "pilot", "injection", "geotechnical", "ucs"],
    "environment": ["环境", "氨氮", "废液", "LCA", "碳", "生态", "environment", "ammonia", "life cycle", "排放"],
    "strategy": ["全面", "完整", "战略", "路线", "系统", "深", "strategy", "roadmap", "comprehensive", "deep", "方案"],
}

# 工程/安全触发词 -> 人类批准要求
APPROVAL_TRIGGERS: dict[str, re.Pattern] = {
    "real_experiment": re.compile(r"做.*实验|跑.*实验|开展.*实验|执行.*实验|真实实验|execute.*experiment|run.*experiment|real experiment", re.I),
    "field_deployment": re.compile(r"现场|部署|deployment|field|中试|pilot", re.I),
    "environment_release": re.compile(r"释放|环境.*菌|release|地下水.*注入", re.I),
    "hazardous_chemical": re.compile(r"危险.*化学品|hazardous|强酸|强碱|重金属", re.I),
}


class EnvelopeError(Exception):
    """输入信封错误。"""


def read_json_stdin() -> dict[str, Any]:
    raw = sys.stdin.read().strip()
    if not raw:
        raise EnvelopeError("empty stdin")
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        raise EnvelopeError(f"invalid JSON: {e}") from e
    if not isinstance(data, dict):
        raise EnvelopeError("input must be a JSON object")
    return data


def input_hash(data: dict[str, Any]) -> str:
    canonical = json.dumps(data, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


def classify(request: str) -> list[str]:
    classes: list[str] = []
    for cls, keywords in CLASSIFICATION_KEYWORDS.items():
        for kw in keywords:
            if kw.lower() in request.lower():
                classes.append(cls)
                break
    return classes or ["literature"]  # 默认至少一类


def detect_constitutional_conflicts(request: str) -> list[str]:
    conflicts: list[str] = []
    for label, pattern in CONSTITUTIONAL_VIOLATION_PATTERNS:
        if pattern.search(request):
            conflicts.append(label)
    return conflicts


def detect_approvals(request: str) -> list[str]:
    required: list[str] = []
    for label, pattern in APPROVAL_TRIGGERS.items():
        if pattern.search(request):
            required.append(label)
    return required


def score_complexity(request: str) -> tuple[int, dict[str, int]]:
    """按宪法附录 B 对 7 个维度打分(0—3)。启发式,可被领域判断覆盖。"""
    subscores: dict[str, int] = {}

    # 学科数量: 通过分类数近似
    n_classes = len(classify(request))
    subscores["disciplines"] = 0 if n_classes <= 1 else (1 if n_classes == 2 else (2 if n_classes <= 4 else 3))

    # 数据来源: 提到数据/图表/表格/实测
    subscores["data_sources"] = 0
    if re.search(r"数据|data|实测|图表|表格|实验记录|文献", request):
        subscores["data_sources"] = 1
    if re.search(r"多.*数据|多.*来源|多模态|冲突|矛盾", request):
        subscores["data_sources"] = 3
    elif subscores["data_sources"] == 1 and re.search(r"对比|比较|多组|不同.*方案", request):
        subscores["data_sources"] = 2

    # 领域升级: 均匀性/堵塞/尺度/环境 等 MICP 关键概念 -> 升高复杂度
    # 宪法第 51/52/53/54 条: 强度/沉淀/均匀性/菌株类任务必须拆分多智能体
    # 说明: domain_boost 是领域升级量,计入 disciplines 维度后并入 total(不再额外
    # 混入 subscores,保证 7 维结构规范;total 上限用 cap_total 截断到 21)。
    domain_boost = 0
    if re.search(r"均匀性|空间分布|离散|uniformity", request):
        domain_boost += 2  # 宪法附录 F.5 均匀性诊断: 多智能体
    if re.search(r"堵塞|clogging|入口", request):
        domain_boost += 1
    if re.search(r"菌株.*比较|菌株.*最好|筛选菌株|菌株筛选", request):
        domain_boost += 2  # 宪法第 54 条: 拒绝无边界菌株排名
    if re.search(r"提高.*强度|强度.*提高|how.*strength", request):
        domain_boost += 1  # 宪法第 51 条: 至少 6 个智能体
    if re.search(r"沉淀多.*强度低|强度低.*沉淀", request):
        domain_boost += 2  # 宪法第 52 条: 竞争假设

    # 风险
    subscores["risk"] = 0
    if re.search(r"现场|环境|安全|废液|氨氮|释放|危险", request):
        subscores["risk"] = 2
    if re.search(r"现场.*部署|部署.*现场|地下水.*注入|生态环境", request):
        subscores["risk"] = 3
    elif re.search(r"环境|安全", request):
        subscores["risk"] = 2

    # 尺度
    subscores["scale"] = 0
    if re.search(r"实验室|烧杯|砂柱|小柱", request):
        subscores["scale"] = 1
    if re.search(r"中试|米级|大柱", request):
        subscores["scale"] = 2
    if re.search(r"现场|场地|field|工程应用", request):
        subscores["scale"] = 3

    # 建模
    subscores["modeling"] = 0
    if re.search(r"模型|建模|模拟|反演|预测", request):
        subscores["modeling"] = 2
    if re.search(r"多物理|耦合|反应运移|PDE|数值模拟", request):
        subscores["modeling"] = 3
    elif re.search(r"计算|estimate", request):
        subscores["modeling"] = 1

    # 决策影响
    subscores["decision_impact"] = 0
    if re.search(r"选择|方案.*选|比较.*方案", request):
        subscores["decision_impact"] = 2
    if re.search(r"部署|放行|批准|资金|投资|论文发表|正式.*方案", request):
        subscores["decision_impact"] = 3
    elif re.search(r"实验", request):
        subscores["decision_impact"] = 1

    # 不确定性
    subscores["uncertainty"] = 1
    if re.search(r"核心未知|未知|不确定|没有.*数据|缺.*数据", request):
        subscores["uncertainty"] = 3
    elif re.search(r"冲突|矛盾|争议", request):
        subscores["uncertainty"] = 2

    # 总分 = 7 维之和 + 领域升级量,上限截断到 21(宪法附录 B 满分)
    total = min(sum(subscores.values()) + domain_boost, 21)
    return total, subscores


def level_for(total: int) -> str:
    """宪法附录 B:0-4→L1, 5-8→L2, 9-13→L3, 14+→L4。"""
    if total <= 4:
        return "LEVEL_1"
    if total <= 8:
        return "LEVEL_2"
    if total <= 13:
        return "LEVEL_3"
    return "LEVEL_4"


def agent_count_for(total: int) -> str:
    """宪法附录 B 子智能体规模区间映射(3-5 / 6-10 / 11-17 / 18-24)。"""
    if total <= 4:
        return "3-5"
    if total <= 8:
        return "6-10"
    if total <= 13:
        return "11-17"
    return "18-24"


def build_tiered_plan(classes: list[str], total: int, approvals: list[str], request: str = "") -> dict[str, Any]:
    """三级模型编组建议。"""
    # 泛化层: 默认完整 12 个,但按分类裁剪到最相关的主 Skill
    primary_by_class = {
        "literature": ["micp-literature-scout", "micp-evidence-extractor"],
        "mechanism": ["micp-biology-reasoner", "micp-ureolysis-chemistry", "micp-porous-media-transport", "micp-mineral-phase-interpreter"],
        "experiment": ["micp-experiment-designer", "micp-instrumentation-qc"],
        "data": ["micp-data-analyst"],
        "model": ["micp-modeling-optimizer"],
        "engineering": ["micp-geotechnical-performance", "micp-scaleup-injection-engineer"],
        "environment": ["micp-biosafety-environment-auditor", "micp-lca-technoeconomic"],
        "strategy": ["obsidian-mission-lock", "obsidian-task-decomposer"],
    }
    general: list[str] = []
    for cls in classes:
        for s in primary_by_class.get(cls, []):
            if s not in general and s in GENERAL_TIER:
                general.append(s)
    # 基础编排: 复杂任务必含 mission-lock + task-decomposer
    for s in ["obsidian-mission-lock", "obsidian-task-decomposer"]:
        if total >= 5 and s not in general:
            general.insert(0, s)
    # 兜底
    if not general:
        general = ["obsidian-mission-lock"]

    # 审层: 按复杂度决定必过门;任何 >= L2 都必须过 Red Team + Decision Gate
    review = ["obsidian-decision-gate"]
    if total >= 5:
        review.append("obsidian-red-team")
    if total >= 5 and ("experiment" in classes or "data" in classes):
        review.append("micp-instrumentation-qc")
    if "mechanism" in classes or "literature" in classes:
        review.append("micp-evidence-synthesizer")
    if total >= 9 or "data" in classes:
        review.append("micp-reproducibility-versioning")
    if "engineering" in classes or "environment" in classes or "field_deployment" in approvals or total >= 9:
        review.append("micp-biosafety-environment-auditor")
    if "environment" in classes:
        review.append("micp-lca-technoeconomic")

    # 专项层: 按需(执行中命中才拉)
    special: list[str] = []
    if total >= 9 or "strategy" in classes:
        special.append("obsidian-skill-router")
    if total >= 9:
        special.append("obsidian-state-manager")
    if re.search(r"晶型|矿物|XRD|SEM|EDS|晶体", request):
        special.append("micp-mineral-phase-interpreter")
    if "engineering" in classes or "field_deployment" in approvals:
        special.append("micp-scaleup-injection-engineer")
    if "environment" in classes:
        special.append("micp-lca-technoeconomic")
    if total >= 13:
        special.append("micp-knowledge-graph-steward")

    # 去重、保序、不混入审层/专项层
    general = [s for s in general if s in GENERAL_TIER]
    review = [s for s in review if s in REVIEW_TIER]
    special = [s for s in special if s in SPECIAL_TIER]

    return {
        "general_tier": general,
        "review_tier": review,
        "special_tier": special,
    }


# 审门映射(按产出类型强制,宪法 NODE 4)—— 与复杂度分数无关
REVIEW_GATES_BY_OUTPUT = [
    ("scientific_conclusion", "obsidian-red-team", "任何正式科学结论必须反证"),
    ("final_decision", "obsidian-decision-gate", "状态判定必须过决策门"),
    ("data_conclusion", "micp-instrumentation-qc", "QC 失败数据不得进入分析"),
    ("evidence_merge", "micp-evidence-synthesizer", "多来源证据合并前必须条件对齐"),
    ("reproducibility_claim", "micp-reproducibility-versioning", "声称可复现/已验证必须过复现审"),
    ("engineering_field", "micp-biosafety-environment-auditor", "涉及工程/现场必须过环境安全审"),
    ("sustainability_claim", "micp-lca-technoeconomic", "环境/低碳声明必须过 LCA"),
]


def output_types_for(classes: list[str]) -> list[str]:
    """由任务分类推导可能产出类型。"""
    types: list[str] = []
    if "mechanism" in classes or "strategy" in classes:
        types.append("scientific_conclusion")
    if "data" in classes or "experiment" in classes:
        types.append("data_conclusion")
    if "literature" in classes or "mechanism" in classes:
        types.append("evidence_merge")
    if "engineering" in classes or "environment" in classes:
        types.append("engineering_field")
    if "environment" in classes:
        types.append("sustainability_claim")
    types.append("final_decision")  # 任何正式任务最终都要过 Decision Gate
    return types


def build_decision_path(classes: list[str], total: int, level: str, approvals: list[str], request: str) -> dict[str, Any]:
    """生成可执行的决策路径(NODE 0-7)。让 AI 知道怎么调动计算系统。"""
    mode = "FOCUSED_RESEARCH"
    if total <= 4:
        mode = "FOCUSED_RESEARCH"
    elif total <= 8:
        mode = "DEEP_RESEARCH"
    elif total <= 13:
        mode = "FULL_RESEARCH_CYCLE"
    else:
        mode = "OBSIDIAN_TOTAL_MOBILIZATION"

    # NODE 3: 泛化层主路径(按分类 + 固定顺序规则)
    primary_by_class = {
        "literature": ["micp-literature-scout", "micp-evidence-extractor"],
        "mechanism": ["micp-biology-reasoner", "micp-ureolysis-chemistry", "micp-porous-media-transport"],
        "experiment": ["micp-experiment-designer"],
        "data": ["micp-data-analyst"],
        "model": ["micp-modeling-optimizer"],
        "engineering": ["micp-geotechnical-performance"],
        "environment": ["micp-biosafety-environment-auditor"],
        "strategy": ["obsidian-mission-lock", "obsidian-task-decomposer"],
    }
    main_path: list[str] = []
    for cls in classes:
        for s in primary_by_class.get(cls, []):
            if s not in main_path and s in GENERAL_TIER:
                main_path.append(s)
    # 固定顺序: 任何模式先 mission-lock;≥DEEP 加 task-decomposer
    mission_first = ["obsidian-mission-lock"]
    if total >= 5:
        mission_first.append("obsidian-task-decomposer")
    main_path = [s for s in mission_first if s not in main_path] + main_path
    # 数据顺序规则: 涉及 data/experiment → QC 先于 data-analyst
    if "data" in classes and "micp-instrumentation-qc" not in main_path:
        pass  # QC 在审门里处理,不重复进主路径

    # NODE 4: 审门映射(按产出类型)
    output_types = output_types_for(classes)
    review_gates: list[str] = []
    for _, gate_skill, _ in REVIEW_GATES_BY_OUTPUT:
        if gate_skill not in REVIEW_TIER:
            continue
        # 逐类型判定
        if gate_skill == "obsidian-red-team":
            if total >= 5 or "scientific_conclusion" in output_types:
                review_gates.append(gate_skill)
        elif gate_skill == "obsidian-decision-gate":
            review_gates.append(gate_skill)
        elif gate_skill == "micp-instrumentation-qc":
            if "data" in classes or "experiment" in classes:
                review_gates.append(gate_skill)
        elif gate_skill == "micp-evidence-synthesizer":
            if "literature" in classes or "mechanism" in classes:
                review_gates.append(gate_skill)
        elif gate_skill == "micp-reproducibility-versioning":
            if total >= 9 or "data" in classes:
                review_gates.append(gate_skill)
        elif gate_skill == "micp-biosafety-environment-auditor":
            if "engineering" in classes or "environment" in classes or "field_deployment" in approvals:
                review_gates.append(gate_skill)
        elif gate_skill == "micp-lca-technoeconomic":
            if "environment" in classes:
                review_gates.append(gate_skill)
    # 去重保序
    review_gates = list(dict.fromkeys(review_gates))

    # NODE 5: 专项层升级触发(条件映射)
    upgrade_triggers: list[dict[str, str]] = []
    trigger_rules = [
        ("multi_skill_or_conflict", "obsidian-skill-router", "多 Skill 协同/权限冲突/CAPABILITY_GAP"),
        ("long_task_or_interrupt", "obsidian-state-manager", "长任务/上下文耗尽/进程中断(先 checkpoint)"),
        ("long_term_memory", "micp-knowledge-graph-steward", "写长期记忆/跨项目复用"),
        ("mineral_characterization", "micp-mineral-phase-interpreter", "出现 XRD/SEM/EDS 表征数据"),
        ("scale_up", "micp-scaleup-injection-engineer", "实验室→现场外推"),
        ("cost_carbon", "micp-lca-technoeconomic", "成本/碳/资源比较"),
    ]
    for cond, skill, note in trigger_rules:
        fired = False
        if cond == "multi_skill_or_conflict" and (total >= 9 or "strategy" in classes):
            fired = True
        elif cond == "long_task_or_interrupt" and total >= 9:
            fired = True
        elif cond == "long_term_memory" and total >= 13:
            fired = True
        elif cond == "mineral_characterization" and re.search(r"晶型|矿物|XRD|SEM|EDS|晶体", request):
            fired = True
        elif cond == "scale_up" and ("engineering" in classes or "field_deployment" in approvals):
            fired = True
        elif cond == "cost_carbon" and "environment" in classes:
            fired = True
        if fired:
            upgrade_triggers.append({"condition": cond, "skill": skill, "note": note})

    # NODE 6: 停止条件(宪法 §66)
    stop_conditions = [
        "goal_satisfied",
        "threshold_triggered",
        "key_input_missing",
        "human_approval_missing",
        "tool_unavailable",
        "evidence_insufficient",
        "budget_exhausted",
        "no_new_information_two_rounds",
        "skill_repeated_failure",
        "red_team_blocking",
        "unacceptable_risk",
        "beyond_capability",
    ]

    # NODE 7: 状态落地
    deposition = ["micp-knowledge-graph-steward", "micp-reproducibility-versioning"]
    if "engineering" in classes or approvals:
        deposition.append("Failure Ledger(负结果必须记录,宪法 §30)")

    return {
        "mode": mode,
        "main_path": main_path,
        "output_types": output_types,
        "review_gates": review_gates,
        "upgrade_triggers": upgrade_triggers,
        "stop_conditions": stop_conditions,
        "deposition": deposition,
    }



def draft_amplified_prompt(request: str, classes: list[str], total: int, tiered: dict[str, Any], approvals: list[str], conflicts: list[str], decision_path: dict[str, Any] | None = None) -> str:
    """产出强化提示词草案。强化 = 定界 + 编组 + 决策路径 + 宪法约束,不是加花哨措辞。"""
    lines: list[str] = []
    lines.append("【强化提示词草案 · 由 obsidian-prompt-amplifier 生成】")
    lines.append("")
    lines.append(f"原始请求: {request}")
    lines.append("")
    lines.append("1. 任务边界")
    lines.append(f"   分类: {', '.join(classes)}")
    lines.append(f"   复杂度评分: {total}/21,对应子智能体规模 {agent_count_for(total)} 个")
    lines.append("   请明确: 研究对象、材料与尺度、成功指标、失败阈值、约束、排除项。")
    lines.append("   若存在含糊词(更好/更环保/更强/更均匀),必须推导或要求可测指标。")
    lines.append("")
    lines.append("2. 三级模型编组")
    lines.append(f"   泛化层: {', '.join(tiered['general_tier'])}")
    lines.append(f"   审层:   {', '.join(tiered['review_tier'])}")
    lines.append(f"   专项层: {', '.join(tiered['special_tier']) or '(按需)'}")
    lines.append("   编组必须遵循宪法第 11 条: 至少一个反方、一个数据/单位检查、必要时环境/安全审查。")
    lines.append("")
    if decision_path:
        lines.append("3. 决策路径(如何调动计算系统)")
        lines.append(f"   运行模式: {decision_path.get('mode', '')}")
        lines.append(f"   主路径顺序: {' → '.join(decision_path.get('main_path', []))}")
        lines.append(f"   产出类型: {', '.join(decision_path.get('output_types', []))}")
        lines.append(f"   必过审门: {' → '.join(decision_path.get('review_gates', [])) or '(低复杂度结论仍过 Decision Gate)'}")
        lines.append("   专项层升级触发(命中才拉):")
        for t in decision_path.get("upgrade_triggers", []):
            lines.append(f"     - [{t.get('condition')}] {t.get('skill')}: {t.get('note')}")
        lines.append("   停止条件(宪法 §66): 目标满足/阈值触发/关键输入缺失/批准缺失/预算耗尽/两轮无新信息/环境风险不可接受。")
        lines.append("   状态落地: " + ", ".join(decision_path.get("deposition", [])))
        lines.append("")
    lines.append("4. 强制宪法约束")
    lines.append("   - 所有重要陈述标记认识论标签(OBSERVED/REPORTED/CALCULATED/INFERRED/HYPOTHESIS/RECOMMENDATION);")
    lines.append("   - 任何数值带单位与来源;质量/元素/电荷守恒必须检查;")
    lines.append("   - 正式结论升级前必须过 Red Team;状态判定必须过 Decision Gate;")
    lines.append("   - 真实实验/现场/环境释放/长期知识写入必须有人类批准;")
    lines.append("   - 不得把 CaCO₃ 总量当作有效胶结,不得把实验室结果直接外推现场。")
    lines.append("")
    lines.append("4. 需要用户提供")
    if approvals:
        lines.append(f"   触发人类批准项: {', '.join(approvals)} —— 需真实批准,不可省略。")
    lines.append("   - 已有数据/实验记录/文献引用;")
    lines.append("   - 材料、菌株、尺度、时间与预算边界;")
    lines.append("   - 项目状态与 Mission Contract(如有)。")
    lines.append("")
    if conflicts:
        lines.append("5. 宪法冲突提示")
        lines.append(f"   原始请求含与宪法冲突的指令: {', '.join(conflicts)}。冲突部分已排除,不采纳。")
        lines.append("")

    lines.append("【执行方式】按上述边界与编组,遵循 Panshi Constitution 展开三级模型研究循环;")
    lines.append("若证据不足返回 BLOCKED;若能力不足请求 Skill;一切以宪法解释为准。")
    return "\n".join(lines)


def validate_input(data: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    for f in ("task_id", "project_id", "request"):
        v = data.get(f)
        if not isinstance(v, str) or not v.strip():
            errors.append(f"required field {f} missing/empty")
    rounds = data.get("max_amplification_rounds", DEFAULT_MAX_ROUNDS)
    if not isinstance(rounds, int) or isinstance(rounds, bool):
        errors.append("max_amplification_rounds must be an integer")
    elif rounds < 1 or rounds > HARD_MAX_ROUNDS:
        errors.append(f"max_amplification_rounds must be 1..{HARD_MAX_ROUNDS}")
    return errors


def build_envelope(task_id: str, project_id: str, status: str, summary: str, findings: list[dict[str, Any]], errors: list[dict[str, str]] | None = None) -> dict[str, Any]:
    env: dict[str, Any] = {
        "contract_version": CONTRACT_VERSION,
        "task_id": task_id,
        "project_id": project_id,
        "skill": SKILL_ID,
        "skill_version": SKILL_VERSION,
        "status": status,
        "summary": summary,
        "findings": findings,
        "assumptions": [],
        "evidence_used": [],
        "uncertainty": [],
        "risks": [],
        "artifacts": [],
        "requested_next_skills": [],
        "validation": {"input_hash": ""},
        "provenance": {},
        "errors": errors or [],
    }
    return env


def run(data: dict[str, Any]) -> dict[str, Any]:
    task_id = str(data.get("task_id", ""))
    project_id = str(data.get("project_id", ""))
    request = str(data.get("request", ""))
    rounds = data.get("max_amplification_rounds", DEFAULT_MAX_ROUNDS)
    h = input_hash(data)

    env = build_envelope(task_id, project_id, "SUCCESS", "", [], [])
    env["validation"] = {"input_hash": h}

    # 输入校验
    v_errors = validate_input(data)
    if v_errors:
        return build_envelope(task_id, project_id, "INPUT_SCHEMA_INVALID",
                              "输入不符合 schema: " + "; ".join(v_errors),
                              [], [{"code": "OPA-E1001", "message": m} for m in v_errors])

    # 宪法冲突检测
    conflicts = detect_constitutional_conflicts(request)
    constitutional_blocked = False
    if conflicts:
        # 部分冲突可记录并排除;涉及伪造/绕过批准的直接标记
        if any(c in ("fabricate", "lower_approval", "skip_red_team", "skip_decision_gate") for c in conflicts):
            constitutional_blocked = True

    # 任务分类 + 复杂度评分
    classes = classify(request)
    total, subscores = score_complexity(request)
    level = level_for(total)
    approvals = detect_approvals(request)
    tiered = build_tiered_plan(classes, total, approvals, request)
    decision_path = build_decision_path(classes, total, level, approvals, request)
    prompt = draft_amplified_prompt(request, classes, total, tiered, approvals, conflicts, decision_path)

    finding = {
        "classification": classes,
        "complexity_score": {"total": total, "subscores": subscores, "level": level},
        "agent_count_estimate": agent_count_for(total),
        "tiered_plan": tiered,
        "decision_path": decision_path,
        "amplified_prompt": prompt,
        "max_rounds": rounds,
        "rounds_used": 1,
        "constitutional_conflicts": conflicts,
        "required_user_inputs": approvals + ["材料/尺度/时间/预算边界", "已有数据或引用(如有)"],
        "acceptance_pending": True,
    }

    if constitutional_blocked:
        env = build_envelope(task_id, project_id, "CONSTITUTIONAL_CONFLICT",
                             "请求含与 Panshi 宪法冲突的指令,冲突部分已排除;请修正后重试。",
                             [finding],
                             [{"code": "OPA-E1002", "message": f"constitutional conflict: {', '.join(conflicts)}"}])
        return env

    if approvals:
        env["status"] = "HUMAN_APPROVAL_REQUIRED"
        env["summary"] = ("报告已生成;任务触发人类批准项: "
                          + ", ".join(approvals) + "。采纳强化提示词不豁免任何批准。")
    else:
        env["summary"] = "报告已生成,等待接受与否。采纳后按强化提示词展开;不接受则按标准流程执行(仍完整遵守宪法)。"

    env["findings"] = [finding]
    env["assumptions"] = ["复杂度评分为宪法附录 B 启发式评分,可被领域判断覆盖。",
                          "三级模型编组为默认建议,可由 Skill Router 调整。"]
    env["requested_next_skills"] = decision_path.get("main_path", [])[:3] + (decision_path.get("review_gates", [])[:1] or [])
    return env


def main() -> int:
    try:
        data = read_json_stdin()
    except EnvelopeError as e:
        sys.stderr.write(f"error: {e}\n")
        env = build_envelope("", "", "INPUT_SCHEMA_INVALID", f"无法读取输入: {e}", [],
                             [{"code": "OPA-E1004", "message": str(e)}])
        print(json.dumps(env, ensure_ascii=False, indent=2))
        return 2
    env = run(data)
    print(json.dumps(env, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
