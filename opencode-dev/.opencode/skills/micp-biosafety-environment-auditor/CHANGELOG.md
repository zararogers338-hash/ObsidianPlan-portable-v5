# Changelog

All notable changes to `micp-biosafety-environment-auditor` are documented here.

## [1.0.0] - 2026-08-07

### Added
- **Skill 工程包**：SKILL.md / skill.yaml / manifest.json / README.md / prompts/system.md / schemas(4) / tools / tests / evals / examples / references。
- **11 项工具**（`tools/mbs_auditor.py` 动作）：`audit`、`mass_balance`、`nh3_speciation`、`waste_loading`、`strain_verify`、`regulatory_lookup`、`risk_matrix`、`monitoring`、`treatment_compare`、`sampling_plan`、`emergency`、`permit_check`。
- **氮质量平衡**：尿素→理论总氮→NH₄⁺ 上限→NH₃ 潜在量→液相/吸附/排放路径；守恒容差校验（MBS-E301 阻止环境结论）。
- **NH₃ 形态分布**：pH/温度/离子强度（Davies 活度校正 + Bates-Pinching pKa）。
- **风险模型**：5×5 矩阵（LOW/MODERATE/HIGH/CRITICAL）；危害识别（菌株致病性/环境释放/气溶胶/水体传播/氨毒性/氮负荷/盐负荷/钙盐结垢/ARG/土壤生态/气味/密闭空间）；暴露路径；残余风险（CRITICAL 下限 MODERATE）。
- **法规核验**：本地核验库（12 条中国法规记录，2026-08-07 核验）；空库/过期/检索失败 → `REGULATORY_VERIFICATION_REQUIRED`，绝不编造。
- **11 类审批门** → `HUMAN_APPROVAL_REQUIRED`；绕过审批请求被拒绝（MBS-E205）。
- **监测与应急**：阈值/告警/停止条件/采样计划/应急清单/许可检查。
- **测试**：46 个 pytest（含 10 项强制测试全绿）。
- **评测**：12 用例 + M1–M7 指标全部通过。

### Fixed（实现期自检）
- 质量平衡 `accounted` 缺键 → 仅理论路径时正常返回。
- 空法规库被误判为已验证 → 空库标记 `no-verified-regulatory-records`，`fully_verified=False`。
- 法规时效误用 `issued_date` → 改用 `verified_on` 判断。
- 残余风险 CRITICAL+高控制可降至 LOW → 保守下限 MODERATE。
- `regulatory_lookup` 失败未带错误码 → 传播 MBS-E201。
- 嵌套 `limits` 存储未解析 → 支持扁平 `limit_mgL` 与 `limits` map 两种形式。

### Fixed（Red Team 对抗修复，2026-08-07）
10 项独立对抗审查确认缺陷全部修复（详见 references/red-team-report.md）：
- 零尿素输入+非零实测路径被强制判定闭合 → MBS-E301（守恒门不可绕过）。
- 致病菌株（含保藏号）返回 SUCCESS 零危害 → `PATHOGENIC_STRAIN_UNCERTIFIED`/`STRAIN_BIOSAFETY_UNCONFIRMED`/`HAZARD_*` 门。
- 法规分类门在含未核验限值记录时误判已验证 → 分类 `fully_verified` 要求全部记录核验。
- 计算的 NH3 形态孤立不驱动危害 → `computed_nh3_n_mgL` 接入 identify_hazards。
- 残余风险 HIGH→LOW 淡化 → HIGH 增设 MODERATE 下限；effectiveness 从实际控制推导。
- `nh4_n_mgL` 无监测阈值致 G7 永不触发 → 加入阈值；未知测量参数升级 `no-threshold` 告警。
- `residual_paths` 双计 NH3 潜在量 → 从 sink 集移除，schema 同步。
- 现场方案省略可选 flags 逃逸法规门 → 从 plan 非可选信号推断。
- 用户提供 `nh3_potential_g` 被静默丢弃（参数遮蔽）→ 交叉核对，冲突 MBS-E301。
- 回归锁定：tests/test_redteam_regressions.py（RT1-RT9）。
