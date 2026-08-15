# micp-data-analyst 交付报告

**Skill 名称**: micp-data-analyst
**中文名称**: MICP Data Analyst｜数据清洗、统计推断与可视化
**版本**: 1.0.0 · **交付日期**: 2026-08-06
**验收状态**: ✅ 全部阻断项关闭 · 测试 38/38 · 评测 7/7 · 自举 5/5

---

## 1. 仓库与标准识别结果

**真实仓库位置**（本轮施工的目标工程）:
```
.opencode\
```
这是一个基于 **OpenCode（anomalyco/opencode）fork** 的 Obsidian Plan / Panshi 研究工程，`skills/` 与 `.opencode/skills/` 是 Skill 的两个注册根目录。

**Skill 格式约定**（从仓库真实实现提炼，非臆造）:

| 文件 | 来源惯例 | 本交付 |
|---|---|---|
| `SKILL.md` + frontmatter（`name`/`description`） | OpenCode 加载器（`packages/opencode/src/skill/index.ts`）+ 仓库全部 4 个 MICP Skill | ✅ 7 正触发/4 反触发/4 边界 |
| `skill.yaml` manifest | `obsidian-skill-router/tools/osr/registry.ts` 的索引器契约 | ✅ 已通过 registry 扫描（usable=true） |
| `prompts/system.md` | `obsidian-task-decomposer`、`obsidian-skill-router` 惯例 | ✅ |
| `schemas/input|output.schema.json` | 仓库既有 Skill 的严格契约惯例 | ✅ |
| `tools/` 纯标准库 + stdin/stdout 信封 | `obsidian-task-decomposer`（Python）惯例：`{ok,tool,version,result\|error}`、exit 0/2/3/4 | ✅ |
| `tests/`（pytest 离线） | `obsidian-task-decomposer` 惯例 | ✅ |
| `evals/cases.yaml` + 离线 runner | `obsidian-task-decomposer` 惯例 | ✅ |
| `references/sources.md`、`CHANGELOG.md` | 全仓库惯例 | ✅ |

**重要发现**：`obsidian-task-decomposer` 的 `examples/` 目录是空的（CHANGELOG 声称有但实际缺失）——本交付**没有复制这个缺陷**，examples/ 有 3 个真实可运行输入。

## 2. 新增文件清单

全部文件位于 `skills/micp-data-analyst/`（共 39 个文件，9 个目录）：

```
SKILL.md            — OpenCode frontmatter + 触发/边界/流程/错误码/版本策略/性能指标
skill.yaml          — OSR registry manifest（capabilities/units/permissions/risk_tier）
README.md           — 面向维护者的安装/调用/测试/限制文档
CHANGELOG.md        — 初始版本记录 + 版本策略
prompts/system.md   — 最小系统提示词（身份/流程/边界/认识论/停止规则）
schemas/input.schema.json   — 严格输入契约（draft 2020-12 子集）
schemas/output.schema.json  — 严格输出契约 + status 条件门（BLOCKED⇒missing_inputs 等）
tools/README.md     — 工具契约文档
tools/micp/_common.py       — 信封 + 数值/类型守卫
tools/micp/_jsonschema.py   — JSON Schema 2020-12 子集校验器
tools/micp/_numerics.py     — norm/t/F/χ² 数值原语（Acklam/A&S/NR，已验证）
tools/micp/errors.py        — MDA-E### 错误码体系（唯一事实源）
tools/micp/qc.py            — schema/单位/缺失/范围/时间/批次/伪重复检查
tools/micp/stats.py         — 描述统计/t CI/正态筛查/异常值/Hedges' g/power/OLS/ANOVA/均匀性/敏感性
tools/micp/service.py       — 全流程编排（校验→版本→前置→QC→统计→自检→输出）
tools/micp/cli.py           — stdin/stdout 入口（service|qc|stats|validate）
tests/conftest.py           — 测试夹具 + 真实 CLI 调用
tests/test_unit.py          — 单元测试（统计数学）
tests/test_failure.py       — 失败路径（恶意/冲突/缺失）
tests/test_regression.py    — 确定性与契约稳定性
tests/test_schema_subset.py — schema 校验器子集守卫
tests/test_integration.py   — 全流程集成
evals/cases.yaml            — 10 个评测用例
evals/run_evals.py          — 离线评测 runner（7 指标）
evals/bootstrap/*.json      — 5 个自举测试输入
evals/bootstrap/run_bootstrap.py — 自举测试 runner
examples/01-clean-infer.md  — 示例 1（清洗+推断）
examples/02-sensitivity.json — 示例 2（敏感性）
examples/03-blocked.json    — 示例 3（BLOCKED）
references/sources.md       — 17 条来源（方法学 + 领域 + 契约）
```

