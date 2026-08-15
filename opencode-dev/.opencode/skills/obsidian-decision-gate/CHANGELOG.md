# Changelog

## 1.0.0 (2026-08-07)

初版交付。Obsidian Plan 工程循环的最终放行 Skill。

### 核心能力
- **9 态状态体系**：REJECTED / OPEN / EVIDENCE_GATHERING / SUPPORTED / VALIDATED / PILOT_READY / DEPLOYABLE / SUSPENDED / EXPIRED，每态有客观证据门槛（`schemas/gate-rules.json` `state_grades` + `dimension_floors`）。
- **12 决策维度**评分器（`tools/odg/scoring.py`），门控为最小维度门槛而非加权总分。
- **13 条机器强制阻断规则**（`tools/odg/rules.py`），规则表为数据（`schemas/gate-rules.json` + `gate-rule.schema.json`）。
- **状态转换白名单**：非法跳跃硬拒绝（ODG-E305），`DEPLOYABLE` 不可逆。
- **Mission Lock 对照器**（`tools/odg/mission.py`）：success_criteria 逐条判定、failure_thresholds 触发、metrics 方向/目标/阈值对照，含中英文同义词与单位阈值启发式。
- **人类审批门**（B10）：目标状态 grade ≥ VALIDATED 要求审批，scope/revision 匹配检查，缺失/过期 → `HUMAN_APPROVAL_REQUIRED`。
- **到期复审**（`tools/odg/expiry.py`）：法规过期、review horizon、标准/场地/版本变化、假设被推翻触发 EXPIRED。
- **决策差异比较**（`tools/odg/compare.py`）：与历史决策对比，警示"阻断项增多却 PASS"式 fudge。
- **Decision Memo + 状态转换请求**（`tools/odg/memo.py`、service）。

### 工程包
- schemas：input / output / decision-memo / gate-rule（2020-12，`additionalProperties:false`）+ gate-rules.json 规则表。
- 工具：纯 Python 3.10+ 标准库，jsonschema 可选带内建回退；CLI stdin/stdout 信封 `{ok,tool,version,result|error}`，exit 0/2/3/4。
- 测试：46 pytest（12 强制场景 + 白名单 + 13 阻断 + 审批 + 到期 + 比较 + schema）。
- 评测：12 cases.yaml 用例，M1–M7 全绿（1.0 / 1.0 / 1.0 / 1.0 / 1.0 / 1.0 / 310ms）。

### 集成
- `obsidian-skill-router` planner.ts 已预置 `decision_gate` 能力（Gate 5 强制 high/critical 走 red-team → decision-gate 审计链）；注册表扫描 `usable=true`。

### 错误码体系
`ODG-E1xx` 输入 · `E2xx` 证据与指标 · `E3xx` 状态机与阻断 · `E4xx` 工具环境 · `E5xx` 审批与权限 · `E6xx` 下游能力 · `E7xx` 输出与自检 · `E8xx` 版本兼容。
