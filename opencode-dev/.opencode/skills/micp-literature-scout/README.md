# micp-literature-scout

**MICP Literature Scout｜文献、标准、专利与工程案例检索**

MICP（微生物诱导碳酸盐沉淀）、EICP（酶诱导碳酸盐沉淀）、生物矿化、尿素水解、
非尿素路径、岩土加固与环境影响领域的**可复现证据检索**能力：真实检索、DOI/元数据
核验、去重、证据分层与质量初筛、引用导出、来源登记与可复现性记录。

## 标准识别（重要）

本 Skill 处于既有 OpenCode 工程包（`opencode-dev`，OBSIDIAN 底仓）内，采用两层标准：

1. **加载标准（原生）**：OpenCode 原生加载器 `packages/opencode/src/skill/index.ts`
   扫描 `{skill,skills}/**/SKILL.md`，读取 YAML frontmatter 的 `name`（须为小写连字符、
   与目录名一致）与 `description`。本 Skill 满足该契约。
2. **工程包标准（项目自定义约定）**：`skill.yaml / schemas / prompts / tools / tests /
   evals / examples / references / CHANGELOG.md` 为本仓库既有扩展约定（由
   `obsidian-skill-router` 注册表与 `obsidian-state-manager` 首落）。`skill.yaml`
   被 Router 注册表（`tools/osr/registry.ts`）消费做路由匹配。

## 安装

无第三方依赖要求（jsonschema 有则用，无则内置降级校验器；requests 有则用，无则
走 `--offline` fixture 或报 `MLS-E402`）。建议 Python ≥3.11。

```bash
python tools/literature_scout.py --help
```

## 调用

```bash
# 真实检索（需要人工审批 granted=true）
python tools/literature_scout.py --offline < input.json > output.json

# 离线（强制 fixture，CI 安全）
python tools/literature_scout.py --offline < examples/search-micp-uniformity.json > out.json
```

- **stdin**：一个 JSON 对象，符合 `schemas/input.schema.json`。
- **stdout**：一个 JSON 对象，符合 `schemas/output.schema.json`（成功与失败都满足）。
- **stderr**：仅供诊断；协议数据只走 stdout。
- **trace 日志**：`traces/<project_id>/<repro_id>.jsonl`（可复现性审计），
  可用 `--trace-dir` 覆盖。

## 动作矩阵

| 动作 | 说明 | 网络 | 审批门 |
|---|---|---|---|
| `search.run` | 构造检索式→检索→去重→分层初筛→元数据核验 | ✅ | ✅ 人工审批 |
| `search.repeat` | 复现上次检索（相同检索式→相同 repro_id） | 可选 | — |
| `doi.verify` | DOI 存在性 + 元数据一致性核验 | 可选 | — |
| `dedup.merge` | 三规则去重（DOI/标题规范化/同题-同年-同刊） | — | — |
| `triage.screen` | 证据分层（TIER1/2/3/REJECT）+ 质量初筛 | — | — |
| `cite.export` | 导出 BibTeX/CSL-JSON/CSV/RIS | — | 写文件时 |
| `sources.register` | 登记来源与检索式档案（追加式） | — | ✅ 人工审批 |
| `validate.self` | 内置自检（认识论标签/输出 schema/trace 完整性） | — | — |

所有变更动作支持 `dry_run`；每次 `search.*` 写 trace 日志 + `repro_id`。

## 错误码

`MLS-E1xx` 输入契约 · `MLS-E2xx` 证据/引用 · `MLS-E3xx` 数据/存储完整性 ·
`MLS-E4xx` 工具/环境 · `MLS-E5xx` 权限/审批 · `MLS-E6xx` 下游能力 ·
`MLS-E7xx` 输出/自检 · `MLS-E8xx` 版本兼容。完整定义见 `SKILL.md` §9 与
`tools/micp_lit/errors.py`。

## 测试与评测

```bash
python -m pytest tests/ -q              # 单元 + 集成 + 失败 + 自举
python evals/run.py --verbose           # ≥8 评测用例 + 7 项指标，写入 evals/results/latest.json
```

指标阈值：结构化输出通过率 ≥0.95、工具真实调用率 =1.0、引用可追溯率 ≥0.9、
缺失输入识别率 =1.0、对抗拦截率 =1.0、重复运行一致性 =1.0、平均失败恢复 ≤5000ms。
指标定义与测量方法见 `evals/metrics.py` 与 `evals/metrics.md`。

## 版本策略

输入/输出 schema 破坏性变更 → 主版本 +1（旧版本输出必须迁移或明确拒绝，
`MLS-E801`/`MLS-E802`）；新增可选字段 → 次版本 +1；实现修复不改契约 → 修订 +1。
见 `CHANGELOG.md`。

## 已知限制

- **检索覆盖偏差**：OpenAlex/Crossref 侧重已登记 DOI 的文献；付费墙文献可能只有
  元数据而无全文（`fulltext_available=false`）；中文文献覆盖有限。检索盲区须显式报告，
  不得用检索排名冒充证据强度。
- **DOI 离线核验有限**：离线只能按结构规则判定 `suspected_forged` 或
  `not_checked`，不声称"已核验存在"。
- **无实时检索的确定性**：网络检索结果随上游排名变化；`repro_id` 只保证"相同检索式"
  可复现，不保证上游返回逐字节一致。离线 fixture 保证确定性。
- **并发写 trace**：单项目 trace 由 `repro_id` 分文件，互不覆盖；同一 repro_id 并发写
  未加文件锁（追加式，最多重复行，不会损坏）。
- **领域判断**：本 Skill 做证据检索与初筛，不做工艺决策；决策由对应专业能力完成。

## 故障排除

| 症状 | 排查 |
|---|---|
| `MLS-E101` 输入被拒 | 对照 `schemas/input.schema.json`；detail.violations 给出字段路径 |
| `MLS-E102` 缺失字段 | 每个缺失字段的 detail 给出"为什么关键/如何获得" |
| `MLS-E201/E202/E203` 引用核验失败 | 用 `doi.verify` 单独复查；`suspected_forged` 表示判定为伪造 |
| `MLS-E402` 网络不可用 | 用 `--offline` 走 fixture；或等待网络恢复后重试 |
| `MLS-E501` 审批未通过 | 设置 `human_approval_state.granted=true` + approver |
| `MLS-E801` 版本不符 | 升级 payload 到 1.x 或升级 Skill |
| 测试失败 | 用 `MLS_TEST_CLOCK` 固定时钟重跑，排除时间差异 |

## 维护者清单

- 契约变更：先改 `schemas/*.json` 与 `SKILL.md` §11 版本策略，再改实现与测试。
- 领域事实更新：编辑 `tools/fixtures/*.json`（离线 fixture）与 `references/sources.md`。
- 检索式模板：`tools/micp_lit/adapters.py` 的 `BUILD_QUERY`。
- 发布：更新 `skill.yaml`、`CHANGELOG.md`，跑 `pytest` + `evals/run.py`。
