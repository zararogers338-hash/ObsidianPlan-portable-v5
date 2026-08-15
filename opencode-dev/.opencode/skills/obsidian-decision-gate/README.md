# Obsidian Decision Gate ｜ 黑曜石证据成熟度与工程决策门

**Skill ID**: `obsidian-decision-gate` · **版本**: 1.0.0 · **状态**: 已交付

Obsidian Plan（Panshi 磐石）工程循环的**最终放行 Skill**。综合 Mission Lock 指标、Evidence Card、证据综合、Hypothesis Card、实验结果、数据 QC、统计、模型验证、岩土性能、工程放大、生物安全与环境审计、LCA 与成本、Reproducibility、Red Team 发现和人类审批状态，输出正式 **Decision Memo** 与 **状态转换请求**，决定研究路线进入何种状态。

**核心铁律**：*科学有效 ≠ 可工程部署*。证据不足时不得用完整语言包装成"基本通过"。

---

## 一、状态体系（9 态）

| 状态 | 门槛 |
|---|---|
| `REJECTED` | 核心假设被可靠证据推翻或方案存在不可接受风险 |
| `OPEN` | 问题已建立，证据不足 |
| `EVIDENCE_GATHERING` | ≥1 条未撤回证据，尚无综合结论 |
| `SUPPORTED` | 证据支持方向，未完成独立验证 |
| `VALIDATED` | 在明确材料/尺度/边界/指标内完成验证 + 独立验证 + 人类批准 |
| `PILOT_READY` | 受控中试条件齐备（监测/停工/回退）+ 人类批准 |
| `DEPLOYABLE` | 全部 12 维度达标 + 无阻断 + 法规核验 + 人类批准（终态不可逆） |
| `SUSPENDED` | 因风险/资源/法规/数据质量暂停 |
| `EXPIRED` | 证据/版本/场地/标准变化需重新审查 |

## 二、决策维度（12 维）

`SCIENTIFIC_VALIDITY` · `EVIDENCE_QUALITY` · `REPRODUCIBILITY` · `ENGINEERING_FEASIBILITY` · `SCALE_READINESS` · `ENVIRONMENTAL_ACCEPTABILITY` · `BIOSAFETY` · `REGULATORY_STATUS` · `ECONOMIC_VIABILITY` · `MONITORABILITY` · `REVERSIBILITY` · `RESIDUAL_RISK`

门控是**最小维度门槛**（任一维度低于 floor 即阻断），不是加权总分。

## 三、阻断规则（13 条，机器强制）

`B1` Red Team BLOCKING · `B2` 证据不可核验 · `B3` 数据不可复现 · `B4` 缺关键对照 · `B5` 质量守恒失败 · `B6` 模型无独立验证 · `B7` 尺度未阶段放大 · `B8` 环境风险未关闭 · `B9` 法规未核验 · `B10` 人类审批缺失 · `B11` 无监测/停工条件 · `B12` 成功指标未达标 · `B13` 失败阈值触发

规则表是**数据**（`schemas/gate-rules.json`，`when` 语义见 `schemas/gate-rule.schema.json`），非代码——可审计、可版本化。

## 四、状态转换图

白名单见 `schemas/gate-rules.json`。**非法跳跃硬拒绝**（ODG-E305）：`OPEN→DEPLOYABLE`、`SUPPORTED→DEPLOYABLE`、`EVIDENCE_GATHERING→PILOT_READY` 等。`DEPLOYABLE` 不可逆。

## 五、目录结构

