# 示例 2 — 数据清单与污染检测（manifest + check-pollution）

先生成项目清单（含数据分层与哈希），再在手工覆盖产物后运行污染检测。

```json
{
  "task_id": "ex-02a",
  "project_id": "panshi-ucs-demo",
  "request": "生成 data/raw 与 data/processed 下所有文件的清单与哈希",
  "action": "manifest",
  "root": "C:/projects/ucs-experiment",
  "skill_version": "1.0.0",
  "controller_version": "obsidian-ctl-0.1.0",
  "timestamp": "2026-08-07T10:05:00Z",
  "risk_level": "low",
  "human_approval_state": "not_required"
}
```

预期：`manifest.entry_count`、每文件的 `layer`（raw/processed/…）、`sha256`、`raw_write_protection_ok`。

手工覆盖 `data/processed/summary.csv` 后：

```json
{
  "task_id": "ex-02b",
  "project_id": "panshi-ucs-demo",
  "request": "检测产物污染：手工覆盖后应报警",
  "action": "check-pollution",
  "root": "C:/projects/ucs-experiment",
  "skill_version": "1.0.0",
  "controller_version": "obsidian-ctl-0.1.0",
  "timestamp": "2026-08-07T10:10:00Z",
  "risk_level": "low",
  "human_approval_state": "not_required"
}
```

预期：
- `verdict: "pollution_detected"`
- findings 含 `kind: "manifest_mismatch"`，指明 `data/processed/summary.csv` 的登记哈希与当前哈希不一致
- provenance 链被篡改（如追加伪造行）→ findings 含 `kind: "provenance_tamper"`
