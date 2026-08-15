# obsidian-skill-router.zip — 用途说明（README）

**这是什么**：Obsidian Skill Router（OSR，黑曜石技能路由器）的完整 Skill 工程包，v1.0.0。
基于 **OpenCode 原生 Skill 标准**（`SKILL.md` + YAML frontmatter，放置于 `skills/` 或 `.opencode/skills/` 后由 OpenCode 加载器发现），用于 Obsidian Plan（黑曜石计划）/ Panshi（磐石）MICP 研究项目。

**它干什么用**：为 Obsidian Controller 做 **Skill 路由、权限与调用治理**——根据任务节点、上下文、证据状态和风险等级选择最合适的专业 Skill，控制调用顺序、深度、预算和权限，防止递归失控与职责越界。Router 本身**不产生领域结论**（不计算反应速率、不解释矿相、不评估岩土性能），只产出路由计划与决策审计记录。

## 安装

```bash
# 方式一：放入项目 skills 目录（本 zip 解压后即含 SKILL.md 与完整工程包）
unzip obsidian-skill-router.zip -d <你的项目>/skills/

# 方式二：通过 opencode.json 的 skills.paths 注册任意位置
# { "skills": { "paths": ["./skills"] } }
```

OpenCode 会扫描 `**/SKILL.md`，frontmatter 的 `name`/`description` 用于 `<available_skills>` 列表；`skill.yaml` 是给本 Router 的注册表索引器用的机器元数据（能力、输入输出契约、单位、工具权限）。

## 快速开始

```bash
# 1) 运行完整测试（85 个用例：单元/集成/失败/回归/评测）
bun test

# 2) 索引技能注册表（需要其余专业技能就位后执行）
bun tools/bin/osr.ts registry --roots ../../skills ../../.opencode/skills

# 3) 路由一个请求（stdin 输入 JSON，stdout 输出机器可读信封）
cat examples/route-micp-biocementation.json | bun tools/bin/osr.ts route

# 4) 校验决策日志 hash 链
bun tools/bin/osr.ts verify logs/decisions/<project>.jsonl
```

> 注意：`examples/route-*.json` 里的示例请求会路由到真实注册表；若仓库里尚无其他专业技能（ureolysis-chemistry、geotechnical-performance 等），Router 会正确返回 `NEED_ADDITIONAL_SKILL` + `capability_gap_spec`——这正是它的设计行为。

## 目录结构

```
obsidian-skill-router/
├── SKILL.md                  # 触发/边界/流程/错误码/版本策略（OpenCode 加载入口）
├── skill.yaml                # 机器元数据（能力、契约、单位、权限、停止条件）
├── schemas/
│   ├── input.schema.json     # 严格输入契约（JSON Schema 2020-12）
│   └── output.schema.json    # 严格输出契约
├── prompts/system.md         # 最小系统提示词（身份/流程/边界/认识论/停止）
├── tools/                    # 真实工具（纯 TS，无第三方依赖）
│   ├── bin/osr.ts            # CLI 入口（registry/route/verify/check-self）
│   └── osr/                  # 注册表索引器、schema 校验器、权限引擎、
│                             #   调用图监控器、预算器、冲突仲裁器、决策日志…
├── tests/                    # 单元/集成/失败/回归（85 用例全部通过）
├── evals/                    # 12 个评测用例 + 7 项性能指标（全达标）
├── examples/                 # 3 个可运行示例
├── references/sources.md     # 实现与领域依据（含来源、访问日期、限制）
└── CHANGELOG.md              # 版本记录
```

## 关键特性

- **契约路由，绝不因名字相似而路由**：按能力/输入/单位打分，单位冲突是硬否决。
- **星型拓扑**：专业 Skill 不得互调，跨 Skill 请求一律回到 Router；`auditEdges` 可审计违规直连边。
- **风险强制审计**：`risk_level ∈ {high, critical}` 强制 `obsidian-red-team → obsidian-decision-gate` 审计链 + 人工批准门。
- **8 道门控**：能力匹配 → 权限 → 风险 → 冲突 → 调用图（深度/循环/重复）→ 预算 → 批准 → 组计划。
- **17 个错误码**（OSR-E001..E017），人类可读 + 机器可解析。
- **hash 链决策日志**：每条路由决策可追溯、可验证防篡改。
- **离线可用**：无网络依赖，全部测试离线运行。

## 依赖

- **运行时**：Bun（测试与 CLI 用 `bun test` / `bun tools/bin/osr.ts` 运行）。
- **依赖包**：零第三方运行时依赖；仅 devDependency `@types/bun`（类型检查用）。

## 版本

- 当前：**1.0.0**（2026-08-06，初始交付）
- 兼容性：`skill_version = 1.x.y`；`controller_version >= 1.0.0`
- 变更见 `CHANGELOG.md`；契约破坏性变更将提升主版本。

## 限制

- `skill.yaml` 是本项目约定，OpenCode 原生加载器不读取；需本 Router 的索引器或 Controller 层消费。
- YAML / JSON Schema 为自研子集实现（不支持锚点、`$dynamicRef` 等），详见 `README.md`。
- Router 不做领域推理；领域关键词表（`tools/osr/planner.ts` DOMAIN_MAP）后续可迁移到知识库。
