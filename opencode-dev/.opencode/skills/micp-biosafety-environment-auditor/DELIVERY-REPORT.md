# DELIVERY-REPORT — micp-biosafety-environment-auditor v1.0.0

交付日期：2026-08-07
位置：`.opencode/skills/micp-biosafety-environment-auditor/`
维护者：Panshi / Obsidian Plan

---

## 一、交付内容

### Skill ID / 版本
- `micp-biosafety-environment-auditor` v1.0.0（中文名：MICP 生物安全与环境风险审计器）

### 工程包（task brief §五 全部文件）
```
skills/micp-biosafety-environment-auditor/
├── SKILL.md                      # OpenCode 加载契约（frontmatter name+description）
├── skill.yaml                    # Router registry manifest（capabilities 含裸 token）
├── manifest.json                 # 打包清单
├── README.md
├── CHANGELOG.md
├── prompts/system.md             # 系统提示词（铁律：不编造法规/守恒阻止结论/不默认安全）
├── schemas/
│   ├── input.schema.json         # 统一输入信封 + 场地/方案/菌株/法规载荷
│   ├── output.schema.json        # 统一输出信封（12 字段）+ task brief §七 11 个领域字段
│   ├── risk-assessment.schema.json  # HAZARD/EXPOSURE/LIKELIHOOD/SEVERITY/CONTROL/RESIDUAL_RISK
│   └── nitrogen-balance.schema.json # 尿素氮质量平衡契约（守恒门）
├── tools/
│   ├── mbs_auditor.py            # CLI 入口（stdin JSON → stdout JSON）
│   └── mbs/                      # 纯 stdlib Python 包（11 项工具）
│       ├── errors.py             # MBS-E### 错误码
│       ├── chemistry.py          # 质量平衡/NH3 形态/废液负荷
│       ├── strain.py             # 菌株身份/生物安全分级
│       ├── regulatory.py         # 本地核验库检索（不联网）
│       ├── risk.py               # 风险矩阵/危害/监测/应急
│       ├── treatment.py          # 处理比较/采样计划/许可
│       ├── service.py            # 分派+信封+审批门+自检
│       └── validate.py           # schema 校验
├── tests/                        # pytest 59 用例（含 10 项强制测试 + router 集成）
├── evals/
│   ├── cases.yaml                # 12 评测用例
│   ├── run.py                    # 评测运行器
│   └── metrics.py                # M1–M7 指标
├── examples/                     # 3 个真实可运行示例（run-examples.sh）
└── references/
    ├── sources.md                # 法规核验记录（地区/版本/日期/来源/待核验项）
    ├── regulatory_db/            # 27 条本地法规核验记录
    ├── bootstrap-case.json       # 自举用例（完整砂柱方案）
    ├── bootstrap-case.out.json   # 自举输出
    └── bootstrap-log.md          # 自举日志
```

## 二、法规核验方式

**方法**：2026-08-07 当日 WebSearch + WebFetch 交叉核验，三个独立检索视角（生物安全菌株 / 地下水氨氮废水 / 土壤实验室安全）。官方域名 WebFetch 被环境策略拦截，改用官方镜像 + 省级主管部门转发 + 权威标准平台，**至少两个独立来源一致才记为已核验**。

**关键核验结果**（27 条记录，地区=中国）：

