# micp-evidence-synthesizer (MES)

> 跨研究证据综合与矛盾解析 —— 将多个 Evidence Card 综合为条件化结论,识别可比性、异质性、冲突来源和证据缺口,避免简单多数投票。

**版本** 1.0.0 · **契约** contract_version 1.0 · **维护者** Panshi / Obsidian Plan

---

## 1. 这是什么

MES 是 Obsidian Plan（黑曜石计划）Panshi 研究核心下的一个**受治理专业 Skill**。消费上游 `evidence-extractor` / `literature-scout` 产出的 Evidence Card，产出**机器可读**的综合信封：PICO 对齐、可比性检查、证据矩阵、矛盾矩阵、效应量、条件化 meta 合并、四类异质性分类、留一法敏感性、GRADE 分级、过度概括自检。

**它不做什么**：不提取卡片、不管理研究状态、不设计实验、不路由、不编造数据、不取代 Controller / Router。

## 2. 安装与调用

Skill 根目录：`skills/micp-evidence-synthesizer/`。全部离线、零外部依赖（`jsonschema`/`pyyaml`/`pytest` 均为可选；缺失时使用内建回退）。

```bash
# 单次调用（stdin 进 JSON，stdout 出 JSON 信封）
python3 tools/mes_cli.py < input.json > output.json

# 校验输入文件是否符合契约
python3 tools/mes_cli.py --validate-schema < input.json

# 运行测试
python3 -m pytest -q

# 运行评测（10 个用例 + 7 项性能指标）
python3 evals/run.py
```

被 Obsidian Controller / Router 调用时，直接以 JSON 信封交换（见 `schemas/`）。

## 3. 输入 / 输出契约

| 文件 | 说明 |
|---|---|
| `schemas/input.schema.json` | 输入契约。必填 `contract_version, task_id, project_id, request, action, skill_version, timestamp, evidence_cards, pico` |
| `schemas/output.schema.json` | 输出信封。状态枚举 `SUCCESS / PARTIAL / BLOCKED / FAILED / NEED_ADDITIONAL_SKILL / HUMAN_APPROVAL_REQUIRED` |

输入要点：

- `action` 恒为 `evidence.synthesize`。
- `evidence_cards[]` 每张必含 `ref_id, study_id, study_type, outcome{name,value,unit}, reported_effect, evidence_level`；双臂卡提供 `reported_effect.arms[]`（n/mean/sd/unit）才可参与定量合并。
- `pico` 至少含 `population/intervention/outcome`。
- 卡片自带 `claims` 一律按 `REPORTED`/`CALCULATED` 处理，绝不自动升级为 `OBSERVED`。

输出信封包含：`status, summary, findings, assumptions, evidence_used, uncertainty, risks, artifacts, requested_next_skills, validation, provenance, errors, synthesis`。`synthesis` 内含 `pico_framework, comparability_check, evidence_matrix, conflict_matrix, conclusions, synthesis_method, conditions, gaps`，以及按需的 `meta_analysis, heterogeneity, sensitivity, grade`。

## 4. 目录结构

