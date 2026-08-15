---
name: micp-porous-media-transport
description: >-
  MICP porous media transport modeling: bacteria, urea, calcium and calcite
  precipitation coupled through a porous medium — advection, dispersion,
  adsorption/filtration retention, ureolysis, precipitation and the clogging
  feedback on porosity and permeability. Use when the Obsidian controller asks
  to simulate or analyze a MICP column / sand-pack / core / field flow-and-
  reaction system: constant-flux vs constant-head boundary comparison, inlet
  clogging, bypass/preferential flow, permeability-porosity evolution,
  Damköhler/Péclet scale analysis, conservation checks and grid sensitivity.
  Do NOT use for: ureolysis-only chemistry without transport, mineral-phase
  identification, geotechnical strength evaluation, field injection logistics,
  or generating literature reviews — those belong to other specialist skills.
  Trigger keywords: 运移, transport, 对流, 弥散, 堵塞, clogging, permeability,
  渗透率, porosity, Damköhler, Péclet, 反应运移, MICP column, 岩芯, 砂柱,
  恒流, 恒压, flux boundary, head boundary.
---

# MICP Porous Media Transport｜菌液、溶质、沉淀与堵塞耦合

本 Skill 是 Obsidian Plan（黑曜石计划 / Panshi 磐石）下的受治理专业能力。它分析 MICP 中细胞、尿素、钙离子与碳酸钙沉淀在多孔介质中的迁移、反应、截留与渗透率演化，并解释和预测空间不均匀性。它是 Panshi 宪法下的受治理能力，**不得取代 Obsidian Controller**；需要协作时向 Router 返回 `requested_next_skills`，**绝不自行无限调用其他专业 Skill**。

> 版本：1.0.0（与 `schemas/`、`tools/micp/` 同源）。调用方须在输入 `skill_version` 声明本版本；不兼容版本被拒绝（OPM-E801）。

---

## 一、何时触发 / 何时不触发

### 正触发示例（满足任一即考虑）

1. Controller 要求"模拟 MICP 砂柱中尿素水解 + 碳酸钙沉淀 + 渗透率演化"。
2. 需要比较恒流（constant-flux）与恒压（constant-head）边界对堵塞进程的影响。
3. 需评估入口堵塞、旁路流或优先流（入口段孔隙率率先下降 → 流量重新分配）。
4. 需对同一工况做无量纲分析（Damköhler、Péclet）以判断输运/反应主导机制。
5. 需为模拟输出做质量守恒检查、网格敏感性分析与数值稳定性声明。
6. 缺失孔隙率/流量等关键边界条件时，要求返回 `MODEL_BLOCKED` 而非编造。

### 反触发示例（不应触发）

1. 直接要求"写一段 MICP 综述"——应路由给 `evidence-synthesizer` / `literature-scout`。
2. 纯矿相鉴定（"这段 XRD 是什么相"）——属于 `mineral-phase-interpreter`。
3. 岩土强度评估（"处理后的 UCS 是多少"）——属于 `geotechnical-performance`。
4. 现场注浆作业的排期与人员安排——属于 `scaleup-injection-engineer`。

### 边界案例（触发与否取决于输入）

1. **给了孔隙率但缺流量**："phi=0.4 但没给流量或压力" → 触发，返回 `MODEL_BLOCKED`（OPM-E102），列明缺 `flow`、为何关键、如何获得。
2. **给了流量但缺渗透率**：恒流边界下渗透率只影响堵塞判据的 `K/K0` 演化 → 仍可解，但堵塞判定降级为仅孔隙率判据，并在 `uncertainty` 中说明。
3. **尿素水解 vs 非尿素路径**：若请求明确是"尿素循环 + CaCl₂"，走本模型；若请求是醋酸钙或其他非尿素钙源，**不得套用尿素化学计量**，返回 `NEED_ADDITIONAL_SKILL`。
4. **尺度超出验证范围**：请求对真实地层（公里级、非均质、裂隙）做确定性预测 → 返回 `BLOCKED`（OPM-E204），附验证尺度说明。

### 最低输入与缺失处理

输入须满足 `schemas/input.schema.json`。缺失必需字段时，输出明确列出**字段名、为何关键、如何获得**（不笼统说"信息不足"）。场景缺失处理见 `tools/micp/scenario.py` 的 `_REQUIRED` 表；关键边界条件缺失 → `MODEL_BLOCKED`（OPM-E102）。

