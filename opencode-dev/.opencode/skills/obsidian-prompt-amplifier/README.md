# Obsidian Prompt Amplifier — 提示词扩充机制 + 调动决策树

> **第 25 号 Skill · 最高优先级 · 任务入口首检**
> 受《Panshi Constitution v1.0》约束。优先级仅表示"最先运行",不表示凌驾于宪法;
> 任何冲突以宪法解释状态为准。

## Overview

`obsidian-prompt-amplifier` 是 Obsidian 研究循环的**入口首检**。对任何实质性研究/工程请求,它先:

1. **任务分类** — 按宪法第 67 条 Step 2 归入文献/机制/实验/数据/模型/工程/环境/战略;
2. **复杂度评分** — 按宪法附录 B 七维打分,映射 3—24 个子智能体规模;
3. **三级模型编组** — 建议 12 泛化 / 6 审 / 6 专项的调用组合;
4. **决策路径生成** — 输出 `decision_path`: 运行模式、主路径顺序、审门映射、专项升级触发、停止条件、状态落地(见 `DECISION-TREE.md`);
5. **强化提示词草案** — 定界 + 编组 + 决策路径 + 宪法约束,不降低任何审查门槛;
6. **接受询问** — 输出可审计报告,用户决定采纳与否(最多两轮扩充,不接受回标准流程)。

## 宪法至上 (Constitutional Supremacy)

本 Skill 的全部产出置于宪法之下。若请求含以下内容,一律判定 `CONSTITUTIONAL_CONFLICT` 并排除冲突部分:

- 跳过 Red Team / Decision Gate / 环境审查 / 复现审查 / 人类批准;
- 编造数据、引用、工具调用、实验结果或工程许可;
- 把 `HYPOTHESIS`/`INFERRED`/`RECOMMENDATION` 写成 `OBSERVED`;
- 复杂任务不拆分子智能体直接下结论;
- 直接宣布现场可部署而不经门槛。

## Installation / Loading

放入 `.opencode/skills/obsidian-prompt-amplifier/` 即可被 opencode 加载器发现。

## Inputs

```json
{
  "task_id": "T-xxx",
  "project_id": "P-xxx",
  "request": "用户原始请求",
  "context": {},
  "max_amplification_rounds": 2
}
```

`max_amplification_rounds` 上限 **2**(宪法第 65 条预算),超出拒绝。

## Outputs

结构化信封(见 `schemas/output.schema.json`),核心是 `findings[0]`:

- `classification` — 任务分类;
- `complexity_score` — 七维评分 + 总分 + Level;
- `tiered_plan` — 泛化/审/专项三层编组;
- `decision_path` — 运行模式、主路径、审门、升级触发、停止条件、状态落地(调动决策树);
- `amplified_prompt` — 强化提示词草案;
- `max_rounds` / `rounds_used` — 轮数;
- `constitutional_conflicts` — 检出的宪法冲突;
- `required_user_inputs` — 含人类批准项(如触发);
- `acceptance_pending` — 是否等待用户决定。

## Tools

- `tools/prompt_amplifier.py` — 唯一工具,stdin JSON → stdout JSON,离线、确定性。

## Examples

| 输入 | 关键输出 |
|---|---|
| "提高砂柱 MICP 胶结均匀性" | mechanism+data,Level 2,8 agents,审层含 QC/Red Team/Synthesizer |
| "设计现场 MICP 加固方案并部署" | `HUMAN_APPROVAL_REQUIRED`,Level 3,审层含 Environment/Reproducibility,专项层含 Scale-up |

## Testing

```bash
python -m pytest tests/ -q
```

测试覆盖:宪法至上、两轮上限、不接受=标准流程、复杂度评分、三层编组、决策路径(主路径/审门映射/升级触发/停止条件)、人类批准、输出契约、输入校验、分类。

## Safety / Approval

- 本 Skill 只分析,不执行、不写记忆、不改文件。
- 触发真实实验/现场/环境释放时返回 `HUMAN_APPROVAL_REQUIRED`,采纳强化提示词**不豁免**批准。
- 宪法冲突时站在宪法一边,向用户明示。

## Limitations

- 复杂度评分是启发式(宪法附录 B),可被领域判断覆盖;
- 只做任务入口定界与编组,不产生科研结论;
- 对已有结论的审查交给 `obsidian-red-team`。

## Versioning

- 当前版本: 1.1.0
- 契约版本: 1.0.0
- 详见 `CHANGELOG.md`。
