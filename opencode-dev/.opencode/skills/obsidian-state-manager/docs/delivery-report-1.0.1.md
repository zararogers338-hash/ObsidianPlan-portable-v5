# obsidian-state-manager 交付报告

**版本**: 1.0.1 · **日期**: 2026-08-06 · **状态**: 已通过验收（66 测试 + 8 评测 + 7 指标）

---

## 1. 仓库与标准识别结果

**仓库定位**: 本任务的"当前仓库"识别为 `Desktop/opencode-src/opencode-dev`（OpenCode dev 源码树，bun workspace，非 git 仓库）。这是 OBSIDIAN-PLAN.md 所述改造的 fork 源。桌面 `.claude/skills/` 不存在——并行会话 01/02/03 同样在定位该仓库，但均未落地任何文件（经转录核实）。

**Skill 标准识别（OBSERVED）**:
- OpenCode **原生加载器契约**（`packages/opencode/src/skill/index.ts`）:
  - 扫描模式 `{skill,skills}/**/SKILL.md`（配置目录下）与 `.claude/skills/`、`.agents/skills/`（全局/项目）
  - 前置元数据要求：`name`（必填，string）+ `description`（可选，string）
  - 通过 `opencode.json` 的 `skills.paths` 可指向任意目录
- 仓库内现有 Skill 样例：`packages/opencode/test/fixture/skills/agents-sdk/SKILL.md`（frontmatter + body 结构）

**结论**: 仓库**没有** Skill 工程包标准（SKILL.md 之外的 schema/tools/tests/evals 结构）。因此采用提示词 §二.4 的回退标准：以 OpenCode 原生加载器契约为兼容层（SKILL.md frontmatter 完全合规），工程包结构（skill.yaml/schemas/tools/tests/evals/examples/references）为本仓库首次落地的**项目自定义约定**，已在 README.md 明确标注。

**运行时**: Python 3.13.9 + jsonschema 4.25.0 + pytest 8.4.2；`tools/` 纯标准库实现，离线可用（jsonschema 缺失时自动降级为内建校验器）。

## 2. 新增/修改文件清单（`skills/obsidian-state-manager/`）

| 文件 | 用途 |
|---|---|
| `SKILL.md` | OpenCode 加载契约 + 角色/触发/边界/流程/错误码/停止规则（frontmatter 合规） |
| `skill.yaml` | 机器可读元数据：版本、依赖、入口、权限、兼容性 |
| `README.md` | 维护者文档：安装、调用、示例、限制、故障排除、版本策略 |
| `CHANGELOG.md` | 1.0.0 初始 + 1.0.1 修复记录 |
| `schemas/input.schema.json` | 严格输入契约（contract_version 1.0） |
| `schemas/output.schema.json` | 严格输出契约（统一信封，成功/失败同构） |
| `prompts/system.md` | 最小系统提示词（身份/边界/认识论/停止规则，无领域知识硬编码） |
| `tools/state_manager.py` | CLI 入口（stdin JSON → stdout JSON，store 可注入） |
| `tools/osm/{errors,models,transition,store,recovery,rollback,watcher,validate,service}.py` | 领域引擎 |
| `tests/{conftest,test_unit,test_integration,test_failure,test_bootstrap}.py` | 66 项测试 |
| `evals/{cases.yaml,run.py,metrics.py}` | 8 评测用例 + 7 指标 + 报告生成 |
| `examples/{01-init,02-lifecycle,03-recover}.json` + `run-examples.sh` | 3 个可运行示例 |
| `references/sources.md` | 实现与领域依据（含 OBSERVED 标注） |
| `.gitignore` | 排除 __pycache__/.pytest_cache |

## 3. 输入/输出契约（spec §六）

- **输入必填**: `contract_version`(1.x)、`task_id`、`project_id`、`request`、`action`、`skill_version`、`timestamp`
- **输入可选**: `context`、`constraints`、`evidence_refs`、`data_refs`、`upstream_outputs`、`requested_output_format`、`risk_level`、`human_approval_state`、`actor`(默认 skill)、`expected_revision`、`dry_run`、`auto_downgrade`、各 action 专属载荷
- **输出固定字段**: `status`、`summary`、`findings`、`assumptions`、`evidence_used`、`uncertainty`、`risks`、`artifacts`、`requested_next_skills`、`state`、`validation`、`provenance`、`errors`（成功/失败同构）
- **status 枚举**: SUCCESS / PARTIAL / BLOCKED / FAILED / NEED_ADDITIONAL_SKILL / HUMAN_APPROVAL_REQUIRED
- **认识论标签**: 所有 findings/risks 强制 OBSERVED/REPORTED/CALCULATED/INFERRED/HYPOTHESIS/RECOMMENDATION（schema 约束）

## 4. 所造工具及其用途（spec §五）

| 工具 | 能力 |
|---|---|
| `transition.py` | 11 状态转换表 + 守卫求值（证据数/假设状态/检查点/评审/批准/争议阻断），非法边 OSM-E305 硬拦，角色白名单 OSM-E501，重复边=构建错误 |
| `store.py` | 事件溯源：hash 链 JSONL + 快照 + 原子追加（temp+os.replace）+ 乐观并发（OSM-E104）+ 完整性验证（OSM-E301） |
| `recovery.py` | 崩溃/截断恢复分类（CLEAN/STALE/CORRUPT）+ 断点续跑（内容哈希去重，已完成工作不重跑，验收 §九.3） |
| `rollback.py` | 补偿式回滚（改写历史被禁止）+ 快照差异比较器（用于审计"批准了什么"） |
| `watcher.py` | 过期证据/矛盾假设监听：返回降级提案，可自动执行（auto_downgrade） |
| `validate.py` | schema 校验适配器（jsonschema + 内建降级 + 默认值填充） |
| `service.py` | 外观层：校验→守卫→追加→快照→自检→输出校验，统一错误映射 |

