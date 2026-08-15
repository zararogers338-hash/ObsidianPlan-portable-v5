# micp-porous-media-transport

**MICP Porous Media Transport｜菌液、溶质、沉淀与堵塞耦合**

分析 MICP 中细胞、尿素、钙离子与碳酸钙沉淀在多孔介质中的迁移、反应、截留与渗透率演化，解释和预测空间不均匀性（入口堵塞、旁路流、渗透率—孔隙率关系）。

## 标准识别（重要）

本 Skill 处于**既有 OpenCode 工程包内**，采用两层标准：

1. **加载标准（原生）**：仓库 OpenCode 原生加载器在 `packages/opencode/src/skill/index.ts` 扫描 `{skill,skills}/**/SKILL.md`，读取 YAML frontmatter 的 `name` 与 `description`。本 Skill 的 `SKILL.md` 满足该契约，目录放在 `skills/micp-porous-media-transport/`。
2. **工程包标准（项目自定义约定）**：`skill.yaml / schemas / prompts / tools / tests / evals / examples / references / CHANGELOG.md` 是本项目的扩展约定（与 `obsidian-state-manager`、`obsidian-task-decomposer` 一致），不干扰原生加载。

## 安装与调用

```bash
# 无第三方依赖要求（jsonschema 有则用，无则内置降级校验器）
python tools/transport.py < input.json > output.json
```

- **stdin**：一个 JSON 对象，符合 `schemas/input.schema.json`。
- **stdout**：一个 JSON 对象，符合 `schemas/output.schema.json`（成功与失败都满足）。
- **stderr**：仅供诊断；协议数据只走 stdout。
- 工件目录：`--artifact-dir <dir>` 或环境变量 `OPM_ARTIFACT_DIR`（可选，不设则纯内存）。
- 子命令：`transport`（默认，stdin→stdout）、`schema`（打印输入 schema）、`selfcheck <json>`（用输出 schema 校验一个 JSON 文件）。

## 能力矩阵

| 动作 | 说明 | 审批门 |
|---|---|---|
| `analyze` | 全流程：校验→无量纲→求解→堵塞→守恒/网格自检 | — |
| `dimensionless` | 仅无量纲分析（Pe/Da/rDa，不求解） | — |
| `validate` | 场景校验（dry-run 门，不求解） | — |
| `clogging` | 在调用方提供的剖面上跑堵塞判据 | — |

现场部署、真实生物实验、危险化学品操作、长期知识写入 → 人工批准门（OPM-E502）。

## 概念模型

连续性（Darcy）尺度，1D 柱（可扩展到伪 2D 分段）：

| 变量 | 含义 | 单位 |
|---|---|---|
| U | 尿素浓度 | mol/m³ 孔隙水 |
| Ca | 钙离子浓度 | mol/m³ |
| NH | 铵态氮浓度 | mol/m³ |
| C | 碳酸盐浓度（CO₃²⁻+HCO₃⁻） | mol/m³ |
| B | 固定化生物量密度 | kg/m³ |
| M | 沉淀方解石质量 | kg/m³ |

反应（隐式 Euler 闭式）：

- 尿素水解（Michaelis-Menten）：`dU/dt = -k_ure·B·U/(K_half+U)`，1 尿素 → 2 NH₄⁺ + 1 碳酸盐。
- 沉淀：`r_pre = k_pre·min(Ca, C)`，Ca + C → CaCO₃(s) 1:1 消耗。

输运（显式迎风对流 + 中心弥散，CFL 受限）：`∂C/∂t = -u·∂C/∂x + D·∂²C/∂x² + 反应`。

孔隙率/渗透率耦合（Kozeny-Carman，堵塞反馈）：

- `phi = phi0 − M/ρ_caco3`
- `K(phi) = K0·(phi/phi0)³·((1−phi0)/(1−phi))²`

边界：**恒流**（Dirichlet 进水 + 零梯度出口，恒定 Darcy 速度）或**恒压**（逐时间步由入口渗透率与压差重解 Darcy 速度）。详见 `references/sources.md` 与 `tools/micp/solver.py`。

## 无量纲分析

- `Pe = u·L/D`：输运主导（Pe≥1 对流，Pe<1 弥散）。
- `Da = k·L/(u·c0)`：反应 vs 对流（Da≥1 反应主导 → 强前锋梯度/堵塞倾向）。
- `rDa = k·(L/u)/c0`：反应 vs 停留时间。
详见 `tools/micp/dimensionless.py`。

## 错误码

`OPM-E1xx` 输入契约 · `OPM-E2xx` 证据/单位 · `OPM-E3xx` 上下文/文件 · `OPM-E4xx` 工具/数值 · `OPM-E5xx` 权限/审批 · `OPM-E6xx` 下游能力 · `OPM-E7xx` 输出/自检 · `OPM-E8xx` 版本兼容。完整定义见 `tools/micp/errors.py`。关键：缺失关键边界条件 → `MODEL_BLOCKED`（OPM-E102），附逐字段指引。

## 测试与评测

```bash
python -m pytest tests/ -q          # 单元 + 集成 + 失败 + 回归
python evals/run.py --verbose       # 评测用例 + 7 项指标，写入 evals/results/latest.json
```

指标阈值：结构化输出通过率 ≥0.95、工具真实调用率 =1.0、证据可追溯率 ≥0.9、缺失输入识别率 =1.0、对抗拦截率 =1.0、重复运行一致性 =1.0、平均失败恢复时间 ≤1 轮。

## 版本策略

输入/输出 schema 破坏性变更 → 主版本 +1；新增可选字段 → 次版本 +1；实现修复不改契约 → 修订 +1。旧主版本输出必须显式迁移（OPM-E802）或拒绝（OPM-E801），绝不静默重释。见 `CHANGELOG.md`。

## 已知限制

- **1D 连续性假设**：孔隙率低于约 0.05 时 Darcy 连续性假设失效，结果仅定性（`clogging.py` 会给出警告）。
- **简化化学**：碳酸盐采用单物种代理（CO₃²⁻+HCO₃⁻ 合并），无完整碳酸平衡与 pH 演化；生物量恒定、无吸附/截留单独项（截留效应通过沉淀—孔隙率耦合间接体现）。这些是明确假设（`assumptions` 中标注 INFERRED），生产模型应接入完整碳酸盐化学（见 `references/sources.md`）。
- **弥散系数**：默认 `D = 0.1·u·L`（保守代理），调用方可传入。
- **确定性**：求解器确定、离线、纯 stdlib；同输入同输出。

## 故障排除

| 症状 | 排查 |
|---|---|
| `OPM-E101` 输入被拒 | 对照 `schemas/input.schema.json`；`errors[0].detail` 给出字段路径 |
| `OPM-E102` MODEL_BLOCKED | 补齐缺失边界条件（`errors[0].detail.missing_fields` 含为何关键/如何获得） |
| `OPM-E202/E203` 单位问题 | 检查单位字符串是否在支持族内 |
| `OPM-E403` 未收敛 | 减小 `dt` 或 `t_end`；检查 `k_ure/k_pre` 是否过大 |
| `PARTIAL` 自检失败 | `validation.checks` 列出失败项（守恒/网格/有限性） |
| 测试失败 | 用固定 `OPM_TEST_CLOCK` 无关（本 Skill 无时钟依赖）；检查 Python 版本 ≥ 3.10 |


---

> 原 `README-ZIP.md` 已归档至 [`audit/README-ZIP.md`](audit/README-ZIP.md)。