## 3. Skill 输入输出契约

### 输入（`schemas/input.schema.json`，严格 `additionalProperties:false`）

必填：`task_id, project_id, request, skill_version, controller_version, timestamp`。
关键可选：`samples`（数据行）、`data_columns`（变量字典：role/type/unit/sampling_unit）、`data_refs`、`evidence_refs`、`upstream_outputs`、`constraints`（significance_level/confidence_level/engineering_thresholds/random_seed/outlier_policy/analysis_modes）、`reproducibility`、`risk_level`、`human_approval_state`、`requested_output_format`。

**最低条件与缺失处理**：缺失字段时输出 `BLOCKED` + `missing_inputs`，每项含 `field`/`why_critical`/`how_to_obtain`（逐字段，不笼统说"信息不足"）。

### 输出（`schemas/output.schema.json`）

必填：`status, summary, findings, assumptions, evidence_used, uncertainty, risks, artifacts, requested_next_skills, validation, provenance, errors`。
可选：`missing_inputs`（BLOCKED 时强制）、`data_quality`、`pseudo_replication`、`statistics`。
`status ∈ {SUCCESS, PARTIAL, BLOCKED, FAILED, NEED_ADDITIONAL_SKILL, HUMAN_APPROVAL_REQUIRED}`，schema 用 `allOf/anyOf` 强制：BLOCKED⇒`missing_inputs` 非空、SUCCESS/PARTIAL⇒`artifacts` 存在。

**认识论标签**：每条 finding 必须带 `OBSERVED|REPORTED|CALCULATED|INFERRED|HYPOTHESIS|RECOMMENDATION` 之一；OBSERVED/REPORTED 必须带 `source`。schema 枚举强制。

## 4. 所造工具及其用途

| 工具/子命令 | 真实用途 | 离线? | 确定性? |
|---|---|---|---|
| `cli.py service` | 完整管线：输入校验→版本门→前置条件→数据质量→统计→自检→统一信封 | ✅ | ✅ |
| `cli.py qc` | schema/单位/缺失/范围/时间/批次/独立性与**伪重复检测** | ✅ | ✅ |
| `cli.py stats` | 11 个统计操作：descriptive/ci/cohens_d/power/normality/outliers/sensitivity/regression/anova/uniformity/repro_hash | ✅ | ✅ |
| `cli.py validate` | 仅输入 schema 校验 | ✅ | ✅ |

所有工具：纯 Python 3.10+ 标准库、无 numpy/scipy、无网络、RNG 受 seed 控制、输入拒绝非有限值、错误走 `{code,message,retryable,details}` 信封、进度写 stderr。

## 5. 真实执行过的测试和结果

| 套件 | 命令 | 结果 |
|---|---|---|
| 单元+失败+回归+子集+集成 | `python -m pytest tests/` | **38 passed** |
| 静态检查 | `ruff check tools/ tests/ evals/` | **All checks passed** |
| 编译检查 | `python -m py_compile tools/micp/*.py` | **OK** |
| 离线评测（10 用例 × 7 指标） | `python evals/run_evals.py` | **7/7 PASS，exit 0** |
| 自举测试（5 场景） | `python evals/bootstrap/run_bootstrap.py` | **5/5 PASS** |
| 注册表扫描 | `bun tools/bin/osr.ts registry` | **micp-data-analyst usable=true，manifest_valid=true** |

**评测指标明细**（`evals/run_evals.py` 实测）：

```
structured_output_pass_rate   1.00  (≥0.95) PASS
tool_invocation_rate          1.00  (=1.0)  PASS
evidence_traceability_rate    1.00  (≥0.9)  PASS
missing_input_detection_rate  1.00  (=1.0)  PASS
adversarial_interception_rate 1.00  (=1.0)  PASS
repeat_run_consistency        1.00  (=1.0)  PASS
mean_failure_recovery_time    ~0.06s/case
```

## 6. 自举测试中发现的问题及修复

自举测试要求"以普通用户请求调用，不泄露预期答案"。5 个场景全部通过，过程中发现并修复了以下问题：

