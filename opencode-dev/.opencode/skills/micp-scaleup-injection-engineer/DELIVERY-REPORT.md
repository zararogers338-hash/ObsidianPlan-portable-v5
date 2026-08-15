# DELIVERY-REPORT — micp-scaleup-injection-engineer v1.0.1

> 交付日期：2026-08-07 ｜ Obsidian Plan（Panshi 磐石）受治理专业能力
> 位置：`skills/micp-scaleup-injection-engineer/`（opencode-dev fork）

## 一、交付内容

### 工程包（完整标准结构）
```
micp-scaleup-injection-engineer/
├── SKILL.md                    # 技能说明书（OpenCode 加载器 frontmatter: name+description）
├── skill.yaml                  # Router registry 清单（capabilities: [scaleup]，8 数组字段全字符串）
├── manifest.json               # 机器清单
├── README.md                   # 工程文档
├── CHANGELOG.md                # v1.0.0 初始 + v1.0.1 审查修复
├── prompts/system.md           # 技能提示词
├── schemas/                    # input / output / injection-plan / monitoring-plan 四份 JSON Schema
├── tools/
│   ├── scaleup.py              # stdin/stdout 入口（唯一触碰 IO 的文件）
│   └── msi/                    # 纯 Python 计算内核（13 模块）
├── tests/                      # 6 个测试文件，81 测试
├── evals/                      # cases.yaml(10) + run.py + metrics.py(7 指标) + metrics.md
├── examples/                   # 3 个真实可运行示例
├── references/sources.md       # 文献溯源（带 DOI/URL，零伪造）
└── work/                       # BOOTSTRAP-REPORT + REVIEW-FIXES-REPORT
```

### 工具（11 项全部实现）
1. 注入体积和质量平衡计算器（`material.py`）
2. 恒流/恒压边界检查器（`pressure.py`）
3. 管路和井网参数计算（`layout.py`）
4. 压力风险检查器（`pressure.py` boundary_check）
5. 均匀性指标（`clogging.py` uniformity + 尺度惩罚）
6. 示踪数据分析器（`tracer.py`）
7. 堵塞风险判定工具（`clogging.py`）
8. 分区注入规划器（`layout.py` zones）
9. 现场监测报警模块（`monitoring.py` evaluate_monitoring）
10. 阶段门决策模板（`stage_gate.py`）
11. 施工参数表和监测表生成器（`generate_tables` 动作）

### 统一输出信封（§八 全字段）
基础 17 字段（status/summary/findings/assumptions/evidence_used/uncertainty/risks/artifacts/requested_next_skills/validation/provenance/errors + contract/skill/version/action/project_id/task_id）+ 领域 12 字段（scale_level/site_assumptions/similarity_matrix/non_scalable_factors/injection_layout/injection_schedule/material_balance/pressure_constraints/monitoring_plan/stop_conditions/fallback_plan/environmental_requirements）。

## 二、强制测试（10 场景）验证结果

| # | 场景 | 结果 |
|---|---|---|
| 1 | 5cm 砂柱 → 1m 柱 | PASS（eval-01） |
| 2 | 米级 → 场地 | PASS（eval-02/04） |
| 3 | 恒流 vs 恒压 | PASS（eval-03） |
| 4 | 非均质双层土体 | PASS（eval-04） |
| 5 | 注入口堵塞 | PASS（eval-05，inlet_clogging HIGH） |
| 6 | 压力超地层允许值 | PASS（eval-06，EXCEEDS） |
| 7 | 氨氮超阈值 | PASS（eval-07，over_limit） |
| 8 | 优先流旁路 | PASS（eval-08，preferential HIGH） |
| 9 | 缺场地渗透率 → BLOCKED | PASS（eval-02/09，MSI-E102 点名字段） |
| 10 | 模拟监测触发停工回退 | PASS（eval-10，RT stop + fallback） |

## 三、测试与评测

