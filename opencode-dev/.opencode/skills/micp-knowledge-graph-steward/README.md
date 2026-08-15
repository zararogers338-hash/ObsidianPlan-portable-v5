# MICP Knowledge Graph Steward

本体、知识图谱与长期记忆治理。MICP 研究中所有知识项——菌株、酶、底物/反应物/产物、离子、矿物相、多孔介质、工艺、仪器、实验、性能、环境指标——的统一、可审计、可版本化、可迁移、可备份恢复的知识图谱治理 Skill。

## 这是什么

一个**真实可加载、可测试、可维护的 Skill 工程包**（标准 Skill 格式，与兄弟 Skill `obsidian-state-manager` 同一契约族）：

- **事件溯源存储**：每个 `project_id` 一条 hash 链 `events.jsonl`；快照是纯投影；追加原子；备份确定性 zip；恢复拒绝写入存活流。
- **冲突共存**：矛盾声明（如 calcite vs vaterite）**同时保留**，追加 OPEN 冲突记录，绝不静默覆盖。
- **认识论标签治理**：`INFERRED`/`HYPOTHESIS`/`RECOMMENDATION` 永不被标成 `OBSERVED`；声明标签强度不得超过证据层级（KGE-E204）。
- **单位与量程校验**：数值声明必须带 `{value, unit}`；维数兼容与基准换算（KGE-E203）。
- **审批门**：`VALIDATED` 写入、迁移、恢复、破坏性本体替换、冲突裁决、批量导入需版本化人工审批（KGE-E502/E503）。
- **本体演进**：非破坏性扩展 / 破坏性替换都作为 `ONTOLOGY_UPDATED` 事件落链，历史不丢。
- **版本兼容**：主版本不符 → KGE-E801；旧布局 → 显式迁移或拒绝（KGE-E802）。

## 快速开始

```bash
# 初始化知识库
python tools/knowledge_graph_steward.py --store /tmp/kge-store < examples/01-init.json

# 运行测试
python -m pytest tests/ -q

# 运行评估（含 M1–M7 最低性能指标）
python evals/run.py

# 运行示例
bash examples/run-examples.sh
```

## 包结构（标准 Skill 格式）

```
micp-knowledge-graph-steward/
├── SKILL.md                    # 加载器契约（frontmatter name+description）+ 触发/边界/错误码/协作
├── skill.yaml                  # 机器可读清单（capabilities/units/permissions/stop_conditions…）
├── README.md                   # 本文档
├── prompts/system.md           # 系统提示（角色、标签、审批、失败行为）
├── schemas/
│   ├── input.schema.json       # 输入契约（统一封套 + 全部 action 载荷）
│   └── output.schema.json      # 输出契约（统一输出封套）
├── tools/
│   ├── knowledge_graph_steward.py  # CLI 入口（stdin=JSON→stdout=JSON，离线）
│   └── kg/                     # 核心库（纯函数，无网络）
│       ├── models.py           # 实体/关系/证据层级/认识论标签/错误码（单一真源）
│       ├── store.py            # 事件溯源存储 + 快照 + 备份/恢复
│       ├── io.py               # 本体 schema 生成 + 图谱导入/导出
│       ├── conflicts.py        # 冲突检测与证据链
│       ├── normalize.py        # 同义词/缩写/单位规范化
│       ├── migration.py        # 迁移决策与执行
│       ├── service.py          # 服务门面（动作分派 + 全部治理门）
│       ├── validate.py         # jsonschema（含内置回退）
│       ├── errors.py / ontology.py / __init__.py
├── tests/                      # 单元/集成/失败/自举自测（conftest 共享夹具）
├── evals/
│   ├── cases.yaml              # ≥8 用例（正常/缺失/冲突/对抗/边界）
│   ├── metrics.py              # M1–M7 最低性能指标
│   └── run.py                  # 经真实 CLI 执行评估
├── examples/                   # ≥3 个可直接运行的示例
├── references/sources.md       # 契约/实现来源（含访问日期与局限）
└── CHANGELOG.md
```

## 动作一览

| 分组 | 动作 |
|---|---|
| 知识库 | `kb.init` `kb.get` `kb.list` `kb.backup` `kb.restore` `kb.migrate` `kb.integrity` |
| 图写入 | `graph.upsert_entity` `graph.add_relation` `graph.remove_relation` |
| 声明 | `graph.add_claim` `graph.supersede_claim` `graph.retract_claim` |
| 证据 | `graph.evidence_register` `graph.evidence_retract` `graph.evidence_chain` |
| 冲突 | `graph.conflict_scan` `graph.conflict_resolve` |
| 本体/查询 | `graph.ontology` `graph.ontology_update` `graph.query` `graph.import` `graph.export` |
| 审批 | `approval.grant` |

## 自举自测（验收 §八）

1. **同名不同条件不误合并**：两个不同实体共享规范名 → 记录但**不合并**，仅给出身份候选建议（IDENTITY 声明才可确立同一性）。
2. **矛盾晶体相共存可追溯**：同一对象 calcite vs vaterite → 两条声明并存 + OPEN 冲突 + 证据链。
3. **本体演进保留历史**：ONTOLOGY_UPDATED 后旧声明照常可查，版本单调递增。
4. **查询不把假设当事实**：HYPOTHESIS 声明在查询结果中标签恒为 `HYPOTHESIS`。

## 测试与评估

```bash
python -m pytest tests/ -q                    # 单元/集成/失败/自举
python evals/run.py                           # 经真实 CLI 跑全部用例 + M1–M7
bash examples/run-examples.sh                 # 端到端示例
```

环境注意：本机用 `python`（Anaconda 3.13），`python3` 是无效的 Store 别名。
