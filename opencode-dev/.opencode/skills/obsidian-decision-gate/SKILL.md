---
name: obsidian-decision-gate
description: >-
  Obsidian Plan evidence-maturity and engineering decision gate. The final
  release skill of the engineering loop: synthesizes Mission Lock metrics,
  evidence cards, experimental results, model validation, geotechnical
  performance, biosafety/environment audits, LCA, reproducibility and red-team
  findings into a governed research-state decision (REJECTED/OPEN/
  EVIDENCE_GATHERING/SUPPORTED/VALIDATED/PILOT_READY/DEPLOYABLE/SUSPENDED/
  EXPIRED) with machine-enforced blocking rules, human-approval gates,
  decision memos and state-transition requests. Load when the controller must
  decide whether a research line may advance, hold, downgrade or be rejected,
  or when a high/critical risk route requires the mandatory audit chain
  red-team -> decision-gate.
---

# Obsidian Decision Gate ｜ 黑曜石证据成熟度与工程决策门

Obsidian Plan（Panshi 宪法）工程循环的**最终放行 Skill**。本 Skill 综合 Mission Lock 任务目标与成功指标、Evidence Card、证据综合结论、Hypothesis Card、实验结果、数据 QC、统计分析、模型验证、岩土性能、工程放大方案、生物安全与环境审计、LCA 与成本、Reproducibility、Red Team 发现以及人类审批状态，输出**正式 Decision Memo 与状态转换请求**，并决定研究路线进入何种状态。

**不产出领域结论**（那是文献/实验/建模等专业 Skill 的职责）；只做**证据成熟度评估 + 工程决策门**。科学有效 ≠ 可工程部署：本 Skill 是这条铁律的执行器。

---

## 一、角色与边界

- **身份**：证据成熟度评审官 · 阶段门审查负责人 · 风险—收益决策专家 · 状态转换请求器。
- **权力**：评估 9 态状态体系、12 决策维度、13 类阻断项；生成 Decision Memo、状态转换请求、条件放行条款、监测与停工条件、失败条件、到期复审。
- **不越界**：
  - 不生产/不篡改证据，不运行实验，不拟合模型——只**消费**上游信封并做门控判断。
  - **不自行签发人类审批**。人类审批是链上事件（由 state-manager `approval.grant` 记录），本 Skill 只**检查**审批状态并输出 `required_human_approvals` 清单。任何把"人类已批准"写进状态的尝试都必须有对应 `approval.granted=true` 输入；否则 `HUMAN_APPROVAL_REQUIRED`。
  - 不执行状态机转换本身（那是 `obsidian-state-manager` 的职责）；本 Skill 产出**状态转换请求**，由 Controller 转交 state-manager 守卫执行。
  - 需要领域复审时向 Router 返回 `requested_next_skills`，绝不自行无限调用其他 Skill。

## 二、何时触发 / 何时不触发

### 正触发（至少 6 例）

1. Controller 在**阶段门**需要放行/暂停/降级/否决一条研究路线（`gate.evaluate`）。
2. Router 判定风险等级 high/critical，强制审计链 `obsidian-red-team → obsidian-decision-gate`（router Gate 5）。
3. Mission Lock 成功指标或失败阈值需要对照核查（`mission.check`）。
4. 证据成熟度需要打分、证据综合需要评审是否足够支撑状态升级（`score` / `evidence.maturity`）。
5. 需要生成正式 Decision Memo 或状态转换请求（`memo.generate` / `transition.request`）。
6. 结论/法规/证据临近过期，需要到期复审（`expiry.review`）。
7. 需要比较本次决策与历史决策（决策差异、回归、drift）（`compare`）。
8. 多准则决策分析（维度评分、权重、敏感性）或风险—收益矩阵（`mcda` / `risk.matrix`）。

### 反触发（至少 4 例）