| 字段 | 为何关键 | 如何获得 |
|---|---|---|
| `scenario.geometry.length` | 建立网格、Péclet 数与守恒误差量纲 | 柱长/岩芯长自实验设计 |
| `scenario.porosity` | Kozeny-Carman 渗透率演化的基线 | 干湿密度法或饱和法 |
| `scenario.flow` | 对流输运与 CFL 时间步定义 | 泵流量 Q/截面积 A → u=Q/A；或进出口压力 |
| `scenario.permeability` | 渗透率演化与堵塞判据 | 恒压渗透仪 / 落球法 / Kozeny-Carman 估算 |
| `scenario.species` | 反应-输运耦合的物质基础 | 进水尿素/钙浓度与注入菌液 OD/CFU |

---

## 二、能力边界

- 本 Skill 做**建模与数值分析**，不做实验、不测数据、不鉴定矿相。
- 区分**生物过程**（尿素水解动力学）、**化学过程**（沉淀）、**矿物相**（方解石质量）、**多孔介质**（孔隙率/渗透率演化）、**工程性能**（堵塞→流量下降）与**环境影响**（铵态氮产出与质量守恒）。
- 涉及尿素水解**必须关注铵态氮与质量守恒**（1 尿素 → 2 NH₄⁺ + 1 碳酸盐）；非尿素路径不得套用尿素模型。
- 结论必须给出**适用条件、尺度、证据等级和最可能反例**（见"认识论标签"）。
- 现场部署、真实生物实验、危险化学品操作、长期知识库写入 → 必须经人工批准门（OPM-E502 → `HUMAN_APPROVAL_REQUIRED`）。
- 模型**不得超出验证尺度给出确定性预测**（验收门槛 2）。

---

## 三、输入（机器可读契约）

读取 `schemas/input.schema.json`。必填：`task_id, project_id, request, action, skill_version, controller_version, timestamp`。可选且已定义语义：

- `scenario`：域载荷（geometry / porosity / permeability / flow / species / scale）
- `k_ure, k_pre, k_half`：反应常数；`t_end, dt, clog_threshold, permeability_ratio`：数值控制
- `context, constraints, evidence_refs, data_refs, upstream_outputs`
- `requested_output_format`：`json`（默认）| `summary`
- `risk_level`：`low | medium | high | critical`（默认 `medium`）
- `human_approval_state`：`granted / approver / revision / scope`
- `dry_run`：`validate` 动作的模拟门

## 四、执行步骤（流程）

1. **校验输入**。对 `input.schema.json` 严格校验；失败 → `BLOCKED` + OPM-E101/E102 + 逐字段指引。
2. **契约版本门**。`contract_version` 非 1.x → `BLOCKED`（OPM-E801）。
3. **场景规范化**。`normalize_scenario` 做单位族 + 物理范围校验（OPM-E202/E203/E204），返回 SI 求解器配置。
4. **无量纲分析**。计算 Pe、Da、rDa，分类输运/反应主导（`dimensionless.py`）。
5. **数值求解**。`solve_transport` 运行算子分裂 1D 反应运移（对流+弥散+尿素水解+沉淀+孔隙率/渗透率反馈）。
6. **堵塞判据**。`clogging.py` 按孔隙率下限与 K/K0 阈值判定。
7. **守恒与敏感性自检**。`validate.py`：尿素/钙/铵/碳酸盐化学计量守恒、网格敏感性、有限性与 CFL。
8. **输出自检**。`output.schema.json` 校验 + 认识论标签检查。
9. **返回**。`SUCCESS | PARTIAL | BLOCKED | FAILED | NEED_ADDITIONAL_SKILL | HUMAN_APPROVAL_REQUIRED`。

### 停止条件

- 全部门控满足且输出过自检 → `SUCCESS`。
- 关键输入缺失 → `MODEL_BLOCKED`（OPM-E102）+ 明确指引，不编造。
- 需要其他能力 → `NEED_ADDITIONAL_SKILL` + 所需输入与理由。
- 自检失败（守恒/网格/有限性）→ `PARTIAL` + 失败检查明细。
- 输出未过输出契约 → 内部失败（exit 4），绝不输出坏契约。

---

## 五、专业执行规则

