# micp-instrumentation-qc — 性能指标与测量方法

指标定义、测量方法与最低阈值（对应 SKILL.md §9）。全部指标在
`evals/run_evals.py` 中实现并真实执行。

| 指标 | 测量方法 | 最低阈值 |
|---|---|---|
| 结构化输出通过率 | 所有评测用例的输出必须是合法 JSON 且含 `qc_report`（或 `errors`）；由 CLI 自身保证 JSON 序列化 + `test_schema.py` 用 jsonschema 严格校验 envelope | ≥ 0.95 |
| 工具真实调用率 | 每个用例通过 `tools/cli.py` 子进程真实执行（`run_case` 用 `subprocess.run`），无 mock；这是不变量 | = 1.0 |
| 引用/数据可追溯率 | 输出 `evidence_used` 必须能回溯到输入 `data_refs`/`evidence_refs`（CASE-09 验证不可解析引用被拦截）；输出 `provenance.tools_used` 列出真实工具 | ≥ 0.9 |
| 缺失输入识别率 | `drop_fields` 用例（CASE-04/05）必须被拒绝（MICQ-E1001）且 `details.missing` 逐字段给出 why/how | = 1.0 |
| 对抗用例拦截率 | adversarial 类别（CASE-09/10）绝不允许产生 `overall_passed=true` | = 1.0 |
| 重复运行一致性 | 每个用例连续运行两次，输出必须逐字节一致（确定性，时间戳固定注入） | = 1.0 |
| 平均失败恢复时间 | 回归守卫：本次评测必须全部通过；若出现失败，按 SKILL.md 自举流程修复后重跑，阈值 ≤ 1 轮 | ≤ 1 轮 |

运行：
```
cd skills/micp-instrumentation-qc
python evals/run_evals.py
```

阈值达标记录见 `../CHANGELOG.md` 与交付报告。
