# Changelog — obsidian-prompt-amplifier

All notable changes to `obsidian-prompt-amplifier` are documented here.
受《Panshi Constitution v1.0》约束。

## [1.1.0] — 2026-08-07

### Added — 调动决策树

- **DECISION-TREE.md**: 完整调动决策树(NODE 0—7),定义 AI 如何调动 25-Skill 计算系统。
- **CLI 输出 `decision_path`**: 报告携带 `mode` / `main_path` / `output_types` / `review_gates` / `upgrade_triggers` / `stop_conditions` / `deposition`,即可执行调用图。
- **审门按产出类型映射**(NODE 4): 科学结论→Red Team+Decision Gate;数据→先 QC;多来源→Synthesizer;可复现→Reproducibility;工程→Environment;低碳→LCA。与复杂度分数无关。
- **专项层升级触发**(NODE 5): 多技能→Router;长任务→State;长期记忆→KG;矿物表征→Mineral;现场→Scale-up;成本碳→LCA。执行中命中才拉。
- **循环与停止**(NODE 6): Red Team 阻断→修复→复验→两轮无进展→Decision Gate 降级;宪法 §66 停止条件。
- **状态落地**(NODE 7): 沉积→KG;归档→Reproducibility;失败→Failure Ledger。
- 修复: `micp-mineral-phase-interpreter` 专项升级原本因空正则永不触发,已修复。
- SKILL.md 增加"调动决策树"章节;prompts/system.md 增加决策路径要点。
- 输出 schema 增加 `decision_path` 字段。

## [1.0.0] — 2026-08-07

### Added

- 任务入口首检: 对任何实质性研究/工程请求做任务分类 + 复杂度评分 + 三级模型编组。
- 宪法至上声明: 冲突时以宪法解释为准,检出 `CONSTITUTIONAL_CONFLICT` 并排除冲突指令。
- 扩充轮数上限: `max_amplification_rounds` 硬上限 2(宪法第 65 条预算)。
- 不接受路径: 用户不接受强化提示词时回标准流程(仍完整遵守宪法)。
- 人类批准: 触发真实实验/现场/环境释放时返回 `HUMAN_APPROVAL_REQUIRED`,采纳不豁免。
- 三级模型常量: 12 泛化 / 6 审 / 6 专项,合计 24。
- 复杂度评分: 宪法附录 B 七维(学科/数据/风险/尺度/建模/决策/不确定性)+ MICP 领域升级词。
- 测试套件: 39 项 pytest,覆盖宪法、轮数、编组、批准、契约、校验、分类。

### Priority

- 优先级: **最高(第 25 号,任务入口首检)**。此优先级仅表示最先运行,不表示凌驾于宪法。
