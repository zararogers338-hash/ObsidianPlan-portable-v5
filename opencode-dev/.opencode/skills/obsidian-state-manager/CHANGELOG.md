# Changelog

All notable changes to obsidian-state-manager. Versioning follows the skill's
own contract policy (README §版本策略): breaking schema change → major;
optional fields → minor; implementation fix without contract change → patch.

## [1.0.1] - 2026-08-06

### Fixed
- **信任边界漏洞（对抗评审确认）**：`state.transition` / `state.rollback` 的
  `requires_approval` 守卫原先信任调用方自报的 `human_approval_state.granted`，
  攻击者可自报 `actor.role="human"` + 伪造批准，把已 VALIDATED 的流直接推到
  不可逆的 DEPLOYABLE。现改为要求事件日志中存在**先于当前 head、scope 覆盖目标
  状态的 `APPROVAL_GRANTED` 事件**；无链上批准 → OSM-E502，批准先于授予 →
  OSM-E503。新增回归测试（`test_approval_requires_onchain_record`、
  `test_deployable_human_only_and_irreversible` 的 spoof 分支）。
- **dry_run 绕过乐观并发守卫（对抗评审确认）**：dry_run 路径原先不校验
  `expected_revision`，现与真实写入同等校验（OSM-E104）。
- 守卫失败聚合顺序：缺 review + 缺批准时先报 OSM-E306 而非 E502，便于一次性修复全部前置条件。

### Notes
- 测试总数 64 → 66；`evals/` 中 eval-06 与相关用例改为使用链上 `approval.grant`。

## [1.0.0] - 2026-08-06

### Added
- 初始交付：Obsidian State Manager 完整工程包。
- 11 状态研究生命周期状态机 + 守卫求值（`tools/osm/transition.py`）。
- 事件溯源存储：hash 链 JSONL + 快照 + 原子追加 + 乐观并发（`tools/osm/store.py`）。
- 恢复/断点续跑（`tools/osm/recovery.py`）、回滚+差异（`tools/osm/rollback.py`）、
  过期/矛盾监听（`tools/osm/watcher.py`）。
- 统一输入/输出 schema（`schemas/`）、错误码体系 OSM-E1xx~E8xx、认识论标签。
- 单测/集成/失败/自举共 64 项测试（`tests/`），8 个评测用例 + 7 项指标（`evals/`）。
- 3 个可运行示例（`examples/`）、系统提示词（`prompts/system.md`）、维护文档（`README.md`）、来源记录（`references/sources.md`）。

### Notes
- 工程包目录约定为本仓库首次落地（OpenCode 原生加载器契约保持兼容）。
- `OSM_TEST_CLOCK` 环境变量用于确定性测试。

## [Unreleased]
- 并发写文件锁（当前靠 OSM-E104 安全失败）。
- 与 01–03 号 Skill 的流间链接（mission-lock 产出 → SCOPED 守卫）。
