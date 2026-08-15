---
name: micp-evidence-synthesizer
description: >-
  Synthesize multiple MICP / biocementation Evidence Cards into conditioned
  conclusions: align a PICO/PECO framework, check cross-study comparability
  (strain, material, grain size, concentration, scale, injection protocol,
  measurement, endpoint), unify units while preserving raw values, build
  evidence and conflict matrices, distinguish statistical / methodological /
  mechanistic / scale heterogeneity, pool quantitatively only when conditions
  allow, run leave-one-out sensitivity, rate certainty GRADE-style, and attach
  every conclusion with an evidence level, scope, counterexample and open
  questions — never a naive majority vote. Trigger when the controller or
  router asks to synthesize/compare/combine multiple evidence cards, resolve
  inter-study conflicts, or produce a conditioned cross-study conclusion.
  Do NOT use for: extracting cards from papers (use literature-scout /
  evidence-extractor), managing research state (obsidian-state-manager),
  designing experiments (experiment-designer), or routing (obsidian-skill-router).
---

# MICP Evidence Synthesizer (MES) — 跨研究证据综合与矛盾解析

将多个 Evidence Card 综合为**条件化结论**,识别研究之间可比性、异质性、冲突来源和证据缺口,避免简单多数投票。本 Skill 是 Obsidian Plan / Panshi 研究项目的受治理专业能力。

> 版本: **1.0.0**(Skill 版本,与 `schemas/`、`tools/mes/`、`tools/mes_cli.py` 同源)。调用方须在输入 `skill_version` 声明本版本;主版本不匹配会按 OES-E801 拒绝(见第九节版本兼容策略)。

---

## 一、何时触发 / 何时不触发

### 正触发示例(满足任一即考虑)

1. 控制器/Router 要求"综合这 N 张 Evidence Card,给出结论"。
2. 需要跨研究比较 MICP 处理效果(如"比较三篇砂柱 UCS 研究的效应方向")。
3. 上游多张卡片对同一指标报告不同数值,需要矛盾矩阵与来源解释。
4. 请求给出**条件化**结论:"在什么条件下 MICP 能提升强度、什么条件下不能"。
5. 需要识别证据缺口(缺失维度、缺双臂数据、低证据等级)以决定下一步检索。
6. 需要判定是否可定量合并(meta-analysis 前置检查),或明确隔离不可比数据。

### 反触发示例(不应触发)

1. 单篇文献的卡片提取/摘要 → `evidence-extractor` / `literature-scout`。
2. 请求"管理研究状态/登记证据/升级假设" → `obsidian-state-manager`。
3. 请求"为实验设计方案" → `experiment-designer`。
4. 请求"分配技能/调度/预算" → `obsidian-skill-router`(本 Skill 是执行性能力,不自路由)。

### 边界案例(触发与否取决于输入)

1. **只有一张卡**:可做单卡 PICO 对齐与证据分级,但**不得声称跨研究综合**;输出 `PARTIAL` 并说明至少 2 张卡才能综合。
2. **多张卡但无 PICO**:缺 `pico.population/intervention/outcome` → `BLOCKED` + OES-E113 + 逐字段获取指引。
3. **多张卡、PICO 完整、但单位不兼容**:允许构建证据矩阵(保留原值),但**禁止合并**;`PARTIAL` + OES-E103。
4. **冲突未消解**:冲突矩阵照常输出,但结论必须"解释冲突来源,不得平均掩盖";若无法解释 → 结论降级为 `HYPOTHESIS` + 建议 `obsidian-red-team` 复核。

### 最低输入与缺失处理

输入须满足 `schemas/input.schema.json`。**缺失必需字段时,输出明确列出字段名、为何关键、如何获得**(而非笼统"信息不足")。字段获取指引:

| 字段 | 为何关键 | 如何获得 |
|---|---|---|
| `task_id` | 审计锚点、provenance 追踪 | Controller 分配 |
| `project_id` | 归档与审计文件定位 | 项目注册 |
| `request` | 综合语义的唯一文本信号 | 调用方请求 |
| `action` | 必须是 `evidence.synthesize` | Controller 构造 |
| `pico.population` | PICO 锚定,决定可比性 | 从任务/文献提取(如"Ottawa sand, Dr=60%") |
| `pico.intervention` | 明确处理(菌株/浓度/注浆) | 从任务/卡片提取 |
| `pico.outcome` | 决定终点与单位 | 从任务/卡片提取 |
| `evidence_cards[]` | 待综合证据;至少 1 张 | evidence-extractor / literature-scout 产出 |
| `skill_version` | 版本兼容门 | 本 Skill frontmatter 声明 |
| `timestamp` | 审计与复现 | Controller 注入 |

