# 自举测试记录 (2026-08-06, Skill v1.0.0)

## 测试 1: pH 电极漂移 + 标准液失败
- 输入: audit/selftest-1.json(标定 status=failed + 漂移测量 8.60 vs mean 7.0/sd 0.05)
- 结果: calibration.status=failed;OUT_OF_CONTROL(s2);retest=['s2'];
  restrictions=['measurements with OUT_OF_CONTROL/OVER_RANGE/SATURATION must not enter formal analysis']
- 判定: 正确拒绝标准液失败后的测量进入分析。

## 测试 2: 样品编号重复 + 时间戳错位
- 输入: audit/selftest-2.json(S-001 出现 2 次;测量时间早于采集时间)
- 结果: TIMESTAMP_MISALIGNMENT(S-001) + DUPLICATE_ID(S-001);
  restrictions=['duplicate sample IDs break the chain of custody; resolve before analysis']
- 判定: 采样链完整性被拦截。

## 测试 3: 原始数据不可覆盖(哈希链)
- 过程: append_log x2 → verify(True) → 篡改 entry0.value → verify(False, broken_at=0);
  sha256(原始)=233d5975... ≠ sha256(篡改)=126b054b...
- 判定: 原始数据逐字节保留,任何修改破坏哈希链。

## 测试 4: 审查角色攻击自产输出
- A 空 qc_input → overall_passed=False(拒绝空输入通过)
- B 退化标定(共线标准)→ status=failed, passed=False
- C 伪造 data_ref → MICQ-E1002
- D NaN 测量 → passed=False
- 判定: 无非法 SUCCESS;对抗输入全部拦截。

## 修复记录
- audit 哈希链自引用 bug(entry_hash 参与自身哈希)→ 改为 exclude='entry_hash'
- qc_pipeline 空输入静默通过 → 增加 MICQ-E1001 逐字段缺失门
- data_refs/evidence_refs 信封级字段未进入 evidence 检查 → 在 run() 内线程化
- 其余为测试期望修正(见 CHANGELOG/报告)
