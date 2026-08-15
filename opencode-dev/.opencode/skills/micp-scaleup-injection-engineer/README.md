# MICP Scale-Up Injection Engineer

> 版本 1.0.1 ｜ Obsidian Plan（黑曜石计划 / Panshi 磐石）受治理专业能力
> 部署目录：`skills/micp-scaleup-injection-engineer/`

## 一、这是什么

**MICP 注入设计与工程尺度放大器**。将实验室烧杯、试样、砂柱方案逐级转换为**中型砂柱 → 米级试验 → 场地试验 → 现场施工方案**，并明确哪些参数可以相似缩放、哪些**绝不能按体积线性放大**。

放大 ≠ 线性。这是本 Skill 的核心工程纪律：

- **可以按孔隙体积线性缩放**：处理体积、PV 数、尿素/钙摩尔需求总量、CaCO₃ 质量目标。
- **必须保持不变（守恒量）**：尿素/钙摩尔浓度、孔隙流速、无量纲数（Péclet Pe、Damköhler Da、Ca 数）、停留时间（相对）。
- **必须重算/逐级确认**：注入流量（随截面积）、注入压力（随渗透率与路径）、轮次（随停留时间与反应速率）、均匀性（随尺度增大而恶化）。

**不得**将实验室最优尿素浓度、钙浓度、流量或处理轮次直接作为现场最优参数。文献依据见 [references/sources.md](references/sources.md)（Al Qabany & Soga 2013：0.5 M 最优、1 M 强度降 ~50% 且局部堵塞；van Paassen 2010：100 mM 需 20 PV 不经济，宜摩尔级）。

## 二、能力清单

| 动作 | 说明 |
|---|---|
| `scaleup` | 全流程：相似性矩阵 → 质量平衡 → 边界/压力 → 布局/调度 → 监测 → 堵塞 → 阶段门 |
| `similarity` | 仅相似性矩阵与不可相似因素 |
| `material_balance` | 孔隙体积、菌液/胶结液体积、尿素/钙摩尔、CaCO₃、NH₄⁺ |
| `boundary_check` | 恒流 vs 恒压边界检查 |
| `pressure_risk` | 注入压力 vs 地层允许压力/水力劈裂判据 |
| `injection_layout` | 井网、分区、注入/抽提/监测点 |
| `injection_schedule` | 注入顺序、脉冲、停留、轮次、冲洗 |
| `monitoring_plan` | 逐参数监测计划（位置/频率/设备/阈值/报警/停工/保存） |
| `clogging_risk` | 入口堵塞、优先流、均匀性 |
| `tracer` | 示踪突破数据分析（若有数据） |
| `stage_gate` | 阶段门决策与停工/回退 |
| `validate` | 输入校验（dry-run 门） |
| `generate_tables` | 施工参数表与监测表 |

## 三、标准工程包

```
micp-scaleup-injection-engineer/
├── SKILL.md                  # 技能说明书（OpenCode 加载器读取 frontmatter）
├── skill.yaml                # Router registry 清单（能力 token: scaleup）
├── manifest.json             # 机器清单
├── README.md                 # 本文档
├── CHANGELOG.md              # 版本历史
├── prompts/system.md         # 技能提示词
├── schemas/                  # 输入/输出/注入计划/监测计划 四份 JSON Schema
├── tools/
│   ├── scaleup.py            # stdin/stdout 入口（唯一触碰 IO 的文件）
│   └── msi/                  # 纯 Python 计算内核（stdlib + scipy 可选）
├── tests/                    # pytest 单元/集成/失败/回归/路由集成
├── evals/                    # cases.yaml + run.py + metrics.py（7 指标）
├── examples/                 # 真实可运行示例输入
└── references/sources.md     # 文献溯源（不编造）
```

## 四、契约

