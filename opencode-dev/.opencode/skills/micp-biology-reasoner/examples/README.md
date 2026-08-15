# 示例

三个可运行示例，均通过真实 CLI 执行（`bash examples/run-examples.sh` 一键运行）。

| 文件 | 动作 | 演示点 |
|---|---|---|
| `01-compare-batches.json` | `compare` | 同 OD600 不同活性 → 不当作等价；活性归一化到 U/mL；标注非组成型脲酶 |
| `02-salinity-assessment.json` | `assess` | 高盐菌株适配性 → 证据等级 REPORTED（无直接数据时禁止 OBSERVED） |
| `03-treatment-strategy.json` | `assess` | 生物刺激 vs 强化 → 群落机制 + 低有机碳建议 + 高危生物安全审计请求 |

每个示例输入满足 `schemas/input.schema.json`，输出满足 `schemas/output.schema.json`。
