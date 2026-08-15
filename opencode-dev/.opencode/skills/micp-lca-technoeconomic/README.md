# micp-lca-technoeconomic — MICP 生命周期与技术经济评价器 v1.0.0

Obsidian Plan (Panshi) 项目下的受治理专业能力:对 MICP / 生物矿化土壤加固方案做**生命周期评价 (LCA)** 与**技术经济分析 (TEA)**,并与水泥搅拌桩 / 化学注浆等传统基准做**边界对称、功能单位公平、不确定度量化**的比较。

> **立场**:本 Skill **不默认** MICP 天然低碳、绿色或比水泥便宜。所有碳排/能耗/成本结论都来自真实计算(清单 × 因子),并强制要求功能单位与基准方案;缺任一即 BLOCKED。

---

## 一、能做什么

| 能力 | 说明 |
|---|---|
| 生命周期清单 | 菌种培养/培养基/尿素/钙源/水/电力/加热/泵送/压缩空气/运输/管路/注入/监测/试验/废液收集/氨氮处理/清洗/维护/返工/最终处置 |
| 环境评价 | 碳排 (GWP, kg CO2eq)、能耗 (MJ)、用水 (m3)、氮与盐负荷 (kg NH3-N)、富营养化 (kg PO4eq)、材料消耗 |
| 技术经济 | CAPEX / 固定 OPEX / 可变 OPEX / 人工 / 能源 / 监测 / 废物处理 / 风险储备 / 停工与失败成本 / 单位工程量成本 / 规模化成本 |
| 比较 | 与水泥 / 注浆 / 化学方案同功能单位比较;强制边界对称 (LCA-E704) 与公平功能单位 (LCA-E705) |
| 不确定度 | 蒙特卡洛(seed 确定可复现)、单因素敏感性 (OAT)、全局敏感性 (Morris)、Pareto 热点 |
| 门控 | 缺功能单位/基准 → BLOCKED;实验室试剂价当现场成本 → LCA-E204 标记;因子过期/不可核验 → 告警/拒绝 |

## 二、快速开始

```bash
# 完整管线(3 情景:2×MICP + 1×水泥)
python tools/micp_lca.py service < examples/01-sandbody-lca-tea.json

# 仅校验输入
python tools/micp_lca.py validate < input.json

# 测试(43 项,含 Router 集成)
python -m pytest tests/ -q

# 评测(12 用例 + M1–M7 指标)
python evals/run_evals.py
```

## 三、目录结构

```
skills/micp-lca-technoeconomic/
├── SKILL.md                 # 能力契约与纪律
├── skill.yaml               # Router manifest(capabilities 含裸 token "lca")
├── README.md
├── CHANGELOG.md
├── prompts/system.md        # 系统提示词
├── schemas/
│   ├── input.schema.json    # 输入契约
│   ├── output.schema.json   # 统一输出信封(22 字段,含 §八 全部要求)
│   ├── inventory.schema.json
│   └── cost-model.schema.json
├── tools/
│   ├── micp_lca.py          # CLI 唯一 stdin/stdout 入口
│   └── micp_lca/            # 纯 Python 标准库模块
│       ├── _common.py       # 信封/类型守卫
│       ├── _jsonschema.py   # draft-07 子集校验
│       ├── errors.py        # LCA-E### 错误码
│       ├── factors.py       # 因子库(带来源/地区/年份/版本/不确定度)
│       ├── units.py         # 功能单位转换器 + 量纲系统
│       ├── inventory.py     # 生命周期清单 + 环境影响
│       ├── cost.py          # CAPEX/OPEX 模型 + 规模因子 + 价格档位
│       ├── uncertainty.py   # 蒙特卡洛 + OAT/Morris + Pareto + 情景比较
│       └── service.py       # 门控管线 + 自检
├── tests/                   # pytest(43 项,含 10 个强制用例 + Router 集成)
├── evals/
│   ├── cases.yaml           # 12 个评测用例
│   ├── metrics.py           # M1–M7
│   ├── run_evals.py         # 运行器(真实 CLI 驱动)
│   └── results/latest.json  # 最近一次结果
├── examples/
│   ├── 01-sandbody-lca-tea.json      # 砂体处理:2×MICP + 1×水泥,SUCCESS
│   ├── 02-blocked-missing-fu.json    # 缺功能单位 → BLOCKED LCA-E103
│   └── run-examples.sh
└── references/
    └── sources.md           # 因子与来源(含待证标记)
```

## 四、Router / Controller 接入

- **能力 token**:`lca`(planner.ts `DOMAIN_MAP` 第 108 行已把 `全生命周期|LCA|成本|经济|技术经济|碳` 映射为 `lca`;`UPSTREAM_HINTS["lca-technoeconomic"]="lca"` 已存在)。
- **Registry**:`skill.yaml` 声明 `capabilities: ["lca"]`,`inputs_required` 只列 Router 可供给字段(7/7),`dependencies` 为字符串数组 → `usable: true`。
- **Controller**:`controller_version` 兼容 `obsidian-ctl-0.1.0` 格式。

验证:

```bash
cd skills/obsidian-skill-router
bun tools/bin/osr.ts registry --build --roots ../../skills
# 应看到 micp-lca-technoeconomic usable=true, 0 issues
```

## 五、统一输出(§八)

`status / functional_unit / system_boundary / baseline / inventory / environmental_results / cost_results / hotspots / scenario_comparison / sensitivity / uncertainty / limitations / recommendations / artifacts / validation / provenance / errors / requested_next_skills`(外加信封字段)。

## 六、限制与诚实声明

- 因子库为 2026 参考值,正式报告须以 `references/sources.md` 逐因子核验;不得直接宣称"绿色/低碳"。
- 未做时间贴现与价格通胀(v1 局限)。
- 蒙特卡洛仅覆盖主要材料/电力/废液因子;运输与其它因子不确定度未计入。
- 生物学路径的菌种排放未单独建模(计入培养能耗)。
- 成本依赖调用方声明的设备利用率与现场条件;未核验时标 INFERRED。

## 七、许可

MIT(项目约定,见仓库根 LICENSE)。维护者:Panshi / Obsidian Plan。
