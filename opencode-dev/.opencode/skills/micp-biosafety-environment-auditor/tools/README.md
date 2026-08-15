# micp-biosafety-environment-auditor — 工具

纯 Python 3.10+ 标准库实现，**完全离线**。单一 CLI 入口 `tools/mbs_auditor.py`（stdin JSON → stdout JSON），信封 `{status, ..., errors, ...}`，exit 0（信封已产生）或 2（stdin 非 JSON）。

```bash
python tools/mbs_auditor.py < payload.json
python tools/mbs_auditor.py --output /tmp/out.json < payload.json   # evals 用
```

## 动作与工具

| 动作 | 工具/模块 | 用途 |
|---|---|---|
| `audit` | service._handle_audit | 完整审计：危害/暴露/氮平衡/废物流/法规/监测/控制/残余风险/审批门/停止条件/应急 |
| `mass_balance` | chemistry.urea_to_nitrogen_balance | 尿素→总氮→NH4+→NH3 质量平衡；不闭合阻止结论（MBS-E301） |
| `nh3_speciation` | chemistry.nh3_concentration | pH/温度/离子强度 → 游离 NH3 占比与浓度 |
| `waste_loading` | chemistry.waste_loading | 废液体积与 NH4-N/NH3-N/总氮污染负荷 |
| `strain_verify` | strain.classify_biosafety | 菌株身份核验 + 生物安全分级；常用 MICP 菌不默认安全 |
| `regulatory_lookup` | regulatory.lookup_regulation | 本地核验库检索；失败/过期 → REGULATORY_VERIFICATION_REQUIRED |
| `risk_matrix` | risk.risk_matrix | 5×5 风险矩阵 |
| `monitoring` | risk.monitoring_plan / alarm_rules | 监测阈值 + 报警规则 + 停工判断 |
| `treatment_compare` | treatment.compare_treatment_options | 废液处理方案比较；高残余 NH3 方案不绿灯 |
| `sampling_plan` | treatment.sampling_plan | 环境采样计划模板 |
| `emergency` | risk.emergency_actions | 事故响应清单 |
| `permit_check` | treatment.permit_status | 许可证/审批状态检查 |

## 包结构（tools/mbs/）

- `errors.py` — MBS-E### 错误码分类（1xx 输入/2xx 法规菌株/3xx 守恒/4xx 工具/5xx 审批/6xx 下游/7xx 自检/8xx 版本）
- `chemistry.py` — 质量平衡、NH3 形态、废液负荷
- `strain.py` — 菌株身份与生物安全分级（RG-1~4、BSL-1~4、致病标记筛查）
- `regulatory.py` — 本地核验库（`references/regulatory_db/`）检索、时效判定、场地相关分类核验
- `risk.py` — 风险矩阵、危害识别、暴露路径、残余风险、监测告警、应急
- `treatment.py` — 处理方案比较、采样计划、许可状态
- `service.py` — 分派、统一信封、审批门、自检
- `validate.py` — jsonschema 校验（jsonschema 可用时）+ 内置回退

## 安全属性

- 不联网、不写文件（除非 `--output`）。
- 数值工具拒绝 NaN/Inf/越界。
- 法规检索失败不编造 → `REGULATORY_VERIFICATION_REQUIRED`。
- 11 类审批门 → `HUMAN_APPROVAL_REQUIRED`；不提供绕过许可/生物安全/废物处理的方案。
