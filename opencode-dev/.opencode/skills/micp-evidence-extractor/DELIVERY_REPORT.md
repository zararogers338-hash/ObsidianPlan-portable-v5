# 交付报告 — micp-evidence-extractor v1.0.0

**交付日期**：2026-08-07
**交付位置**：`.opencode/skills/micp-evidence-extractor/`
**状态**：✅ 可加载、可调用、可审计，真实生成合格 Evidence Card

---

## 1. 新增与修改的文件

### 新增（Skill 工程包，全部真实落地）

```
micp-evidence-extractor/
├── SKILL.md                      # Skill 主文档（frontmatter name+description，OpenCode 加载器要求）
├── skill.yaml                    # Router 机器元数据（capabilities 含裸 token `evidence`）
├── README.md                     # 使用说明 + 目录 + 契约 + 注册方式
├── CHANGELOG.md                  # 版本历史
├── prompts/system.md             # 系统提示（角色 + 纪律 + 流程）
├── schemas/
│   ├── input.schema.json         # 输入契约（draft 2020-12，additionalProperties:false）
│   ├── output.schema.json        # 12 字段统一信封 + 抽取扩展
│   └── evidence-card.schema.json # Evidence Card 数据模型（五元组 + 溯源 + 获取方式 + 认识论）
├── tools/
│   ├── README.md                 # 工具集文档
│   └── mee/                      # 纯 stdlib Python 工具集（13 个模块）
│       ├── cli.py                # stdin/stdout 入口（11 个子命令）
│       ├── _common.py            # 信封 / 超时 / 日志 / 类型守卫
│       ├── errors.py             # MEE-E101…E900 错误码
│       ├── models.py             # 领域常量
│       ├── _jsonschema.py        # JSON Schema 子集校验器
│       ├── adapters.py           # PDF/HTML/Markdown/CSV/JSON 解析
│       ├── doi.py                # DOI 结构校验 + 元数据一致性
│       ├── units.py              # 单位规范化 + 量纲 + 防混淆
│       ├── quantity.py           # 五元组构造 + 占位守卫
│       ├── extract.py            # 表/正文/图候选抽取
│       ├── card_check.py         # 卡片 schema + 不变量校验
│       ├── isolation.py          # 实验组/时间点隔离
│       ├── conflict.py           # 重复值 + 内部矛盾
│       ├── exporter.py           # JSON/YAML/CSV 导出
│       └── digitizer.py          # 图数字化接口
├── tests/                        # pytest：51 测试
│   ├── conftest.py
│   ├── test_scenarios.py         # 十项强制场景
│   ├── test_unit.py              # 工具单元测试
│   └── test_regression.py        # 版本门/鲁棒性/确定性
├── evals/
│   ├── cases.yaml                # 11 评测用例
│   ├── run_evals.py              # 7 项指标评测运行器
│   └── bootstrap/
│       └── run_bootstrap.py      # 自举测试（27 项检查）
├── examples/
│   ├── 01-multi-group-paper.md   # 示例说明
│   ├── 01-multi-group-paper.json # 多组多时间点论文 → SUCCESS
│   ├── 02-figure-digitized.json  # 图数字化 → DIGITIZED_FROM_FIGURE
│   └── 03-non-micp-blocked.json  # 非 MICP → BLOCKED
└── references/
    └── sources.md                # 方法学来源
```

### 修改（无）

未修改仓库内任何既有文件（纯新增 Skill 包）。

---

## 2. 工具及用途

| 工具 | 命令 | 用途 |
|---|---|---|
| service | `python tools/mee/cli.py service` | 完整抽取管线（校验→版本→解析→抽取→建卡→隔离→自检） |
| adapters | `python tools/mee/cli.py adapters` | PDF（内置流级文本恢复）/HTML/Markdown/CSV/JSON 解析 |
| doi | `python tools/mee/cli.py doi` | DOI 结构校验 + 伪造启发式；在线元数据一致性（可注入 fetcher） |
| units | `python tools/mee/cli.py units` | 单位规范化（强度/渗透/摩尔/长度/时间/密度/电导/流量/压力/能量） |
| extract | `python tools/mee/cli.py extract` | 表逐行逐列 / 正文条件结果 / 图数字化候选抽取 |
| validate | `python tools/mee/cli.py validate` | Evidence Card schema + 不变量校验 |
| isolation | `python tools/mee/cli.py isolation` | 实验组/时间点隔离检查 |
| conflict | `python tools/mee/cli.py conflict` | 重复值 + 内部矛盾 + 方法/结果冲突检测 |
| export | `python tools/mee/cli.py export` | 卡片导出为 JSON / YAML / CSV |
| digitize | `python tools/mee/cli.py digitize` | 图数字化接口（估读误差计算） |
| check-self | `python tools/mee/cli.py check-self` | 输出信封自检 |

