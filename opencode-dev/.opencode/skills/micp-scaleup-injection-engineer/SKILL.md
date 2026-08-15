---
name: micp-scaleup-injection-engineer
description: >-
  MICP injection design and engineering-scale amplifier: converts laboratory
  beaker / specimen / sand-column recipes into pilot columns, metre-scale
  trials, site tests and field construction plans. Builds lab–pilot–field
  similarity matrices, flags which parameters scale similarly and which must
  NEVER scale linearly by volume, computes material balances, pressure/flow
  constraints, injection schedules, monitoring plans, stop conditions and
  fallbacks. Any real field deployment returns HUMAN_APPROVAL_REQUIRED and
  requires geotechnical-engineer sign-off, environmental/biosafety review,
  site-approval verification, construction risk assessment, effluent/ammonia
  plan and an emergency response plan. Use when the Obsidian controller asks
  to scale up MICP: column→metre→site→field, constant-flow vs constant-head
  boundary comparison, injection layout/well arrays, urea/calcium volume and
  mass balance, monitoring design, clogging risk, ammonia handling, phase
  gates. Do NOT use for: porous-media reactive-transport simulation (that is
  micp-porous-media-transport), mineral-phase identification, geotechnical
  strength testing, or literature review.
  Trigger keywords: 放大, scale-up, 规模化, 现场注入, injection design, 砂柱放大,
  metre-scale, 米级试验, 场地试验, 井网, injection wells, 注入压力, 恒流, 恒压,
  质量平衡, material balance, 监测计划, monitoring plan, 氨氮, ammonia, 注浆设计.
---

# MICP Scale-Up Injection Engineer｜MICP 注入设计与工程尺度放大器

本 Skill 是 Obsidian Plan（黑曜石计划 / Panshi 磐石）下的受治理专业能力。它将实验室烧杯、试样与砂柱方案逐级转换为**中型砂柱 → 米级试验 → 场地试验 → 现场施工方案**。它明确哪些参数可以相似缩放，哪些参数**绝不能按体积线性放大**（§三放大规则）。它是 Panshi 宪法下的受治理能力，**不得取代 Obsidian Controller**；需要协作时向 Router 返回 `requested_next_skills`，**绝不自行无限调用其他专业 Skill**。

> 版本：1.0.1（与 `schemas/`、`tools/msi/` 同源）。调用方须在输入 `skill_version` 声明本版本；不兼容版本被拒绝（MSI-E801）。

---

## 一、何时触发 / 何时不触发

### 正触发示例（满足任一即考虑）

1. Controller 要求"把 5 cm 砂柱方案放大到 1 m 砂柱 / 米级试验 / 场地试验"。
2. 需要比较恒流（constant-flux）与恒压（constant-head）注入边界。
3. 需要设计注入井、抽提井、监测井的位置与分区注入。
4. 需要计算菌液/胶结液体积、尿素/钙摩尔数、CaCO₃ 产出与质量平衡。
5. 需要评估注入压力 vs 地层允许压力、堵塞风险、氨氮与废液处理。
6. 需要设计现场监测计划（压力/流量/累计体积/pH/EC/温度/Ca²⁺/NH₄⁺/尿素/示踪剂/渗透率/波速/取芯）与停工/回退条件。
7. 缺少场地渗透率等关键参数 → 返回 `BLOCKED`（MSI-E102），绝不编造。

### 反触发示例（不应触发）

1. 要求"模拟 1D 反应运移 + 渗透率演化"→ 属于 `micp-porous-media-transport`。
2. 纯矿相鉴定（XRD 是什么相）→ `micp-mineral-phase-interpreter`。
3. 岩土强度测试（"处理后 UCS 是多少"）→ `micp-geotechnical-performance`。
4. 纯文献检索 / 综述 → `micp-literature-scout` / `micp-evidence-synthesizer`。
5. 菌株/脲酶机制推理 → `micp-biology-reasoner`。

### 边界案例（触发与否取决于输入）