```
skills/obsidian-decision-gate/
├── SKILL.md                      # 技能定义（loader frontmatter）
├── skill.yaml                    # router manifest（全字符串数组）
├── manifest.json                 # 机器清单镜像
├── README.md                     # 本文档
├── CHANGELOG.md
├── prompts/system.md             # 系统提示
├── schemas/
│   ├── input.schema.json         # 输入契约（2020-12, additionalProperties:false）
│   ├── output.schema.json        # 统一输出封套
│   ├── decision-memo.schema.json # Decision Memo 契约
│   ├── gate-rule.schema.json     # 规则表契约
│   └── gate-rules.json           # 机器读取的规则表（白名单/维度floor/阻断when）
├── tools/odg/
│   ├── cli.py                    # stdin/stdout 入口（service|score|blockers|mcda|risk|memo|transition|expiry|compare|validate）
│   ├── models.py                 # 9 态/12 维/13 阻断/决策/状态枚举
│   ├── rules.py                  # 白名单 + 阻断规则引擎
│   ├── scoring.py                # 12 维度评分器 + MCDA + 风险-收益矩阵
│   ├── mission.py                # Mission Lock 指标对照器
│   ├── expiry.py                 # 到期复审检查器
│   ├── compare.py                # 决策差异比较
│   ├── memo.py                   # Decision Memo 生成器
│   ├── service.py                # 决策门主引擎（编排）
│   ├── validate.py               # schema 校验（jsonschema + 内建回退）
│   └── errors.py                 # ODG-E### 错误码
├── tests/                        # pytest（46 个，含 12 强制场景 + 机器机制）
├── evals/
│   ├── cases.yaml                # 12 个评测用例
│   └── run.py                    # M1–M7 指标评测驱动
├── examples/                     # 真实可运行的示例
├── references/sources.md
└── audit/                        # 自举日志与交付记录
```

## 六、快速开始

```bash
# 全量测试
python -m pytest tests/ -q

# 评测（12 用例 + M1-M7 指标）
python evals/run.py

# 对一个决策门请求执行完整评估
python tools/odg/cli.py service < examples/example-bootstrap.json
```

## 七、CLI 契约

**信封**: `{"ok": bool, "tool": str, "version": str, "result": {...} | null, "error": {...} | null}`
**退出码**: `0` 成功 · `2` 输入/校验错误 · `3` 引擎/规则错误 · `4` 用法错误

子命令：`service`（完整决策门）· `score`（维度评分）· `blockers`（阻断检查）· `mcda`（多准则分析）· `risk`（风险-收益矩阵）· `memo`（Decision Memo）· `transition`（状态转换请求）· `expiry`（到期复审）· `compare`（决策差异）· `validate`（schema 校验）

## 八、与现有 Skill 的对接

- **消费**：`obsidian-mission-lock`（contract/metrics/success/failure）、`micp-evidence-*`、`micp-hypothesis-forge`、`micp-data-analyst`、`micp-geotechnical-performance`、`micp-porous-media-transport`、`micp-instrumentation-qc`、`obsidian-experiment-designer`、`micp-biology-reasoner`、biosafety/LCA/reproducibility、`obsidian-red-team`。
- **输出**：状态转换请求转交 `obsidian-state-manager` 执行（守卫求值 + 链上 `APPROVAL_GRANTED`）。
- **Router**：已注册 `decision_gate` 能力 token（planner.ts DOMAIN_MAP 已含 `决策门|审批|go/no-go|放行决策`）。high/critical 风险路由强制 `obsidian-red-team → obsidian-decision-gate` 审计链。

## 九、已知限制与遗留风险

- `actor.role` 仍是自报身份；物理身份验证依赖外层 Controller（与 state-manager 同）。
- 决策差异比较使用输入 `history` 字段，跨会话历史需由 Controller/state-manager 供入。
- MCDA 权重默认等权；领域专家可通过 `dimension_overrides.weights` 覆盖。
- 人类审批 `revision` 匹配链上状态流的机制由 state-manager 保证，本 Skill 只检查、不代签。

## 十、许可

MIT（项目约定，repo 根 LICENSE）。


---

> 原 `README_USE_THIS.txt` 已归档至 [`audit/README_USE_THIS.txt`](audit/README_USE_THIS.txt)。