所有工具：stdin JSON → stdout JSON 信封 `{ok, tool, version, result|error}`；
exit 0/2/3/4；日志写 stderr；超时 `MEE_TOOL_TIMEOUT`（默认 120s）；纯 stdlib、
离线、确定性、无硬编码密钥。

---

## 3. 输入输出契约

### 输入（`schemas/input.schema.json`）
必填：`task_id, project_id, request, skill_version, controller_version, timestamp`。
文档来源三选一：`document`（结构化）/ `document_text`（全文）/ `source_path`（文件路径）。
可选：`evidence_refs`、`data_refs`、`upstream_outputs`、`context`、`constraints`
（`offline`/`allow_figure_digitization`/`max_cards`）、`risk_level`、
`human_approval_state`、`requested_output_format`、`reproducibility`。

### 输出（`schemas/output.schema.json`）
12 字段统一信封：`status, summary, findings, assumptions, evidence_used,
uncertainty, risks, artifacts, requested_next_skills, validation, provenance,
errors`。
抽取专属扩展：`document`、`doi_verifications`、`isolation_report`、
`evidence_cards`、`duplicates_contradictions`、`card_validation`、`extractor_stats`。

### Evidence Card（`schemas/evidence-card.schema.json`）
每个数值量携带：
- **原始值 + 原始单位**（`value`/`unit`，保留原文原样）
- **规范化值 + 规范化单位**（`normalized_value`/`normalized_unit`，可跨论文比较）
- **统计类型**（`statistic_type`：mean/median/single_measurement/...）
- **样本量**（`n`）
- **不确定性**（`uncertainty_type`：sd/se/ci/range/iqr/error_bar + `uncertainty_value`）
- **所属实验组**（`group_id`）+ **所属时间点**（`timepoint_id`）
- **原文定位**（`sources[]`：页码/表号/图号/补充材料位置）
- **获取方式**（`acquisition_mode`：REPORTED_TEXT/REPORTED_TABLE/DIGITIZED_FROM_FIGURE/
  CALCULATED_FROM_REPORTED_DATA/INFERRED/NOT_REPORTED/AMBIGUOUS）
- **认识论标签**（`epistemic_tag`：OBSERVED/REPORTED/CALCULATED/INFERRED/HYPOTHESIS/RECOMMENDATION）
- 图数字化量额外携带 `digitization`（含 `error_estimate` 估读误差）

---

## 4. 实际运行命令

```bash
# 测试（51 个全部通过）
cd skills/micp-evidence-extractor
python -m pytest tests/ -q

# 评测（11 用例 × 7 指标全部通过）
python evals/run_evals.py

# 自举（27 项检查全部通过）
python evals/bootstrap/run_bootstrap.py

# 处理示例论文
python tools/mee/cli.py service < examples/01-multi-group-paper.json

# Router 真实路由验证（评分 6.00，锚定本 Skill）
cd ../obsidian-skill-router
bun run tools/osr/router-cli.ts --input <request.json>

# Router registry 索引验证（usable=true）
bun run tools/osr/_verify_extractor.ts   # 已执行并删除
```

---

## 5. 测试通过情况

| 套件 | 数量 | 结果 |
|---|---|---|
| pytest `tests/` | 51 | ✅ 全部通过（2.4s） |
| 强制场景（十项） | 17 | ✅ 全过 |
| 单元测试 | 16 | ✅ 全过 |
| 回归测试 | 18 | ✅ 全过 |
| evals `run_evals.py` | 11 用例 | ✅ 全过 |
| 评测指标 | 7 | ✅ 全过（全 1.00） |
| 自举 `run_bootstrap.py` | 27 检查 | ✅ 全过 |

### 十项强制场景 → 测试映射

| # | 场景 | 测试 | 验证点 |
|---|---|---|---|
| 1 | 多实验组不混组 | `test_groups_never_mixed` | Control 150/210、MICP 1200/2500 各归其组 |
| 2 | OD600 与脲酶不混淆 | `test_od600_never_conflated_with_urease` | canonical 单位 `OD600` vs `mmol_urea/min/OD` |
| 3 | 图估读标 DIGITIZED_FROM_FIGURE | `test_figure_only_data_is_digitized` | 值+误差估计，非 OBSERVED |
| 4 | 缺单位标 AMBIGUOUS | `test_missing_unit_is_ambiguous` | normalized_value=null |
| 5 | 方法/结果矛盾报警 | `test_contradiction_detector_direct` | CONTRADICTION error |
| 6 | 时间点不合并 | `test_time_points_never_merged` | Day7/14 各自绑定 |
| 7 | 伪造 DOI 拒绝 | `test_forged_doi_rejected` | suspected_forged |
| 8 | 损坏 PDF 错误恢复 | `test_corrupt_pdf_rejected` | MEE-E303，不伪造内容 |
| 9 | 非 MICP 不误触发 | `test_non_micp_does_not_trigger` | BLOCKED + MEE-E103 |
| 10 | 卡片反向定位原文 | `test_reverse_lookup_from_card_to_document` | locator 指向 Table 1，值可回查 |