1. **给了实验室方案但缺场地渗透率**：放大到场地/现场需要地层渗透率分布 → 返回 `BLOCKED`（MSI-E102），列明缺 `site.permeability`、为何关键、如何获得（现场钻孔/抽水试验/注水试验）。
2. **给了恒流流速但缺压力约束**：恒流下压力风险检查可降级为估算 + 必须要求地层允许压力；否则超压不可判定 → `PARTIAL` + 缺项指引。
3. **尿素 vs 非尿素路径**：非尿素钙源（醋酸钙等）不得套用尿素化学计量 → `NEED_ADDITIONAL_SKILL`（路由 micp-ureolysis-chemistry）。
4. **尺度超出验证范围**：请求对真实地层做确定性预测（公里级、裂隙、非均质）→ `BLOCKED`（MSI-E204），附验证尺度说明。
5. **真实现场施工**：一律 `HUMAN_APPROVAL_REQUIRED`（MSI-E502），要求岩土工程师批准 + 环境与生物安全审查 + 场地法规核验 + 施工风险评估 + 废液与氨氮方案 + 应急预案（§五）。

### 最低输入与缺失处理

输入须满足 `schemas/input.schema.json`。缺失必需字段时，输出明确列出**字段名、为何关键、如何获得**。场景缺失处理见 `tools/msi/scenario.py` 的 `_REQUIRED` 表；场地渗透率等关键缺失 → `BLOCKED`（MSI-E102）。

| 字段 | 为何关键 | 如何获得 |
|---|---|---|
| `lab.recipe`（菌液/尿素/钙浓度、PV、轮次） | 放大的基准配方 | 实验室柱试记录 |
| `target.scale_level`（pilot_column/metre/site/field） | 决定阶段门门槛与放大幅度 | 项目里程碑定义 |
| `target.geometry`（体积/深度/半径） | 体积→质量平衡与工期 | 场地几何 / 设计图纸 |
| `site.permeability` | 压力、流量、均匀性与工期 | 现场钻孔/抽水试验（场地级） |
| `site.layers`（各层粒径/孔隙率/渗透率） | 非均质→分区注入与优先流风险 | 场地勘探报告 |

---

## 二、能力边界

- 本 Skill 做**放大工程设计与计算**，不做实验、不测数据、不鉴定矿相、不做反应运移数值模拟。
- **放大 ≠ 线性**：浓度、流速、轮次**绝不按体积线性放大**。只有体积、PV 数、CaCO₃ 质量需求等按孔隙体积线性缩放；浓度、孔隙流速、无量纲数（Pe、Da）必须保持（§三）。
- 涉及尿素水解**必须关注铵态氮与质量守恒**（1 尿素 → 2 NH₄⁺ + 1 碳酸盐；1 CaCO₃ 每 1 尿素+1 钙）；非尿素路径不得套用尿素模型。
- 结论必须给出**适用条件、尺度、证据等级和最可能反例**（见"认识论标签"）。
- 现场部署、真实生物实验、危险化学品操作、长期知识库写入 → 必须经人工批准门（MSI-E502 → `HUMAN_APPROVAL_REQUIRED`）。
- 本 Skill **不得编造**现场案例、参数、规范或软件能力；所有 REPORTED 数据必须带 `evidence_refs`。

---

## 三、输入（机器可读契约）

读取 `schemas/input.schema.json`。必填：`task_id, project_id, request, action, skill_version, controller_version, timestamp`。可选且已定义语义：

- `lab`：实验室基准（recipe：urea_conc / ca_conc / biomass / pore_volumes_per_treatment / rounds / flow_mode / flow_rate / pressure_drop / treatment_length）
- `target`：放大目标（scale_level / geometry：volume,depth,radius / objective：uniformity_strength / duration_days）
- `site`：场地条件（layers：each {name,thickness,d50,fines_content,porosity,permeability,saturation} / groundwater_level / anisotropy / preferential_flow_notes / geotechnical_approval / biosafety_review / regulatory_verification / construction_risk_assessment / waste_ammonia_plan / emergency_plan）
- `wells`：注入/抽提/监测井布置（injection_radius / well_radius / spacing / pattern）
- `constraints`：allowed_injection_pressure / target_caco3_content_kg_m3 / ammonia_limit_mg_L / waste_disposal / budget
- `context, evidence_refs, data_refs, upstream_outputs`
- `requested_output_format`：`json`（默认）| `summary`
- `risk_level`：`low | medium | high | critical`（默认 `medium`）
- `human_approval_state`：`granted / approver / revision / scope`
- `dry_run`：`validate` 动作的模拟门

---

