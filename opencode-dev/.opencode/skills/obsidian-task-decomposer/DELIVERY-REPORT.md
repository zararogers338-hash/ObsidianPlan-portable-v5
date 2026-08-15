# 交付报告 — obsidian-task-decomposer v1.0.0

> 生成日期：2026-08-06 ｜ 生成者：Claude Fable 5（以「首席工程师 + 首席科学家 + Claude Code 实施者」标准执行）
> 本报告对应该 skill 工程包在仓库中的真实路径 `.opencode/skills/obsidian-task-decomposer/`。

## 1. 仓库与标准识别结果

| 项 | 结论 |
|---|---|
| 仓库 | `.opencode` —— OpenCode (anomalyco) monorepo 的本地 fork，`bun` workspace。OBSIDIAN-PLAN.md 确认这是 OBSIDIAN 改造的基底。 |
| Skill 真实加载方式 | **OBSERVED**（读自 `packages/opencode/src/skill/index.ts`）：扫描 `.opencode/skills/**/SKILL.md`、`{skill,skills}/**/SKILL.md`（config 目录）、`.claude/skills/`、`.agents/skills/`；只读取 frontmatter 的 `name` + `description`（`^[a-z0-9]+(-[a-z0-9]+)*$`，须与目录名一致）。 |
| 调用契约 | **OBSERVED**（`packages/opencode/src/tool/skill.ts`）：`skill` 工具把 SKILL.md 正文 + skill 基目录 + 采样文件列表注入对话；相对路径由执行 agent 解析。 |
| 测试框架 | pytest 8.4.2（已装）；工具全部为 Python 3.10+ stdlib，离线、确定性。 |
| 依赖 | 运行时零第三方依赖；评测 runner 仅在报告阶段需要 PyYAML（已避免——改用 markdown 解析器）。 |
| 自定义约定声明 | `skill.yaml`（machine-readable manifest）、`schemas/`、`tools/`、`tests/`、`evals/`、`examples/` 的完整目录布局、错误码表、认识论标签、信封契约，均为 **Obsidian Plan / Panshi 项目自定义约定**，已在 `README.md`/`skill.yaml`/`references/sources.md` 中明确标注，非 OpenCode 标准。 |

## 2. 新增和修改文件清单

（全部位于 `.opencode/skills/obsidian-task-decomposer/`，纯增量，未触碰仓库任何存量文件）

```
SKILL.md                      入口：frontmatter(name/description) + 触发/流程/工具表/停止规则
skill.yaml                    机器可读 manifest：版本、兼容性、权限、入口点、schema 路径、版本策略、最低性能指标
prompts/system.md             最小系统提示词（身份/边界/认识论/停止规则/错误码/MICP guardrail）
schemas/input.schema.json     严格输入契约 v1.0.0
schemas/output.schema.json    严格输出契约 v1.0.0
schemas/task-node.schema.json 单 DAG 节点契约 v1.0.0
tools/_common.py              信封契约 + 校验器（工具集共享）
tools/_jsonschema.py          最小 JSON Schema 2020-12 子集校验器（离线）
tools/validate.py             schema 校验
tools/dag_check.py            Kahn 拓扑排序、环证据、层级、并行度
tools/granularity_scorer.py   粒度评分（TOO_FINE/OK/TOO_COARSE/UNDER_SPECIFIED）
tools/budget_estimator.py     参考类预算（计划谬误对冲）
tools/critical_path.py        CPM 前/后向、slack、关键路径
tools/replan_diff.py          局部重规划（保留已确认事实与已完成工作）
tools/self_audit.py           验收门 G1–G6
tools/README.md               工具逐个契约
tests/conftest.py             测试夹具 + run_tool 助手
tests/test_integration.py     集成测试（完整管线过 G1–G6）
tests/test_failure.py         失败路径（malformed/conflict/adversarial）
tests/test_unit.py            单元测试（数学/语义）
tests/test_regression.py      契约稳定性/确定性回归
tests/test_schema_subset.py   证明我们的 schema 只在校验器支持的子集内
evals/cases.yaml              ≥8 个评测用例（含对抗/冲突/边界）
evals/run_evals.py            离线评测运行器（真实工具调用，7 项指标）
evals/run_bootstrap.py        自举测试（4 场景，以 skill persona 运行）
evals/_bootstrap_nodes.py     自举共享 DAG 节点
examples/01-basic-micp/       MICP DAG 端到端示例（input/expected-dag/run.sh）
examples/02-replan-after-failure/ 局部重规划示例
examples/03-blocked-missing-request/ BLOCKED 示例
references/sources.md         来源（含访问日期、用途、关键限制）
CHANGELOG.md                  版本记录
README.md                     维护者说明
```