| # | 发现的问题 | 修复 |
|---|---|---|
| 1 | `t_ppf` 二分目标/方向错误 → CI 荒谬（±525000 MPa） | 重写为 `P(\|T\|>x)=2(1−p)` 求解，对照 R 已知分位数验证（t_ppf(0.975,5)=2.5706 ✅） |
| 2 | 伪重复未被检出（同一柱多位置当独立样本） | `qc.pseudo_replication_check` 采样单位解析回退（列声明>batch>id 列） |
| 3 | 组比较把行数当独立样本 | 检测到伪重复时**先聚合到采样单位**再算效应量，报告 effective_n vs 行数 |
| 4 | `generated_at` 用当前时间 → 重复运行不一致 | 改用输入 `timestamp`，同输入→逐字节一致 |
| 5 | 正态性筛查在 n<3 时崩溃整个服务 | 优雅降级为 `insufficient_data` |
| 6 | 非有限/NaN 值导致服务 FAILED | `qc.to_numeric` 跳过并记录 `skipped` 到 data_quality.issues |
| 7 | 工程阈值判定缺失（统计显著≠工程显著） | 新增 `_engineering_judgment`：min/max/min_gain 三态判定 + RECOMMENDATION finding |
| 8 | 小值 group_means 显示精度丢失（1.0e-6 vs 1.2e-6 都显示 1e-6） | `_fmt` 对小值保留 10 位 |
| 9 | 对抗攻击：1000x 夸大声明、不可核验证据、500 MPa 异常值 | 夸大声明不采纳；证据引用带 `verifiable`/`note` 标注；异常值 n<5 报 `low_confidence` |
| 10 | cli 入口未统一异常捕获 | `MdaError` 继承 `ToolError`，cli 统一 catch，退出码规范 |

## 7. 尚未关闭的风险和限制

1. **正态性筛查近似**：n∈[8,30) 用 D'Agostino 风格 z-score 近似；n<8 拒绝认证。关键决策需模型诊断确认（已在 CHANGELOG 声明）。
2. **混合效应/响应面/多目标/时间序列模型未实现**：按约定路由 `NEED_ADDITIONAL_SKILL` → `obsidian-modeling-optimizer`，不越界。
3. **可视化资产声明但未实现 PNG/HTML 渲染器**：输出契约含 `visualization_png/html` 枚举，但渲染由配套技能承担（未越界制造伪渲染）。
4. **功效分析用非中心 t 正态近似**（规划级），关键决策需模拟验证。
5. **`obsidian-skill-router` 的 `skills/` 根已含 `micp-data-analyst`**，但 router 的 `capability_gap` 检测依赖注册表快照刷新；生产部署需重跑 `osr.ts registry --write`。
6. 评测的 `mean_failure_recovery_time` 测量的是单 case 墙钟时间（~0.06s），非"失败→修复"轮次；后者以 ≤1 轮为基线记录。

## 8. 调用示例

```bash
# 完整管线：伪重复检测 + 统计 + 效应量 + 工程判定
cd skills/micp-data-analyst
python tools/micp/cli.py service < examples/01-clean-infer.json

# 数据质量检查
python tools/micp/cli.py qc < input.json

# 单统计操作
echo '{"op":"cohens_d","a":[10,11,12,13,14],"b":[5,6,7,8,9]}' | \
  python tools/micp/cli.py stats

# 输入校验
python tools/micp/cli.py validate < input.json

# 测试与评测
python -m pytest tests/
python evals/run_evals.py
python evals/bootstrap/run_bootstrap.py
```

作为 Obsidian Router 的受调度能力：注册表已验证可发现（`usable=true`），输出信封直接可被 Controller 机器解析（status/errors/validation/provenance）。

## 9. 版本号与后续演进建议

**当前版本**：`1.0.0`（contract_version 1.0.0，错误码 MDA-E1xx..E9xx）。

**演进建议**（按优先级）：
1. **可视化渲染器**：补 `visualization_png/html` 的实际渲染（matplotlib 依赖或 HTML 模板），完成第 5 项工具能力的闭环。
2. **混合效应模型**：集成 statsmodels/lme4 类能力，把 `NEED_ADDITIONAL_SKILL` 降为原生支持。
3. **上游/下游契约互操作测试**：与 `micp-geotechnical-performance`、`micp-porous-media-transport` 做端到端 cross-layer 测试（`upstream_outputs` 真实接线）。
4. **工程阈值知识库**：把 MICP 典型工程阈值（强度、渗透、CaCO3）从示例提升为 `references/` 可检索库。
5. **CI 集成**：把 `pytest + ruff + run_evals.py + run_bootstrap.py` 挂进仓库 CI，防回归。
