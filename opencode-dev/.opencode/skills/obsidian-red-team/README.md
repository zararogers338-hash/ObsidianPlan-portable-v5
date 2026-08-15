# obsidian-red-team — 黑曜石科学反证与对抗审查器

> **v1.0.0** · 全系统强制审计 Skill · Panshi 宪法之下的受治理能力

本 Skill 是整个 Obsidian Plan / Panshi 研究系统的**强制对抗审查门**。它不负责帮助主模型证明结论，而是负责**主动攻击**：任务定义、文献证据、数据抽取、机制假设、实验设计、统计分析、数值模型、工程放大、环境评估、LCA、最终决策。

存在 `BLOCKING` 问题时，`obsidian-state-manager` 必须拒绝状态升级（`SUPPORTED→VALIDATED→PILOT_READY→DEPLOYABLE`）；本 Skill **只提交发现与判定，绝不修改主结论或数据**。

---

## 一、核心使命

> 目标是寻找**最可能推翻当前结论的证据和缺陷**，而不是生成泛泛的"还需要更多研究"。

十维强制攻击（每次审查至少覆盖，跳过须显式声明）：

1. 来源真实性 — 引用是否存在、DOI 是否匹配、是否只依赖摘要、是否错误引用综述、是否虚构数据
2. 认识论越级 — 推断写成事实 / 假设写成结论 / 建议写成已验证方案
3. 数值与单位 — 单位一致、量纲正确、质量守恒、数量级、虚假精确
4. 实验设计 — 对照 / 重复 / 随机化 / 伪重复 / 排除规则 / 竞争假设区分
5. 统计分析 — 只报 p、选择性报告、过拟合、忽视效应量、违反模型假设
6. MICP 专业机制 — OD600≠CFU≠脲酶活性；CaCO3 总量≠有效晶桥；晶型与空间位置；堵塞；氨氮；非尿素路径
7. 模型 — 边界条件、可识别性、同数据校准+验证、尺度越界
8. 工程放大 — 实验室参数直接放大、非均质/地下水/优先流、停工条件
9. 环境与安全 — 风险淡化、法规核验、人工审批门
10. 决策 — 科学支持但工程不具备部署条件；阻断项未关闭即放行

---

## 二、严重度与输出

每个发现带：`finding_id | location | dimension | severity | evidence | why | counterexample | required_fix | verification_method | blocks_state_upgrade`。

严重度五级：`INFO < MINOR < MAJOR < CRITICAL < BLOCKING`。

**BLOCKING 判定规则**（见 `tools/ort/blocking_rules.py`）：伪造引用/虚构数据、氨氮超限仍建议部署、阻断项未关闭仍升级、模型违反质量守恒、伪重复撑起关键结论、法规未核验仍放行、工程阻断未处理即放行、状态越级、权限越界、认识论越级支撑部署。

统一输出信封（15 段 + 12 字段）：`status | review_scope | findings | blocking_findings | counterexamples | alternative_explanations | required_evidence | required_fixes | retest_plan | state_recommendation | risks | artifacts | validation | provenance | errors`。

---

## 三、系统集成

- **Router**：`planner.ts` 已将 `red_team` 映射为能力 token，`risk_level ∈ {high, critical}` 强制 `obsidian-red-team → obsidian-decision-gate` 审计链。
- **State Manager**：`review.complete` 的 `requested_next_skills` 已内建指向本 Skill；`UNDER_REVIEW→VALIDATED` 与 `VALIDATED→DEPLOYABLE` 均要求 `requires_review + requires_approval`。本 Skill 输出 `state_recommendation ∈ {REVIEW_FAIL, HOLD}` 时，verdict 应为 `fail`。
- **本 Skill 只读**：`tool_permissions: [read]`、`network: false`、`writes: audit/**`。

---

## 四、快速使用