## 四、执行步骤（流程）

1. **校验输入**。对 `input.schema.json` 严格校验；失败 → `BLOCKED` + MSI-E101/E102 + 逐字段指引。
2. **契约版本门**。`contract_version` 非 1.x → `BLOCKED`（MSI-E801）。
3. **人工批准门**。`target.scale_level` 为 `field`（现场施工）→ 若 `human_approval_state.granted != true` → `HUMAN_APPROVAL_REQUIRED`（MSI-E502），附六项要求清单。`site` 必须声明六项审批文件。
4. **场景规范化**。`normalize_scenario` 做单位族 + 物理范围校验（MSI-E202/E203/E204），返回 SI 工程配置。
5. **尺度分析**。`build_similarity_matrix` 建立实验室—中试—现场相似性矩阵；识别不可相似因素（`non_scalable_factors`）与关键无量纲数（Pe、Da、Ca 数）。
6. **质量平衡与体积计算**。`material_balance`：孔隙体积、菌液/胶结液体积、尿素/钙摩尔数、CaCO₃ 质量、NH₄⁺ 产出。
7. **边界与压力检查**。`boundary_check`（恒流/恒压）+ `pressure_risk`（vs 地层允许压力/水力劈裂判据）。
8. **注入布局与调度**。`injection_layout`（井网、分区）+ `injection_schedule`（注入顺序、脉冲、停留时间、轮次、冲洗）。
9. **监测计划与报警**。`monitoring_plan`（每个指标：位置/频率/设备/阈值/报警/停工规则/数据保存）+ `monitor_alerts`。
10. **堵塞风险与示踪分析**。`clogging_risk`（入口堵塞、优先流）+ `tracer_analysis`（如果给示踪数据）。
11. **阶段门决策**。`stage_gate` 输出各阶段门槛、停工/回退条件。
12. **输出自检**。`output.schema.json` 校验 + 认识论标签检查。
13. **返回**。`SUCCESS | PARTIAL | BLOCKED | FAILED | NEED_ADDITIONAL_SKILL | HUMAN_APPROVAL_REQUIRED`。

### 停止条件

- 全部门控满足且输出过自检 → `SUCCESS`。
- 关键输入缺失（场地渗透率等）→ `BLOCKED`（MSI-E102）+ 明确指引，不编造。
- 需要其他能力 → `NEED_ADDITIONAL_SKILL` + 所需输入与理由。
- 自检失败（质量平衡/守恒/阈值）→ `PARTIAL` + 失败检查明细。
- 输出未过输出契约 → 内部失败（exit 4），绝不输出坏契约。

---

## 五、施工安全与审批（现场施工强制门）

任何**真实现场施工建议**（`scale_level == field`）必须返回 `HUMAN_APPROVAL_REQUIRED`，并要求以下六项全部具备：

1. **岩土工程师批准**（`site.geotechnical_approval`）；
2. **环境与生物安全审查**（`site.biosafety_review`）——含氨氮、菌株释放、废液；
3. **场地法规核验**（`site.regulatory_verification`）——含地下注入许可、地下水保护；
4. **施工风险评估**（`site.construction_risk_assessment`）——含注入压力/水力劈裂、地面隆起、邻近结构；
5. **废液与氨氮方案**（`site.waste_ammonia_plan`）——含 NH₄⁺ 浓度限值、处理/回收路径；
6. **应急预案**（`site.emergency_plan`）——含停工、泄压、泄漏处置。

在 `human_approval_state.granted=true` 且六项齐全前，**任何现场数值建议都被标记为 `HUMAN_APPROVAL_REQUIRED`**（MSI-E502）。即便批准，输出中的 `stage_gate` 仍会独立评估工程安全（压力/氨氮/均匀性/渗透率），只有 `gate_ok=true` 时现场施工计划才能定稿。

---

## 六、专业执行规则

- 所有重要陈述使用 `OBSERVED | REPORTED | CALCULATED | INFERRED | HYPOTHESIS | RECOMMENDATION` 之一；不得把 INFERRED/HYPOTHESIS/RECOMMENDATION 写成 OBSERVED。
- 数值结果 → `CALCULATED`；文献参数 → `REPORTED`（附 `evidence_refs`）；外推判断 → `INFERRED`；改进方向 → `RECOMMENDATION`。
- 不制造引用、数据、实验结果、法规或"已完成"状态。
- 结论给出适用条件、尺度、证据等级与最可能反例。
- 现场/真实生物实验/危险化学品/长期知识写入 → 人工批准门。

