# obsidian-state-manager

**Obsidian State Manager｜工程循环状态机与长期恢复**

维护 Obsidian Plan（黑曜石计划）研究流的生命周期状态、事件溯源历史与长期恢复能力，使长周期 MICP 研究可以暂停、恢复、回滚、审计。

## 标准识别（重要）

本 Skill 处于**既有 OpenCode 工程包内**，采用两层标准：

1. **加载标准（原生）**：仓库 OpenCode 原生加载器在 `packages/opencode/src/skill/index.ts` 扫描 `{skill,skills}/**/SKILL.md`，读取 YAML frontmatter 的 `name` 与 `description`。本 Skill 的 `SKILL.md` 满足该契约，目录放在 `skills/obsidian-state-manager/`。
2. **工程包标准（项目自定义约定）**：提示词要求的 `skill.yaml / schemas / prompts / tools / tests / evals / examples / references / CHANGELOG.md` 是本项目的扩展约定，不干扰原生加载。**这是本仓库首次落地该扩展约定**——前序 Skill（01–03）尚未写入本仓库（见"现状与备注"）。

## 安装与调用

```bash
# 无第三方依赖要求（jsonschema 有则用，无则内置降级校验器）
python tools/state_manager.py --store "$OBSIDIAN_STATE_STORE" < input.json > output.json
```

- **stdin**：一个 JSON 对象，符合 `schemas/input.schema.json`。
- **stdout**：一个 JSON 对象，符合 `schemas/output.schema.json`（成功与失败都满足）。
- **stderr**：仅供诊断；协议数据只走 stdout。
- 存储根：`--store <dir>` 优先，其次环境变量 `OBSIDIAN_STATE_STORE`，再次 `<skill>/state_store/`。

## 能力矩阵

| 动作 | 说明 | 审批门 |
|---|---|---|
| `project.init` / `project.list` | 初始化/列出研究流 | — |
| `state.get` / `state.timeline` / `state.diff` | 读状态 / 人类+机器时间线 / 快照差异 | — |
| `state.transition` | 合法生命周期转换（守卫求值） | `VALIDATED→DEPLOYABLE`、`REJECTED→OPEN` |
| `state.rollback` | 补偿性回滚（不重写历史） | ✅ |
| `evidence.attach` / `evidence.retract` | 登记/撤回证据（附加式，不删除） | `tier=verified_knowledge` |
| `hypothesis.record` / `set_status` | 假设登记/状态变更（含 CONTRADICTION 联动） | — |
| `task.checkpoint` / `resume_plan` | 断点登记 / 恢复计划（内容哈希去重） | — |
| `memory.promote` | 提升到项目/已验证记忆层 | ✅ |
| `review.request` / `review.complete` | 评审请求/记录（供 VALIDATED 守卫） | — |
| `approval.grant` | 记录人工审批事件 | — |
| `watcher.scan` | 过期与矛盾检测（只建议，不擅写） | — |
| `recovery.recover` / `snapshot.verify` | 崩溃恢复分类 / 快照一致性 | — |

所有变更动作都支持 `dry_run`；每次变更都写 hash 链事件日志 + 快照 + 自检。

## 状态机

11 个状态：`OPEN → SCOPED → EVIDENCE_GATHERING → HYPOTHESIS_BUILDING → DESIGNING → AWAITING_DATA → ANALYZING → UNDER_REVIEW → VALIDATED → DEPLOYABLE`，另有 `REJECTED`。守卫包括：证据充分性、假设存在性、检查点、评审结论、审批（含 revision 新鲜度）、矛盾禁止、角色权限。`DEPLOYABLE` 不可逆；`VALIDATED` 可因新证据/过期降级回 `UNDER_REVIEW`。表定义在 `tools/osm/transition.py`（纯数据）。

## 错误码

`OSM-E1xx` 输入契约 · `OSM-E2xx` 证据/单位 · `OSM-E3xx` 存储完整性 · `OSM-E4xx` 工具/环境 · `OSM-E5xx` 权限/审批 · `OSM-E6xx` 下游能力 · `OSM-E7xx` 输出/自检 · `OSM-E8xx` 版本兼容。完整定义见 `tools/osm/errors.py`。

## 测试与评测

```bash
python -m pytest tests/ -q          # 64 项：单元 + 集成 + 失败 + 自举
python evals/run.py --verbose       # 8 个评测用例 + 7 项指标，写入 evals/results/latest.json
```

指标阈值：结构化输出通过率 ≥0.95、工具真实调用率 =1.0、证据可追溯率 ≥0.9、缺失输入识别率 =1.0、对抗拦截率 =1.0、重复运行一致性 =1.0、平均恢复时间 ≤5000ms。

## 版本策略

输入/输出 schema 破坏性变更 → 主版本 +1；新增可选字段 → 次版本 +1；实现修复不改契约 → 修订 +1。旧主版本输出必须显式迁移（`OSM-E802`）或拒绝（`OSM-E801`），绝不静默重释。见 `CHANGELOG.md`。

## 已知限制

- **并发写**：单流并发由 `expected_revision` 乐观锁保护（OSM-E104），但未做写者间文件锁；两进程同时写同一流时后者会以 OSM-E104 失败（安全失败，不会损坏链）。
- **Windows 原子写**：`os.replace` 在同一卷内是原子的；跨卷回退为拷贝+fsync（速度较慢但一致）。
- **时间源**：事件 `recorded_at` 使用 UTC；`OSM_TEST_CLOCK` 可注入固定时钟用于确定性测试。
- **领域知识**：本 Skill 不做 MICP 领域判断；领域结论由对应专业 Skill 生产，本 Skill 仅管理其状态与证据。

## 故障排除

| 症状 | 排查 |
|---|---|
| `OSM-E101` 输入被拒 | 对照 `schemas/input.schema.json`；detail.violations 给出字段路径 |
| `OSM-E304` 项目不存在 | 先 `project.init` |
| `OSM-E301` 日志损坏 | hash 链断裂；**不得手工修补**，从快照/备份重建并记录事件 |
| `OSM-E502` 需要审批 | 设置 `human_approval_state.granted=true` + approver + 当前 revision |
| `OSM-E801` 版本不符 | 升级 payload 到 1.x 或升级 Skill |
| 测试失败 | 用 `OSM_TEST_CLOCK` 固定时钟重跑，排除时间差异 |
