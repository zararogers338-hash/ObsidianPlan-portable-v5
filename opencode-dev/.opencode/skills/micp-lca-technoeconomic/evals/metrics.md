# 评测指标 (M1–M7) — micp-lca-technoeconomic

指标测量方法、阈值与实现位置。实现于 `evals/metrics.py`(测量)与 `evals/run_evals.py`(运行)。

| 指标 | 测量方法 | 最低阈值 | 实现 |
|---|---|---|---|
| M1 结构化输出通过率 | 全部评测输出过 `output.schema.json` 自检(passed)或 BLOCKED 信封(pending) | ≥ 0.95 | `run_case` 中 `check("output_schema", ...)` |
| M2 工具真实调用率 | 每个评测用例经真实 CLI 子进程驱动;SUCCESS 用例产生 `artifacts` | = 1.0 | `_invoke` 子进程调用 `micp_lca.py service` |
| M3 引用/数据可追溯率 | SUCCESS 输出的 `provenance.factors` 非空,覆盖实际使用的因子 | ≥ 0.9 | `run_suite.traceable_outputs` |
| M4 缺失输入识别率 | 分别删除 functional_unit / baseline,均须 BLOCKED 且 detail 指名该字段 | = 1.0 | `_measure_missing_input` |
| M5 对抗用例拦截率 | 实验室价外推(标记)、过期因子(告警)、缺功能单位(阻断)、缺基准(阻断) | = 1.0 | `_measure_adversarial` |
| M6 重复运行一致性 | 固定 `LCA_TEST_CLOCK` 下同输入两次运行,输出信封逐字节一致 | = 1.0 | `_repeat_consistency` |
| M7 平均失败恢复时间 | 5 次畸形输入从 stdin 到有效信封的平均墙钟(ms) | ≤ 2000 ms | `_recovery_mean_ms` |

运行:`python evals/run_evals.py [--verbose]` → `evals/results/latest.json`。
