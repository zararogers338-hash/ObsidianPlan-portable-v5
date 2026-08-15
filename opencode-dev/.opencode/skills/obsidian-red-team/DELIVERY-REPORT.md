# obsidian-red-team — 交付报告 v1.0.0

> 黑曜石科学反证与对抗审查器 · 全系统强制审计 Skill
> 交付日期：2026-08-07 · 位置：`skills/obsidian-red-team/`

## 一、交付内容

| 类别 | 内容 |
|---|---|
| Skill 包 | `SKILL.md`、`skill.yaml`、`manifest.json`、`README.md`、`CHANGELOG.md`、`prompts/system.md`、`references/sources.md` |
| Schemas | `input.schema.json`、`output.schema.json`、`finding.schema.json`（draft 2020-12，`additionalProperties: false`） |
| 工具（16 个 CLI 子命令） | `review`、`validate`、`check-self`、`citation`（引用核验）、`provenance`（来源链）、`units`（单位量纲）、`balance`（质量守恒）、`stats`（统计结构）、`pseudo`（伪重复）、`modelcheck`（模型边界）、`escalation`（状态越级）、`permissions`（权限越界）、`counterexamp`（对抗用例）、`severity`（严重度评分）、`blocking`（阻断引擎）、`retest`（修复复验） |
| 工具实现 | `tools/ort/` 纯 Python 3.10+ 标准库，stdin/stdout 信封，错误码 `ORT-E###`，离线、确定性 |
| 测试 | `tests/` — 68 个 pytest 全绿 |
| 评测 | `evals/cases.yaml` 15 个强制对抗案例；`run_evals.py` + `metrics.py`，M1–M7 全绿 |
| 自举 | `evals/bootstrap/` — 审查真实产物 + 自我复检 + 修复重跑 |
| 示例 | `examples/` — 3 个真实可运行示例 |

## 二、验证结果

| 项 | 结果 |
|---|---|
| pytest（red-team） | **68 passed** |
| 评测 M1–M7 | **all_pass=true**（M1 结构化 1.0 / M2 工具真实调用 1.0 / M3 可追溯 1.0 / M4 缺失识别 1.0 / M5 对抗拦截 **1.0** / M6 重复一致 1.0） |
| 15 个对抗案例 | 全部被拦截（伪造论文、DOI 不匹配、OD600 当脲酶、CaCO3 当晶桥、伪重复、缺对照、p 显著效应极小、违反质量守恒、同数据校准验证、小柱推现场、强度升渗透降、氨氮超限、法规未核验、阻断未关闭升级、越权写知识库） |
| Router 注册 | `obsidian-skill-router` registry：`usable=true`、`manifest_valid=true`、capabilities 含裸 token `red_team`、`network=false`、`risk_tier=critical`；`tests/integration/red-team-registry.test.ts` 4/4 通过（含高风险 `red-team→decision-gate` 审计链强制） |
| Router 全量 | `bun test` 94 pass（含 12 用例 eval，M5=1.0） |
| State Manager 集成 | `UNDER_REVIEW→VALIDATED` 与 `VALIDATED→DEPLOYABLE` 增加 `requires_review_pass` 守卫；`tests/test_red_team_gate.py` 3/3 通过（fail 阻断 VALIDATED / pass 放行 / 无 review 阻断） |
| State Manager 全量 | 69 passed（含 gate 测试） |
| 自举 | Step1 审查 `micp-evidence-synthesizer` 方法学 → BLOCKED/REVIEW_FAIL；Step2 自我复检确认未遗漏最强反例（I² 精度混淆、k<3 固定效应合并）；修复 gap 后重跑全绿 |

## 三、强制阻断规则（BLOCKING）

`tools/ort/blocking_rules.py` 为唯一事实源，`models.BlockingRuleId` 定义 BLOCK-1..BLOCK-11：

| 规则 | 触发 | 状态建议 |
|---|---|---|
| BLOCK-1 | 伪造引用/虚构数据（citation verdict REJECTED/SUSPECTED） | REVIEW_FAIL |
| BLOCK-2 | 氨氮超限仍建议部署 | REVIEW_FAIL |
| BLOCK-3 | 阻断项未关闭仍声明升级/放行 | REVIEW_FAIL |
| BLOCK-4 | 质量守恒/物料流违反 | REVIEW_FAIL |
| BLOCK-5 | 伪重复撑起关键结论显著性 | REVIEW_FAIL |
| BLOCK-6 | 法规未核验仍放行部署 | REVIEW_FAIL |
| BLOCK-7 | 工程阻断（渗透降、小柱外推、缺停工条件）未处理即放行 | REVIEW_FAIL |
| BLOCK-8 | 状态越级（跳过中间门） | REVIEW_FAIL |
| BLOCK-9 | 权限越界（长期知识库写入未批准 / 修改被审结论） | REVIEW_FAIL |
| BLOCK-10 | 认识论越级支撑部署 | REVIEW_FAIL |
| BLOCK-11 | 模型边界违反（同数据校准+验证、尺度溢出） | REVIEW_FAIL |

存在 BLOCKING 时：`status != SUCCESS`、`state_recommendation ∈ {REVIEW_FAIL, HOLD}`、`check-self` 不变量强制。State Manager 在最新 review verdict=fail 时拒绝 `→VALIDATED`/`→DEPLOYABLE`。

## 四、统一输出信封

`status | review_scope | findings | blocking_findings | counterexamples | alternative_explanations | required_evidence | required_fixes | retest_plan | state_recommendation | risks | artifacts | validation | provenance | errors`（外加 12 字段统一封套）。

每个 finding：`finding_id | target_id | location | dimension | severity | summary | evidence | evidence_epistemic_tag | why | counterexample | required_fix | verification_method | blocks_state_upgrade | status | rule_id`。

## 五、系统集成（升级强制门）

- **Router**：`risk_level ∈ {high, critical}` 强制 `obsidian-red-team → obsidian-decision-gate` 审计链（planner.ts 已内置）；缺失任一审计技能 → `BLOCKED` (OSR-E006)。
- **State Manager**：`requires_review_pass` 守卫使 BLOCKING 时机器拒绝升级；verdict=fail 事件阻止 `UNDER_REVIEW→VALIDATED` 与 `VALIDATED→DEPLOYABLE`。
- **Red Team 只读**：`tool_permissions: [read]`、`network: false`、`writes: audit/**`；只提交发现与判定，不修改结论或数据。

## 六、未关闭风险（见 `evals/bootstrap/BUILT-IN-REPORT.md`）

1. 引用核验为离线结构核验：格式合法但内容不符的 DOI 标记 UNVERIFIED 而非 REJECTED，需人工/联网复核。
2. 氨氮/法规限值使用内置默认表（GB/T 14848-2017 III 类 0.5 mg/L 等）；更严辖区需 `constraints.ammonia_limit_source`。
3. 方法学模式为策展集合：新增陷阱须追加到 `STAT_METHOD_PATTERNS` 并加测试。
4. escalation 门的命名与项目门表同步。
5. Red Team 判定对人工是建议性的：人工可关闭发现后重新 review.complete pass 走正当覆盖路径。

## 七、如何运行

```bash
# 全量测试
python -m pytest tests/
# 评测（15 对抗案例，7 指标）
python evals/run_evals.py
# 审查一个结论
python tools/ort/cli.py review < examples/01-blocked-deployment.json
```

## 八、关联

- Router：`obsidian-skill-router`（注册 + 高风险审计链）
- 状态机：`obsidian-state-manager`（升级门 `requires_review_pass`）
- 决策门：`obsidian-decision-gate`（审计链下游）
