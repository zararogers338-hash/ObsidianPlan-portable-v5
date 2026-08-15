# Delivery Report — micp-lca-technoeconomic v1.0.0

> 交付日期:2026-08-07。仓库:opencode-src/opencode-dev (OpenCode fork, Obsidian Plan / Panshi)。

## 1. 交付物清单

| 类别 | 内容 | 状态 |
|---|---|---|
| Skill 包 | `skills/micp-lca-technoeconomic/` 完整工程包 | ✅ |
| SKILL.md | 能力契约(触发/反触发/边界案例/纪律/错误码/指标/版本策略) | ✅ |
| skill.yaml | Router manifest,`capabilities: ["lca"]`,`usable: true` | ✅ |
| schemas | input / output / inventory / cost-model 四个契约 | ✅ |
| tools | `micp_lca.py` + 9 个纯标准库模块 | ✅ |
| tests | 43 项 pytest(含 10 个强制用例 + Router 集成) | ✅ 全绿 |
| evals | 12 用例 + M1–M7 指标 | ✅ 全绿 |
| examples | 2 个真实示例 + runner | ✅ 跑通 |
| references | sources.md(因子来源)、bootstrap-log.md(自举+Red Team) | ✅ |
| prompts | system.md | ✅ |
| README / CHANGELOG | 文档 | ✅ |

## 2. 工具(§七 全部实现)

| 工具 | 模块 | 说明 |
|---|---|---|
| 生命周期清单计算器 | inventory.py | 按功能单位归一化,覆盖 20+ 流程 |
| 功能单位转换器 | units.py | 量纲系统 + 参考流/分析规模归一化 |
| 材料/能源因子管理器 | factors.py | 50+ 因子,带来源/地区/年份/版本/不确定度 |
| 成本数据库接口 | factors.py (cost.*) + cost.py | 工业价 + 档位 + 报价覆盖 |
| CAPEX/OPEX 模型 | cost.py | CAPEX/固定/可变/风险储备/停工失败 |
| 规模因子工具 | cost.py scale_up_cost | 指数 0.7 |
| 运输影响计算器 | inventory.py | 质量×距离 → t-km |
| 废液处理情景工具 | inventory.py | nitrification/stripping/anammox/none |
| Monte Carlo 不确定性分析器 | uncertainty.py | seed 确定,对数正态,90% 区间 |
| 单因素/全局敏感性 | uncertainty.py | OAT + Morris |
| 情景比较工具 | uncertainty.py compare_scenarios | 跨情景指标表 + 最优识别 |
| Pareto/热点报告生成器 | uncertainty.py pareto_hotspots | 累计份额 + 80% 前沿 |

## 3. 因子来源

- `references/sources.md` 逐因子登记来源 id/地区/年份/状态(已核验/待证),每条附 URL/DOI。
- **联网核验已完成**(研究代理 35 次检索):电力(MEE 2022 公告)、水泥(IEA/EPD)、尿素(煤基 2.7–3.43)、CaCl₂(Ecoinvent)、运输(GEMIS/WTW)、废液处理(中国全规模成本)、Porter2021/Naeimi&Haddad2020/Quan2026 方法学锚点。
- 已核验:ISO 14040/14044/15686-5、IPCC 2006、尿素水解化学计量、DEFRA/GEMIS 燃料因子、CML 富营养化。
- 待证(不得引用):乳酸钙/乙酸钙 GWP 与价格、MICP 现场级每 m³ GWP 标准值。

## 4. 运行命令

```bash
# 测试
cd skills/micp-lca-technoeconomic && python -m pytest tests/ -q          # 43 passed
# 评测
python evals/run_evals.py                                                # 12 cases + M1-M7 全绿
# 示例
bash examples/run-examples.sh
# Router 注册验证
cd skills/obsidian-skill-router && bun tools/bin/osr.ts registry --build \
  --roots ../../skills                                                   # usable=true, 0 issues
```

## 5. 自举日志

见 `references/bootstrap-log.md`。要点:

- Claude 以本 Skill 身份完成砂体处理 LCA/TEA(2×MICP + 1×水泥)。
- Red Team 审查 5 点:边界偏向(MICP 含设备、水泥未含 → 已声明限制 + 不对称检查)、漏氨氮(未漏,route=none 仍报告负荷)、不公平功能单位(公平,同一 FU)、实验室价当现场价(未,lab_catalogue → LCA-E204)、隐藏不确定性(碳排完整,成本 MC 列 v1 限制)。
- **发现并修复真实缺陷**:边界不对称检查结果原先未写入输出信封,现已并入 `limitations` 并有回归测试锁定。

## 6. Registry 注册情况

- `indexRegistry` 动态扫描命中:✅
- `validateManifest`:`version=1.0.0` ✅;`capabilities/inputs_required/outputs/domain_keywords/dependencies` 全为字符串数组 ✅;`risk_tier/network` 合法 ✅
- `usable: true`、`manifest_valid: true`、`issues: []`
- planner 路由:请求「全生命周期评价(LCA)与技术经济分析」→ `capabilities=[lca]` → 组合 `micp-lca-technoeconomic`,SUCCESS
- Router 输入侧约束:`controller_version` 须为 `X.Y.Z`(Router input schema),本 Skill 的 `compatible_controller` 已兼容

## 7. 限制(诚实声明)

1. 因子库为 2026 参考值;正式报告须逐因子核验 `references/sources.md`,不得直接宣称"绿色/低碳"。
2. 未做时间贴现与价格通胀(v1 局限)。
3. 蒙特卡洛覆盖主要材料/电力/废液因子;运输等其余因子不确定度未计入。
4. 生物学路径菌种排放未单独建模(计入培养能耗)。
5. 成本依赖调用方声明的设备利用率、单价与现场条件;未核验时结论标 INFERRED。
6. 水泥基准未含搅拌桩机折旧等 CAPEX 细项(与 MICP 情景的 CAPEX 口径差异),已声明为边界限制。

## 8. 遗留项

- `micp-data-analyst` 等下游:若需对结果做统计分析,输出 `requested_next_skills` 已指向。
- 联网检索代理的最终因子核验结果将回填 `references/sources.md` 与 `factors.py` 的注释。