| 项 | 结果 |
|---|---|
| pytest 单元/集成/失败/回归/路由 | **81 passed** |
| 审查回归（test_review_fixes.py） | **16 passed**（锁定 12 项修复） |
| eval 用例 | **10/10** all_pass |
| eval 7 指标 | M1 1.0 / M2 1.0 / M3 1.0 / M4 1.0 / M5 1.0 / M6 1.0 / M7 0.0 |
| Router 注册 | **usable=true, issues=[], manifest_valid=true** |
| Router 路由 | 放大/注浆/现场注入/阶段门 → scaleup；反应运移 → 正确不路由 |
| Router 自身测试 | **94 pass**（DOMAIN_MAP 扩展后） |

## 四、自举案例（任务 §十）

以本 Skill 角色从实验室柱试 → 米级试验完整放大（`examples/01-lab-to-metre.json` → `work/bootstrap_out.json` → `work/BOOTSTRAP-REPORT.md`）：

- **参数表**：0.05 m³ 体积 / 0.02 m³ 孔隙 / 60 kg/m³ → 3.0 kg CaCO₃ / 60 mol 尿素+钙 / 0.13 m³ 总注入
- **管路布置**：单点注入 + 3 监测点，1 分区（单层）
- **注入周期**：bacteria → cementation×5 → flushing，5 轮，0.26 d
- **质量平衡**：59.9 mol 尿素 → 119.9 mol NH₄-N（保守，NH₄/尿素=2.00 自检 ✓）
- **监测计划**：12 参数（位置/频率/设备/阈值/报警/停工/保存）
- **堵塞预警**：入口 MEDIUM / 优先流 LOW / 均匀性 0.60
- **停工条件**：5 条模板
- **回退方案**：7 条动作
- **阶段门**：压力 EXCEEDS → `PARTIAL`（诚实结果，不报 SUCCESS）

## 五、三方审查（任务 §十）

Red Team / Environment Auditor / Decision Gate 三个独立 agent 并行审查，复现并修复全部阻断项：

| 审查者 | 阻断项 | 修复验证 |
|---|---|---|
| Red Team | 阶段门永不通过、现场批准仍报 SUCCESS、审批门 11 动作绕过、流量到不了调度、停留 2×、tracer NaN、停工不降状态 | 全修 |
| Environment Auditor | NH4-N 低估 1/转化率（eff=0.12 假安全 8.3×）、审批门 11 动作绕过 | 全修 |
| Decision Gate | 阶段门 gate_ok 恒 false、uniformity 伪造 | 全修 |

修复报告：`work/REVIEW-FIXES-REPORT.md`；16 项回归锁定于 `tests/test_review_fixes.py`。

## 六、Router 集成

- `planner.ts` DOMAIN_MAP 扩展现有 `scaleup` token 正则，覆盖 `注浆|grouting|质量平衡|注入压力|监测计划|米级试验|场地试验|井网|示踪|停工`（此前注浆设计请求误路由到 literature-scout）。
- `skill.yaml`：capabilities `[scaleup]`（裸 token）、inputs_required 7 项 ⊆ router availableInputs、8 数组字段全字符串、version 1.0.1 semver、risk_tier high。
- 路由实测：A/B/C/E → scaleup；D（反应运移）→ 正确不路由。

## 七、已知限制

- 非尿素钙源不适用尿素化学计量（请求路由给 micp-ureolysis-chemistry）。
- 反应运移数值模拟不在此 Skill（交给 micp-porous-media-transport）。
- 均匀性/转化率/密度假设是工程近似，最终以取芯/波速/现场验证为准。
- 六项审批是调用方自报布尔；真实现场由 Panshi 宪法人工批准链背书（物理身份验证在 Controller 层）。
- 施工参数表/监测表是设计输出，不替代承包商施工组织设计。

## 八、无遗留

- 无 TODO、无固定答案、无伪造现场验证。
- 全部文献（references/sources.md）带 DOI/URL 可核验；REPORTED 数据与代码锚点一一对应。
- 所有工具离线可跑、确定性、纯 stdlib。