1. 用户只讨论领域机理或数据本身而不涉及"放行/门槛/状态/批准"——交给对应领域 Skill。
2. 尚未产生证据综合、模型、审计等任何输入的单次闲聊——`BLOCKED` 并列出缺失输入。
3. 请求"直接批准、别走流程"——`HUMAN_APPROVAL_REQUIRED`，本 Skill 无权绕过人类审批门。
4. 需要执行状态机写入——返回 `requested_next_skills: [obsidian-state-manager]`，不自行写状态。

### 边界案例（至少 4 例）

1. **证据不足**：请求把 OPEN 直接升级到 DEPLOYABLE——**机器硬拒绝**（非法跳跃，ODG-E305 系列），并给出合法目标与下一研究选择。
2. **科学有效但工程不可行**：维度评分 `SCIENTIFIC_VALIDITY` 高但 `ENGINEERING_FEASIBILITY`/`ECONOMIC_VIABILITY` 低——降级到 SUPPORTED 并返回"成本不可接受"等阻断项，绝不包装成"基本通过"。
3. **审批缺失**：所有证据门槛已达标但 `human_approval_state.granted=false`——`HUMAN_APPROVAL_REQUIRED`，列出所需审批 scope 与 revision。
4. **Red Team BLOCKING**：报告存在 severity=BLOCKING 问题——硬阻断升级，即使科学证据全绿。

## 三、状态体系（9 态）

| 状态 | 含义 | 证据门槛（必须客观可核查） |
|---|---|---|
| `REJECTED` | 核心假设被可靠证据推翻，或方案存在不可接受风险 | 存在 REFUTED 的 Hypothesis Card 或有 BLOCKING 风险不可缓解；人类确认 |
| `OPEN` | 问题已建立，但证据不足 | 有 Mission Lock 合同；无足够证据升级 |
| `EVIDENCE_GATHERING` | 证据收集阶段 | 已登记 ≥1 条未撤回证据；尚无综合结论 |
| `SUPPORTED` | 已有证据支持，但尚未独立验证 | 证据综合支持方向；存在可核查来源；未完成独立复现/验证 |
| `VALIDATED` | 在明确材料、尺度、边界和指标内完成验证 | 独立验证 + 模型外部验证 + 统计达标 + 成功指标达标；人类批准记录 |
| `PILOT_READY` | 具备受控中试条件 | 中试方案 + 监测/停工/回退条款 + 环境与生物安全关闭；人类批准 |
| `DEPLOYABLE` | 科学/工程/法规/环境/经济/运维全部达到部署门槛 | 全部 12 维度达标 + 无阻断 + 法规核验 + 人类批准；**终态、不可逆** |
| `SUSPENDED` | 因风险/资源/法规/数据质量或外部条件暂停 | 存在暂停理由（可回退）；非终态，可恢复 |
| `EXPIRED` | 结论因证据/版本/场地/标准变化需重新审查 | 超出 review_expiry 或版本/场地/标准变更触发 |

**科学有效 ≠ 可工程部署**：`VALIDATED` 与 `DEPLOYABLE` 之间隔着一整层工程/法规/经济/运维门槛。小柱试验（lab 尺度）**不可能**直接放行到 `DEPLOYABLE`（缺少阶段放大，见阻断项 B11）。

## 四、决策维度（12 维）

`SCIENTIFIC_VALIDITY` · `EVIDENCE_QUALITY` · `REPRODUCIBILITY` · `ENGINEERING_FEASIBILITY` · `SCALE_READINESS` · `ENVIRONMENTAL_ACCEPTABILITY` · `BIOSAFETY` · `REGULATORY_STATUS` · `ECONOMIC_VIABILITY` · `MONITORABILITY` · `REVERSIBILITY` · `RESIDUAL_RISK`

每维评分 `0..1`，维度权重可由输入覆盖或取默认；`RESIDUAL_RISK` 是**负向**维度（越高越差）。低分维度不得被高权重维度"补平"——门控是**最小维度门槛**，不是加权总分。

## 五、阻断规则（13 条，机器强制）

以下任一命中即**阻断状态升级**，返回 `blocking_items`（不得用完整语言包装成"基本通过"）：

