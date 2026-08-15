# Changelog

所有对使用者可见的变更都记录于此。格式基于 Keep a Changelog 思路；版本遵循
SemVer（见 SKILL.md §11 版本策略）。

## [1.0.0] - 2026-08-06

### Added（初版交付）
- **契约**：`SKILL.md`（含触发/反触发/边界案例、错误码体系、停止条件、性能指标、
  版本策略）、`skill.yaml`（Router 注册表可消费）、`schemas/input.schema.json` 与
  `schemas/output.schema.json`（统一输入输出信封 + action 专属字段）。
- **工具套件** `tools/micp_lit/`：
  - `adapters.py`：OpenAlex/Crossref/PubMed 检索适配器（超时/重试/错误分类/离线降级）
    与检索式构造（`BUILD_QUERY`）。
  - `doi.py`：DOI 结构校验、元数据一致性核验、伪造识别（离线规则）。
  - `dedup.py`：三规则去重（DOI/标题规范化/同标题-年份-期刊）。
  - `triage.py`：证据分层（TIER1/2/3/REJECT）+ 质量/可比性/偏倚/全文可得性初筛。
  - `cite.py`：自研 BibTeX/CSL-JSON/CSV/RIS 导出生成器（无第三方依赖）。
  - `errors.py`：`MLS-E1xx`~`MLS-E8xx` 错误码体系。
  - `models.py`：认识论标签、输出状态、证据尺度、来源类型枚举。
  - `validate.py`：schema 校验（jsonschema 优先，内置降级）。
  - `literature_scout.py`：CLI 入口（stdin→stdout，符合统一契约）。
- **测试**：`tests/`（单元/集成/失败/自举）。
- **评测**：`evals/cases.yaml`（12 用例）+ `evals/run.py` + `evals/metrics.py`
  （M1–M7 指标）+ `evals/metrics.md`。
- **示例**：`examples/`（3 个可运行示例）。
- **领域依据**：`references/sources.md`（真实核验的 DOI 样本 + 检索盲区声明）。

### Fixed（自举阶段发现并修复）
- 缺失必需字段改为 dispatch 前 BLOCKED + `MLS-E102`（原先被 schema 校验拦为 E101，
  不满足 M4 指标）。
- 未知 action 在 schema 校验前拦截为 `MLS-E103`。
- Crossref 在线核验：修正 `fetch()` 返回 `{status, message}` 包裹的解包，
  title/year/container 现能正确提取；元数据一致性检测（`suspected_forged`）可用。
- `dedup` 规则优先级修正：同标题 + 同年 + 同刊 → `title_year_journal`；
  仅当无年份/期刊可区分时 → `title_norm`。
- DOI 离线伪造启发式：新增保留注册前缀 `10.9999/`、`10.0000/` 判定。
- `skill.yaml` 对齐 Router 契约：capabilities 含裸 token `literature`/`evidence`，
  `inputs_required` 对齐 router availableInputs（`capabilities 2/2; inputs 7/7`）。

### Notes
- 初版契约 `contract_version 1.0`。破坏性变更 → 主版本 +1；旧主版本输出拒绝
  （`MLS-E801`）或迁移（`MLS-E802`），绝不静默重释。
- 检索覆盖盲区与付费墙限制已在 `references/sources.md` 显式记录。
