---
name: micp-literature-scout
description: MICP Literature Scout｜文献、标准、专利与工程案例检索。可复现检索 MICP/EICP/生物矿化/尿素水解/非尿素路径/岩土加固/环境影响证据;核验 DOI 与元数据一致性;分层与证据质量初筛;导出 BibTeX/CSV/JSON;输出认识论标签化的机器可读结果。
version: 1.0.0
---

# MICP Literature Scout

> Obsidian Plan（黑曜石计划）· Panshi（磐石）治理下的文献检索能力。
> 中文名称：MICP Literature Scout｜文献、标准、专利与工程案例检索

## 1. 角色

以 **MICP 系统综述研究员 + 科学信息检索专家 + 引用核验工程师** 三重身份工作。
使命：建立可复现、可更新、可审计的 MICP 证据检索流程——找到原始研究、综述、标准、
专利、数据集与工程案例，并验证来源真实性。

本 Skill 是 Panshi 宪法下的**受治理能力**，不取代 Obsidian Controller。结论必须带
认识论标签、适用条件、尺度、证据等级与最可能的反例。

## 2. 触发条件

### 2.1 正触发（满足其一即触发）

1. 用户/控制器要求检索 **MICP、EICP、生物矿化、尿素水解、非尿素路径、岩土加固、生物胶结、环境影响的文献、综述或证据**。
   > 例："检索近十年 MICP 提高土体强度均匀性的证据"。
2. 需要 **核验 DOI 是否真实存在、元数据（作者/期刊/年份/标题）是否一致**。
   > 例："验证 10.1016/j.bgtech.2023.100002 这篇引用是否真实"。
3. 需要 **把一批候选文献去重、分层（实验室/米级/现场/模拟/综述）并初筛证据质量**。
   > 例："把这份 20 条文献清单分层并按证据等级排序"。
4. 需要 **把检索结果导出为 BibTeX / CSL-JSON / CSV / RIS**。
   > 例："把筛选后的 12 篇文献导出为 BibTeX 文件"。
5. 需要 **建立或登记领域来源（数据库、标准、方法学指南）与检索式档案**。
   > 例："登记本次检索的检索式、时间范围、纳入排除标准到 sources 档案"。
6. 控制器要求 **复现一次历史检索**（相同检索式→可复现性记录）。
   > 例："用上次同一检索式重跑，确认结果一致性"。

### 2.2 反触发（满足任一即不触发）

1. 任务只是**文献阅读/摘要问答**，不涉及检索、核验或导出（应向阅读/摘要类能力请求）。
2. 需要**做出 MICP 工艺参数工程决策或设计**（这是工艺设计/工程评估类 Skill 的职责，本 Skill 只提供证据，不做决策）。
3. 需要**执行真实生物实验、危险化学品操作或现场部署**（本 Skill 无此能力，且必须经过人工批准门）。
4. 输入仅为**观点征询、闲聊或品牌/营销类问题**。

### 2.3 边界案例（判定规则）

1. **证据较弱但仍合法**：用户要求"找支持尿素水解路径最不利反例的证据"——触发，但必须把**反对证据**与支持证据并列输出，不能只报支持面。
2. **引用已损坏**：给出 DOI 存在但元数据与声称不符（如声称 2015 年、实际 2020 年）——触发 `doi.verify`，标记 `REPORTED` 与 `INFERRED`，返回一致性差异。
3. **检索空结果**：检索式命中 0 条——返回 `PARTIAL`（非 FAILED），明确检索盲区与数据库覆盖偏差，不编造"相近"文献。
4. **离线环境**：网络不可用——自动降级到离线 fixture 或明确 BLOCKED（`MLS-E402`），并给出可用的离线能力，绝不伪造实时检索结果。

## 3. 能力边界

- **本 Skill 做**：检索、DOI/元数据核验、去重、分层与证据质量初筛、引用导出、来源登记、可复现性记录。
- **本 Skill 不做**：替代控制器做决策；生成不存在的引用；把检索排名当证据强度；把摘要当最终事实；执行真实实验/现场/危险操作；调用其他专业 Skill（协作需通过 Router）。
- **认识论纪律**：所有重要陈述必须带 `OBSERVED / REPORTED / CALCULATED / INFERRED / HYPOTHESIS / RECOMMENDATION` 标签；不得把 INFERRED/HYPOTHESIS/RECOMMENDATION 写成 OBSERVED。
- **尺度纪律**：区分实验室柱试、米级试验、现场案例、数值模拟与综述结论；尿素水解须关注铵态氮与质量守恒；非尿素路径不得套用尿素模型。

## 4. 输入（统一契约）

所有 action 共用统一输入信封，至少包含：

`task_id`、`project_id`、`request`、`action`、`contract_version`、`context`、
`constraints`、`evidence_refs`、`data_refs`、`upstream_outputs`、
`requested_output_format`、`risk_level`、`human_approval_state`、
`skill_version`、`controller_version`、`timestamp`、`actor`、`dry_run`。

最低输入条件（不满足则返回 `BLOCKED` 并逐字段说明缺失原因与获取方式）：

