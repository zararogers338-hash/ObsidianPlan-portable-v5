# 示例 3 — 版本兼容与 Schema 迁移（compat + migrate）

检查声明版本与有效版本的兼容性，并对旧版本 manifest 执行迁移。

```json
{
  "task_id": "ex-03",
  "project_id": "panshi-ucs-demo",
  "request": "检查 manifest schema 版本兼容性并给出迁移动作",
  "action": "compat",
  "root": "C:/projects/ucs-experiment",
  "schema_versions": {
    "manifest": "2.0.0",
    "provenance": "1.0.0",
    "output": "1.0.0"
  },
  "skill_version": "1.0.0",
  "controller_version": "obsidian-ctl-0.1.0",
  "timestamp": "2026-08-07T10:15:00Z",
  "risk_level": "low",
  "human_approval_state": "not_required"
}
```

预期：
- `manifest 2.0.0` → 主版本不兼容，`compatible: false`（需显式迁移，`MRV-E801` 语义）
- `provenance 1.0.0` / `output 1.0.0` → 兼容
- 迁移动作（`migrate`）对主版本缺口拒绝且不伪造应用；同一主版本内仅在声明低于有效版本时给出动作
- **Schema 版本策略**：破坏性变化 → 主版本 +1；新增兼容字段 → 次版本 +1；兼容修复 → 修订版本 +1