```
micp-evidence-synthesizer/
├── SKILL.md                    角色、触发/反触发/边界、流程、错误码、权限、版本、指标
├── skill.yaml                  机器可读 manifest（Obsidian 约定，见 §9）
├── README.md                   本文档
├── schemas/
│   ├── input.schema.json       输入契约
│   └── output.schema.json      输出契约
├── prompts/system.md           最小系统提示词（不复制宪法）
├── tools/
│   ├── mes_cli.py              stdin→stdout 入口（唯一触碰 IO 的文件）
│   └── mes/
│       ├── errors.py           OES 错误码注册表（唯一事实源）
│       ├── models.py           信封/认识论标签/层/摘要工具
│       ├── jsonschema.py       内建回退校验器
│       ├── evidence_validate.py 卡片校验
│       ├── unit_map.py         单位归一化
│       ├── effect_compute.py   效应量（Hedges' g / Cohen's d）
│       ├── meta_analyze.py     固定/随机效应合并 + I2/τ²/Q
│       ├── heterogeneity_compute.py 四类异质性 + 可比性
│       ├── evidence_map.py     证据/矛盾矩阵
│       ├── sensitivity_run.py  留一法敏感性
│       ├── grade_assess.py     GRADE 分级
│       ├── result_check_overgeneralization.py 过度概括自检
│       └── service.py          编排 + 统一信封
├── tests/                      pytest：unit / integration / failure / regression
├── evals/
│   ├── cases.yaml              10 个评测用例
│   ├── metrics.py              指标公式与阈值
│   ├── run.py                  评测运行器
│   └── results/latest.json     最近一次评测结果
├── examples/                   3 个可运行示例（含自举场景）
├── references/sources.md       领域与方法学依据
└── CHANGELOG.md                版本历史
```

## 5. 示例

```bash
python3 tools/mes_cli.py < examples/01-caco3-similar-content.json | python3 -m json.tool
```

| 示例 | 场景 |
|---|---|
| `examples/01-caco3-similar-content.json` | 两张 CaCO3 含量相似但强度不同的研究 → 识别晶体位置/材料差异（自举场景 1） |
| `examples/02-ucs-scale-nonmerge.json` | 不同试样尺寸/加载速率 → 验证不直接合并（自举场景 2） |
| `examples/03-high-bias-sensitivity.json` | 移除高偏倚研究 → 敏感性变化（自举场景 3） |

## 6. 限制与故障排除

| 现象 | 原因 | 处理 |
|---|---|---|
| 输出 `BLOCKED` + `OES-E101` | 输入未过 schema | 看 `errors[0].detail.issues[]` 逐字段修正 |
| `OES-E102` | ref_id 不可核验 / 重复 / 数值非有限 | 修正卡片 |
| `OES-E103` | 单位不可比 | 证据矩阵保留原值，不合并 |
| `OES-E113` | PICO 缺字段 | 补齐 population/intervention/outcome |
| `OES-E107` | 现场部署等未批准 | 走人工批准门 |
| `OES-E108` | 结论过度概括 | 收紧 scope/counterexample/标签 |
| 无 `meta_analysis` | I2 超阈值或无 ≥2 双臂卡 | 结构化叙述综合是预期行为 |

**已知限制**：GRADE 域评分为启发式规则（非完整 GRADEpro）；卡方 p 值用 Wilson-Hilferty 近似；`jsonschema` 回退校验器只覆盖本仓库 schema 用到的 draft-07 子集。均记录于 `references/sources.md`。

## 7. 与仓库既有 Skill 的关系

对齐 `obsidian-skill-router` / `obsidian-state-manager` 的既有约定：统一信封、错误码注册表、`skill.yaml` manifest、`evals/` + `tests/` 分层、认识论标签、版本兼容策略。星型拓扑：本 Skill 不直接调用其他 Skill，协作一律回 Router。

## 8. 版本与演进

见 `CHANGELOG.md`。破坏性契约变更 → 主版本 +1；新增可选字段 → 次版本；实现修复 → 修订版本。旧主版本输出：迁移或明确拒绝（`OES-E801`）。

## 9. 约定说明（项目自定义）

OpenCode 原生 loader 只读 `SKILL.md` frontmatter 的 `name` + `description`（见 `packages/opencode/src/skill/index.ts`）。`skill.yaml` 是 **Obsidian Plan / Panshi 项目自定义**的机器可读扩展 manifest，供 Controller / 打包 / CI 消费，非 OpenCode 标准。`contract_version` 语义与 `obsidian-state-manager` 一致（主版本 1.x 接受，2.x 拒绝）。


---

> 原 `ZIP-README.md` 已归档至 [`audit/ZIP-README.md`](audit/ZIP-README.md)。
