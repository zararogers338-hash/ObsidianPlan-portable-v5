# 示例：从一篇多实验组 MICP 论文提取 Evidence Card

本示例展示 `service` 管线的真实调用与输出。输入是一个结构化 MICP 文档
（两实验组、两个时间点、OD600 与脲酶活性分离、含图表）。运行：

```bash
python tools/mee/cli.py service < examples/01-multi-group-paper.json
```

输出为 12 字段统一信封 + `evidence_cards`（每表一卡 + 正文一卡）+ `isolation_report`
+ `doi_verifications` + `duplicates_contradictions` + `card_validation` + `extractor_stats`。

## 输入要点

- 表 t1「UCS results」：Control/MICP 两组 × Day 7/Day 14 两个时间点 →
  **每个值绑定唯一的 group_id + timepoint_id，绝不混组**。
- 表 t2「Biological characterization」：OD600 与 Urease（mM urea/min/OD）
  两列 → **物理不同的量，绝不互换**，canonical 单位分别为 `OD600` 与
  `mmol_urea/min/OD`。
- methods 正文：urea 0.5 M / CaCl2 0.5 M → 条件候选（`urea_conc`/`calcium_conc`）。
- results 正文：UCS reached 3.2 MPa → 正文结果候选（`REPORTED_TEXT`）。

## 关键输出断言（自举验证）

| 检查 | 期望 |
|---|---|
| `status` | `SUCCESS` |
| `extractor_stats.cards_built` | `3`（t1 + t2 + text） |
| t1 组 | `{Control, MICP}`，时间点 `{Day 7, Day 14}` |
| t1 每个 ucs 量 | `group_id ∈ {g1, g2}`，`timepoint_id ∈ {t1, t2}` |
| t2 `od600[*].normalized_unit` | `OD600` |
| t2 `urease_activity[*].normalized_unit` | `mmol_urea/min/OD` |
| `isolation_report.passed` | `true` |
| `card_validation.passed` | `true` |
| `doi_verifications[0].status` | `verifiable_structure`（离线） |
| 输出过 `output.schema.json` 自检 | `validation.self_audit_pass == true` |