---

## 二、能力边界

- 本 Skill 是 Panshi 宪法下的受治理能力,**不得取代 Obsidian Controller**。
- 专业 Skill **不得自行无限调用其他专业 Skill**;需要协作时向 Router 返回 `requested_next_skills`(星型拓扑)。
- 本 Skill **不做**证据提取、状态管理、实验设计、路由治理。
- 不得编造:引用、数据、实验结果、法规、工具能力、"已完成"状态。缺失即 `BLOCKED`。
- 涉及 MICP:必须区分生物/化学/矿物相/多孔介质/工程性能/环境影响六层面;尿素水解必须关注铵态氮与质量守恒;非尿素路径不得套用尿素模型。
- 现场部署、真实生物实验、危险化学品操作、长期知识库写入 → 必须人工批准门(OES-E107)。
- 结论必须给出适用条件、尺度、证据等级和最可能的反例。

---

## 三、输入(机器可读契约)

读取 `schemas/input.schema.json`。必填:`contract_version, task_id, project_id, request, action, skill_version, timestamp, evidence_cards, pico`。

- `action`: 仅支持 `evidence.synthesize`;其他 action → `OES-E115`。
- `pico`: `{population, intervention, comparison?, outcome, unit?, setting?}`;population/intervention/outcome 必填。
- `evidence_cards`: 至少 1 张。每张必含 `ref_id, study_id, study_type, outcome{name,value,unit}, reported_effect, evidence_level`。卡片**不得携带最终结论**;卡片自带 `claims` 一律按 REPORTED/CALCULATED 处理,绝不自动升级为 OBSERVED。
- `constraints`(可选):`min_poolable_studies`(默认 2)、`max_heterogeneity_allowable`(默认 75%)、`significance_level`(默认 0.05)、`output_units`、`field_deployment`、`live_bio_experiment`、`hazardous_chemicals`、`long_term_knowledge_write`(布尔,触发批准门)。
- `risk_level`(默认 `medium`):`high/critical` → 强制审计链 `obsidian-red-team` + `obsidian-decision-gate` 入 `requested_next_skills`。
- `requested_output_format`(默认 `synthesis_report`):`synthesis_report | evidence_matrix | conflict_matrix | meta_analysis_report | heterogeneity_report | sensitivity_report | audit_report | summary`。
- `human_approval_state`(可选):`{granted, approver, scope, revision}`。

---

## 四、执行步骤(流程)

1. **校验输入**。对 `input.schema.json` 严格校验;失败 → `BLOCKED` + OES-E101 + 逐字段指引。
2. **卡片校验**。`evidence_validate.validate_cards`:必需字段、ref_id 可核验性、数值有限性、重复 ref_id;失败 → `BLOCKED` + OES-E102。
3. **PICO 对齐**。缺 population/intervention/outcome → `BLOCKED` + OES-E113 + 获取指引。
4. **可比性检查**(真实工具 `check_comparability`)。菌株/材料/粒径/饱和度/浓度/尺度/注入协议/测量方法/终点/单位 10 维;不可比数据**明确隔离**。
5. **证据矩阵与矛盾矩阵**(`evidence_map`)。矛盾不得被平均掩盖——每条冲突记录类型(direction/magnitude/unit/explicit)、方向与解释。
6. **效应量计算**(`effect_compute`)。双臂卡 → Hedges' g + 方差;无双臂卡 → 原值单卡行,不参与合并。
7. **合并决策**(`meta_analyze.can_pool`)。I2 ≤ 阈值且 ≥2 研究 → 定量合并(fixed/random);否则**结构化叙述综合**。区分四类异质性(`classify_heterogeneity`)。
8. **敏感性分析**(`sensitivity_run`)。留一法 + 剔除高偏倚卡,报告效应量漂移(delta)。
9. **证据分级**(`grade_assess`)。GRADE 式五域:基线按研究类型;降级于偏倚/不一致/间接/不精确;升级于剂量梯度。
10. **结论构建**。每条结论带证据等级、适用边界、最可能反例、未决问题。
11. **过度概括自检**(`result_check_overgeneralization`)。缺边界/标签膨胀/全称词 → 自检失败 → `FAILED` + OES-E108。
12. **返回信封**。`SUCCESS | PARTIAL | BLOCKED | FAILED | NEED_ADDITIONAL_SKILL | HUMAN_APPROVAL_REQUIRED`。

