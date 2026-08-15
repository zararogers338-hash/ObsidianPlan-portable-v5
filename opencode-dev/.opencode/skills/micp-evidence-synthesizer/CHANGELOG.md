# Changelog

## 1.0.0 — 2026-08-06 (initial release)

### Added

- **SKILL.md**：角色、6 正触发 / 4 反触发 / 4 边界案例、最低输入与缺失字段获取指引、能力边界、执行流程（12 步）、停止条件、错误码表、工具权限、版本兼容策略、性能指标。
- **skill.yaml**：机器可读 manifest（Obsidian Plan 项目约定）。
- **schemas/**：`input.schema.json`（统一信封 + PICO + evidence_cards 契约）、`output.schema.json`（统一信封 + `synthesis` 完整定义）。
- **prompts/system.md**：最小系统提示词（身份/流程/边界/认识论/停止）。
- **tools/mes_cli.py**：stdin→stdout CLI，`--validate-schema` 子命令，离线、零写。
- **tools/mes/**：10 个纯 Python 模块（见 README §4），全部类型标注 + 数值守卫 + 内建 schema 回退校验。
- **tests/**：pytest 四层 —— `test_unit.py`（20+ 用例）、`test_integration.py`（管道/契约/CLI/确定性）、`test_failure.py`（缺失/对抗/损坏）、`test_regression.py`（单位/效应/meta/敏感性/认识论纪律）。
- **evals/**：`cases.yaml`（10 用例，覆盖正常/缺失/冲突/对抗/边界）、`metrics.py`（7 指标公式与阈值）、`run.py`（离线评测器，产出 `results/latest.json`）。
- **examples/**：3 个可运行示例（CaCO3 相似含量、UCS 尺度不可合并、高偏倚敏感性）。
- **references/sources.md**：领域与方法学依据（见该文件）。

### Governance

- Panshi 宪法受治理：不取代 Controller/Router；不自行无限调用其他 Skill（星型拓扑）；`risk_level=high/critical` 强制 `obsidian-red-team` + `obsidian-decision-gate` 审计链；现场部署/真实生物实验/危险化学品/长期知识写入 → 人工批准门（`OES-E107`）。
- 认识论标签纪律：卡片 `claims` 不自动升级为 `OBSERVED`；OBSERVED/REPORTED 必须带 `source`；过度概括自检（`OES-E108`）。

### Known limitations (recorded)

- GRADE 域评分为启发式规则，非完整 GRADEpro 工具。
- 卡方 p 值用 Wilson-Hilferty 正态近似。
- 内建 `jsonschema` 回退校验器只覆盖仓库 schema 用到的 draft-07 子集。

### Performance baseline (evals/run.py)

- 结构化输出通过率、工具真实调用率、可追溯率、缺失识别率、对抗拦截率、确定性、失败恢复轮次 —— 首轮基线见 `evals/results/latest.json`。

---

## Versioning policy

- Breaking contract change → **major** bump.
- New optional field (backward-compatible) → **minor** bump.
- Implementation fix without contract change → **patch** bump.
- Old-major outputs: migrate or reject with `OES-E801`; never silently reinterpret.
