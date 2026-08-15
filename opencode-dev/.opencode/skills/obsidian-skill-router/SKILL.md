---
name: obsidian-skill-router
description: >-
  Skill routing, permission and invocation governance for the Obsidian Plan / Panshi research
  project. Use ONLY when the Obsidian Controller asks the router to choose which specialist skills
  (ureolysis-chemistry, mineral-phase-interpreter, porous-media-transport, geotechnical-performance,
  red-team, decision-gate, literature-scout, evidence-extractor, evidence-synthesizer,
  knowledge-graph-steward, hypothesis-forge, biology-reasoner, experiment-designer,
  instrumentation-qc, data-analyst, modeling-optimizer, scaleup-injection-engineer,
  biosafety-environment-auditor, lca-technoeconomic, reproducibility-versioning, task-decomposer,
  state-manager) should run for a task node, in what order/mode, with what budget, permissions and
  audit chain; when a task needs capabilities no skill covers (returns NEED_ADDITIONAL_SKILL with a
  capability-gap spec); when upstream skill outputs conflict; when recursion/depth/cost budgets must
  be enforced. Do NOT use for: generating scientific content directly, executing experiments, or
  writing literature reviews — the router selects and governs other skills; it never performs the
  work itself. Trigger keywords: 路由, skill-router, 调度, 选择技能, 调用图, 预算, 权限, 冲突仲裁,
  capability-gap, red-team 强制审计, decision-gate, star topology, 递归截断.
---

# Obsidian Skill Router (OSR) — Skill 路由、权限与调用治理

本 Skill 是 Obsidian Plan（黑曜石计划）的受治理调度中枢。它不产生领域结论,只做四件事:选技能、排顺序、定预算、守边界。它依据注册表中每个技能声明的**能力、输入输出契约、单位、工具权限、停止条件**做契约级匹配——**绝不因名字相似而路由**。

> 版本: 1.0.0（Skill 版本,与 `schemas/`、`tools/osr/` 同源）。调用方须在输入 `skill_version` 中声明本版本;不兼容版本会被拒绝(见"版本兼容"节)。

---

## 一、何时触发 / 何时不触发

### 正触发示例（满足任一即考虑）

1. Controller 询问"这个任务节点该由哪些 Skill 执行、以什么顺序/模式"。
2. 任务横跨多个领域(如"MICP 处理砂的强度+渗流+矿物相"),需要一个组合而不是单个通用 Skill。
3. 任务风险等级为 `high`/`critical`,需要强制接入 `obsidian-red-team` 与 `obsidian-decision-gate` 审计链。
4. 上游某个专业 Skill 返回 `NEED_ADDITIONAL_SKILL`/协作请求,需要 Router 决定下一步。
5. 需要为一次调用分配 token/成本/时间/重试预算,并防止递归或重复调用。
6. 上游技能输出之间出现冲突,需要检测并选择 `cross_review` 仲裁模式。

### 反触发示例（不应触发）

1. 直接要求"写一段 MICP 综述"——应路由给 `evidence-synthesizer` 或 `literature-scout`,Router 自己不写。
2. 纯工具性任务(读取文件、格式化 JSON)已有通用工具覆盖,无需 Router。
3. 对话/元问题("你是谁""解释一下路由原理")——直接回答,不调用。
4. 请求已明确指定单一技能且无治理诉求(如"跑一下 `data-analyst`")——直接转发,不重新决策。

### 边界案例（触发与否取决于输入）

1. **指定了技能但给出新约束**: "用 data-analyst 但只允许读 state/ 目录" → 触发(需权限策略检查)。
2. **指定了技能但无注册表条目**: "调用 ureolysis-chemistry" 而注册表缺失 → 触发,返回 `CAPABILITY_GAP`(OSR-E006),附缺失技能需求说明。
3. **上游冲突未解决**: 两个技能报告同一指标不同值 → 触发 `cross_review` 模式或返回 `BLOCKED`(OSR-E013)。
4. **风险高但审计技能缺失**: `risk_level=high` 而 `obsidian-red-team` 未注册 → 返回 `BLOCKED`(OSR-E006),不降级直接调度。

### 最低输入与缺失处理

输入须满足 `schemas/input.schema.json`。**缺失必需字段时,输出明确列出字段名、为何关键、如何获得**(而非笼统"信息不足")。字段获取指引:

| 字段 | 为何关键 | 如何获得 |
|---|---|---|
| `task_id` | 决策日志锚点、预算与递归记账 | Task Decomposer 分配 |
| `project_id` | 选择决策日志文件 | 项目注册 |
| `request` | 能力与领域匹配的唯一文本信号 | Mission Lock 的任务合同 |
| `skill_version` | 版本兼容门(不兼容拒绝) | 本 Skill frontmatter 声明 |
| `controller_version` | 权限模型版本门 | Controller 版本常量注入 |
| `timestamp` | 审计与复现 | Controller 调用时注入 |

---

## 二、能力边界

