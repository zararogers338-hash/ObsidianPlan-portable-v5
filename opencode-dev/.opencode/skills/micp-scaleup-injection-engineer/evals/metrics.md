# Eval Metrics — micp-scaleup-injection-engineer

Measured by `evals/run.py` against `evals/cases.yaml` through the real CLI
(`tools/scaleup.py`). All 7 metrics must pass for a clean delivery.

| # | 指标 | 测量方法 | 阈值 | 当前 |
|---|---|---|---|---|
| M1 | 结构化输出通过率 | 每个 CLI 输出过 `schemas/output.schema.json` | ≥ 0.95 | 1.0 |
| M2 | 工具真实调用率 | 所有用例走真实 CLI + 计算内核，无 mock | = 1.0 | 1.0 |
| M3 | 引用/数据可追溯率 | 输入 `evidence_refs` 在输出 `evidence_used` 中可追溯 | ≥ 0.9 | 1.0 |
| M4 | 缺失输入识别率 | 缺场地渗透率 → `BLOCKED`(MSI-E102) 且逐字段点名 | = 1.0 | 1.0 |
| M5 | 对抗用例拦截率 | 契约 v2 / 未知动作 / 单位冲突 / 现场未批准 全被拦截 | = 1.0 | 1.0 |
| M6 | 重复运行一致性 | 同输入两次运行 material_balance/pressure 块一致 | = 1.0 | 1.0 |
| M7 | 平均失败恢复轮次 | 当前失败用例数 | ≤ 1.0 | 0 |

## 用例覆盖（10 个强制场景）

| 用例 | 场景 | 期望 |
|---|---|---|
| eval-01 | 5cm 砂柱 → 1m 柱 | SUCCESS + 8 artifacts + similarity |
| eval-02 | 米级 → 场地（缺渗透率） | BLOCKED MSI-E102 |
| eval-03 | 恒流 vs 恒压 | SUCCESS + 边界说明 |
| eval-04 | 非均质双层（100× 渗透率反差） | 优先流 MEDIUM/HIGH，均匀性 <0.9 |
| eval-05 | 注入口堵塞（1.5M 浓度） | inlet_clogging HIGH |
| eval-06 | 超压（高流量 + 低压限） | pressure EXCEEDS |
| eval-07 | 氨氮超阈值 | environmental over_limit true |
| eval-08 | 优先流旁路 | preferential_flow HIGH |
| eval-09 | 缺场地渗透率 | BLOCKED MSI-E102 |
| eval-10 | 模拟监测触发停工回退 | RT stop + fallback 存在 |

## 额外对抗/一致性

- 对抗：contract v2、未知动作、单位冲突、现场未批准 → 全部拦截。
- 一致性：eval-01 重复运行，material_balance/pressure 块逐字节一致。

## 运行

```bash
python evals/run.py --verbose
```