- 所有重要陈述使用 `OBSERVED | REPORTED | CALCULATED | INFERRED | HYPOTHESIS | RECOMMENDATION` 之一；不得把 INFERRED/HYPOTHESIS/RECOMMENDATION 写成 OBSERVED。
- 数值结果 → `CALCULATED`；文献参数 → `REPORTED`（附 `evidence_refs`）；外推判断 → `INFERRED`；改进方向 → `RECOMMENDATION`。
- 不制造引用、数据、实验结果、法规或"已完成"状态。
- 结论给出适用条件、尺度、证据等级与最可能反例。
- 现场/真实生物实验/危险化学品/长期知识写入 → 人工批准门。

## 六、错误码体系

`tools/micp/errors.py` 是唯一事实源；控制器按 `code` 机器解析，按 `message` 人类可读，`retryable` 指示可重试。

| 码 | 类 | 含义 | 可重试 |
|---|---|---|---|
| OPM-E101 | input | 输入未通过 input.schema.json | 否 |
| OPM-E102 | input | 关键边界条件缺失（MODEL_BLOCKED），附逐字段指引 | 否 |
| OPM-E103 | input | 未知动作 | 否 |
| OPM-E104 | input | 场景结构非法 | 否 |
| OPM-E201 | evidence | 证据/数据引用不可核验 | 否 |
| OPM-E202 | units | 单位族不一致 | 否 |
| OPM-E203 | units | 单位字符串无法解析 | 否 |
| OPM-E204 | units | 物理参数超出本模型尺度验证范围 | 否 |
| OPM-E301 | context | 上下文/文件损坏或非有限值（NaN/Inf） | 否 |
| OPM-E302 | context | 引用的输入文件不可读 | 否 |
| OPM-E401 | tooling | 依赖工具不可用 | 是 |
| OPM-E402 | tooling | 工具调用超时 | 是 |
| OPM-E403 | tooling | 数值求解器未收敛 | 是 |
| OPM-E501 | policy | 权限不足 | 否 |
| OPM-E502 | policy | 人工批准未完成 | 否 |
| OPM-E601 | capability | 下游能力缺失 | 否 |
| OPM-E602 | capability | 下游产物契约不匹配 | 否 |
| OPM-E701 | self-check | 输出未通过 output.schema.json | 否 |
| OPM-E702 | self-check | 自检失败（守恒/网格/有限性） | 否 |
| OPM-E703 | self-check | 认识论标签过强 | 否 |
| OPM-E801 | compat | 契约版本不受支持 | 否 |
| OPM-E802 | compat | 旧主版本输出需显式迁移 | 否 |

## 七、工具权限

运行时只用本地文件系统与内置数值模块——**不联网、不执行外部命令、不写用户数据**。仅当调用方提供 `--artifact-dir` / `OPM_ARTIFACT_DIR` 时才写工件目录。现场部署/真实实验/危险化学品/长期知识写入一律人工批准门。

## 八、版本兼容策略

- 输入/输出 schema 破坏性变更 → 主版本 +1；新增可选字段 → 次版本 +1；实现修复不改契约 → 修订 +1。
- 旧版本输出：主版本不匹配且未提供迁移器 → 明确拒绝（OPM-E801），绝不静默重释。
- 当前支持：`skill_version == 1.x.y`、`controller_version >= 1.0.0`、`contract_version == 1.x`。

## 九、性能指标（在 `evals/` 中实现）

| 指标 | 测量方法 | 最低阈值 |
|---|---|---|
| 结构化输出通过率 | 全部评测输出过 output.schema.json | ≥ 0.95 |
| 工具真实调用率 | 评测调用真实 CLI/求解器而非 mock | = 1.0（不变量） |
| 引用/数据可追溯率 | `evidence_used` 引用上游 `ref_id` 比例 | ≥ 0.9 |
| 缺失输入识别率 | 缺字段样本中被逐字段指出的比例 | = 1.0 |
| 对抗用例拦截率 | 对抗样本未产生非法 SUCCESS 的比例 | = 1.0 |
| 重复运行一致性 | 同输入两次运行数值结果一致（确定性求解器） | = 1.0 |
| 平均失败恢复时间 | 失败用例从报告到修复的轮次 | ≤ 1 轮（当前基线） |

## 十、维护

- `tools/micp/` 纯 Python；`tools/transport.py` 是唯一触碰 stdin/stdout 的文件。
- 运行测试：`python -m pytest tests/ -q`（单元+集成+失败+回归）。
- 运行评测：`python evals/run.py --verbose`（写入 `evals/results/latest.json`）。
- 修改 `SKILL.md` 后更新 frontmatter 版本与 `CHANGELOG.md`。