---

## 6. 自举测试结果（27/27）

- **Skill 真实加载**：B1 — SKILL.md + skill.yaml + schemas + cli 全在，frontmatter name 匹配目录。
- **工具真实调用**：B2 — service 子进程退出 0，`validation.tool_runs` 记录 adapters/extract/card_check/isolation/conflict 真实运行。
- **输出通过 Schema**：B3 — 过 output.schema.json + evidence-card.schema.json（3/3 卡）。
- **数值可溯源**：B4 — 每个 REPORTED 量带 locator，脲酶定位 `Table 2 row0 col2`，图值定位 fig1。
- **图估读不伪装**：B5 — DIGITIZED_FROM_FIGURE + error=0.02，非 OBSERVED；无标定图不伪造。
- **不混组**：B6 — 组/时间点全部绑定，Control/MICP 值精确隔离；GROUP_SMEAR 检出。
- **失败输入正确返回**：B7 — 非 MICP→BLOCKED、缺文档→BLOCKED+missing_inputs、版本错→BLOCKED+E801、损坏 PDF→E303。
- **对抗审查零缺陷**：B8 — 独立审查角色攻击输出（R1 混组/R2 单位跨界/R3 伪造值/R4 缺引用/R5 伪造引用/R6 时间合并/R7 schema），无缺陷。

---

## 7. 未解决限制

1. **PDF 表格布局保留有限**：文本恢复是流级最佳努力；表格检测为启发式（重复对齐行），
   复杂 PDF 表格可能需手动结构化后送入 `document.tables`。
2. **图数字化需标定记录**：纯 stdlib 不做光栅处理；调用方须在 figure note 提供
   `read`/`axis_px`/`axis_range` 标定，否则标记 AMBIGUOUS 不伪造。
3. **DOI 在线核验需注入 fetcher**：离线仅结构校验（`verifiable_structure`/
   `offline_unverified`），绝不声称已在线验证存在性。
4. **自由格式正文推断保守**：时间点/组绑定依赖表头与首列的结构化解析；纯散文
   推断留待人工或上游结构化。
5. **单位字典覆盖有限**：不常见单位（如 D（达西）作为渗透率代理）保留原值但
   不做跨测定换算；OD600/CFU/细胞浓度/活细胞比/脲酶活性之间**永不换算**。

---

## 8. 在 Obsidian Router 中的注册方式

Skill 已被 Router **真实注册并路由**（2026-08-07 实测）：

### 注册机制（无需手动改代码）
- Router 的 `obsidian-skill-router/tools/osr/registry.ts` `indexRegistry` 动态扫描
  `skills/**/SKILL.md`。本 Skill 的 `SKILL.md` frontmatter 含 `name:
  micp-evidence-extractor`（匹配目录名）+ `description`，自动入册。
- `validateManifest` 校验 `skill.yaml`：`version: 1.0.0`（semver）、
  `capabilities/inputs_required/outputs/tool_permissions/writes/stop_conditions/
  domain_keywords/dependencies` **均为字符串数组**、`network: false`（boolean）、
  `risk_tier: low` —— 全部通过，`usable=true`、`manifest_valid=true`、`issues=[]`。

### 路由匹配
- `planner.ts` `DOMAIN_MAP` 第 98 行已有 `["evidence", /(证据|提取|抽取|extract|页码|DOI)/i]`；
  `UPSTREAM_HINTS` 第 69 行已有 `"evidence-extractor": "evidence"`。
- `matchSkill` 评分 = 3×能力覆盖 + 2×输入覆盖 + 1×关键词重叠。
  实测请求「从这篇 MICP 论文提取结构化证据卡，区分实验组与时间点，核验 DOI」
  路由到本 Skill，评分 **6.00**，`status=SUCCESS`，`summary=已路由组合:
  micp-evidence-extractor`。
- `inputs_required` 只列 router 可供给字段（task_id/project_id/request/context/
  evidence_refs/data_refs/upstream_outputs），保证 input 覆盖分满分。

### 注册验证命令
```bash
cd skills/obsidian-skill-router
bun run tools/osr/router-cli.ts --input <route-request.json>
```
Registry 索引实测：`entries=20`，`micp-evidence-extractor` `usable=true`。
