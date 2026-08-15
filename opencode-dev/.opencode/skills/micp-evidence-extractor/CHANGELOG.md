# Changelog — micp-evidence-extractor

## 1.0.0 (2026-08-07)

首个交付版本。Skill 完整实现并集成到 opencode-dev 仓库。

### 新增
- **契约**：`schemas/input.schema.json`、`schemas/output.schema.json`（12 字段统一信封）、
  `schemas/evidence-card.schema.json`（五元组 + 溯源 + 获取方式 + 认识论标签）。
- **工具集**（`tools/mee/`，纯 stdlib Python）：
  - `adapters`：PDF 内置流解析（zlib）、HTML/Markdown/CSV/JSON 解析；损坏 PDF → MEE-E303。
  - `doi`：离线结构校验 + 伪造启发式；在线元数据一致性（可注入 fetcher）。
  - `units`：单位规范化（强度/渗透/摩尔/长度/时间/密度/电导/流量/压力/能量），
    上下文消歧 `M`（摩尔 vs 米）、`mM`（毫摩尔 vs 毫米）；OD600/CFU/细胞浓度/
    活细胞比/脲酶活性防混淆（`classify_role` + `detect_distinct_conflation`）。
  - `quantity`：五元组构造 + 占位守卫（NOT_REPORTED/AMBIGUOUS 值不参与计算）。
  - `extract`：表逐行逐列候选（含表头时间点）、正文条件/结果候选、图数字化候选。
  - `card_check`：卡片 schema + 不变量（组引用、占位、估读误差、认识论、防混淆）。
  - `isolation`：组/时间点隔离（GROUP_UNRESOLVED/TIME_UNRESOLVED/GROUP_SMEAR/SCALE_MIX）。
  - `conflict`：重复值（DUPLICATE_VALUE）+ 内部矛盾（CONTRADICTION）+
    方法/结果冲突（METHODS_RESULTS_CONFLICT）。
  - `exporter`：JSON / YAML（stdlib 手写发射器）/ CSV（逐 quantity 一行）。
  - `digitizer`：估读误差计算接口。
- **错误码**：MEE-E101…E900（input/units/provenance/adapters/tooling/policy/
  capability/self-check/compat/internal）。
- **测试**：51 个 pytest 全绿，覆盖十项强制场景 + 单元 + 回归。
- **评测**：11 用例 × 7 指标全绿（结构化输出/工具调用/可追溯/缺失识别/对抗拦截/复现一致/恢复时间）。
- **Router 注册**：`skill.yaml` capabilities 含裸 token `evidence`，满足
  `obsidian-skill-router` `validateManifest` 全部约束。

### 修复（开发期）
- 单位字典中 `M`（摩尔）与 `m`（米）冲突 → 上下文消歧。
- `mM`（毫摩尔）与 `mm`（毫米）小写折叠冲突 → 保留大小写的 `_fold`。
- 表头时间点（Day 7/14）绑定错位 → 候选携带 `column_index`。
- 图数字化被单位缺失降级为 AMBIGUOUS → DIGITIZED_FROM_FIGURE 显式保留。
- 非 MICP 文档 BLOCKED 时缺 `evidence_cards` 字段 → 恒为数组。
- `EpistemicTag.NOT_REPORTED` 不存在 → 占位符认识论默认 REPORTED。

### 已知限制
- PDF 文本恢复是流级最佳努力：表格布局保留有限（表格检测为启发式）。
- 图数字化需要调用方在 figure note 中提供标定记录（read/axis_px/axis_range）；
  纯 stdlib 不做光栅处理。
- DOI 在线核验需注入 fetcher；离线仅结构校验，绝不声称已在线验证。
- 时间点/组绑定依赖表头与首列的结构化解析；自由格式正文的推断保守。
