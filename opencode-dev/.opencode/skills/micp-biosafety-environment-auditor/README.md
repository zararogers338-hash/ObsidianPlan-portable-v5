# micp-biosafety-environment-auditor

**MICP 生物安全与环境风险审计器**（v1.0.0）

Obsidian Plan（黑曜石计划 / Panshi 磐石）的 MICP 生物安全与环境风险审计权威。对 MICP 砂柱/现场方案做**质量守恒约束 + 法规核验约束**的风险审计，产出带认识论标签、可追溯、机器可读的结论与明确的人工审批门。

## 能力

- **菌株审计**：身份核验（名称 + 保藏号/来源）、生物安全分级、致病标记筛查、国家病原名录现场核验要求。
- **氮质量平衡**：尿素→理论总氮→NH₄⁺ 上限→NH₃ 潜在量→液相残留/吸附滞留/排放处理；**守恒不成立阻止环境结论**（MBS-E301）。
- **NH₃ 形态分布**：pH/温度/离子强度 → 游离氨占比（Davies 活度校正 + Bates-Pinching pKa）。
- **废物流**：体积、NH₄-N/NH₃-N/总氮负荷；处理方案比较（折点氯化/生物硝化反硝化/鸟粪石/RO/吹脱/外运）。
- **法规核验**：本地核验库（`references/regulatory_db/`）——每记录含地区/名称/文号/日期/核验日/来源；**空库或过期 ≠ 已验证**；检索失败标记 `REGULATORY_VERIFICATION_REQUIRED`。
- **风险**：5×5 矩阵（LOW/MODERATE/HIGH/CRITICAL）、危害识别、暴露路径、残余风险（CRITICAL 永不降至 LOW 以下）。
- **监测与应急**：监测阈值、报警规则、停止条件、采样计划、事故响应清单。
- **审批门**：11 类触发 → `HUMAN_APPROVAL_REQUIRED`；**不提供绕过许可/生物安全/废物处理的方案**。

## 工具

`tools/mbs_auditor.py`（纯 Python stdlib，stdin JSON → stdout JSON，完全离线）。动作：`audit` / `mass_balance` / `nh3_speciation` / `waste_loading` / `strain_verify` / `regulatory_lookup` / `risk_matrix` / `monitoring` / `treatment_compare` / `sampling_plan` / `emergency` / `permit_check`。

```bash
python tools/mbs_auditor.py < payload.json
```

## 工程包结构

```
skills/micp-biosafety-environment-auditor/
├── SKILL.md                      # OpenCode 加载契约（frontmatter name+description）
├── skill.yaml                    # Router registry manifest
├── manifest.json                 # 打包清单
├── README.md
├── CHANGELOG.md
├── prompts/system.md
├── schemas/
│   ├── input.schema.json
│   ├── output.schema.json
│   ├── risk-assessment.schema.json
│   └── nitrogen-balance.schema.json
├── tools/
│   ├── mbs_auditor.py            # CLI 入口
│   └── mbs/                      # 纯 stdlib Python 包
│       ├── errors.py             # MBS-E### 错误码
│       ├── chemistry.py          # 质量平衡 / NH3 形态 / 废液负荷
│       ├── strain.py             # 菌株身份与生物安全分级
│       ├── regulatory.py         # 本地核验库检索（不联网）
│       ├── risk.py               # 风险矩阵 / 危害 / 监测 / 应急
│       ├── treatment.py          # 处理方案比较 / 采样计划 / 许可
│       ├── service.py            # 分派 + 统一信封 + 审批门
│       └── validate.py           # schema 校验（jsonschema + 内置回退）
├── tests/                        # pytest（46 个用例，含 10 项强制测试）
├── evals/
│   ├── cases.yaml                # 12 个评测用例
│   ├── run.py                    # 评测运行器（M1–M7 指标）
│   └── metrics.py
├── examples/                     # 真实可运行示例
└── references/
    ├── sources.md                # 法规核验记录（地区/版本/日期/来源）
    └── regulatory_db/            # 本地法规核验库（JSON 记录）
```

## 标准识别

- **OpenCode 原生加载器**：扫描 `{skill,skills}/**/SKILL.md`，frontmatter `name`（小写连字符、= 目录名）+ `description`（见 `packages/opencode/src/skill/index.ts`）。
- **Router registry**（`obsidian-skill-router/tools/osr/registry.ts`）：消费 `skill.yaml`；`capabilities` 含裸 token（`biosafety`/`biosafety_ammonia`/`mass_balance`），`inputs_required` 只列 router 可供给字段，所有数组字段为字符串数组。`planner.ts` 的 DOMAIN_MAP 已把 `生物安全|biosafety|环境影响|氨气泄漏|安全评估` → `biosafety`、`氨|铵|ammon` → `biosafety_ammonia`、`质量守恒|质量平衡|mass balance` → `mass_balance` 映射到本 Skill。

## 状态与信封

- status 枚举：`SUCCESS` / `PARTIAL` / `BLOCKED` / `FAILED` / `NEED_ADDITIONAL_SKILL` / `HUMAN_APPROVAL_REQUIRED`。
- 统一信封 12 字段（spec §六）+ 领域字段 `hazards/exposure_pathways/nitrogen_balance/waste_streams/regulatory_context/monitoring_requirements/control_measures/residual_risk/approval_requirements/stop_conditions/emergency_actions`（task brief §七）。

## 测试与评测

- `python -m pytest tests/` —— 69 用例（含 10 项强制测试 + Red Team 回归 RT1-RT9：尿素→NH₄⁺ 计算、不守恒数据、未知菌株、地下水注入、废液处理不足、高 pH 高温 NH₃、法规过期、绕过审批、敏感生态、超阈值停工）。
- `python evals/run.py` —— 12 用例 + M1–M7 指标（结构化输出通过率/工具真实调用率/可追溯/缺失输入识别/对抗拦截/复现一致/恢复时间）。

## 限制

- 法规检索走**本地核验库**（不联网）；核验库需持续维护（`verified_on` 一年内有效）。
- 处理方案性能为工程默认带；应替换为场地/厂商实测。
- 监测频率与采样点位为模板；需主管部门确认。
- 不执行真实实验、不部署、不写长期知识库（除非人工批准）。

## 维护

Panshi / Obsidian Plan。License: MIT（项目约定，见仓库根 LICENSE）。
