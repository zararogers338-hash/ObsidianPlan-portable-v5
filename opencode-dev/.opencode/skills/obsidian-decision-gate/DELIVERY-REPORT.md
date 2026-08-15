# 交付报告 — obsidian-decision-gate v1.0.0

日期：2026-08-07 · Skill：`obsidian-decision-gate`（黑曜石证据成熟度与工程决策门）· 版本：1.0.0

## 一、结论

**已交付且验证通过。** 这是 Obsidian Plan 工程循环的最终放行 Skill，具备：机器强制的 9 态状态体系、12 维决策评分、13 条阻断规则、状态转换白名单、Mission Lock 对照、人类审批门、Decision Memo、状态转换请求、到期复审、决策差异比较。**非法状态升级被真正阻止、人类审批门未被绕过、46+8 测试全绿。**

## 二、位置

`.opencode\skills\obsidian-decision-gate\`

## 三、交付清单

| 项 | 状态 |
|---|---|
| SKILL.md（frontmatter name+description） | ✅ |
| skill.yaml + manifest.json（router 契约） | ✅ |
| README.md / CHANGELOG.md / prompts/system.md | ✅ |
| schemas: input / output / decision-memo / gate-rule + gate-rules.json | ✅ |
| tools/odg/ 纯 Python 3.10+ 标准库 CLI | ✅ |
| tests/ pytest | ✅ 54 通过 |
| evals/cases.yaml + run.py | ✅ 12/12 用例 |
| examples/ 真实可运行 | ✅ |
| references/sources.md | ✅ |
| audit/ 自举日志与交付记录 | ✅ |
| Router 注册 | ✅ usable=true |

## 四、能力实现（对照要求）

- ✅ 证据成熟度评分器（`scoring.py`，12 维）
- ✅ 阶段门规则引擎（`rules.py`，白名单 + 阻断）
- ✅ 阻断项检查器（B1–B13，机器强制）
- ✅ Mission Lock 指标对照器（`mission.py`）
- ✅ 多准则决策分析工具（`mcda`）
- ✅ 风险—收益矩阵（`risk`）
- ✅ 可逆性和残余风险评估器（REVERSIBILITY / RESIDUAL_RISK 维度）
- ✅ 人类审批状态检查器（B10，scope/revision 匹配）
- ✅ Decision Memo 生成器（`memo.py`）
- ✅ 状态转换请求器（`transition`）
- ✅ 到期复审和结论过期检查器（`expiry.py`）
- ✅ 决策差异与历史比较工具（`compare.py`）

## 五、强制测试（12 项）

| # | 场景 | 判定 |
|---|---|---|
| 1 | 强度达标但氨排放不达标 | ✅ BLOCKED / HOLD / B12 |
| 2 | 证据支持但样本量极小 | ✅ BLOCKED / HOLD / B3 |
| 3 | 模型通过拟合但没有独立验证 | ✅ BLOCKED / HOLD / B6 |
| 4 | Red Team 存在 BLOCKING 问题 | ✅ BLOCKED / HOLD / B1 |
| 5 | 缺少人工批准 | ✅ HUMAN_APPROVAL_REQUIRED / B10 |
| 6 | 小柱试验要求直接 DEPLOYABLE | ✅ BLOCKED / HOLD / B7+B11 |
| 7 | 中试方案具有完整监测和回退 | ✅ SUCCESS / PASS |
| 8 | 成本不可接受但科学有效 | ✅ BLOCKED / HOLD / B12 |
| 9 | 法规信息已经过期 | ✅ BLOCKED / EXPIRE / B9 |
| 10 | 结论因新证据需要降级 | ✅ SUCCESS / PASS（降级） |
| 11 | 非法从 OPEN 跳到 DEPLOYABLE | ✅ BLOCKED / REJECT / ODG-E305 |
| 12 | 失败阈值已触发但主模型要求继续 | ✅ BLOCKED / SUSPEND / B13 |

## 六、自举决策

模拟完整 MICP 道路加固部署项目（`examples/example-bootstrap.json`）：
`PILOT_READY → DEPLOYABLE`，**PASS / SUCCESS**。12 维度全达标、无阻断、人类审批 on-chain（revision=42）、监测 8 项、停工条件 4 项。

**对抗复审**（相反立场，6 类失败模式攻击）：全部 DEFENDED。复审期间修复 1 处缺陷（BIOSAFETY 评分误把已关闭 high finding 计入风险），修复后重测通过。详见 `audit/bootstrap-log.md`。

## 七、实际运行命令

```bash
# 测试（54 pytest）
cd .opencode\skills\obsidian-decision-gate
python -m pytest tests/ -q

# 评测（12 用例 + M1-M7）
python evals/run.py

# 自举决策
python tools/odg/cli.py service < examples/example-bootstrap.json

# Router 集成测试（5 项，扫描真实注册表）
cd .opencode\skills\obsidian-skill-router
bun test tests/integration/decision-gate.test.ts

# Router 全量回归（90 测试）
bun test

# 注册表扫描
bun tools/bin/osr.ts registry --build
```

## 八、测试结果汇总

| 套件 | 结果 |
|---|---|
| obsidian-decision-gate pytest | 54/54 ✅ |
| evals（12 用例） | 12/12 ✅ |
| M1 结构化输出 | 1.0 ✅ |
| M2 工具真实调用 | 1.0 ✅ |
| M3 可追溯 | 1.0 ✅ |
| M4 缺失输入识别 | 1.0 ✅ |
| M5 对抗拦截 | 1.0 ✅ |
| M6 复现一致 | 1.0 ✅ |
| M7 失败恢复 | 294ms ✅ |
| Router 集成（decision-gate） | 5/5 ✅ |
| Router 全量回归 | 90/90 ✅（无回归） |
| 注册表 | usable=true, manifest_valid=true, issues=[] |

## 九、未关闭风险

1. `actor.role` 为自报身份；物理身份验证依赖外层 Controller（与 state-manager 同）。
2. 长期耐久性（>5 年）以部署后监测计划覆盖（Red Team MEDIUM accepted_risk）。
3. 决策差异比较依赖输入 `history` 字段；跨会话历史由 Controller/state-manager 供入。
4. MCDA 权重默认等权；领域专家可用 `dimension_overrides.weights` 覆盖。
5. Router 注册的 `writes: ["state/gates/**"]` 表明本 Skill 写门记录目录；当前实现纯只读 + dry-run，写入委托 state-manager。若未来放开写权限需再评审。

## 十、注册状态

`obsidian-skill-router` 注册表（`bun tools/bin/osr.ts registry --build`）：
- `obsidian-decision-gate`：**usable=True**，manifest_valid=True，issues=[]
- capabilities: `["decision_gate"]`（planner.ts DOMAIN_MAP 已含，`决策门|审批|go/no-go|放行决策`）
- risk_tier: high，network: false
- high/critical 风险路由强制 `obsidian-red-team → obsidian-decision-gate` 审计链（router Gate 5）
- Router 全量 90 测试无回归（含新增 5 项决策门集成测试）