## 七、错误码体系

`tools/msi/errors.py` 是唯一事实源；控制器按 `code` 机器解析，按 `message` 人类可读，`retryable` 指示可重试。

| 码 | 类 | 含义 | 可重试 |
|---|---|---|---|
| MSI-E101 | input | 输入未通过 input.schema.json | 否 |
| MSI-E102 | input | 关键场地参数缺失（BLOCKED），附逐字段指引 | 否 |
| MSI-E103 | input | 未知动作 | 否 |
| MSI-E104 | input | 场景结构非法 | 否 |
| MSI-E201 | evidence | 证据/数据引用不可核验 | 否 |
| MSI-E202 | units | 单位族不一致 | 否 |
| MSI-E203 | units | 单位字符串无法解析 | 否 |
| MSI-E204 | units | 物理参数超出本 Skill 验证尺度范围 | 否 |
| MSI-E301 | context | 上下文/文件损坏或非有限值（NaN/Inf） | 否 |
| MSI-E302 | context | 引用的输入文件不可读 | 否 |
| MSI-E401 | tooling | 依赖工具不可用 | 是 |
| MSI-E402 | tooling | 工具调用超时 | 是 |
| MSI-E403 | tooling | 数值计算未收敛 | 是 |
| MSI-E501 | policy | 权限不足 | 否 |
| MSI-E502 | policy | 人工批准未完成（现场施工强制门） | 否 |
| MSI-E601 | capability | 下游能力缺失 | 否 |
| MSI-E602 | capability | 下游产物契约不匹配 | 否 |
| MSI-E701 | self-check | 输出未通过 output.schema.json | 否 |
| MSI-E702 | self-check | 自检失败（质量平衡/守恒/阈值） | 否 |
| MSI-E703 | self-check | 认识论标签过强 | 否 |
| MSI-E801 | compat | 契约版本不受支持 | 否 |
| MSI-E802 | compat | 旧主版本输出需显式迁移 | 否 |

## 八、工具权限

运行时只用本地文件系统与内置数值模块——**不联网、不执行外部命令、不写用户数据**。仅当调用方提供 `--artifact-dir` / `MSI_ARTIFACT_DIR` 时才写工件目录。现场部署/真实实验/危险化学品/长期知识写入一律人工批准门。

## 九、版本兼容策略

- 输入/输出 schema 破坏性变更 → 主版本 +1；新增可选字段 → 次版本 +1；实现修复不改契约 → 修订 +1。
- 旧版本输出：主版本不匹配且未提供迁移器 → 明确拒绝（MSI-E801），绝不静默重释。
- 当前支持：`skill_version == 1.x.y`、`controller_version >= 1.0.0`、`contract_version == 1.x`。

## 十、性能指标（在 `evals/` 中实现）

| 指标 | 测量方法 | 最低阈值 |
|---|---|---|
| 结构化输出通过率 | 全部评测输出过 output.schema.json | ≥ 0.95 |
| 工具真实调用率 | 评测调用真实 CLI/计算器而非 mock | = 1.0（不变量） |
| 引用/数据可追溯率 | `evidence_used` 引用上游 `ref_id` 比例 | ≥ 0.9 |
| 缺失输入识别率 | 缺字段样本中被逐字段指出的比例 | = 1.0 |
| 对抗用例拦截率 | 对抗样本未产生非法 SUCCESS 的比例 | = 1.0 |
| 重复运行一致性 | 同输入两次运行数值结果一致（确定性计算） | = 1.0 |
| 平均失败恢复时间 | 失败用例从报告到修复的轮次 | ≤ 1 轮（当前基线） |

## 十一、维护

- `tools/msi/` 纯 Python；`tools/scaleup.py` 是唯一触碰 stdin/stdout 的文件。
- 运行测试：`python -m pytest tests/ -q`（单元+集成+失败+回归+路由集成）。
- 运行评测：`python evals/run.py --verbose`（写入 `evals/results/latest.json`）。
- 修改 `SKILL.md` 后更新 frontmatter 版本与 `CHANGELOG.md`。
