# MICP Evidence Extractor (micp-evidence-extractor)

**版本 1.0.0** · Panshi / Obsidian Plan 受治理专业能力 · 纯 Python 标准库 · 离线确定性

MICP 结构化证据抽取器：读取 MICP 论文全文、补充材料、实验报告、CSV 与表格，
转换为**可比较、可追溯、可验证**的 Evidence Card。

## 一、它做什么

- **逐实验组、逐时间点、逐测量方法抽取**，绝不把不同试验组、不同论文或不同尺度混合。
- **七个获取方式**：`REPORTED_TEXT / REPORTED_TABLE / DIGITIZED_FROM_FIGURE /
  CALCULATED_FROM_REPORTED_DATA / INFERRED / NOT_REPORTED / AMBIGUOUS`。
- **六个认识论标签**：`OBSERVED / REPORTED / CALCULATED / INFERRED /
  HYPOTHESIS / RECOMMENDATION`。
- **MICP 纪律**：OD600 ≠ 细胞浓度 ≠ CFU ≠ 脲酶活性，绝不互换；图中估读必须带误差；
  缺单位标 AMBIGUOUS；无法确认写 NOT_REPORTED；矛盾并排报告。
- **统一返回信封**（12 字段）+ 文献元数据、DOI 核验、隔离报告、证据卡、矛盾检查、抽取统计。

## 二、目录

```
micp-evidence-extractor/
├── SKILL.md                  # Skill 主文档（frontmatter + 完整契约）
├── skill.yaml                # Router 机器元数据（capabilities 含 evidence）
├── README.md                 # 本文件
├── CHANGELOG.md              # 版本历史
├── prompts/
│   └── system.md             # 系统提示（角色 + 流程）
├── schemas/
│   ├── input.schema.json     # 输入契约
│   ├── output.schema.json    # 统一输出信封
│   └── evidence-card.schema.json  # Evidence Card 数据模型
├── tools/
│   └── mee/                  # 纯 stdlib Python 工具集
│       ├── cli.py            # stdin/stdout 入口
│       ├── _common.py        # 信封 / 超时 / 日志 / 类型守卫
│       ├── errors.py         # MEE-E### 错误码
│       ├── models.py         # 领域常量
│       ├── _jsonschema.py    # JSON Schema 子集校验器
│       ├── adapters.py       # PDF/HTML/Markdown/CSV/JSON 解析
│       ├── doi.py            # DOI 结构校验 + 元数据一致性
│       ├── units.py          # 单位规范化 + 量纲 + 防混淆
│       ├── quantity.py       # 五元组构造 + 占位守卫
│       ├── extract.py        # 表/正文/图候选抽取
│       ├── card_check.py     # 卡片 schema + 不变量校验
│       ├── isolation.py      # 实验组/时间点隔离
│       ├── conflict.py       # 重复值 + 内部矛盾
│       ├── exporter.py       # JSON/YAML/CSV 导出
│       └── digitizer.py      # 图数字化接口
├── tests/                    # pytest（51 测试）
├── evals/                    # 评测（11 用例 + 7 指标）
├── examples/                 # 真实可运行示例
└── references/
    └── sources.md            # 方法学来源
```

## 三、工具与用途

| 工具 | 命令 | 用途 |
|---|---|---|
| service | `python tools/mee/cli.py service` | 完整抽取管线 |
| adapters | `python tools/mee/cli.py adapters` | 源解析 |
| doi | `python tools/mee/cli.py doi` | DOI 核验 |
| units | `python tools/mee/cli.py units` | 单位规范化 + 防混淆 |
| extract | `python tools/mee/cli.py extract` | 候选抽取 |
| validate | `python tools/mee/cli.py validate` | 卡片校验 |
| isolation | `python tools/mee/cli.py isolation` | 隔离检查 |
| conflict | `python tools/mee/cli.py conflict` | 矛盾检测 |
| export | `python tools/mee/cli.py export` | JSON/YAML/CSV 导出 |
| digitize | `python tools/mee/cli.py digitize` | 图数字化接口 |
| check-self | `python tools/mee/cli.py check-self` | 自检 |

所有工具：stdin JSON → stdout JSON 信封 `{ok, tool, version, result|error}`；
exit 0/2/3/4；日志写 stderr；超时（`MEE_TOOL_TIMEOUT`，默认 120s）；纯 stdlib、离线、确定性。

## 四、输入 / 输出契约

- **输入**：`schemas/input.schema.json`。必填 `task_id, project_id, request,
  skill_version, controller_version, timestamp`；文档来源三选一
  （`document` / `document_text` / `source_path`）。
- **输出**：`schemas/output.schema.json`。12 字段统一信封 + `document`、
  `doi_verifications`、`isolation_report`、`evidence_cards`、
  `duplicates_contradictions`、`card_validation`、`extractor_stats`。
- **证据卡**：`schemas/evidence-card.schema.json`。每个数值含原始值/单位、
  规范化值/单位、统计类型、样本量、不确定性、组绑定、时间点绑定、来源定位、获取方式、认识论标签。

## 五、运行

```bash
# 测试（51 个）
python -m pytest tests/

# 评测（11 用例 × 7 指标）
python evals/run_evals.py

# 处理一篇 MICP 文档
python tools/mee/cli.py service < input.json
```

## 六、Router 注册

- `skill.yaml` 声明 `capabilities: ["evidence"]`——匹配 obsidian-skill-router
  `planner.ts` 的 `DOMAIN_MAP` `["evidence", /(证据|提取|抽取|extract|页码|DOI)/i]`
  与 `UPSTREAM_HINTS["evidence-extractor"] = "evidence"`。
- `inputs_required` 只列 router 可供给字段（task_id/project_id/request/context/
  evidence_refs/data_refs/upstream_outputs），保证 input 覆盖分高。
- `dependencies: []`（字符串数组），`version: 1.0.0`（semver），
  `risk_tier: low`，`network: false`——满足 `validateManifest` 全部约束。

## 七、与其他 Skill 的关系

- 上游：`micp-literature-scout`（DOI 预核验、文献元数据）。
- 下游：`micp-evidence-synthesizer`（消费本 Skill 的 Evidence Card 做跨论文综合）；
  `micp-data-analyst`（对卡片中的数值做统计推断）。
- 姊妹：`micp-instrumentation-qc`（测量不确定度）、`micp-ureolysis-chemistry`（尿素水解化学）。