- **本 Skill 是 Panshi 宪法下的受治理能力,不得取代 Obsidian Controller。**
- 专业 Skill 不得自行无限调用其他专业 Skill;需要协作时向 Router 返回请求。Router 强制执行**星型拓扑**(第 5.2 节)。
- Router 自身**不做领域推理**:它不计算反应速率、不解释矿相、不评估岩土性能。它只产出路由计划与决策记录。
- Router 不生成文献引用、数据、实验结果或"已完成"状态。所有正式结论带认识论标签(第 5.6 节)。
- 涉及 MICP:必须区分生物/化学/矿物相/多孔介质/工程性能/环境影响六个层面;涉及尿素水解必须关注铵态氮与质量守恒;非尿素路径不得套用尿素模型。
- 现场部署、真实生物实验、危险化学品操作、长期知识库写入 → 必须经人工批准门(OSR-E007)。

---

## 三、输入（机器可读契约）

读取 `schemas/input.schema.json`。必填: `task_id, project_id, request, skill_version, controller_version, timestamp`。可选且已定义语义:

- `context`: `task_graph, memory_refs, call_chain, completed_calls, prior_decisions, environment`
- `constraints`: `max_depth, max_total_calls, max_retries_per_skill, max_parallel, max_tokens_total, max_cost_usd_total, max_wall_time_sec, forbidden_skills, required_skills, deadline, budget`
- `evidence_refs, data_refs`: 证据与数据引用(决策日志中记录其 `ref_id`,验证其可核验性)
- `upstream_outputs`: 上游技能的机器输出,用于单位推断与冲突检测
- `requested_output_format`: `route_plan`(默认) | `capability_gap_spec` | `conflict_report` | `audit_report`
- `risk_level`: `low | medium | high | critical`(默认 `medium`)
- `human_approval_state`: `not_required | pending | approved | rejected`

---

## 四、执行步骤（流程）

1. **校验输入**。对 `input.schema.json` 做严格校验;失败 → `FAILED` + OSR-E001 + 逐字段指引。
2. **读注册表**。索引器扫描 `skills.paths` 根目录(仓库 `skills/`、`.opencode/skills/`),解析 `SKILL.md` frontmatter 与 `skill.yaml`,产出带哈希指纹的快照。损坏条目仅记录问题、不崩溃(发现阶段宽松;路由阶段严格)。
3. **能力推导**。从 `request` 文本与 `upstream_outputs` 推导所需能力 token;从上游输出推断单位预期。
4. **契约匹配**。按能力覆盖、输入覆盖、领域关键词打分;有**单位冲突**或**零能力覆盖**的条目排除。名似能力不似 → 不得分。
5. **策略门**。`tools/network/writes/risk` 过权限引擎;`deny` → `BLOCKED`(OSR-E005)。
6. **风险门**。`high/critical` 强制审计链 `obsidian-red-team → obsidian-decision-gate`;缺失 → `BLOCKED`(OSR-E006)。
7. **冲突门**。上游输出冲突检测;未消解 → 强制 `cross_review` 模式。
8. **调用图门**。深度/总调用/循环/精确重复检查;违规 → `BLOCKED`(OSR-E011 / OSR-E012)。
9. **预算门**。token/成本/墙钟时间/重试上限;超限 → `BLOCKED`(OSR-E010),先估算后调度。
10. **批准门**。高风险 + 需批准且 `human_approval_state != approved` → `HUMAN_APPROVAL_REQUIRED`(OSR-E007)。
11. **组计划**。选择模式(`sequential | parallel | vote | cross_review | primary_support`),为每步记录理由、输入摘要、预期产物、预算、依赖、权限请求。
12. **自检与日志**。输出过 `output.schema.json` 自检;决策写入 hash 链 JSONL 日志;工件写 `state/plans/`。
13. **返回**。`SUCCESS | PARTIAL | BLOCKED | FAILED | NEED_ADDITIONAL_SKILL | HUMAN_APPROVAL_REQUIRED`。

### 停止条件

- 满足全部门控且计划合法 → 返回 `SUCCESS` + `route_plan`。
- 无法满足门控 → 返回 `BLOCKED` + 明确错误码,不猜测、不降级、不编造。
- 无能力覆盖 → `NEED_ADDITIONAL_SKILL` + `capability_gap_spec`(第 4.4 节)。
- 输出未过自检 → 抛内部错误(exit 4),绝不输出坏契约。

---

## 五、专业执行规则

### 5.1 协作模式

| 模式 | 适用 | 说明 |
|---|---|---|
| `sequential` | 默认链式依赖 | 上一步产物作为下一步输入 |
| `parallel` | 互不依赖的独立步骤 | 受 `max_parallel` 约束 |
| `vote` | 需多源一致(如证据交叉验证) | 多数一致才采信 |
| `cross_review` | 冲突未消解 / 高风险 | 附加审查维度,由 Router 汇集 |
| `primary_support` | 主技能 + 支持技能 | 明确主从关系 |

### 5.2 星型拓扑

跨 Skill 请求一律回到 Router;Router 是唯一枢纽。`auditEdges()` 可对已记录的调用图审计,**专业→专业直连边**判定为拓扑违规。