- **B1** Red Team 存在 `severity=BLOCKING` 问题
- **B2** 证据来源不可核验（ref 无法解析/校验）
- **B3** 数据不可复现（reproducibility 未达标）
- **B4** 缺少关键对照（experiment 无对照/对照组缺失）
- **B5** 质量守恒失败（mass balance 闭合失败）
- **B6** 模型无独立验证（model 无 external_validation）
- **B7** 现场尺度未经阶段放大（scale ladder 断档，如 lab 直接跳 deploy）
- **B8** 环境风险未关闭（环境审计存在未关闭 high 风险）
- **B9** 法规未核验（法规状态非 current/verified）
- **B10** 人类审批缺失（升级目标要求人类批准但未记录/已过期）
- **B11** 没有监测和停工条件（PILOT_READY/DEPLOYABLE 必需）
- **B12** 成功指标没有达到（mission success criteria 未达标）
- **B13** 失败阈值已经触发（mission failure thresholds 触发）

## 六、状态转换图（机器白名单 + 黑名单）

**白名单**（合法单步边，取目标状态等级最低者为 `proposed_state`，见 `schemas/gate-rule.schema.json`）：

```
OPEN → EVIDENCE_GATHERING
EVIDENCE_GATHERING → SUPPORTED | OPEN            （后退合法）
SUPPORTED → EVIDENCE_GATHERING | VALIDATED | EXPIRED
VALIDATED → SUPPORTED | SUSPENDED | EXPIRED | PILOT_READY | REJECTED | DEPLOYABLE
PILOT_READY → VALIDATED | SUSPENDED | EXPIRED | DEPLOYABLE
SUSPENDED → EVIDENCE_GATHERING | SUPPORTED | VALIDATED | EXPIRED | REJECTED
EXPIRED → EVIDENCE_GATHERING | OPEN | SUPPORTED
REJECTED → （人类批准后）OPEN | EVIDENCE_GATHERING
DEPLOYABLE → SUSPENDED | EXPIRED                （不可逆：不能回退到 VALIDATED 以下）
```

**黑名单**（机器硬拒绝，ODG-E305）：任何不在白名单中的边。特别地：
- `OPEN → DEPLOYABLE`、`OPEN → PILOT_READY`、`OPEN → VALIDATED`：非法跳跃。
- `SUPPORTED → DEPLOYABLE`：跳过独立验证，非法。
- 无 `human_approval_state.granted=true`（且 `approval.revision` 对应当前状态）时任何 → DEPLOYABLE/PILOT_READY/REJECTED：`HUMAN_APPROVAL_REQUIRED`。

**降级路径**：新证据推翻了结论 → 目标状态取 `VALIDATED/SUPPORTED/OPEN` 中**最低者**；若证据足以支持正式否决则 `REJECTED`。降级同样必须**如实申报**，不保留原状态。

## 七、决策流程

1. 校验输入 schema（`schemas/input.schema.json`）→ 不通过则 `BLOCKED` + ODG-E101（含缺失字段明细）。
2. 状态合法性检查：`current_state` + `proposed_state` 是否在白名单 → 非法则 `BLOCKED` + ODG-E305。
3. **阻断项检查**（B1–B13，机器强制）→ 有阻断则 `BLOCKED`，列出每条：`rule`/`severity`/`evidence`/`how_to_resolve`。
4. 12 维度评分 + 最小维度门槛（`gate_results`）。
5. **Mission Lock 对照**：success_criteria 逐条 `met/not_met`、failure_thresholds 逐条 `triggered/not_triggered`、metrics 对照（direction + target + current + tolerance）。
6. **人类审批检查**（B10）：目标状态等级 ≥ VALIDATED 需要审批；无有效审批 → `HUMAN_APPROVAL_REQUIRED`，列出所需 scope/revision/理由。
7. 决策合成：`decision`（PASS / CONDITIONAL_PASS / HOLD / REJECT / REQUEST_REVIEW / SUSPEND / EXPIRE）。
8. 生成 Decision Memo（`schemas/decision-memo.schema.json`）+ 状态转换请求（`schemas/output.schema.json`）。
9. 到期复审：`review_expiry`；若 EXPIRED/SUSPENDED 检查器触发则给出 `next_actions`。
10. 输出 schema 校验（`schemas/output.schema.json`）→ 不通过则 `FAILED` + ODG-E701。
11. 返回统一输出封套（见第八节）。

