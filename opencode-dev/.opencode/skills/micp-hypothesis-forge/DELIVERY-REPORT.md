# micp-hypothesis-forge — 最终交付报告

> 版本 1.0.0 · 2026-08-06 · Obsidian Plan (Panshi) 受治理 Skill

## 1. 仓库与标准识别结果

- **仓库根**:`opencode-src/opencode-dev`(anomalyco/opencode 的 Obsidian 改造 fork,bun workspace)。
- **OpenCode 原生 Skill 约定**(实测 `packages/opencode/src/skill/index.ts`):发现模式 `**/SKILL.md`;frontmatter 只读 `name` + `description`;`name` 必须 `^[a-z0-9]+(-[a-z0-9]+)*$` 且匹配目录名。
- **Obsidian/Panshi 项目自定义约定**(由 `obsidian-skill-router`、`obsidian-state-manager`、`obsidian-task-decomposer`、`micp-*` 等已确立):`SKILL.md` + `skill.yaml`(机器元数据,注明"项目自定义约定")+ `schemas/{input,output}.schema.json` + `prompts/system.md` + `tools/`(纯 Python 3.10+ stdlib,stdin 一 JSON → stdout 一 JSON 信封,退出码 0/2/3/4)+ `tests/` + `evals/` + `examples/` + `references/sources.md` + `CHANGELOG.md`。
- 本 Skill 严格遵循以上约定;`skill.yaml` 注明 `schema_version: "1.0"` 为项目自定义。

## 2. 新增/修改文件清单(39 个文件)

| 类别 | 文件 |
|---|---|
| 身份 | `SKILL.md`, `skill.yaml`, `prompts/system.md` |
| 契约 | `schemas/input.schema.json`, `schemas/output.schema.json`, `schemas/hypothesis-card.schema.json`, `schemas/card-set.schema.json` |
| 工具 | `tools/dag.py`, `tools/scoring.py`, `tools/card-validate.py`, `tools/competing-matrix.py`, `tools/experiment-priority.py`, `tools/self-audit.py`, `tools/_common.py`, `tools/README.md` |
| 工具核心 | `tools/mhfx/errors.py`(MHX-E 错误码唯一事实源), `tools/mhfx/models.py`, `tools/mhfx/jsonschema.py` |
| 测试 | `tests/conftest.py`, `tests/test_unit.py`, `tests/test_failure.py`, `tests/test_integration.py`, `tests/test_regression.py` |
| 评测 | `evals/cases.yaml`, `evals/run_evals.py`, `evals/metrics.py`, `evals/run_bootstrap.py`, `evals/miniyaml.py`, `evals/results/{latest.json, bootstrap.jsonl}` |
| 示例 | `examples/01-ureolysis-strength.json`, `examples/02-inlet-clogging.json`, `examples/03-nonuniform-calcite.json`, `examples/run-examples.sh` |
| 文档 | `README.md`, `README-安装说明.md`(zip 内), `references/sources.md`, `CHANGELOG.md`, `PLAN.md`(实施计划) |

## 3. Skill 输入输出契约

- **输入**(最小必需):`task_id, project_id, request, risk_level, human_approval_state, requested_output_format, skill_version, controller_version, timestamp`;可选 `context, constraints, evidence_refs, data_refs, upstream_outputs, statement_to_forge, min_hypotheses, max_hypotheses, strict_mode`。
- **输出**:`contract_version, skill, skill_version, status, summary, findings, assumptions, evidence_used, uncertainty, risks, artifacts, requested_next_skills, validation, provenance, errors`;`BLOCKED` 时必带 `missing_inputs`(field / why_critical / how_to_obtain)。状态六类:`SUCCESS/PARTIAL/BLOCKED/FAILED/NEED_ADDITIONAL_SKILL/HUMAN_APPROVAL_REQUIRED`。
- **认识论标签**:`OBSERVED/REPORTED/CALCULATED/INFERRED/HYPOTHESIS/RECOMMENDATION`。

## 4. 所造工具及用途(全部纯 stdlib、离线、确定性)

| 工具 | 用途 |
|---|---|
| `dag.py` | 机制链 → 因果 DAG;环/自环/未知引用检测;祖先/后裔闭包;拓扑序 |
| `scoring.py` | 可证伪性 / 可测量性 / 判别力评分(0–1)与判定 |
| `card-validate.py` | Hypothesis Card / Card Set 严格 schema 校验 + 合规审计(7 项检查) |
| `competing-matrix.py` | 竞争假设矩阵:逐观测显式预测、判别实验、信息增益 |
| `experiment-priority.py` | 判别实验按 信息增益×成本×风险 排序,预算上限 |
| `self-audit.py` | 输出封套自检门 G1–G7(schema/认识论/可追溯/反证/完备/溯源) |
| `mhfx/errors.py` | MHX-E1xx~E8xx 错误码唯一事实源 |
| `mhfx/jsonschema.py` | 自研 JSON-Schema 子集校验器(离线、路径防逃逸) |

