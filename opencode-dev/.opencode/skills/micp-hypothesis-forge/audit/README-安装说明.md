# 📦 micp-hypothesis-forge — Skill 安装包

> **这是什么**:Obsidian Plan(黑曜石计划 / Panshi 磐石)体系下的一个受治理专业
> **Skill**,用于 MICP(微生物诱导碳酸钙沉淀)研究中的**机制假设生成、竞争模型与
> 可证伪预测**。

## 用途一句话

把"已核验的现象/观察"变成 **1 个主机制假设 + ≥2 个竞争机制假设**,每个假设都带
可证伪条件、可测变量(带单位)、时间尺度、适用条件、正反证据,并产出**判别实验矩阵**
供实验设计 Skill 直接消费。

## 版本

- **Skill 版本**:1.0.0
- **契约版本**:1.0(input/output schema)
- **工具集版本**:1.0.0
- **环境**:Python ≥3.10,纯标准库,**离线、确定性**,Windows/Linux/macOS 通用

## 安装

```bash
# 解压后放入 Obsidian fork 的 skills/ 目录(与现有 micp-* 技能平级)
# OpenCode 通过 **/SKILL.md 自动发现本技能
unzip micp-hypothesis-forge-1.0.0.zip -d opencode-dev/skills/
```

无需 `pip install`、无需联网、无运行时依赖。

## 使用

控制器以 **一个 JSON 文档** 调用(最小字段见 `schemas/input.schema.json`),技能
返回 **一个 JSON 文档**(契约见 `schemas/output.schema.json`,状态
`SUCCESS/PARTIAL/BLOCKED/FAILED/NEED_ADDITIONAL_SKILL/HUMAN_APPROVAL_REQUIRED`)。

```bash
cd skills/micp-hypothesis-forge
python evals/run_evals.py        # 11 个评测用例 + 7 项性能指标
python evals/run_bootstrap.py    # 任务书第八节自举测试(真实调用工具)
bash examples/run-examples.sh    # 3 个可运行示例
python -m pytest tests -q        # 58 个单元/失败/集成/回归测试
```

## 目录速览

```
micp-hypothesis-forge/
├── SKILL.md                # 身份、6 正触发 / 4 反触发 / 4 边界、错误码、停止规则
├── skill.yaml              # 机器元数据(项目自定义约定)+ 版本策略 + 评测指标
├── prompts/system.md       # 系统提示词(认识论纪律、可证伪规则、锻造流程)
├── schemas/                # input / output / hypothesis-card / card-set 严格契约
├── tools/                  # 6 个纯 stdlib 工具(dag, scoring, card-validate,
│   │                       #   competing-matrix, experiment-priority, self-audit)
│   └── mhfx/               # errors.py(MHX-E 错误码唯一事实源)、models、jsonschema
├── tests/                  # 58 个真实运行的测试
├── evals/                  # cases.yaml + run_evals + metrics + run_bootstrap
├── examples/               # 3 个可运行示例
├── references/sources.md   # 方法学与 MICP 领域依据(含铵态氮质量守恒 S-UR)
└── CHANGELOG.md            # 版本记录与自测修复清单
```

## 认识论纪律

每个重要陈述带六标签之一:`OBSERVED / REPORTED / CALCULATED / INFERRED /
HYPOTHESIS / RECOMMENDATION`。不得把 HYPOTHESIS/INFERRED/RECOMMENDATION 写成
OBSERVED。尿素水解路径必须跟踪铵态氮与质量守恒(每 mol CaCO₃ ≈ 2 mol NH₄⁺,
CALCULATED);非尿素路径不得套用尿素模型。

## 验收结果(2026-08-06)

- 单元/失败/集成/回归测试:**58 passed**
- 评测用例(正常/缺失/冲突/边界/对抗/确定性):**11/11 passed**
- 7 项性能指标:**全部通过**(阈值见 `skill.yaml` `evaluation.indicators`)
- 自举测试(任务书第八节 4 项 + 封套自检):**全部通过**

## 约束与限制

- 工具是确定性文本处理器:对卡片的*特征*打分,科学判断在系统提示词与控制器层。
- 信息增益假设对称先验 + 默认灵敏度/特异性(0.9/0.9),真实实验应覆盖。
- 方向推断基于关键词,是启发式;歧义时返回 null 方向并如实说明,权威路径是用
  `observable_predictions` 显式声明。
- 按设计离线:证据必须经 `evidence_refs / data_refs / upstream_outputs` 提供。

## 版本策略(语义化)

主版本=契约破坏性变更;次版本=新增可选字段;修订=实现修复。旧主版本输出须迁移或
明确拒绝(`MHX-E801`)。详见 `skill.yaml` `version_policy`。