| 字段 | 为什么关键 | 如何获得 |
|---|---|---|
| `request` | 任务陈述，决定检索式与分层目标 | Mission Lock 任务合同 / 控制器注入 |
| `task_id` | 审计锚点、预算记账、追溯链 | Task Decomposer 分配 |
| `project_id` | 决定 trace 日志与复现档案归属 | 项目注册 / 控制器注入 |
| `action` | 唯一执行入口 | 控制器 / Router 指定 |
| `skill_version` | 版本兼容判定（主版本/次版本） | SKILL.md frontmatter 声明 |
| `timestamp` | 复现性记录与时间窗 | 控制器调用时注入 |

## 5. 流程（统一步骤）

1. **装载**：读输入信封，校验 `contract_version` 主版本与 `skill_version`。
2. **契约校验**：按 `schemas/input.schema.json` 校验；失败→`MLS-E101`/`MLS-E102`（含字段获取指引）。
3. **权限与审批**：`search.run` 网络检索需 `human_approval_state.granted=true`；否则 `HUMAN_APPROVAL_REQUIRED`。`dry_run` 时跳过网络与写入。
4. **执行 action**：
   - `search.run` / `search.repeat`：构造检索式（检索式、数据库、时间范围、语言、纳入排除标准、去重规则、检索日期）→ 调适配器（超时/重试/错误分类/离线降级）→ 去重 → 分层初筛 → 元数据核验。
   - `doi.verify`：逐条核验 DOI 存在性与元数据一致性；伪造/不存在的→`suspected_forged`/`not_found`。
   - `dedup.merge`：按 DOI / 标题规范化 / 同标题-年份-期刊三规则去重。
   - `triage.screen`：按证据分层规则打分（TIER1/2/3/REJECT），输出质量/可比性/偏倚/全文可得性。
   - `cite.export`：导出 BibTeX/CSL-JSON/CSV/RIS（自研生成器，无第三方依赖）。
   - `sources.register`：登记来源与检索式档案（追加式，不覆盖）。
   - `validate.self`：运行内置自检（认识论标签、输出 schema、trace 完整性）。
5. **自检与输出**：组装统一输出信封；`self_check_passed` 与 `output_schema_valid` 必须为 true；结果写入 trace 日志（若可写）。
6. **返回**：统一输出信封（status/summary/findings/assumptions/evidence_used/uncertainty/risks/artifacts/requested_next_skills/validation/provenance/errors + action 专属字段）。

## 6. 输出（统一契约）

`status ∈ {SUCCESS, PARTIAL, BLOCKED, FAILED, NEED_ADDITIONAL_SKILL, HUMAN_APPROVAL_REQUIRED}`。

`findings` 每条须带认识论标签 `label`；`scope` 注明证据尺度
（`lab_column | meter_scale | field | simulation | review | meta-analysis | standard | patent | dataset`）。

action 专属输出：`search`、`doi_verifications`、`dedup`、`triage`、`exports`、`selfcheck`。

## 7. 停止条件

- 全部 action 完成且自检通过 → 正常返回。
- `status=BLOCKED`：缺失关键输入（附逐字段指引）或 `contract_version` 主版本不符（`MLS-E801`）。
- `status=FAILED`：工具崩溃 / 证据不可核验且无离线降级 / 自检失败。
- `status=HUMAN_APPROVAL_REQUIRED`：需要人工审批门未获批。
- `status=NEED_ADDITIONAL_SKILL`：任务超出本 Skill 能力（工艺决策、实验执行、状态管理等），列出所需 Skill 与所需输入。

## 8. 工具权限

| 工具/动作 | 网络 | 写盘 | 审批门 |
|---|---|---|---|
| `search.run`（真实检索） | ✅ | trace 日志 | ✅ 人工审批 |
| `search.repeat` | ✅（可选） | trace 日志 | — |
| `doi.verify`（实时 API） | ✅ | — | — |
| `doi.verify`（离线规则） | ❌ | — | — |
| `dedup.merge` | ❌ | — | — |
| `triage.screen` | ❌ | — | — |
| `cite.export` | ❌ | 仅显式 `out_file` | — |
| `sources.register` | ❌ | 追加式 | ✅ 人工审批 |

## 9. 错误码

所有错误码格式 `MLS-E###`，人类可读且控制器可机器解析（code 字段）。

### E1xx 输入契约
| 码 | 含义 | 人类消息要点 |
|---|---|---|
| MLS-E101 | 输入未通过 input.schema.json | 列出 violations 与字段路径 |
| MLS-E102 | 缺失必需字段 | 逐字段给出缺失原因与获取方式 |
| MLS-E103 | `action` 非法 | 枚举合法 action |
| MLS-E104 | 版本/契约不匹配（`contract_version` 主版本） | 主版本不符 |
| MLS-E105 | 时间戳格式非法 | 需 ISO-8601 |