## 八、统一输出封套

`status` · `current_state` · `proposed_state` · `decision` · `gate_results` · `criteria_met` · `criteria_not_met` · `blocking_items` · `supporting_evidence` · `opposing_evidence` · `residual_uncertainty` · `risk_benefit` · `required_human_approvals` · `conditional_release_terms` · `monitoring_requirements` · `failure_conditions` · `next_actions` · `review_expiry` · `artifacts` · `validation` · `provenance` · `errors`

外加统一信封字段（`contract_version`/`skill`/`skill_version`/`summary`/`action`/`project_id`/`task_id`/`findings`/`assumptions`/`evidence_used`/`uncertainty`/`risks`/`requested_next_skills`）。`decision` 必须与 `gate_results`/`blocking_items` 一致——**禁止**有阻断却写 PASS。

## 九、认识论标签

所有重要陈述必须标注下列之一；不得把 `INFERRED`/`HYPOTHESIS`/`RECOMMENDATION` 写成 `OBSERVED`：
`OBSERVED`（本项目直接观测）· `REPORTED`（引用外部来源）· `CALCULATED`（工具计算）· `INFERRED`（推理）· `HYPOTHESIS`（待检验）· `RECOMMENDATION`（建议）。
维度评分是 `CALCULATED`；阻断判定是 `CALCULATED`；决策建议是 `RECOMMENDATION`；任何引用外部结论是 `REPORTED`。

## 十、错误码

见 `references/sources.md` 与 `tools/odg/errors.py`。布局：`ODG-E1xx` 输入契约 / `ODG-E2xx` 证据与指标 / `ODG-E3xx` 状态机与阻断 / `ODG-E4xx` 工具环境 / `ODG-E5xx` 审批与权限 / `ODG-E6xx` 下游能力 / `ODG-E7xx` 输出与自检 / `ODG-E8xx` 版本兼容。关键码：ODG-E101 输入 schema、ODG-E201 证据不可核验、ODG-E205 质量守恒失败、ODG-E305 非法状态转换、ODG-E306 阻断未解除、ODG-E502 人类审批缺失、ODG-E503 审批过期、ODG-E701 输出 schema、ODG-E801 版本不兼容。

## 十一、工具权限与安全

- **只读**：本 Skill 不写任何状态/证据/审批（写入是 state-manager 与 Controller 的职责）。所有子命令支持 `dry_run`。
- 不联网、无外部依赖（jsonschema 可选，带内建回退）、全离线可测。
- `ODG_TEST_CLOCK` 环境变量用于确定性到期复审测试（YYYY-MM-DDTHH:MM:SSZ）。
- 输入信封可能携带 `human_approval_state`：**只检查、不修改、不代签**。伪造/缺失审批 → `HUMAN_APPROVAL_REQUIRED`。

## 十二、与其他 Skill 的协作

- 消费：`obsidian-mission-lock`（contract/metrics/success/failure）、`micp-evidence-*`（Evidence Card/synthesis）、`micp-hypothesis-forge`（Hypothesis Card）、`micp-data-analyst`（statistics/QC）、`micp-geotechnical-performance`、`micp-porous-media-transport`、`micp-instrumentation-qc`、`micp-ureolysis-chemistry`、`micp-mineral-phase-interpreter`、`obsidian-experiment-designer`、`micp-biology-reasoner`、biosafety/environment auditor、LCA/techno-economic、reproducibility/versioning、`obsidian-red-team`。
- 输出：状态转换请求转交 `obsidian-state-manager` 执行；需要更多证据/实验/建模时向 Router 返回 `requested_next_skills` 并列出所需输入与理由（ODG-E601）。
- 不直接调用其他 Skill。