| 领域 | 核验结果 |
|---|---|
| 菌株安全 | S. pasteurii **不在**《人间传染的病原微生物目录(2023)》→ 单位生物安全委员会评估定级（通常 BSL-1，临时分级）；Bacillus 属仅炭疽(二类)/蜡样(三类)入名录；NY/T 1109-2017 附录A 未列 S. pasteurii → 作肥料菌种须毒理学试验 |
| 氨氮/总氮限值 | 地下水 GB/T 14848-2017 III类 NH4-N **0.50** mg/L；地表水 GB 3838-2002 III类 **1.0**；污水综合 GB 8978 一级 15/二级 25；城镇污水厂 GB 18918 一级A 5(8)/一级B 8(15)（日均） |
| 现场注入地下 | 《地下水管理条例》第40条禁渗井/渗坑/裂隙/溶洞；人工回灌不得恶化水质 → **任何 MICP 现场注入受控** |
| 氨气 | 职业接触 GBZ 2.1-2019：PC-TWA=20 / PC-STEL=30 mg/m³；厂界 GB 14554-93 二级新扩改建 1.5 mg/m³ |
| 危废 | 实验室废液 HW49 900-047-49；属性不明须危废鉴别 |
| 重大时效 | **2026-08-15《生态环境法典》施行**，废止《土壤污染防治法》《固废法》→ 相关记录 status 标注 effective-until-2026-08-15 |

**冲突处理**：GB 5084-2021 氨氮限值两处核验冲突 → 降级为未核验（`verified: false`），绝不确定论。

**无法核验项**（§四，8 项）→ 标注 `REGULATORY_VERIFICATION_REQUIRED`，禁止用于审计判定。

## 三、工具（11 项，全部实现）

| # | 工具 | 模块 | 说明 |
|---|---|---|---|
| 1 | 尿素—总氮—NH4+—NH3 质量平衡计算器 | chemistry.urea_to_nitrogen_balance | 守恒不闭合阻止结论（MBS-E301） |
| 2 | pH/温度/NH3 比例估算 | chemistry.nh3_concentration | Davies 活度校正 + Bates-Pinching pKa |
| 3 | 废液体积与污染负荷 | chemistry.waste_loading | NH4-N/NH3-N/总氮负荷 |
| 4 | 菌株信息核验适配器 | strain.verify/classify | 身份核验 + 生物安全分级 |
| 5 | 法规与标准检索适配器 | regulatory.lookup | 本地核验库，失败→REGULATORY_VERIFICATION_REQUIRED |
| 6 | 风险矩阵生成器 | risk.risk_matrix | 5×5 LOW/CRITICAL |
| 7 | 监测阈值与报警规则 | risk.monitoring_plan/alarm_rules | 比例+绝对余量双模式 |
| 8 | 废液处理方案比较 | treatment.compare_treatment_options | 高残余 NH3 不绿灯 |
| 9 | 环境采样计划生成器 | treatment.sampling_plan | 地下水/土壤/空气/废液点位 |
| 10 | 事故响应清单生成器 | risk.emergency_actions | 氨泄漏/菌释放/溢出/暴露/地下水 |
| 11 | 许可证和审批状态检查器 | treatment.permit_status | 缺失审批→HUMAN_APPROVAL_REQUIRED |

## 四、实际测试

### pytest：69 用例全绿
- **10 项强制测试**（task brief §八）全部通过：
  1. 尿素输入量与理论铵态氮计算 ✅
  2. 故意提供不守恒数据 → MBS-E301 阻止 ✅
  3. 未知菌株 → UNVERIFIED_STRAIN 门 ✅
  4. 现场地下水注入 → GROUNDWATER_INJECTION 门 ✅
  5. 废液处理能力不足 → NO_WASTE_TREATMENT 门 ✅
  6. 高 pH+高温 NH3 风险升高 → 形态计算验证（pH9.5/35°C 占 >50%）✅
  7. 法规信息过期 → REGULATORY_VERIFICATION_REQUIRED ✅
  8. 用户要求绕过审批 → 仍门控，无变通路径 ✅
  9. 敏感生态场地 → SENSITIVE_ECOLOGY 门 ✅
  10. 环境监测超阈值停工 → MONITORING_EXCEEDED + 停止条件 ✅
- 单元测试（化学/菌株/风险/处理/法规）+ 自举集成 + **Router 集成**（bun 实测注册表 usable=true + 路由命中）。

### 评测：12/12 全过，M1–M7 全达标
- M1 结构化输出通过率、M2 工具真实调用率、M3 可追溯率、M4 缺失输入识别、M5 对抗拦截、M6 复现一致、M7 恢复时间 全部通过阈值。

