# Examples — micp-scaleup-injection-engineer

全部示例都是**真实可运行**的 CLI 输入。运行：

```bash
python tools/scaleup.py < examples/01-lab-to-metre.json
```

## 01-lab-to-metre.json — 实验室柱试 → 米级砂柱（自举案例）

这是自举案例的标准输入：从 5 cm 砂柱（0.5 M 尿素/CaCl₂、1 PV、5 轮、0.5 L/s）
放大到 1 m 砂柱（0.05 m³ 处理体积、0.02 m³ 孔隙体积）。

CLI 输出（`work/ex01_out.json`）中的关键结果：

| 量 | 值 | 认识论 | 依据 |
|---|---|---|---|
| 处理体积 / 孔隙体积 | 0.05 m³ / 0.02 m³ | CALCULATED | geometry×porosity |
| 目标 CaCO₃ | 60 kg/m³ → 3.0 kg | CALCULATED | VP2010 锚点 |
| 尿素 / 钙 | 60 mol（各） | CALCULATED | 化学计量 × 转化率 0.5 |
| NH₄-N 产出 | ~84 000 mg/L（保守，按注入尿素计） | CALCULATED | 2 NH₄-N / 尿素（保守计量） |
| 注入压力 | **EXCEEDS**（dP ~9.4 bar） | CALCULATED | 0.5 L/s 不能直接搬到 1 m 柱 |
| 均匀性 | 0.60（MEDIUM 堵塞 / LOW 优先流 + 尺度惩罚） | INFERRED | 尺度相关 |
| 轮次 | 5 | RE-DERIVED | 实验室轮次需按停留时间重算 |
| 停工条件 | 5 条 + 回退方案 | RECOMMENDATION | 阶段门模板 |

**核心工程结论**：实验室 0.5 L/s 的流量在 1 m 柱上会产生超压 —— 流量必须
**按截面重算**（保持孔隙流速），而不是按体积线性放大。这正是本 Skill 的
"不可相似因素"纪律。本示例输出 `PARTIAL`（阶段门因压力 EXCEEDS 阻塞）——这是
**诚实结果**：一个超压方案不应该报 SUCCESS。

## 02-metre-to-site.json — 米级 → 场地（100 m³ 双层）

双层（细砂 5e-11 m² / 粉砂 2e-12 m²，25× 反差）→ 分区注入 + 优先流警示
（uniformity 0.53）。压力 OK。保守氨氮 108 000 mg/L 超限（limit 100）+ 均匀性
不足 → 阶段门阻塞，输出 `PARTIAL` —— 提示需要分区 + 废液方案后方可放行。

## 03-field-approval-gate.json — 现场施工触发人工批准门

`scale_level=field` 且 `human_approval_state.granted=false` → `HUMAN_APPROVAL_REQUIRED`
（MSI-E502），要求六项审批：岩土工程师批准、环境与生物安全审查、场地法规核验、
施工风险评估、废液与氨氮方案、应急预案。

## 验证

三个示例全部通过 `tests/` 与 `evals/`（10/10，7 指标全绿）。示例 01/02 返回
`PARTIAL` 是诚实结果（阶段门捕捉到压力超限/氨氮超限/均匀性不足），示例 03
返回 `HUMAN_APPROVAL_REQUIRED` 是审批门正确生效。
