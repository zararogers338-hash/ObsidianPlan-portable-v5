# 📦 先读我 —— 这个 zip 是干什么的

**这是 Obsidian Experiment Designer 技能包（MICP Experiment Designer）v1.0.0。**

它把一张「假设卡」(Hypothesis Card) 或一句模糊的研究目标,转变成一份**可执行、可复现、有对照、有统计效力、有停止条件**的实验方案与 SOP(标准操作流程),并产出机器可读 JSON 供 Obsidian 控制器 / Router 消费。

---

## 快速上手(3 步)

```bash
# 1. 解压到任意可被 skill 发现的位置
#    建议: <项目>/.opencode/skills/micp-experiment-designer/

# 2. 让工具真正跑起来(示例: 两样本均值设计的样本量)
echo '{"design":{"kind":"two_group_means","delta":1.5,"sigma":2.0}}' \
  | python skills/micp-experiment-designer/tools/doe_power.py

# 3. 跑测试 + 评测 + 自举(全部离线,无需联网,无需第三方包)
python -m unittest discover -s tests -p "test_*.py"
python evals/run_evals.py
python tests/test_bootstrap.py
```

---

## 里面有什么

| 组件 | 路径 | 用途 |
|---|---|---|
| 身份与流程 | `SKILL.md` | 何时触发/不触发、硬规则、流程、错误码、工具权限、性能指标、版本策略 |
| 机器可读元数据 | `manifest.json` | 版本、入口、工具清单、权限、离线/确定性声明 |
| 输入/输出契约 | `schemas/input.schema.json` `schemas/output.schema.json` | 严格 JSON Schema(控制器 ↔ 本 Skill) |
| 最小系统提示词 | `prompts/system.md` | Skill 作为独立 agent 的身份/流程/认识论(不复制整个 Panshi 宪法) |
| **6 个工具** | `tools/cli.py` 等 | DOE/功效、随机化、用量计算、SOP 生成/检查、预注册、schema 校验 |
| 测试 | `tests/` | 33 项单元/集成/失败/回归测试(已全部通过) |
| 评测 | `evals/cases.yaml` `evals/run_evals.py` | 10 个评测用例,结构化输出通过率 100% |
| 自举测试 | `tests/test_bootstrap.py` | 任务规定的 4 个自举场景,全部 PASS |
| 运行示例 | `examples/` | 3 个可直接运行的输入信封 |
| 领域依据 | `references/sources.md` | 文献/标准来源(带访问日期与限制) |
| 审计记录 | `audit/` | 本次真实运行的自测日志 |

## 关键设计

- **纯 Python 标准库 ≥3.10,离线、确定性**:相同输入 → 相同输出。可选 scipy 增强统计精度,不装也能跑。
- **不伪造任何东西**:缺失对照组、重复 <2、端点无单位、预算不足——都**阻断**(返回 BLOCKED/取舍说明),绝不编造。
- **认识论标签**:OBSERVED / REPORTED / CALCULATED / INFERRED / HYPOTHESIS / RECOMMENDATION。
- **MICP 纪律**:尿素路径强制铵/氮质量守恒;非尿素路径不得套用尿素模型。

## 版本

v1.0.0 · 2026-08-06 · MIT License · 遵循仓库 `obsidian-mission-lock` 的工程包约定(项目自定义标准)。