```bash
# 全量对抗审查
python tools/ort/cli.py review < audit_request.json

# 单工具（引用核验 / 单位量纲 / 伪重复 / 阻断引擎 / 严重度 / 复验 …）
python tools/ort/cli.py citation    < citation_input.json
python tools/ort/cli.py units      < units_input.json
python tools/ort/cli.py pseudo     < pseudo_input.json
python tools/ort/cli.py blocking   < findings_input.json
python tools/ort/cli.py severity   < finding_input.json
python tools/ort/cli.py retest     < fix_claim_input.json

# 输出自检
python tools/ort/cli.py check-self < review_output.json
```

示例请求见 [`examples/`](examples/)。测试 `python -m pytest tests/`；评测 `python evals/run_evals.py`。

---

## 五、目录结构

```
obsidian-red-team/
├── SKILL.md                    技能主文件（frontmatter name/description/version）
├── skill.yaml                  机器元数据（Router 注册契约，字段必须为字符串数组）
├── manifest.json               JSON 形态清单（registry 兼容）
├── README.md
├── CHANGELOG.md
├── prompts/
│   └── system.md               红队系统提示词（加载到主模型）
├── schemas/
│   ├── input.schema.json       输入契约（draft 2020-12）
│   ├── output.schema.json      输出契约（统一信封 15 段 + 12 字段）
│   └── finding.schema.json     finding 单项契约
├── tools/
│   ├── ort/                    Python 工具集（纯标准库，stdin/stdout）
│   │   ├── cli.py              唯一 stdin/stdout 入口
│   │   ├── errors.py           错误码 ORT-E###
│   │   ├── common.py           信封/进度/错误处理
│   │   ├── models.py           枚举与数据结构
│   │   ├── citation.py         引用核验器
│   │   ├── provenance.py       Evidence 来源链检查器
│   │   ├── units.py            单位与量纲检查器
│   │   ├── balance.py          质量守恒检查器
│   │   ├── stats.py            统计结构检查器
│   │   ├── pseudo.py           伪重复检测器
│   │   ├── modelcheck.py       模型边界检查器
│   │   ├── escalation.py       状态越级检查器
│   │   ├── permissions.py      权限越界检查器
│   │   ├── counterexamp.py     对抗用例生成器
│   │   ├── severity.py         风险严重度评分器
│   │   ├── blocking_rules.py   阻断规则引擎（唯一事实源）
│   │   └── retest.py           修复复验工具
│   └── README.md
├── tests/                      pytest 测试
├── evals/
│   ├── cases.yaml              15 个强制对抗案例
│   ├── metrics.py              指标计算
│   ├── run_evals.py            评测运行器
│   └── bootstrap/              自举日志
├── examples/                   真实可运行示例
└── references/
    └── sources.md              方法学与参考来源
```

---

## 六、验证状态（v1.0.0）

| 项 | 结果 |
|---|---|
| pytest | `python -m pytest tests/` — 全部通过（见 `docs/` 或 CI） |
| 评测 | `python evals/run_evals.py` — 7 指标（M1–M7） |
| 对抗案例 | 15/15（伪造论文、DOI 不匹配、OD600 当脲酶、CaCO3 当晶桥、伪重复、缺对照、p 显著效应极小、违反质量守恒、同数据校准验证、小柱推现场、强度升渗透降、氨氮超限、法规未核验、阻断未关闭升级、越权写知识库） |
| 自举 | Red Team 审查仓库真实 Skill + 自我复检（见 `evals/bootstrap/`） |
| Router 集成 | `obsidian-skill-router` registry 扫描 usable=true；高风险审计链强制 |

---

## 七、维护

- 工具为纯 Python 3.10+ 标准库，离线、确定性、无硬编码路径。
- 修改契约需同步 `schemas/`、`SKILL.md`、`skill.yaml`、`manifest.json`、`CHANGELOG.md`。
- 阻断规则改动必须更新 `blocking_rules.py` 及其单元测试与评测断言。


---

> 原 `README_USE_THIS.txt` 已归档至 [`audit/README_USE_THIS.txt`](audit/README_USE_THIS.txt)。