## 3. Skill 输入输出契约

- **输入**（`schemas/input.schema.json`，`additionalProperties: false`）：必需字段含 `task_id`、`project_id`、`request`（≥10 字符）、`risk_level`（low/medium/high）、`human_approval_state`（required/granted）、`requested_output_format`（json|markdown+json）、`skill_version`、`controller_version`、`timestamp`；可选 `context`、`constraints`、`evidence_refs`、`data_refs`、`upstream_outputs`、`replan_of`。
- **输出**（`schemas/output.schema.json`）：`status` 六值枚举（SUCCESS/PARTIAL/BLOCKED/FAILED/NEED_ADDITIONAL_SKILL/HUMAN_APPROVAL_REQUIRED）；`BLOCKED` 强制 `missing_inputs`（field/why_critical/how_to_obtain）；SUCCESS/PARTIAL 强制 `artifacts` 含 `task_dag`；`errors[].code` 受限枚举（E_SCHEMA_INPUT…E_INTERNAL）；所有 load-bearing 陈述带认识论标签（OBSERVED/REPORTED/CALCULATED/INFERRED/HYPOTHESIS/RECOMMENDATION）。
- **节点契约**（`schemas/task-node.schema.json`）：单 `primary_skill`、≤1 `collaborator_skill`、显式 `depends_on`/`inputs`（生产者命名）、可验证 `definition_of_done`（artifact + 定量 acceptance_criteria + unit）、`failure_modes`/`retry_policy`/预算/风险/敏感度/`human_approval_gate`。

## 4. 所造工具及其用途

| 工具 | 算法/依据 | 用途 |
|---|---|---|
| `dag_check.py` | Kahn 1962（sources.md S7） | 环证据、未知依赖、自环、重复 id、拓扑序、并行层级 |
| `granularity_scorer.py` | PMBOK 7th + 计划谬误（S5/S8），加权子分 | 防止调度爆炸 / 防止不可验收巨块；UNDER_SPECIFIED 永不为 OK |
| `budget_estimator.py` | 参考类预测（S5），项目自定义参考类 | 按 kind×risk×sensitivity×context×buffer 估算工时/成本，标注 CALCULATED |
| `critical_path.py` | CPM 前/后向（S6） | 关键路径、slack、并行度、可选/失败回退路径 |
| `replan_diff.py` | 下游闭包 + 分类 | 局部重规划：只重做受影响路径；保留/标记 stale 已完成节点；合并图须保持 DAG |
| `self_audit.py` | 契约机械门 | G1 无隐式依赖、G2 单所有者、G3 可验证 DoD、G4 无环、G5 上限+人工门、G6 认识论标签 |
| `validate.py` + `_jsonschema.py` | JSON Schema 2020-12 子集 | 契约强校验（含路径逃逸防护 E_PATH_ESCAPE） |

所有工具：**单 JSON 输入/输出、信封 `{"ok":true,"result":...}`、退出码 0/2/3/4、数值拒绝非有限/空/越界、离线确定性**（同输入两次运行字节一致）。全部工具已实际运行（非口头声明），见 §5。

## 5. 真实执行过的测试和结果

| 套件 | 命令 | 结果 |
|---|---|---|
| 单元+集成+失败+回归+schema子集 | `python -m pytest tests/ -q` | **38 passed** in 2.27s |
| 评测（10 case，含对抗/冲突/边界/畸形） | `python evals/run_evals.py` | **7 项指标全部 1.0**（结构化输出通过率/工具真实调用率/证据可追溯率/缺失输入识别率/对抗拦截率/重复一致性/平均恢复时间 0.045s） |
| 自举（4 场景，真实工具调用） | `python evals/run_bootstrap.py` | **4/4 通过**：MICP 全 DAG 过 G1–G6 + 输出 schema；循环依赖被 dag_check 报告 + critical_path E_GRAPH_CYCLIC(exit 3)；失败实验只重规划受影响路径；纸面研究审查零不可验收节点 |
| 示例端到端 | `bash examples/0{1,2,3}*/run.sh` | 01 全管线 OK；02 replan 语义正确（preserved/rework/invalidated/added/removed 精确匹配）；03 缺失输入被识别 |

## 6. 自举测试中发现的问题及修复

