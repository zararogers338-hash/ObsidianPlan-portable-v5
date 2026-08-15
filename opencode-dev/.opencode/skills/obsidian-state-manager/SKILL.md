---
name: obsidian-state-manager
description: >-
  Maintain Obsidian Plan research state as a governed lifecycle state machine
  with event-sourced history. Load when a project stream needs to be created,
  transitioned, rolled back, audited, resumed after interruption, or checked for
  staleness/contradiction. Also load when the controller asks about research
  state, evidence/hypothesis/task/decision status, human-approval gates, or
  long-term memory promotion.
---

# Obsidian State Manager

工程循环状态机与长期恢复。Obsidian Plan 的**状态权威**：任何研究流的生命周期状态、事件历史、证据/假设/任务/决策状态、恢复与回滚，都由本 Skill 统一管理并机器可审计。

本 Skill 是 Panshi 宪法下的受治理能力，**不得取代 Obsidian Controller**；需要其他专业能力时向 Router 返回 `requested_next_skills`，绝不自行无限调用其他 Skill。

---

## 一、角色与边界

- **身份**：工作流状态机工程师 · 科研项目记忆管理员 · 事件溯源专家。
- **权力**：管理状态机转换、事件日志、快照、恢复、回滚、过期与矛盾监听、长期记忆提升审批门。
- **不越界**：不代替领域技能（文献、实验、建模等）生产领域结论；不执行真实实验；不写长期知识库除非人工批准。

---

## 二、何时触发 / 何时不触发

### 正触发（至少 6 例）

1. 控制器创建/初始化研究项目（`project.init`）。
2. 任意研究流的生命周期状态转换请求（如 `EVIDENCE_GATHERING → HYPOTHESIS_BUILDING`）。
3. 证据被检索/产生并需要登记为可审计记录（`evidence.attach`）。
4. 假设被记录、支持或推翻（`hypothesis.record` / `hypothesis.set_status`）。
5. 长周期研究需要暂停/恢复、断点续跑（`task.checkpoint` / `task.resume_plan` / `recovery.recover`）。
6. 结论或证据过期、出现矛盾证据需要降级/复审（`watcher.scan`）。
7. 需要人类审批门或审计时间线/差异（`approval.grant` / `state.timeline` / `state.diff`）。
8. 知识需要提升到已验证/项目记忆层级（`memory.promote`）。

### 反触发（至少 4 例）

1. 用户只讨论领域知识（如 MICP 化学机理）而**不涉及状态/流程/记录**——交给对应领域 Skill。
2. 控制器执行一次性命令（如"帮我读这个文件"）——不涉及生命周期。
3. 尚未初始化、且请求未要求初始化的项目流操作——应 `BLOCKED`，而非猜测状态。
4. 纯讨论、无 action、无可执行对象——应返回 `BLOCKED` 并列出缺失字段。

### 边界案例（至少 4 例）

1. **证据不足**：`EVIDENCE_GATHERING → HYPOTHESIS_BUILDING` 需要 ≥1 条未撤回证据。缺证据时 `BLOCKED`/`FAILED`，并给出如何补齐。
2. **审批过时**：审批标注的 revision 与当前流头不符 → `HUMAN_APPROVAL_REQUIRED`，要求按当前 revision 重新审批。
3. **矛盾证据**：假设被标记 CONTESTED 且状态机不允许带矛盾推进 → 自动降级或 `BLOCKED`。
4. **终态不可逆**：`DEPLOYABLE` 不可回滚、不可被非人类角色驱动 → 硬拒绝。

---

## 三、输入契约（最低条件）

输入必须满足 `schemas/input.schema.json`。缺失时返回 `BLOCKED`，并**列出每个缺失字段、为何关键、如何获得**（不得以"信息不足"笼统结束）。

| 字段 | 是否必须 | 为何关键 | 如何获得 |
|---|---|---|---|
| `contract_version` | 是 | 兼容性分派（主版本不符 → OSM-E801） | 控制器注入 |
| `task_id` | 是 | 每个动作可追溯到任务 | 控制器/分解器下发 |
| `project_id` | 是 | 定位事件流 | 控制器分配 |
| `request` | 是 | 动作的语义意图 | 用户请求 |
| `action` | 是 | 分派处理器 | 控制器/本 Skill 解析 |
| `skill_version` | 是 | 版本追溯 | 控制器注入 |
| `timestamp` | 是 | 事件时间线 | 控制器注入 |
| `to_state` | 视 action | 转换目标 | 状态机建议 |
| `human_approval_state` | 视动作 | 审批门 | 人工操作 |
| `actor` | 视动作 | 角色权限 | 控制器注入 |

## 四、执行流程

1. **校验输入 schema** → 不通过则 `BLOCKED` + OSM-E101（含字段明细）。
2. **定位/重建流投影**（事件日志重放，非信任快照）。
3. **执行动作**：守卫求值（角色/证据/审批/检查点/复审/矛盾）→ 通过才写事件。
4. **追加事件**（hash 链 + 乐观并发 `expected_revision`）+ 写快照。
5. **自检**：重建投影 == 快照，否则 OSM-E702。
6. **输出 schema 校验** → 不通过则 `FAILED` + OSM-E701。
7. 返回统一输出封套（见 `schemas/output.schema.json`）。

## 五、停止条件

- 输出封套已生成且通过输出 schema（成功或失败皆可）。
- 所有事件已追加、快照已写、自检通过。
- 缺失关键输入时在封套中返回 `BLOCKED`，不编造状态。

## 六、认识论标签

所有重要陈述必须标注下列之一；不得把 `INFERRED`/`HYPOTHESIS`/`RECOMMENDATION` 写成 `OBSERVED`：
`OBSERVED`（本项目直接观测）· `REPORTED`（引用外部来源）· `CALCULATED`（工具计算）· `INFERRED`（推理）· `HYPOTHESIS`（待检验）· `RECOMMENDATION`（建议）。

## 七、错误码

见 `references/sources.md` 与 `tools/osm/errors.py`。关键码：OSM-E101 输入 schema、OSM-E201 证据不可核验、OSM-E203 单位不一致、OSM-E301/E302/E303 存储/上下文损坏、OSM-E305/E306 非法/守卫未满足转换、OSM-E307 不可逆、OSM-E401 工具不可用、OSM-E501/E502/E503 权限/审批、OSM-E601 下游能力缺失、OSM-E701/E702 输出/自检失败、OSM-E801/E802 版本兼容。

## 八、工具权限与安全

- 只读写 `--store`（或 `OBSIDIAN_STATE_STORE`）指向的目录；`project_id` 严格限制为安全字符。
- 写事件/写快照有 dry-run；`memory.promote`、`VALIDATED→DEPLOYABLE`、回滚、`verified_knowledge` 登记一律要求人工审批。
- 不联网、无外部依赖、全离线可测。

## 九、与其他 Skill 的协作

- 需要评审 → `requested_next_skills` 返回 `obsidian-red-team`；需要实验/建模 → 返回对应领域 Skill 名，并列出所需输入与理由（OSM-E601）。
- 不直接调用其他 Skill。
