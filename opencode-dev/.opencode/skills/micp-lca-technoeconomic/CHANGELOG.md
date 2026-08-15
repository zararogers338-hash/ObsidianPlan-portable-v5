# Changelog — micp-lca-technoeconomic

## 1.0.0 — 2026-08-07

**首次交付**。Obsidian Plan (Panshi) 生命周期与技术经济评价能力。

### 能力
- 生命周期清单:菌种培养/培养基/尿素/钙源/水/电力/加热/搅拌/泵送/运输/管路/注入/监测/试验/废液收集/氨氮处理/清洗/维护/返工/处置。
- 环境评价:GWP、能耗、用水、氮与盐负荷、富营养化、材料消耗。
- 技术经济:CAPEX、固定/可变 OPEX、人工、能源、监测、废物处理、风险储备、停工与失败成本、单位工程量成本、规模化成本(指数 0.7)。
- 比较:同功能单位、边界对称检查 (LCA-E704)、功能单位公平性 (LCA-E705)、情景比较表。
- 不确定度:蒙特卡洛(seed 确定)、单因素 (OAT)、全局 (Morris)、Pareto 热点。
- 门控:缺功能单位 → LCA-E103;缺基准 → LCA-E104;边界不完整 → LCA-E106;实验室价外推 → LCA-E204 标记;因子过期 → LCA-E202 告警;不可核验因子 → LCA-E201 拒绝。

### 契约
- `schemas/input.schema.json`(contract_version 1.0,additionalProperties: false)
- `schemas/output.schema.json`(22 字段统一信封,含 §八 全部要求)
- `schemas/inventory.schema.json`、`schemas/cost-model.schema.json`

### 工具(纯标准库,离线,确定性)
- `tools/micp_lca.py`(stdin/stdout,信封 `{ok,tool,version,result|error}`)
- 模块:`_common` / `_jsonschema` / `errors` / `factors` / `units` / `inventory` / `cost` / `uncertainty` / `service`

### 测试与评测
- `tests/`:43 项 pytest 全绿(含 10 个强制用例 + Router 集成 `usable=true`)。
- `evals/`:12 用例全过;M1–M7 全绿(M1/M2/M3/M4/M5/M6 = 1.0,M7 = ~64 ms)。

### 接入
- Router 注册:`capabilities: ["lca"]`(裸能力 token 已内置于 planner.ts),`usable: true`,`manifest_valid: true`,0 issues。
- Controller 版本兼容:`obsidian-ctl-0.1.0`。

### 示例
- `examples/01-sandbody-lca-tea.json`:2×MICP + 1×水泥,SUCCESS(联网核验因子库后:碳排 水泥 2.38 < MICP-A 2.61,仅 MICP-B 氨回收 2.17 略低 —— **MICP 并不天然低碳**;成本 MICP 20–22 万 > 水泥 10.5 万 —— **MICP 更贵**,如实报告)。
- `examples/02-blocked-missing-fu.json`:缺功能单位 → BLOCKED LCA-E103。

### 联网核验回填(2026-08-07)
- 电力:MEE 2022 全国 0.5366 / 华北 0.6776 / 南方 0.3869 kgCO2eq/kWh(生态环境部 2024-12 公告)。
- 水泥:IEA 全球 ~0.60、中国 2020 0.62 kgCO2eq/kg;DSM CEM I EPD 0.913。
- 尿素:煤基 2.7–3.43 kgCO2eq/kg(中国主流);内蕴能耗 18.4 MJ/kg(Porter 2021)。
- CaCl₂:Ecoinvent 0.87 kgCO2eq/kg;工业价 600–950 CNY/t。
- 公路货运 WTW 0.09–0.12 kgCO2eq/t-km;柴油 GEMIS 3.03 kgCO2eq/L。
- 废液:硝化反硝化 2–5 EUR/kgN;吹脱 1.8–10 CNY/kgNH₄-N;anammox 15.6 CNY/kgNH₄-N。
- 方法学锚点:Porter 2021(现场剂量 0.6kg尿素+1.1kgCaCl2/kgCaCO3)、Naeimi & Haddad 2020(同功能单位对比)、Quan 2026(MICP 非天然碳负)。

### 已知限制
- 因子库为 2026 参考值;`references/sources.md` 中 ⚠️ 待复核 项以联网检索代理核验结果为准。
- 未做时间贴现/价格通胀;蒙特卡洛覆盖主要因子(尿素/钙源/培养基/电力/废液)。