| 问题 | 根因 | 修复 |
|---|---|---|
| 自举 replan 场景断言失败 | 工具按字母序返回 invalidated 列表，断言用了插入序 | 断言改为确定性字母序 `["ammonium_balance","mechanism_model"]` |
| 示例 01/02 脚本路径失效 | run.sh 用相对路径、cwd 不在脚本目录 | 全部改用 `$(cd "$(dirname "$0")")` 绝对定位 + 通过环境变量把工具路径传给内嵌 Python |
| 评测 runner 早期报 E_OUTPUT_SHAPE | 给 self_audit 传了完整输出文档（节点包在 artifacts 内），而 self_audit 期望候选形态（顶层 `dag`） | 拆分 `build_candidate_output`（供 self_audit）与 `build_output_doc`（供输出 schema 校验） |
| 评测 eval-10 merged 断言过时 | replan 语义更新为「rework 节点保留、invalidated 删除」后 node_count 变化 | 断言改为「merged 图 2 节点且拓扑有效」 |
| cases.yaml 早期 YAML 解析失败 | 文件实为 markdown 规格而非纯 YAML | runner 改为正则解析 markdown 区块（无需 PyYAML） |

另：`replan_diff.py`、`self_audit.py`、`tests/*` 经工具链/用户修正后重新全量验证通过（replan 改为 rework 保留标记语义；self_audit 扩展 external prefix 处理；schema 子集测试收紧）。

## 7. 尚未关闭的风险和限制

- **参考类预算是估计，不是承诺**：工时/关键路径 slack 继承计划谬误误差（S5/S6），标注 CALCULATED。
- **机械门 ≠ 研究质量**：self_audit 证明的是必要不充分条件；内容对抗审查归属 `obsidian-red-team`。
- **文件列表采样**：OpenCode 的 `skill` 工具只注入采样的文件列表（limit 10）；本 skill 不依赖枚举，所有文件按相对路径按需读取。
- **`skill_version` 不匹配**：控制器不得把 MAJOR 不同的旧 artifact 直接喂给 replan_diff（版本策略见 skill.yaml + CHANGELOG 迁移说明）。
- **schema 子集限制**：我们的校验器只支持 2020-12 的受控子集；新增 schema 关键字前必须先跑 `test_schema_subset.py`。
- **Windows 路径 / PATH**：工具要求 `python` 在 PATH 上（测试用的是 anaconda3 的 python，示例脚本用 `python`，若环境用 `python3` 需改一处变量）。

## 8. 调用示例

控制器/用户以 JSON 契约调用；交互式 OpenCode 会话中由原生 `skill` 工具按需加载，执行 agent 跑 `tools/*.py` 管线。最小调用：

```bash
cd .opencode/skills/obsidian-task-decomposer
# 输入契约校验
python tools/validate.py  <<< '{"schema":"schemas/input.schema.json","document": <input>}'
# 产出节点后依次：
python tools/dag_check.py            <<< '{"nodes": <nodes>}'
python tools/granularity_scorer.py   <<< '{"nodes": <nodes>}'
python tools/budget_estimator.py     <<< '{"tasks": <tasks>}'
python tools/critical_path.py        <<< '{"nodes": <nodes>}'
python tools/self_audit.py           <<< '{"output": <candidate>, "external_inputs": [...]}'
# 局部重规划：
python tools/replan_diff.py          < examples/02-replan-after-failure/replan-input.json
```

完整可运行示例见 `examples/`（01 基本 MICP、02 失败后重规划、03 缺失输入 BLOCKED），各自带 `run.sh`。

## 9. 版本号与后续演进建议

- **当前版本 1.0.0**（契约冻结）。版本策略在 `skill.yaml` `version_policy`：破坏性 schema/错误码/退出码变更 → major；新增可选字段/枚举/工具 → minor；纯实现修复 → patch。变更记入 `CHANGELOG.md`。
- **建议后续**：
  1. 接入 Obsidian Router 的注册表，让 `requested_next_skills` 反向校验下游 skill 是否存在。
  2. 与 `obsidian-red-team` 打通：自举 §4 的「纸面研究审查」升级为真正调用 red-team skill 的对抗回合。
  3. 为 `budget_estimator` 的参考类校准引入真实 MICP 项目历史数据（当前为项目自定义默认值）。
  4. 增加 `format`/`lint`/`type-check` 最小 CI 门（仓库当前无这些基础设施；已提供 pytest + evals 作为最小可行基线）。
  5. 中文报告/示例本地化（当前文档双语，术语以英文为主）。

---

**完成定义确认**：本 skill 已在当前 Obsidian/OpenCode 工程中被加载（位于仓库 `.opencode/skills/` 标准发现路径，frontmatter 满足 loader 约束）、被调用（工具为真实可执行程序，测试与评测全部实际运行）、可审计（错误码/认识论标签/provenance/来源记录）、并通过验收（38 测试 + 10 评测 + 4 自举全绿）。