### 停止条件

- 输出通过自检(输出 schema + 过度概括检查)→ 停止并返回。
- 任一硬门失败 → `BLOCKED`/`FAILED` + 明确错误码,不猜测、不降级、不编造。
- 缺关键输入 → `BLOCKED` + 逐字段指引。
- 需要其他能力 → `NEED_ADDITIONAL_SKILL` + 所需输入与理由。
- 待批准 → `HUMAN_APPROVAL_REQUIRED` + OES-E107。

---

## 五、专业执行规则

### 5.1 PICO/PECO 对齐

优先 PICO;工程研究无对照组时用 PECO(exposure-comparison)。`comparison` 可为空,但 `population/intervention/outcome` 必须存在,否则 OES-E113。

### 5.2 可比性维度(真实工具检查)

菌株、材料、粒径(D50)、饱和度、浓度、尺度(柱/场)、注入协议、测量方法、终点、单位。任一维度在卡间分歧 → 该维度标 `mixed`/`incomparable`;总状态 `comparable | conditional | incomparable | insufficient`。

### 5.3 单位统一但保留原始值

`unit_map` 归一化到规范单位(应力 kPa/MPa、CaCO3 %,温度 C/K,浓度 mol/L,密度 kg/m³);输出同时保留 `value/unit`(原值)与 `normalized_value`。未知单位 → `unmapped`,不静默转换。

### 5.4 证据矩阵与矛盾矩阵

- 证据矩阵每卡一行:ref_id、outcome、value、unit、normalized_value、evidence_level、layer、risk_of_bias。
- 矛盾矩阵:显式 `conflicts_with` + 同终点数值分歧(方向/量级) + 单位不可比。**矛盾必须解释来源,不得平均。**

### 5.5 异质性四分类

| 类型 | 判定信号 |
|---|---|
| 统计异质性 | I2 / tau2 / Q 检验 |
| 方法异质性 | 测量方法、终点时机分歧 |
| 机制异质性 | 跨层面(生物/化学/矿物/渗流/工程/环境)、菌株分歧 |
| 尺度异质性 | 样本尺寸、尺度(柱/场)分歧 |

### 5.6 条件化合并

仅当 ≥`min_poolable_studies` 且 I2 ≤ `max_heterogeneity_allowable`(默认 75%)才定量合并;否则结构化叙述综合并明确隔离不可比数据。合并模型:≥3 研究用随机效应(DerSimonian-Laird),2 研究用固定效应。

### 5.7 结论纪律

每项结论必须带:证据等级(`evidence_level`)、适用边界(`scope`)、最可能反例(`counterexample`)、未决问题(`open_questions`)。不得用论文数量替代证据质量。

### 5.8 认识论标签

所有重要陈述使用 `OBSERVED | REPORTED | CALCULATED | INFERRED | HYPOTHESIS | RECOMMENDATION` 之一;不得把推断/假设/建议写成观测。OBSERVED/REPORTED 必须带 `source`。

---

## 六、错误码体系

`tools/mes/errors.py` 是唯一事实源;控制器按 `code` 机器解析,按 `message` 人类可读。`retryable` 指示是否可重试。

| 码 | 类 | 含义 | 可重试 |
|---|---|---|---|
| OES-E101 | input | 输入未通过 input.schema.json | 否 |
| OES-E102 | input | 证据卡片缺失/不可核验/重复/损坏 | 否 |
| OES-E103 | input | 单位或量纲不一致 | 否 |
| OES-E104 | dependency | 依赖工具不可用 | 是 |
| OES-E105 | policy | 权限不足/被拒 | 否 |
| OES-E106 | capability | 下游能力缺失 | 否 |
| OES-E107 | policy | 人工批准未完成 | 否 |
| OES-E108 | internal | 结果未通过输出自检(含过度概括检查) | 否 |
| OES-E109 | state | 上下文/卡片/文件损坏 | 否 |
| OES-E110 | budget | 预算/卡片数超限 | 否 |
| OES-E111 | numeric | 非有限/越界/量纲非法数值 | 否 |
| OES-E112 | input | 研究不可比,数据须隔离 | 否 |
| OES-E113 | input | PICO/PECO 核心字段缺失 | 否 |
| OES-E114 | input | 证据不足以定量合并 | 否 |
| OES-E115 | input | action 不受支持 | 否 |
| OES-E801 | version | 契约/控制器版本不受支持 | 否 |
| OES-E802 | version | skill_version 不受支持 | 否 |