- **输入/输出**：`schemas/input.schema.json` + `schemas/output.schema.json`（draft 2020-12，`additionalProperties: false`）。
- **统一输出信封**（§八）：`status, summary, findings, assumptions, evidence_used, uncertainty, risks, artifacts, requested_next_skills, validation, provenance, errors` + 领域字段 `scale_level, site_assumptions, similarity_matrix, non_scalable_factors, injection_layout, injection_schedule, material_balance, pressure_constraints, monitoring_plan, stop_conditions, fallback_plan, environmental_requirements`。
- **状态枚举**：`SUCCESS | PARTIAL | BLOCKED | FAILED | NEED_ADDITIONAL_SKILL | HUMAN_APPROVAL_REQUIRED`。
- **认识论标签**：`OBSERVED | REPORTED | CALCULATED | INFERRED | HYPOTHESIS | RECOMMENDATION`。
- **错误码**：`MSI-E1xx`（输入）/`E2xx`（证据/单位）/`E3xx`（上下文）/`E4xx`（工具）/`E5xx`（权限/批准）/`E6xx`（下游）/`E7xx`（自检）/`E8xx`（兼容）。
- **版本**：`skill_version == 1.x.y`、`contract_version == 1.x`。破坏性→major，新增可选→minor，修复→patch。

## 五、人工批准门（现场施工）

任何 `scale_level == field` 的真实施工建议必须返回 `HUMAN_APPROVAL_REQUIRED`，并要求以下六项：

1. 岩土工程师批准 `site.geotechnical_approval`
2. 环境与生物安全审查 `site.biosafety_review`（氨氮、菌株释放、废液）
3. 场地法规核验 `site.regulatory_verification`（地下注入许可、地下水保护）
4. 施工风险评估 `site.construction_risk_assessment`（压力/劈裂、隆起、邻近结构）
5. 废液与氨氮方案 `site.waste_ammonia_plan`（NH₄⁺ 限值、处理/回收路径）
6. 应急预案 `site.emergency_plan`（停工、泄压、泄漏处置）

六项齐全且 `human_approval_state.granted=true` 前，任何现场数值建议都返回 `HUMAN_APPROVAL_REQUIRED`。批准后 `stage_gate` 仍独立评估工程安全（压力/氨氮/均匀性/渗透率），`gate_ok=true` 现场施工计划才能定稿。

## 六、性能指标（evals/）

| 指标 | 阈值 |
|---|---|
| M1 结构化输出通过率 | ≥ 0.95 |
| M2 工具真实调用率 | = 1.0 |
| M3 引用/数据可追溯率 | ≥ 0.9 |
| M4 缺失输入识别率 | = 1.0 |
| M5 对抗用例拦截率 | = 1.0 |
| M6 重复运行一致性 | = 1.0 |
| M7 平均失败恢复轮次 | ≤ 1.0 |

## 七、运行

```bash
# 测试
python -m pytest tests/ -q

# 评测
python evals/run.py --verbose   # 写 evals/results/latest.json

# 直接调用
python tools/scaleup.py < examples/01-lab-to-metre.json
```

## 八、与兄弟技能的关系

| 技能 | 分工 |
|---|---|
| micp-porous-media-transport | 反应运移数值模拟、渗透率演化、堵塞耦合 |
| micp-geotechnical-performance | 岩土强度/刚度/耐久性能评估 |
| micp-ureolysis-chemistry | 尿素水解化学计量、动力学 |
| micp-biology-reasoner | 菌株/脲酶机制 |
| micp-mineral-phase-interpreter | 矿相鉴定 |
| obsidian-skill-router | 能力路由（本 Skill 注册 `scaleup` token） |

## 九、已知限制

- 非尿素钙源不适用尿素化学计量。
- 场地渗透率缺失 → `BLOCKED`，绝不编造。
- 对真实地层的确定性预测超出验证范围 → `BLOCKED`。
- 均匀性预测是工程近似，最终以取芯/波速现场验证为准。
- 反应运移数值模拟不在此 Skill 内（交给 porous-media-transport）。


---

> 原 `ZIP-README.md` 已归档至 [`audit/ZIP-README.md`](audit/ZIP-README.md)。
