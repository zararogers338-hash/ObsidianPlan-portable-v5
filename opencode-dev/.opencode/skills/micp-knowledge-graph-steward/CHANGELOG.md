# MICP Knowledge Graph Steward — 变更日志

版本策略（契约 §十一.3）：破坏性输入/输出契约变更 → major；新增可选字段 → minor；实现修复 → patch。旧 major 下的输出要么显式迁移，要么拒绝（KGE-E801/E802），绝不静默改写。

## [1.0.0] — 2026-08-06

首个可加载、可测试、可维护的发布。

### 新增
- **存储**：事件溯源知识库（`tools/kg/store.py`）——每个 `project_id` 一条 hash 链 `events.jsonl`；快照为纯投影；追加原子（temp+os.replace）；确定性 zip 备份（`backups/kb-r<rev>.zip`，带 checksums）；恢复拒绝写入存活流，支持 `dry_run`。
- **本体与词汇**（`models.py` / `io.py` / `ontology.py`）：16 实体类型、17 关系类型、7 声明种类、6 证据层级、6 认识论标签、3 置信度；本体 JSON-Schema 生成与按词汇校验；图谱 JSON/YAML 导入导出。
- **规范化**（`normalize.py`）：菌株/矿物/离子/术语同义词表；单位维数换算（含温度偏移）；量程/非有限值校验（KGE-E203）。
- **冲突治理**（`conflicts.py`）：IDENTITY / VALUE（单位感知、20% 容差）/ CAUSAL / 分类声明四类冲突；矛盾**共存**为 OPEN 冲突，绝不静默覆盖；证据链（`evidence_chain`）返回 tier/sha256/撤回状态/未解析引用。
- **服务门面**（`service.py`）：24 个动作；证据核验（KGE-E201/E202）、单位校验（KGE-E203）、认识论标签强度校验（KGE-E204）、版本化审批门（KGE-E502/E503）、全部变更动作支持 `dry_run`；统一输出封套 + 重建==快照自检（KGE-E702）。
- **迁移**（`migration.py`）：布局决策（KGE-E801/E802）与 `MIGRATION_PERFORMED` 事件落链。
- **CLI**（`tools/knowledge_graph_steward.py`）：stdin=JSON → stdout=JSON；`--store` > `MICP_KG_STORE` > `state_store/`；`KGE_TEST_CLOCK` 确定性时钟。
- **契约**（`schemas/`）：输入（统一封套 + 全部 action 载荷）、输出（统一输出封套）。
- **文档**：SKILL.md（正/反/边界触发、错误码、协作）、skill.yaml、README.md、prompts/system.md、references/sources.md。
- **测试**：`tests/` 单元/集成/失败/自举自测 4 套；`evals/` cases.yaml（8 用例）+ metrics.py（M1–M7）+ run.py；`examples/` 3 个可运行示例。

### 修复
- `tools/kg/io.py` 导入路径语法错误（括号不配对）修复。
- `tools/kg/conflicts.py` 缺失 `check_value_range` 导入修复；新增分类声明冲突分支。
- `tools/kg/store.py` `ONTOLOGY_UPDATED` 事件现在持久化声明的本体版本号（历史单调保留）。
- `tools/kg/normalize.py` 重复的 `check_value_range` 定义移除。
- `service.py` 主题外键校验仅针对 `subject`（`predicate`/`object` 是属性/分类词汇，不误报 KGE-E104）。

## 待办（下个里程碑）
- 可视化查询图导出（GraphML/dot）作为可选输出。
- 本体类型间合法关系对约束（如 `CATALYZES` 只允许 ENZYME→*）。
- 多级审批工作流（auditor → PI 双签）。