错误信息格式:`OES-E101: <message>`(人类可读)+ `detail`(机器可解析,如 schema issues 路径列表)。

---

## 七、工具权限

| 工具 | 用途 | 写权限 |
|---|---|---|
| `tools/mes_cli.py` | stdin→JSON→stdout 入口 | 无 |
| `tools/mes/evidence_validate.py` | 卡片校验 | 无 |
| `tools/mes/unit_map.py` | 单位归一化 | 无 |
| `tools/mes/effect_compute.py` | 效应量 | 无 |
| `tools/mes/meta_analyze.py` | 定量合并 + I2/τ²/Q | 无 |
| `tools/mes/heterogeneity_compute.py` | 四类异质性 + 可比性 | 无 |
| `tools/mes/evidence_map.py` | 证据/矛盾矩阵 | 无 |
| `tools/mes/sensitivity_run.py` | 留一法敏感性 | 无 |
| `tools/mes/grade_assess.py` | GRADE 分级 | 无 |
| `tools/mes/result_check_overgeneralization.py` | 过度概括自检 | 无 |

全部离线、无网络、无外部命令、无密钥。输出 `artifacts` 仅声明机器可读产物;`dry_run` 时零写入。

---

## 八、与 Controller / Router 的协作

- 本 Skill 是 Panshi 宪法下的受治理能力,不取代 Obsidian Controller,也不取代 Skill Router。
- 需要协作时向 Router 返回 `requested_next_skills`(星型拓扑),**不直接调用其他 Skill**。
- `risk_level ∈ {high, critical}` → 强制审计链 `obsidian-red-team` → `obsidian-decision-gate` 入 `requested_next_skills`。
- 需要证据提取/状态管理/实验设计 → `requested_next_skills` 返回对应 Skill 名 + 所需输入与理由。

---

## 九、版本兼容策略

契约文件:`schemas/input.schema.json`、`schemas/output.schema.json`。

- **破坏性变更**(删除/改义字段、改枚举)→ 主版本 +1。
- **新增可选字段**(向后兼容)→ 次版本 +1。
- **实现修复不改契约** → 修订版本 +1。
- 旧版本输出:若主版本不匹配且未提供迁移器 → 明确拒绝(OES-E801),绝不静默接受。
- 当前支持:`contract_version == 1.x`、`skill_version == 1.x.y`。

---

## 十、性能指标(在 `evals/` 中实现)

| 指标 | 测量方法 | 最低阈值 |
|---|---|---|
| 结构化输出通过率 | 全部评测输出过 output.schema.json | ≥ 0.95 |
| 工具真实调用率 | 评测调用真实 CLI/函数而非 mock | = 1.0(不变量) |
| 引用/数据可追溯率 | `evidence_used` 均来自卡片 ref_id | = 1.0 |
| 缺失输入识别率 | 缺字段样本中被逐字段指出的比例 | = 1.0 |
| 对抗用例拦截率 | 对抗样本中未产生非法 SUCCESS 的比例 | = 1.0 |
| 重复运行一致性 | 同输入两次运行合成体一致 | = 1.0(确定性) |
| 平均失败恢复时间 | 失败用例从报告到修复的轮次 | ≤ 1 轮 |

---

## 十一、维护

- 运行测试:`pytest -q`(或 `python -m pytest`);自包含、无网络。
- 运行评测:`python evals/run.py`(在 skill 根目录)。
- 修改 `SKILL.md` 后更新 `frontmatter` 版本与 `CHANGELOG.md`。
- `tools/mes/` 为纯 Python 模块;`tools/mes_cli.py` 是唯一触碰 stdin/stdout 的文件。
