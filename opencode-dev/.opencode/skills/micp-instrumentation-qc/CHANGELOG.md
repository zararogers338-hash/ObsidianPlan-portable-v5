# CHANGELOG

## 1.0.0 (2026-08-06)

初始发布。

### 能力
- 校准曲线与不确定度计算器:`tools/calibration.py`
  (OLS 线性回归、残差标准差、R²、LOD=3.3σ/S、LOQ=10σ/S、k=2 扩展不确定度)。
- 控制图与漂移检测器:`tools/control_chart.py`
  (Shewhart |z|≥3/≥2、7 点同侧、6 点单调、超量程、饱和、基线异常、时间戳错位)。
- 样品链与条码工具:`tools/sample_chain.py`(Code-39 Modulo-43 校验、重复编号检测)。
- 原始/派生数据校验和与审计日志:`tools/integrity.py`(SHA-256、追加式哈希链、篡改检测)。
- 仪器数据格式标准化适配器:`tools/adapters.py`(CSV/TSV 解析、单位归一化)。
- 全管线编排 + 信封校验:`tools/qc_pipeline.py`(必需字段、版本门、schema、evidence 核验)。

### 契约
- `schemas/input.schema.json` / `schemas/output.schema.json` v1.0.0。
- 错误码 `MICQ-E1001…E1011`;状态 `SUCCESS/PARTIAL/BLOCKED/FAILED/
  NEED_ADDITIONAL_SKILL/HUMAN_APPROVAL_REQUIRED`。

### 质量
- 75 个测试(单元/集成/schema/回归)通过。
- 12 个评测用例(正常/缺失/冲突/对抗/边界)全部通过。
- 性能指标:结构化输出通过率、工具真实调用率、数据可追溯率、缺失输入识别率、
  对抗拦截率、重复一致性、平均失败恢复时间,见 `evals/metrics.md`。

### 已知限制
- 校准统计为简化 GUM/分析化学公式,供 QC 辅助;正式计量以实验室 LIMS 为准。
- 摩尔浓度与质量浓度分属不同维度,需摩尔质量换算时交给下游分析 Skill。
- 审计哈希链非对抗性密码学方案。