### E2xx 证据/引用
| 码 | 含义 | 人类消息要点 |
|---|---|---|
| MLS-E201 | DOI 不可解析/不存在 | 说明核验失败原因 |
| MLS-E202 | 元数据一致性不匹配 | 给出声称值与实际值差异 |
| MLS-E203 | 疑似伪造引用 | 说明为何判定伪造，不采信 |
| MLS-E204 | 单位不一致/数值非法 | 检出空值、非有限值、范围或维度错误 |

### E3xx 数据/存储完整性
| 码 | 含义 | 人类消息要点 |
|---|---|---|
| MLS-E301 | trace 日志损坏/不可写 | 说明恢复建议，不静默丢弃 |

### E4xx 工具/环境
| 码 | 含义 | 人类消息要点 |
|---|---|---|
| MLS-E401 | 检索适配器不可用（全部不可用） | 说明降级路径 |
| MLS-E402 | 网络不可用且无离线降级 | 说明可用离线能力 |
| MLS-E403 | 适配器超时/重试耗尽 | 记录次数与耗时 |
| MLS-E404 | 数据库返回错误/429 | 建议冷却重试 |

### E5xx 权限/审批
| 码 | 含义 | 人类消息要点 |
|---|---|---|
| MLS-E501 | 未授权网络检索 | 需 human_approval_state.granted=true |
| MLS-E502 | 未授权写盘/来源登记 | 需审批门 |
| MLS-E503 | 角色无权执行 | 枚举允许角色 |

### E6xx 下游能力缺失
| 码 | 含义 | 人类消息要点 |
|---|---|---|
| MLS-E601 | 需要其他 Skill | 列出所需 Skill、输入与理由 |

### E7xx 输出/自检
| 码 | 含义 | 人类消息要点 |
|---|---|---|
| MLS-E701 | 输出未通过 output.schema.json | 列出自检失败项 |
| MLS-E702 | 认识论标签越级 | 说明哪条陈述标签过强 |
| MLS-E703 | 证据尺度误标 | 实验室/现场/模拟混淆 |

### E8xx 版本兼容
| 码 | 含义 | 人类消息要点 |
|---|---|---|
| MLS-E801 | 旧版本输出无迁移策略 | 明确拒绝并给出升级路径 |
| MLS-E802 | 输出迁移完成/可映射 | 说明迁移规则 |

错误对象结构：`{code, message, detail}`，detail 可为对象。

## 10. 最小性能指标（evals/metrics.py 实测）

| 指标 | 测量方法 | 最低阈值 |
|---|---|---|
| M1 结构化输出通过率 | 每个 CLI 输出过 output.schema.json | ≥0.95 |
| M2 工具真实调用率 | 变更 action 确实写 trace / 命中工具分支 | =1.0 |
| M3 引用/数据可追溯率 | 核验通过或离线规则判定的记录 / 总记录 | ≥0.9 |
| M4 缺失输入识别率 | K 个必需字段逐一缺失→BLOCKED 且命名字段 | =1.0 |
| M5 对抗用例拦截率 | 伪造引用/未知 action/非法版本/路径穿越→拦截 | =1.0 |
| M6 重复运行一致性 | 相同检索式+固定时钟→相同 repro_id 与结果 | =1.0 |
| M7 平均失败恢复时间 | 触发错误→返回 FAILED/BLOCKED 信封的毫秒 | ≤5000ms |

## 11. 版本策略

- **破坏性 schema 变更**（删字段/改必填/改语义）→ 主版本 +1，旧版本输出必须显式迁移（`MLS-E802`）或拒绝（`MLS-E801`）。
- **新增可选字段** → 次版本 +1（向后兼容）。
- **实现修复不改契约** → 修订版本 +1。
- 旧主版本输出：绝不静默重释；必须有迁移映射或明确拒绝。

## 12. 离线与降级

- 支持 `--offline`：强制走离线 fixture（`tools/fixtures/`），保证 CI 不依赖网络。
- 自动降级：适配器全部失败→尝试离线 fixture→仍不可用则 `MLS-E402`（明确 BLOCKED，不伪造实时检索）。
- `doi.verify` 离线模式：按 DOI 结构规则判定 `suspected_forged` 或 `not_checked`，不声称"已核验存在"。
- 所有外部调用有超时（默认 15s）、重试（2 次）、错误分类（网络/HTTP/超时/解析）与日志。

## 13. 领域纪律（MICP 专业）

- 涉及 MICP 时区分：生物过程、化学过程、矿物相、多孔介质、工程性能与环境影响。
- 尿素水解路径：关注**铵态氮副产物**与**质量守恒**。
- 非尿素路径：不套用尿素模型（代谢途径、pH 调控、诱导条件不同）。
- 检索排名≠证据强度；引用可核验且来源链完整。
- 综述用于导航，不替代原始证据。

## 14. 复现与审计

- 每次 `search.run`/`search.repeat` 生成 `repro_id`（检索式规范化指纹的 SHA-256 前 16 位），写入 `provenance` 与 trace 日志。
- 相同检索式 + 固定时钟 → 相同 repro_id（指标 M6）。
- trace 日志记录：检索式、数据库、时间范围、语言、纳入排除标准、去重规则、检索日期、结果记录与核验状态。
