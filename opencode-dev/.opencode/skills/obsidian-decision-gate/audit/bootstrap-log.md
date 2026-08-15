# Obsidian Decision Gate — 自举决策与对抗复审日志

日期：2026-08-07 · Skill 版本：1.0.0

## 一、自举项目

模拟完整 MICP 道路加固现场部署项目（`examples/example-bootstrap.json`）：

- **Mission Lock**：1 km 试验路段 MICP 加固，强度≥5MPa、氨排放≤500 mg/m3；失败阈值强度<1MPa、氨>1500mg/m3。
- **Evidence**：3 条可核验证据卡（2 lab + 1 pilot）。
- **实验**：中试强度 5.4 MPa（met）、氨 480 mg/m3（met），质量守恒闭合（2.1% < 5%），n=12、独立单位 6、power 0.97。
- **模型**：UCS 动力学模型，外部验证 r²=0.82。
- **环境审计**：cleared（high/medium 项全部 closed）。
- **LCA**：cleared（成本在预算内，碳排低于水泥 40%）。
- **Reproducibility**：数据+代码归档，3 批重复 CV<8%。
- **Red Team**：passed（1 项 MEDIUM accepted_risk：长期耐久性）。
- **法规**：verified + current + permit granted。
- **人类审批**：granted，scope=DEPLOYABLE，revision=42，on-chain。

## 二、自举决策结果

```
status:            SUCCESS
decision:          PASS
current_state:     PILOT_READY
proposed_state:    DEPLOYABLE
blocking_items:    []（13 条阻断全部通过）
criteria_met:      ['强度≥5MPa', '氨排放≤500 mg/m3']
dimensions:        12/12 达标（min 0.750 REVERSIBILITY, max 1.000 SCALE_READINESS）
human_approval:    granted (scope=DEPLOYABLE, revision=42, on_chain=true)
monitoring:        8 项监测要求
failure_conditions: 4 项停工条件
state_transition_request: PILOT_READY → DEPLOYABLE, approval_required=true, on_chain=true
review_expiry:     2027-02-01T00:00:00Z
memo_id:           odg-BOOTSTRAP-01-0001
```

## 三、对抗复审（相反立场，严格审核员）

对自举决策发起 6 类失败模式攻击：

| # | 攻击 | 预期 | 引擎响应 | 结果 |
|---|---|---|---|---|
| 1 | 证据不足仍放行 | 不 PASS | HOLD/BLOCKED/B12 | DEFENDED |
| 2 | 过度保守（移除假设卡仍应放行） | PASS | PASS/SUCCESS | 正确放行 |
| 3 | 失败阈值触发但放行 | 不 PASS | SUSPEND/BLOCKED/B13 | DEFENDED |
| 4 | 阻断项遗漏（注入 BLOCKING RT 发现） | 不 PASS | HOLD/BLOCKED/B1 | DEFENDED |
| 5 | 科学有效误当可部署（成本不可接受） | 不 PASS | HOLD/BLOCKED/B12 | DEFENDED |
| 6 | 人类审批被绕过（撤销批准） | HAR | HOLD/HUMAN_APPROVAL_REQUIRED | DEFENDED |

**结论**：全部 6 类失败模式被防御，无"证据不足却放行"、"科学支持误当工程部署"、"人类审批被绕过"等缺陷。复审期间修复 1 处缺陷：BIOSAFETY 评分误把已关闭 high finding 计入风险（改为仅未关闭项扣分），修复后重测通过。

## 四、测试与评测

- pytest：46 通过（含 12 强制场景 + 白名单 + 13 阻断 + 审批 + 到期 + 比较 + schema）。
- evals：12/12 用例，M1–M7 全绿（1.0 / 1.0 / 1.0 / 1.0 / 1.0 / 1.0 / 310ms）。

## 五、未关闭风险

- `actor.role` 自报身份；物理身份验证依赖外层 Controller。
- 长期耐久性（>5 年）以部署后监测计划覆盖（RED_TEAM MEDIUM accepted_risk）。
- 决策差异比较依赖输入 `history`；跨会话历史由 Controller/state-manager 供入。