### 示例：3/3 真实可运行
- 密闭实验室砂柱 → SUCCESS；现场注入 → HUMAN_APPROVAL_REQUIRED；菌株核验 → SUCCESS。

## 五、自举结果（task brief §九）

用本 Skill 审查完整 MICP 砂柱方案（`references/bootstrap-case.json`）：

| 要求输出 | 结果 |
|---|---|
| 风险登记 | ✅ 2 危害（气溶胶 MODERATE、氨毒性 HIGH）带证据 |
| 氮质量平衡 | ✅ 240g 尿素 → 理论总氮 111.94g，闭合误差 -0.05% |
| 废物流 | ✅ 18L 废液，NH4-N 17.1g，总氮 18.1g，NH3-N 1.46g |
| 监测计划 | ✅ 8 参数阈值+告警 |
| 控制措施 | ✅ 工程/行政/监测/废液处理（推荐折点氯化 0.895） |
| 审批门 | ✅ MONITORING_EXCEEDED + PERSONNEL_EXPOSURE |
| 停止条件 | ✅ 3 项（超限 STOP/预警降速/审批门未过 STOP） |
| 应急响应 | ✅ 氨泄漏/人员暴露/通用三类清单 |

**正确触发人工审批门**，未因"菌株常用于 MICP"而放行。

## 六、Red Team 攻击与修复

独立 3 视角对抗审查（法规依据 / 质量守恒 / 风险淡化）+ 独立验证，**10 条确认为真实缺陷全部修复**（详见 `references/red-team-report.md`）：

| 严重度 | 缺陷 | 修复 |
|---|---|---|
| critical | 零尿素+非零路径被强制判定闭合 | 零总氮+非零路径 → MBS-E301 |
| critical | 致病菌株带保藏号返回 SUCCESS 零危害 | PATHOGENIC_STRAIN_UNCERTIFIED/STRAIN_BIOSAFETY_UNCONFIRMED/HAZARD_* 门 |
| high | 水分类未核验限值记录逃过法规门 | 分类 fully_verified 要求全部记录核验 |
| high | 计算 NH3 形态孤立不驱动危害 | computed_nh3 传入 identify_hazards |
| high | 残余风险 HIGH→LOW 淡化 | HIGH 增设 MODERATE 下限 |
| high | nh4_n_mgL 无监测阈值 | 加入阈值；未知参数 no-threshold 告警 |
| high | residual_paths 双计 NH3 潜在量 | 从 sink 集移除；schema 同步 |
| high | 现场方案省略 flags 逃逸法规门 | 从 plan 非可选信号推断场地相关 |
| medium | 用户提供挥发量被静默丢弃 | 交叉核对，冲突 → MBS-E301 |
| (防) | evaluate_against_limits 混合基质 | 判定不可达（死代码），记录在案 |

**修复后 7 个复现载荷端到端全部拦截**，回归测试 `tests/test_redteam_regressions.py` 锁定。

## 七、Registry 注册

- `obsidian-skill-router` 注册表实测：`usable=true`，`manifest_valid=true`，`issues=[]`。
- 能力 token：`biosafety` / `biosafety_ammonia` / `mass_balance`（planner.ts DOMAIN_MAP 已预置映射，本次实测请求命中）。
- 上游提示：planner.ts `UPSTREAM_HINTS` 已含 `biosafety-environment-auditor → biosafety`。
- 路由集成测试：`tests/test_router_integration.py`（bun 实测，通过）。

## 八、限制

- 法规核验库为本地维护，`verified_on` 一年内有效；需随法规变化更新。
- 处理方案性能为工程默认带，需场地/厂商实测替换。
- 监测频率/采样点位为模板，需主管部门确认。
- S. pasteurii BSL-1 为临时分级，需单位生物安全委员会 + 属地书面确认。
- 生态环境法典（2026-08-15 施行）配套规章清理中，相关记录需在清理决定后复核。
