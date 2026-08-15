# Changelog

## 1.0.0 — 2026-08-06

初始交付。

**新增**
- Skill 契约:`SKILL.md`(触发/边界/流程/错误码/版本策略)、`skill.yaml`(机器元数据)、`schemas/input.schema.json`、`schemas/output.schema.json`、`prompts/system.md`、`README.md`、`references/sources.md`。
- 工具套件 `tools/osr/`(纯 TypeScript,Bun):
  - Skill Registry 索引器(`registry.ts`):frontmatter + skill.yaml 解析、契约校验、确定性哈希快照。
  - 输入/输出 schema 匹配器(`schema-match.ts`)与 JSON Schema 2020-12 子集校验器(`jsonschema.ts`)。
  - 权限策略引擎(`policy.ts`,镜像 OpenCode `Permission.evaluate` 语义)。
  - 调用图与递归深度监控器(`callgraph.ts`,星型拓扑审计、循环/重复检测)。
  - 成本/token/时间/重试预算器(`budget.ts`,先估算后调度)。
  - 冲突输出仲裁器(`arbitrate.ts`,认识论等级 + 证据权重,从不静默平均)。
  - hash 链决策审计日志(`decision-log.ts`)。
  - 路由决策引擎(`planner.ts`,8 道门控)与输出组装(`service.ts`)。
  - CLI 适配器(`router-cli.ts` / `tools/bin/osr.ts`)。
- 测试 `tests/`(单元/集成/失败/回归)与评测 `evals/`(12 用例 + 7 项性能指标)。
- 示例 `examples/`(3 个)。

**已知限制(随版本演进)**
- `skill.yaml` 为项目自定义约定,OpenCode 原生加载器不读取;需要 Controller 层或注册表索引器消费。
- JSON Schema / YAML 解析为子集实现,不支持 `$dynamicRef`、远程 `$ref`、锚点、块标量。
- 领域关键词表(`planner.ts` DOMAIN_MAP)为内置静态映射,后续应迁移到知识库/配置。
