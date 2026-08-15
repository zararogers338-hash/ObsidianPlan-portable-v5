micp-knowledge-graph-steward  v1.0.0
================================================================

用途 / Purpose
================================================================
MICP Knowledge Graph Steward｜本体、知识图谱与长期记忆治理。

这是一个符合标准 Skill 格式（Obsidian Plan / OpenCode 项目约定）的
可加载、可测试、可维护的 Skill 工程包：

  1. 事件溯源知识图谱存储（hash 链 events.jsonl + 纯投影快照）
  2. 实体/关系/声明/证据治理（菌株·酶·离子·矿物相·多孔介质·工艺·
     仪器·实验·性能·环境指标）
  3. 矛盾事实共存为 OPEN 冲突，绝不静默覆盖
  4. 认识论标签强度治理（INFERRED/HYPOTHESIS 永不被标成 OBSERVED）
  5. 单位/量程校验（KGE-E203）
  6. VALIDATED 写入·迁移·恢复·冲突裁决·破坏性本体替换需版本化
     人工审批（KGE-E502/E503）
  7. 本体演进保留历史、迁移、确定性备份/恢复、完整性自检
  8. 24 个动作 + 统一输入/输出封套 + 错误码体系（KGE-E1xx..8xx）

验证状态 / Verification
================================================================
  - pytest:      42 passed (单元/集成/失败/自举自测)
  - evals:       10/10 用例通过，M1-M7 全部达标
  - examples:    3 个端到端示例通过
  - SKILL.md     frontmatter name+description 符合 OpenCode 加载器契约

快速开始 / Quick start
================================================================
  python tools/knowledge_graph_steward.py --store /tmp/kge < examples/01-init.json
  python -m pytest tests/ -q
  python evals/run.py
  bash examples/run-examples.sh

（本机用 python=Anaconda；python3 为无效 Store 别名）
