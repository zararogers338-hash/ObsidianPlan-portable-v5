# 性能指标 — micp-experiment-designer

本 Skill 的最小性能指标、测量方法与最低阈值。均由 `evals/run_evals.py` 依据 `evals/cases.yaml` 执行与统计。

| 指标 | 测量方法 | 最低阈值 |
|---|---|---|
| 结构化输出通过率 | evals:通过 `validate` 校验的输出信封数 / 总输出数 | ≥ 95% |
| 工具真实调用率 | 记录 `validation.tool_calls` 中真实调用的工具数 ≥ 2 的运行占比 | 100% |
| 引用/数据可追溯率 | OBSERVED/REPORTED 陈述带非空 `source` 的比例 | 100% |
| 缺失输入识别率 | 埋设缺失字段被 `missing_inputs` 检出的比例 | ≥ 90% |
| 对抗用例拦截率 | 对抗用例(missing control、单位诱饵、标签膨胀、预算不可能)被阻断或标记的比例 | ≥ 90% |
| 重复运行一致性 | 相同输入两次运行 → 相同状态与相同设计 | 100%(确定性工具) |
| 平均失败恢复时间 | 可修复用例从 FAILED 到修正 PASS 的中位迭代次数 | ≤ 2 次迭代 |

## 测量说明

- **结构化输出通过率**:每个 tool 返回的 `result` 子集用 `validate`(target=inline 或输出 schema)校验。
- **工具真实调用率**:SKILL.md 流程步骤 4 的 5 个工具若被实际执行,输出信封的 `validation.tool_calls` 会记录;evals 检查该记录 ≥ 2。
- **重复运行一致性**:每个 tool 用例运行两次,比较 exit code、`ok` 与 `result` 的规范化 JSON(排序键)。
- **缺失输入识别率**:`sop_check` 对缺失对照/重复/端点的设计返回 `blocking_issues`;被检出的埋设缺失数 / 埋设总数。
- **平均失败恢复时间**:人工在可修复用例上修补输入的迭代数中位数(evals 记录首次失败到下次通过的工具调用次数)。

## 报告

每次 `run_evals.py` 运行输出一份 JSON 汇总到 `audit/evals-latest.json`,并在 stdout 打印每项指标得分与是否达到阈值。
