# 三方审查与修复报告（Red Team / Environment Auditor / Decision Gate）

> 2026-08-07 ｜ 三个独立对抗审查 agent 并行审查，全部缺陷经复现确认，修复后由
> `tests/test_review_fixes.py`（16 项回归）锁定。

## 一、审查结论概览

| 审查者 | 阻断项 | 高危 | 中/低 | 修复 |
|---|---|---|---|---|
| Red Team | 7 | 4 | 7 | 全部修复 |
| Environment Auditor | 2 | 2 | 3 | 全部修复 |
| Decision Gate | 2 | 4 | 4 | 全部修复 |

审查 PASSED 项：契约完整性、Router 注册（usable=true、8 数组字段、scaleup token）、
错误码映射、六项审批门在 scaleup 路径的顺序、缺渗透率 BLOCKED、文献零伪造。

## 二、阻断项修复明细

| # | 缺陷 | 复现 | 修复 |
|---|---|---|---|
| B1 | 阶段门当前门从不标记通过，`gate_ok` 恒 false | clean metre → G2 passed=false | 当前门按实际数据评估（blocked_reasons 空 → passed=true）；未来门不参与 gate_ok |
| B2 | 现场已批准但压力 EXCEEDS/NH4 超限 → SUCCESS "construction may be planned" | 20kPa 限 + 高流量 + 全批准 → SUCCESS | 门阻塞 → 状态降为 PARTIAL；现场摘要按 gate_ok 措辞 |
| B3 | NH4-N 按沉淀 CaCO₃ 计（低估 1/eff），eff=0.12 时假安全 8.3× | 48,000→物理 400,000 mg/L | 改为按**注入尿素**保守计量（2 NH4-N/尿素）；`nh4_precip_tied_mol` 单独给出 |
| B4 | 现场审批被 11 个动作绕过 | generate_tables/schedule 无审批 → SUCCESS | 中央审批门：handle() 对所有动作强制 `_require_field_approval` |
| B5 | 监测停工信号不改变状态 | 900kPa>限 → SUCCESS | `_force_partial` 机制：停工信号 → PARTIAL |
| B6 | 反算流量到不了调度，时长全 0 | 无流量 → duration 0.0 | boundary 先算，flow 传入 material_balance → schedule |
| B7 | 调度停留时间 2× 且含幻影相位 | 7 相位 +1 天停留 → 8.01 天 | `len(phases)-1` 间隙；删除幻影 order++ |
| B8 | tracer NaN 判"acceptable" | injected_conc=0 → 假通过 | NaN → honest "could not be computed" |
| B9 | 均匀性不随尺度衰减 | 现场 uniformity=1.0 | 尺度惩罚（pilot 0/metre .15/site .30/field .45） |

## 三、高危修复明细

| # | 缺陷 | 修复 |
|---|---|---|
| H1 | `_do_scaleup` 无孔隙率 → MSI-E401 崩溃 | 全部 `.3f` 格式化加 None 守卫 |
| H2 | `_do_material_balance` 同崩溃 | 同上 |
| H3 | `_do_tracer` None → 崩溃 | rec/mrt 格式化为 "n/a" |
| H4 | `_environmental` 缺限值静默 false | 新增 `limit_missing`/`limit_status` 标记 |
| H5 | 缺氨氮限值静默默认 50 mg/L（伪造法规值） | 不再默认；monitoring 标注"未设限值不得排放" |
| H6 | 地下水羽流监测无代码路径 | `groundwater_nh4`/`groundwater_ec` 读数 → 停工 |
| H7 | nh4_over 在 scaleup/stage_gate 不一致 | 统一为"实际超限"布尔 |

## 四、中/低修复

- 缺孔隙率 validate 不再绿光（M1）
- 文档 `field_go`/`recommendation` 漂移已修（L1）
- 补充 Harkes et al. 2010 引用（citation gap）
- project_id 非法仍 null（已安全拒绝，保持现状）

## 五、复测

- 81 pytest 全绿（65 原 + 16 回归）
- 10 eval 全绿，7 指标全绿
- Router 90 测试全绿（DOMAIN_MAP 扩展后）
- 阻断项复现场景全部转为正确行为（见上方逐条 CLI 验证）
