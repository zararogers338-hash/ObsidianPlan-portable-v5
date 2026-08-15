# MGE 性能指标与测量方法

本文件定义 micp-geotechnical-performance 的最小性能指标。测量方法全部在 `tests/eval/run-evals.test.ts` 中实现,使用**真实**工具(`tools/src/cli.ts` 子命令 + 真实 schema 校验),评测路径上无 mock。

## M1 结构化输出通过率

- **定义**:通过 `schemas/output.schema.json` 校验的评测输出占比。
- **测量**:每个 EVAL 用例的输出(或 BLOCKED/FAILED 时人工构造的最小合法 envelope)都执行 schema 校验;通过数/总数。
- **最低阈值**: ≥ 0.95。

## M2 工具真实调用率

- **定义**:实际调用真实工具(而非口述假装)的用例占比。
- **测量**:评测对每个用例都真实执行 `bun tools/src/cli.ts evaluate --input <file>`,解析其 stdout。此指标恒为 1.0,作为**不变量**。
- **最低阈值**: = 1.0。

## M3 引用/数据可追溯率

- **定义**:输出 `evidence_used` 覆盖输入 `evidence_refs`/`data_refs` 的比例。
- **测量**:对提供 `evidence_refs` 的用例,检查这些 `ref_id` 是否出现在输出 `evidence_used` 中;未提供的用例视为通过。
- **最低阈值**: ≥ 0.9。

## M4 缺失输入识别率

- **定义**:缺字段样本中被逐字段指出(带获取指引)的比例。
- **测量**:`kind: missing` 且 `expected.status: FAILED` 的用例必须返回 `MGE-E101` 且 `errors[0].details.field_guidance` 非空;`expected.status: BLOCKED` 的用例必须返回 `MGE-E202` 并指明字段。
- **最低阈值**: = 1.0。

## M5 对抗用例拦截率

- **定义**:对抗样本中未产生"非法 SUCCESS"的比例。
- **测量**:`kind: adversarial` 用例全部通过其断言(含输出 schema 校验)→ 拦截。单试样夸大、50 倍无对照、NaN 曲线都不允许产出非法成功结论。
- **最低阈值**: = 1.0。

## M6 重复运行一致性

- **定义**:同输入两次运行,`findings`/`metrics`/`statistical` 等业务字段逐字节一致。
- **测量**:EVAL-01 以固定输入运行两次,比较 `evaluate` 输出的 `performance`/`statistical`/`durability`。
- **最低阈值**: = 1.0(确定性工具)。

## M7 平均失败恢复时间

- **定义**:失败用例从报告到修复的轮次。
- **测量**:当前轮次中未通过用例数 > 0 → 计 1 轮;全部通过 → 0。
- **最低阈值**: ≤ 1 轮(当前基线)。

---

## 阈值汇总

| 指标 | 阈值 | 当前实现 |
|---|---|---|
| M1 结构化输出通过率 | ≥ 0.95 | `m1` |
| M2 工具真实调用率 | = 1.0 | `m2`(不变量) |
| M3 引用可追溯率 | ≥ 0.9 | `m3` |
| M4 缺失输入识别率 | = 1.0 | `m4` |
| M5 对抗拦截率 | = 1.0 | `m5` |
| M6 重复一致性 | = 1.0 | `m6` |
| M7 失败恢复轮次 | ≤ 1 | `m7` |

运行:

```bash
bun test tests/eval/run-evals.test.ts
```

指标 JSON 写入临时目录(每次运行)并打印到 stdout(`EVAL METRICS:` 行)。