## 5. 真实执行过的测试与结果

| 套件 | 结果 |
|---|---|
| `pytest tests/` 单测（状态机/哈希链/守卫/差异） | **66 通过** |
| `pytest tests/` 集成（CLI 全流程/回滚/矛盾降级/dry-run） | 66 通过 |
| `pytest tests/` 失败（缺失字段/未知动作/大载荷/越权） | 66 通过 |
| `pytest tests/test_bootstrap.py` 自举 4 场景 | 4 通过 |
| `evals/run.py` 8 评测用例 | 8/8 通过 |
| `evals/run.py` 7 指标 | 全部达标 |
| `examples/run-examples.sh` | 3 示例 ✓ |

**指标实测**（`evals/results/latest.json`）:
- 结构化输出通过率 1.000（阈值 0.95）
- 工具真实调用率 1.000（阈值 1.0）
- 引用可追溯率 1.000（阈值 0.9）
- 缺失输入识别率 1.000（阈值 1.0）
- 对抗用例拦截率 1.000（阈值 1.0）
- 重复运行一致性 1.000（阈值 1.0，固定时钟下）
- 平均失败恢复时间 243ms（阈值 5000ms）

## 6. 自举测试中发现的问题及修复

**对抗评审发现（CONFIRMED）**:
1. **信任边界漏洞（严重）**: `state.transition`/`state.rollback` 的 `requires_approval` 守卫信任调用方自报 `human_approval_state.granted`，攻击者自报 `role="human"` + 伪造批准即可把已 VALIDATED 流推到不可逆 DEPLOYABLE。**修复**: 改为要求事件日志中存在先于当前 head、scope 覆盖目标状态的 `APPROVAL_GRANTED` 事件；无链上批准 → OSM-E502。验证：攻击复现从"SUCCESS/DEPLOYABLE"变为"HUMAN_APPROVAL_REQUIRED/保持 VALIDATED"。
2. **dry_run 绕过乐观并发**: dry_run 路径不校验 `expected_revision`。**修复**: 双路径同校验，OSM-E104。

**自举测试中发现的测试自身缺陷（已修正）**: eval 用例共享 store 导致的串扰、快照比较含时间戳导致的 M6 误报、`@head` 占位符处理等——均非产品缺陷。

## 7. 尚未关闭的风险与限制

1. **并发写文件锁缺失**: 多进程同时 append 靠 OSM-E104 安全失败，但无文件锁；Windows 下极端并发可能产生竞争。已列入 CHANGELOG [Unreleased]。
2. **actor.role 仍是自报身份**: 引擎按 role 白名单执行（skill 不能驱动 DEPLOYABLE），但"skill 进程"与"human 进程"的区分依赖外层 Obsidian Controller 的角色隔离，本 Skill 无法独立证明调用方物理身份。信任边界已收紧到链上批准，但物理身份验证需 Controller 层补强。
3. **skill.yaml 非 OpenCode 原生**: 工程包扩展格式为本仓库自定义，需 01/02/03 号 Skill 与 Router 采用相同约定。
4. **与 01-03 Skill 的流间链接未落地**: mission-lock 产出 → SCOPED 守卫的自动接线是未来工作。
5. **approved scope 语义**: "all" 通配批准会绕过逐状态批准；默认行为是逐状态 scope，使用者需明确使用 "all"。

## 8. 调用示例

```bash
# 初始化研究流
echo '{"contract_version":"1.0","task_id":"t1","project_id":"micp-urease",
  "request":"建立尿素水解 MICP 研究流","action":"project.init",
  "skill_version":"1.0.1","timestamp":"2026-08-06T00:00:00Z"}' \
  | python tools/state_manager.py --store ./state_store

# 推进状态（控制器角色）
echo '{"contract_version":"1.0","task_id":"t2","project_id":"micp-urease",
  "request":"锁定范围","action":"state.transition","to_state":"SCOPED",
  "actor":{"role":"controller"},"skill_version":"1.0.1",
  "timestamp":"2026-08-06T00:00:00Z"}' \
  | python tools/state_manager.py --store ./state_store

# 获取状态
echo '{"contract_version":"1.0","task_id":"t3","project_id":"micp-urease",
  "request":"当前状态","action":"state.get",
  "skill_version":"1.0.1","timestamp":"2026-08-06T00:00:00Z"}' \
  | python tools/state_manager.py --store ./state_store
```

被 Obsidian Router 调用时：Router 以 stdin 传入上述 JSON，解析 stdout 的 status 字段路由。

## 9. 版本号与后续演进建议

**版本策略（spec §十一，已实现）**: schema 破坏性变化 → 主版本；新增可选字段 → 次版本；实现修复不改契约 → 修订版本。当前 1.0.1。旧版本输出通过 contract_version 检查拒绝（OSM-E801），迁移策略在 README §版本策略。

**演进建议**:
1. 文件锁（Windows 用 msvcrt.locking / 跨平台 fcntl 抽象）关闭并发写窗口
2. 与 01-03 Skill 建流间链接契约（mission-lock → SCOPED，task-decomposer → checkpoint）
3. 引入流间引用解析（evidence_refs 指向其他流的产物时做交叉验证）
4. 快照压缩（事件日志超过阈值时折叠旧快照）
5. 与 Obsidian Router 的调用协议示例落地（本报告 §8 的 Router 段）
