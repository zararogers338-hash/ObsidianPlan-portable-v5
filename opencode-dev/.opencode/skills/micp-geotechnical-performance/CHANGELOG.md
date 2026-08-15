# CHANGELOG

记录 micp-geotechnical-performance (MGE) 的版本演进。遵循语义化版本：破坏性契约变更 → 主版本；新增可选字段 → 次版本；实现修复 → 修订版本。

## [1.0.0] - 2026-08-06

### 初始交付

- 完整的 Skill 工程包（SKILL.md / skill.yaml / schemas / prompts / references / evals / examples / tests）。
- 五个数值工具：`parse`（试验数据解析器）、`metrics`（应力-应变指标）、`stats`（样本统计 + 空间均匀性）、`durability`（耐久循环衰减拟合）、`effect`（效应量 + 安全裕度）。
- 错误码体系 MGE-E101..E803（机器可解析 + 人类可读）。
- 7 项性能指标（M1–M7）与 12 个评测用例。
- 自举测试（BT-1..BT-4）发现并修复的真实缺陷：
  - **Welch t 检验小样本 p 值过度保守**（`min(1, 2/t)` 把明显分离的组也报 p=1）→ 改为精确的 t→不完全 beta 实现。
  - **强度-渗透率权衡未显式表达** → 新增 `engineering_judgment` 输出（渗透率跨试样的数量级）。
  - **跨试样尺寸可比性未检查** → 新增 `crossSpecimenIssues`（直径 >25% 差距、加载速率 >10x、密度 >5% 差异均标出）。
  - **n=1 时伪造 cohens_d=0/negligible** → 不可计算时省略，绝不编造。
- 测试套件：27 单元 + 9 集成 + 11 对抗 + 9 回归 + 13 评测 + 4 自举 = 73 个测试全部通过；评测指标 M1=1.0, M2=1.0, M3=1.0, M4=1.0, M5=1.0, M6=1.0, M7=0。

### 兼容性

- `skill_version == 1.x.y`、`controller_version >= 1.0.0`。
- 契约文件：`schemas/input.schema.json`、`schemas/output.schema.json`。
