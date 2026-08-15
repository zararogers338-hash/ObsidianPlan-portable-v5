# micp-hypothesis-forge — 实施计划

> 本文件是开工前的极简实施计划(任务书要求"写代码前输出一份极简实施计划,但不要停在计划阶段")。真正的工程包从 `SKILL.md` 与 `tools/` 开始。

## 1. 仓库与标准识别结果(摘要)

- 仓库根:`opencode-src/opencode-dev`(anomalyco/opencode 的 Obsidian 改造 fork)。
- OpenCode 原生 Skill 约定(实测 `packages/opencode/src/skill/index.ts`):
  - 发现模式 `**/SKILL.md`;frontmatter 只读取 `name` + `description`;
  - `name` 必须满足 `^[a-z0-9]+(-[a-z0-9]+)*$` 且匹配目录名。
- Obsidian/Panshi 项目自定义约定(由 `obsidian-skill-router`、`obsidian-state-manager`、`obsidian-task-decomposer`、`obsidian-mission-lock`、`micp-*` 已确立):
  - `SKILL.md`(触发/反触发/边界/错误码/停止规则) + `skill.yaml`(机器元数据,注名"项目自定义约定") + `schemas/{input,output}.schema.json` + `prompts/system.md` + `tools/` + `tests/` + `evals/` + `examples/` + `references/sources.md` + `CHANGELOG.md`。
  - 工具:Python 3.10+ 纯标准库、离线、确定性;stdin 一个 JSON → stdout 一个 JSON 信封 `{"ok":true,"result":...}` / `{"ok":false,"error":...}`;退出码 0/2/3/4。
  - 错误码:前缀 + 分类数字(`OPM-E1xx` 等),`errors.py` 为唯一事实源。
  - 认识论标签六类;输出封套六个状态;性能指标在 evals 中实现。

## 2. 目标目录

`skills/micp-hypothesis-forge/`(与现有 MICP 技能平级)。

## 3. 实施步骤

1. `tools/mhfx/` 纯 Python 工具链(见下)+ `tools/mhfx/errors.py` + `tools/_common.py`(信封助手)。
2. `schemas/input.schema.json` + `schemas/output.schema.json` + `schemas/hypothesis-card.schema.json` + `schemas/card-set.schema.json`。
3. `SKILL.md`、`skill.yaml`、`prompts/system.md`、`references/sources.md`。
4. `tests/`(unit + failure + integration + regression)+ `evals/cases.yaml` + `evals/run_evals.py` + `evals/metrics.py`。
5. `examples/`(3 个可运行示例 + 运行脚本)。
6. `CHANGELOG.md`、`README.md`。
7. 真实运行测试与评测;自举测试;修复;验收报告。

## 4. 工具链(五个 + 自检)

| 工具 | 职责 | 关键算法/依据 |
|---|---|---|
| `dag.py` | 机制链 → 因果 DAG;环/未知边/自环检测,祖先闭包 | Kahn 拓扑 |
| `card-validate.py` | Hypothesis Card / Card Set 严格 schema 校验;认识论、反证条件、观测变量、时间尺度完备性 | 自定义 G1–G6 |
| `competing-matrix.py` | 竞争假设矩阵:判别方向/唯一判别实验/信息增益 | 判别实验成本收益 |
| `scoring.py` | 可证伪性 + 可测量性 + 判别力评分(0–1) | 从卡字段特征计算,确定性 |
| `experiment-priority.py` | 判别实验优先级排序 | 信息增益×成本×风险;UR/PR 模型 |
| `self-audit.py` | 输出封套自检门 G1–G7 | 契约 + 认识论 + 可追溯 |

外加 `tools/mhfx/errors.py`(MHX-E 错误码唯一事实源)、`tools/_common.py`(信封/数值守卫)。

## 5. 关键契约决策

- 输出封套:完全镜像 `obsidian-state-manager` 输出 schema 的骨架(`contract_version`、`skill`、`skill_version`、`status`、`summary`、`findings`、`assumptions`、`evidence_used`、`uncertainty`、`risks`、`artifacts`、`requested_next_skills`、`validation`、`provenance`、`errors`),并**新增必需字段** `missing_inputs`(MHF 专业契约,任务书"不得笼统'信息不足'"要求)。
- 认识论标签:六类枚举,输出 schema 对 `findings[]`/`risks[]` 强制。
- 错误码前缀 `MHX-E`;1xx 输入、2xx 证据/单位、3xx 上下文、4xx 工具、5xx 权限/审批、6xx 下游、7xx 自检/输出、8xx 兼容。
- 版本兼容:语义化版本,主版本不匹配明确拒绝(`MHX-E801`)。
- 性能指标 7 项在 evals 中实现,阈值与 router 同量级。

## 6. 自举测试(任务书第八节)

1. "高脲酶活性导致强度下降" → ≥3 机制解释 + 主/竞争假设卡。
2. "入口堵塞" → 化学速率/细胞截留/流场三类竞争假设矩阵。
3. 给出不可证伪表述 → 工具/系统拒绝或重写。
4. 自设计最小判别实验并自检是否真正区分。

完成后按第十节输出结构化交付报告。