### 5.3 强制审计

`risk_level ∈ {high, critical}` → 无条件把 `obsidian-red-team` 与 `obsidian-decision-gate` 加入计划链。这两个审计技能本身**不得被调度为执行性技能**(只读审查)。

### 5.4 重复与上下文污染

- 精确重复调用(同技能 + 同输入摘要)→ OSR-E012。
- 冲突输出 → OSR-E013 / `cross_review`。
- 权限升级 → OSR-E005。成本超限 → OSR-E010。

### 5.5 能力缺口

无技能覆盖 → 生成需求说明(`capability_gap_spec`):缺失能力、所需输入输出、所需工具、领域上下文、建议名称、风险备注。**绝不硬凑答案。**

### 5.6 认识论标签

所有重要陈述使用 `OBSERVED | REPORTED | CALCULATED | INFERRED | HYPOTHESIS | RECOMMENDATION` 之一;不得把推断/假设/建议写成观测。

---

## 六、错误码体系

`tools/osr/errors.ts` 是唯一事实源;控制器按 `code` 机器解析,按 `message` 人类可读。`retryable` 指示是否可重试。

| 码 | 类 | 含义 | 可重试 |
|---|---|---|---|
| OSR-E001 | input | 输入未通过 input.schema.json | 否 |
| OSR-E002 | input | 证据/数据引用缺失、不可读或损坏 | 否 |
| OSR-E003 | input | 链式传递的单位/量纲与下游契约不一致 | 否 |
| OSR-E004 | dependency | 依赖工具不可用 | 是 |
| OSR-E005 | policy | 权限不足/被拒 | 否 |
| OSR-E006 | capability | 下游能力缺失(CAPABILITY_GAP) | 否 |
| OSR-E007 | policy | 人工批准未完成 | 否 |
| OSR-E008 | internal | 结果未通过自身输出契约自检 | 否 |
| OSR-E009 | state | 上下文/引用/决策日志损坏 | 否 |
| OSR-E010 | policy | 预算(成本/token/时间/重试)超限 | 否 |
| OSR-E011 | policy | 调用深度/总调用数超限或循环 | 否 |
| OSR-E012 | input | 精确重复调用 | 否 |
| OSR-E013 | state | 输出冲突且仲裁失败 | 否 |
| OSR-E014 | dependency | 注册表损坏/契约失败 | 否 |
| OSR-E015 | capability | 所选技能契约与请求不兼容 | 否 |
| OSR-E016 | input | skill/controller 版本不受支持 | 否 |
| OSR-E017 | internal | 实现内部错误 | 是 |

---

## 七、工具权限

Router 计划中的每个步骤都声明其权限请求(`permission_request.tools/network/writes`),由权限引擎(默认策略 `tools/osr/policy.ts`)门控。Router 自身运行时只使用本地文件系统与内置校验器——**不联网、不写用户数据、不执行外部命令**。`state/plans/` 与 `logs/decisions/` 是仅有的写入位置。

---

## 八、版本兼容策略

契约文件:`schemas/input.schema.json`、`schemas/output.schema.json`。

- **破坏性变更**(删除/改义字段、改枚举)→ 主版本 +1。
- **新增可选字段**(向后兼容)→ 次版本 +1。
- **实现修复不改契约** → 修订版本 +1。
- 旧版本输出:若主版本不匹配且未提供迁移器 → 明确拒绝(OSR-E016),绝不静默接受。
- 当前支持:`skill_version == 1.x.y`、`controller_version >= 1.0.0`。

---

## 九、性能指标（在 `evals/` 中实现）

| 指标 | 测量方法 | 最低阈值 |
|---|---|---|
| 结构化输出通过率 | 全部评测输出过 output.schema.json | ≥ 0.95 |
| 工具真实调用率 | 评测中调用真实 CLI/函数而非 mock | ≥ 1.0（不变量） |
| 引用/数据可追溯率 | 计划中 `evidence_used` 引用上游 `ref_id` 的比例 | ≥ 0.9 |
| 缺失输入识别率 | 缺字段样本中被逐字段指出的比例 | 1.0 |
| 对抗用例拦截率 | 对抗样本中未产生非法 SUCCESS 的比例 | 1.0 |
| 重复运行一致性 | 同输入两次运行 `route_plan.plan_id` 之外部分一致 | = 1.0（确定性） |
| 平均失败恢复时间 | 失败用例从报告到修复的轮次 | ≤ 1 轮（当前基线） |

---

## 十、维护

- `tools/osr/` 为纯 TypeScript 模块;`router-cli.ts` 是唯一触碰 stdin/stdout 的文件。
- 运行测试:`bun test`(仓库级测试在 `packages/opencode` 目录,本 Skill 自包含测试在本目录)。
- 重新生成注册表快照:`bun tools/bin/osr.ts registry --write`。
- 决策日志用 `bun tools/bin/osr.ts verify <log>` 校验 hash 链。
- 修改 `SKILL.md` 后更新 `frontmatter` 中的版本与 `CHANGELOG.md`。
