# Examples — micp-lca-technoeconomic

真实可运行的输入示例(通过真实 CLI 验证)。

## 01-sandbody-lca-tea.json

**砂体处理方案 LCA + 技术经济分析**。两个 MICP 情景 + 一个水泥基准,统一功能单位(处理 1 m3 砂体至 UCS ≥ 1.0 MPa,5 年服务期)。

- `micp-a-standard`:工业尿素 + CaCl2,废液硝化处理。
- `micp-b-ammonia-recovery`:同 A,废液氨吹脱回收。
- `cement-dsm`:水泥搅拌桩基准,含施工废浆处置。

运行:

```bash
python tools/micp_lca.py service < examples/01-sandbody-lca-tea.json
```

实测结果(2026-08-07,联网核验因子库默认值):

| 情景 | GWP (kgCO2eq) | 能耗 (MJ) | 氮负荷 (kg NH3-N) | 总成本 (CNY/100m3) |
|---|---|---|---|---|
| cement-dsm | 2.38 | 17.7 | 0.00 | 104,651 |
| micp-a-standard | 2.61 | 11.6 | 18.65 | 201,465 |
| micp-b-ammonia-recovery | 2.17 | 12.0 | 18.65 | 220,727 |

热点(micp-a):尿素 47%、废液处理 38%、钙源 10%。**结论不偏袒 MICP:情景 A 的碳排略高于水泥(尿素+CaCl2+氨氮处理),仅情景 B(氨回收)略低;MICP 成本明显更高,且氮负荷必须处理。**

## 02-blocked-missing-fu.json

缺功能单位的请求 → `BLOCKED` + `LCA-E103`(任何正式计算必须先定义功能单位)。

## run-examples.sh

自动跑通全部示例并断言信封形状:

```bash
bash examples/run-examples.sh
```
