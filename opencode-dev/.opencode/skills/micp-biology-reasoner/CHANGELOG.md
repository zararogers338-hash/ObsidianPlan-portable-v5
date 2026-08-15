# Changelog

本 Skill 的变更记录。遵循版本兼容策略（破坏性→major，新增可选→minor，实现修复→patch）。

## 0.1.0 — 2026-08-06

初始可交付版本：

- **能力**：菌株/培养/酶活数据分析（生长曲线、一阶附着/失活拟合、Logistic 生长）、单位转换与活性归一化（U/mL、U/mL/OD600、U/g CDW、U/CFU，含量纲检查）、盐度适配性证据分级、批次比较（同 OD 不同活性）、群落策略评估（纯培养/生物刺激/混合群落）、矛盾数据指标甄别、参数敏感性弹性。
- **契约**：`schemas/input.schema.json` + `schemas/output.schema.json`（draft-07，`additionalProperties: false`），contract_version `1.0`，统一输出封套 + 认识论标签。
- **错误码**：MBR-E101…MBR-E802（见 `tools/micp_bio/errors.py`）。
- **工具**：纯 stdin→stdout CLI，离线，dry-run 感知，无硬编码路径，不联网。
- **测试**：57 个 pytest（单元/集成/失败/对抗）。
- **评测**：12 个 cases + 7 项指标，全部通过（`evals/results/latest.json`）。
- **示例**：3 个可运行示例（`bash examples/run-examples.sh`）。
- **依据**：`references/sources.md`（含检索限制与未核验声明）。

### 已知限制

- `evaluate` 的 `sensitivity` 使用线性占位模型（`linear_scale`），真实模型函数需由调用方经工具接口注入（JSON 无法携带函数）。
- 高盐适配性结论依赖文献条目 #10（未直接读到原文数值），相关机制结论标记为 REPORTED 且注明需核验。
- 附着/失活模型为一阶线性近似；非线性吸附需扩展（见 `references/sources.md` #11）。