## 5. 真实执行过的测试与结果

| 套件 | 结果 |
|---|---|
| `python -m py_compile` 全部 .py | 通过 |
| `pytest tests/`(单元 21 + 失败 25 + 集成 5 + 回归 7) | **58 passed** |
| `python evals/run_evals.py`(11 用例 + 7 指标) | **11/11 passed, 7/7 指标达标** |
| `python evals/run_bootstrap.py`(自举 4 项 + 封套自检) | **全部通过** |
| `bash examples/run-examples.sh` | 全部运行成功 |
| **ZIP 解压副本重跑** | 58 passed + 11/11 evals 通过(包自洽) |

7 项性能指标实测:结构化输出通过率 1.0、工具真实调用率 1.0、证据可追溯率 1.0、缺失输入识别率 1.0、对抗拦截率 1.0、重复运行一致性 1.0、平均失败恢复时间 0.061s(阈值 ≤60s)。

## 6. 自举测试中发现的问题及修复

1. **dag.py 扁平列表误解析** — `["A","B","C"]` 被当多条单步链拒绝。修复:按字段名区分 `mechanism_chain`(单链)与 `chains`(多链)。
2. **dag.py 环/祖先不可见** — `depends_on` 未挂到节点,拓扑排序与祖先闭包看不到边。修复:`build_graph` 为每节点构造 `depends_on`。
3. **jsonschema SKILL_ROOT 路径** — 指向 tools/ 而非技能根,导致 schema 文件"not found"。修复:多上溯一级。
4. **competing-matrix 方向推断** — 只读 refutation 且缺 `declines` 等词;`no_change`/`increase` 无法同卡共存。修复:①读 statement+refutation 全文;②支持 `observable_predictions` 逐观测显式声明(最高优先级);③扩展关键词表。
5. **self-audit G1/G7 共用错误列表** — 一个失败泄漏到另一个。修复:逐门独立。
6. **miniyaml 解析器** — 两版重写解决 `key:` 后列表的前瞻;帧缩进改为父行缩进;剥离引号。
7. **evals 指标计算方向** — 时间指标 `>=` 改为 `<=`;对抗 GHOST-ref 用例从 traceability 分母排除;全流水线用例单列 ≥3 工具要求。

## 7. 尚未关闭的风险与限制

- 工具是**确定性文本处理器**:对卡片特征打分,科学判断在系统提示词 + 控制器层,不在工具内。
- 信息增益假设**对称先验 + 默认灵敏度/特异性 0.9/0.9**;真实实验应覆盖这两个参数。
- 方向推断是**关键词启发式**:含歧义短语(如 "exceeds...declines")时返回 null 方向并如实说明;权威路径是 `observable_predictions`。
- **未做真机自举**(让 Claude 作为本 Skill 在完整控制器会话中运行):当前自举通过子进程真实调用全部 6 工具完成,等价覆盖工具层;端到端控制器接线需在 OpenCode 运行态验证。
- `miniyaml` 是评测专用子集解析器,不用于技能运行路径;若用例文件结构超出其支持子集会显式报错而非误解析。

## 8. 调用示例

```bash
cd opencode-dev/skills/micp-hypothesis-forge
# 技能完整流程(自举演示):
python evals/run_bootstrap.py
# 或直接调单个工具:
echo '{"mechanism_chain":["high urease activity","accelerated hydrolysis","NH4+ accumulation","reduced strength"]}' | python tools/dag.py
```

输出信封示例:
```json
{"ok": true, "tool": "dag", "version": "1.0.0",
 "result": {"acyclic": true, "node_count": 4, "edge_count": 3,
            "topological_order": ["high urease activity", "accelerated hydrolysis",
                                  "NH4+ accumulation", "reduced strength"],
            "ancestry": {...}}}
```

## 9. 版本号与后续演进建议

- 版本:`1.0.0`;契约 `1.0`;工具集 `1.0.0`。语义化策略见 `skill.yaml version_policy`(破坏性→主版本,新增→次版本,修复→修订;旧主版本输出明确拒绝 `MHX-E801`)。
- **建议演进**:
  1. 接入 `obsidian-skill-router` 的真实路由(当前 `requested_next_skills` 已声明合作契约,如 `obsidian-experiment-designer`)。
  2. 信息增益支持真实先验输入(来自 `micp-evidence-synthesizer` 的证据强度)。
  3. 判别实验模板库(成本/风险/时间的 reference-class 估算),对接 `obsidian-state-manager` 的状态持久化。
  4. 在 OpenCode 运行态做端到端控制器验证(本次为工具层自举)。
