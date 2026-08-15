# micp-reproducibility-versioning

**MICP 可复现性、数据溯源与版本治理器** — MICP 研究的可追溯、可重建、可比较、可回滚治理能力。

> 版本 **1.0.0** · Skill ID `micp-reproducibility-versioning` · 错误码前缀 `MRV`

## 使命

确保 MICP 研究中以下对象全部**可追溯、可重建、可比较、可回滚**：

- 原始数据、派生数据、实验参数、仪器配置
- 代码、模型、随机种子、软件依赖
- Skill、Prompt、Panshi 宪法
- Evidence Card、Hypothesis Card、Experiment Spec、Decision Memo
- 报告与图表

## 数据分层

| 目录 | 规则 |
|---|---|
| `data/raw` | 只读。写保护检查失败 → `BLOCKED`（MRV-E501） |
| `data/interim` | 中间产物，可重建 |
| `data/processed` | 必须由代码重建（缺重建命令 → 风险） |
| `data/external` | 外部数据源快照 |
| `artifacts/` | 分析产物 |
| `models/` | 模型权重与元数据 |
| `experiments/` | 实验记录 |
| `evidence/` | Evidence Card |
| `failures/` | 失败记录 |
| `reports/` | 报告与图表 |
| `provenance/` | 溯源事件日志（追加式、防篡改） |

核心规则：
- raw 永远只读；
- processed 必须由代码重建；
- 正式结果必须能追溯到 raw；
- 手工修改必须生成新的派生文件；
- 删除、覆盖、迁移必须留下审计记录；
- 敏感数据必须支持访问控制和脱敏。

## 版本记录

`reproduction_manifest` 记录：Git commit、Skill/Controller/宪法/Schema/模型/Prompt/数据版本、依赖锁文件、OS、运行时版本、工具版本、随机种子、执行时间、输入与输出哈希。

Schema 版本策略：破坏性 → 主版本 +1；新增兼容字段 → 次版本 +1；兼容修复 → 修订版本 +1。

## 目录

```
skills/micp-reproducibility-versioning/
├── SKILL.md                    # 主指令（frontmatter: name/description）
├── skill.yaml                  # Router 机器元数据（OSR registry 消费）
├── manifest.json               # 人类可读的包元数据
├── README.md
├── CHANGELOG.md
├── prompts/system.md           # 注入提示词
├── schemas/
│   ├── input.schema.json
│   ├── output.schema.json
│   ├── reproduction-manifest.schema.json
│   └── provenance-event.schema.json
├── tools/mrv/                  # 纯 stdlib Python 工具集（13 子命令）
├── tests/                      # pytest 套件（含 10 个强制场景）
├── evals/                      # cases.yaml + run_evals.py + metrics.md + bootstrap/
├── examples/
└── references/sources.md
```

## 快速开始

```bash
# 测试（单元 + 10 强制场景 + 路由集成）
python -m pytest skills/micp-reproducibility-versioning/tests/

# 评测（M1-M7 指标，离线）
python skills/micp-reproducibility-versioning/evals/run_evals.py

# 自举复现演示（真实执行：manifest→锁环境→记录输入→执行→保存→重跑→比较）
python skills/micp-reproducibility-versioning/evals/bootstrap/run_bootstrap.py

# 直接调用工具
echo '{"action":"env","task_id":"t1","project_id":"p","request":"采集环境"}' \
  | python skills/micp-reproducibility-versioning/tools/mrv/cli.py env
```

## 工具一览

| 工具 | 用途 |
|---|---|
| `service` | 完整管线（校验→版本→前置→子工具→自检） |
| `reproduce` | 一键复现流水线 |
| `manifest` | 数据清单生成器 |
| `env` | 环境信息采集器 |
| `lock` | 依赖导出与锁定 |
| `seed` | 随机种子管理器 |
| `record` | 输入输出 provenance 记录器 |
| `diff` | 结果差异比较器 |
| `compat` | 版本兼容检查器 |
| `migrate` | Schema 迁移器 |
| `check-raw` | 原始数据写保护检查器 |
| `check-pollution` | 产物污染检测器 |
| `validate` | 输入 schema 校验 |

## 契约

统一输出信封（12 字段）：`status / summary / findings / assumptions / evidence_used / uncertainty / risks / artifacts / requested_next_skills / validation / provenance / errors`，外加 `reproduction_manifest / data_lineage / environment / versions / hashes / reproducibility_checks / differences / migration_actions / risks / artifacts / validation / provenance / errors`。状态枚举：`SUCCESS | PARTIAL | BLOCKED | FAILED | NEED_ADDITIONAL_SKILL | HUMAN_APPROVAL_REQUIRED`。认识论标签：`OBSERVED | REPORTED | CALCULATED | INFERRED | HYPOTHESIS | RECOMMENDATION`。

## 测试覆盖的 10 个强制场景

1. 全新临时环境运行最小示例
2. 修改参数追踪受影响结果
3. 修改原始数据（被阻止或报警）
4. 依赖升级导致结果变化
5. 随机种子缺失
6. Schema 主版本不兼容
7. 中途崩溃后恢复
8. 同一输入重复运行结果一致
9. 外部数据源不可用时使用快照
10. 文件被手工覆盖后检测哈希变化

详见 [tests/](tests/) 与 `tests/test_scenarios.py`。
