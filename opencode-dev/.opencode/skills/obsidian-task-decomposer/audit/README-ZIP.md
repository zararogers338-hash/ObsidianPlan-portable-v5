# obsidian-task-decomposer — Skill 安装包

**这是什么**：Obsidian Plan（黑曜石计划）· Panshi 研究系统的一个受治理专业 Skill 安装包。
版本 **1.0.0**，2026-08-06 交付。

**它干嘛用的**：把 Mission Lock 生成的研究任务合同拆成粒度适当、依赖明确、可并行、可重试、可验收的原子研究任务，并输出工程循环可执行的 DAG（含粒度评分、预算、关键路径、局部重规划支持）。面向 MICP 研究场景（含尿素水解铵态氮质量守恒等 guardrail）。

**标准 / 约定**：本包遵循仓库 `opencode-dev`（OpenCode fork）的真实 Skill 发现与加载约定
（`.opencode/skills/<name>/SKILL.md`，frontmatter `name`+`description`）。完整目录布局、
`skill.yaml` manifest、`schemas/`、`tools/`、`tests/`、`evals/` 为 Obsidian Plan / Panshi
项目自定义约定（详见 `README.md` 与 `references/sources.md`）。

## 安装

把本 zip 解压后，将顶层目录 `obsidian-task-decomposer/` 放进项目的 `.opencode/skills/`
即可被自动发现加载。也可放到 `~/.config/opencode/skills/`、`.claude/skills/` 或
`.agents/skills/`（OpenCode 均会扫描）。

要求：`python >= 3.10` 在 PATH 上（全部工具为 stdlib，无第三方依赖，离线运行）。

## 快速验证

```bash
cd obsidian-task-decomposer
python -m pytest tests/ -q          # 38 项测试
python evals/run_evals.py           # 10 个评测用例 + 7 项最低性能指标
python evals/run_bootstrap.py       # 4 个自举场景（skill persona 真实调用工具）
bash examples/01-basic-micp/run.sh  # 端到端示例
```

## 目录速览

```
SKILL.md          入口（frontmatter + 触发条件/流程/工具表/停止规则）
skill.yaml        机器可读 manifest（版本/权限/入口点/版本策略/最低指标）
prompts/system.md 最小系统提示词
schemas/          输入/输出/节点三份严格契约（JSON Schema 2020-12 子集）
tools/            7 个真实工具（validate/dag_check/granularity_scorer/budget_estimator/
                  critical_path/replan_diff/self_audit），stdin→stdout JSON 信封，离线确定性
tests/            单元/集成/失败/回归/schema子集（pytest，全部真实运行）
evals/            10 个评测用例 + run_evals + run_bootstrap
examples/         3 个可运行端到端示例（MICP DAG / 失败后重规划 / 缺失输入 BLOCKED）
references/       来源与领域依据（含访问日期、用途、限制）
DELIVERY-REPORT.md 本次交付工程报告
CHANGELOG.md      版本记录
```

**入口文档**：先读 `SKILL.md` 与 `README.md`；工具契约见 `tools/README.md`。
