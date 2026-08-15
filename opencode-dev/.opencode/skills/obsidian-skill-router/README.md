# obsidian-skill-router

**中文名**：Obsidian Skill Router（OSR）｜Skill 路由、权限与调用治理

Obsidian Plan（黑曜石计划）的受治理调度中枢：根据任务节点、上下文、证据状态和风险等级选择最合适的 Skill，控制调用顺序、深度、预算和权限，防止递归失控与职责越界。**Router 不产生领域结论**——它只选技能、排顺序、定预算、守边界。

| 项 | 值 |
|---|---|
| Skill 名称 | `obsidian-skill-router` |
| 版本 | `1.0.0` |
| 契约 | `schemas/input.schema.json` / `schemas/output.schema.json` |
| 入口 | `tools/bin/osr.ts` |
| 语言 | TypeScript（Bun runtime） |
| 依赖 | 无（纯标准库 + 仓库内自研子集解析器） |

---

## 安装与注册

本 Skill 自包含于仓库 `skills/obsidian-skill-router/`。OpenCode 通过 `skills.paths` 或项目 `skills/` 目录发现 `**/SKILL.md`：

```jsonc
// opencode.json
{
  "skills": { "paths": ["./skills"] }
}
```

验证发现：

```bash
bun tools/bin/osr.ts registry --roots ../../skills ../../.opencode/skills
```

预期输出一个含本条目（`name: obsidian-skill-router`）的注册表快照。若本条目 `usable:false`，检查 `SKILL.md` frontmatter 与 `skill.yaml`（详见"故障排除"）。

## 调用

CLI 读取 stdin 上的单个 JSON 对象（须符合输入契约），向 stdout 输出输出契约信封，并返回稳定退出码：

```bash
# 用示例路由一个请求
cat examples/route-micp-biocementation.json | bun tools/bin/osr.ts route

# 或从文件读取
bun tools/bin/osr.ts route --input examples/route-micp-biocementation.json
```

| 退出码 | 含义 |
|---|---|
| 0 | SUCCESS / NEED_ADDITIONAL_SKILL / HUMAN_APPROVAL_REQUIRED |
| 2 | FAILED / BLOCKED |
| 3 | 保留 |
| 4 | 内部错误 / 输出自检失败 |

以模型/控制器方式调用时：把输入 JSON 传给 `tools/bin/osr.ts route`，取 stdout 的信封，用 `status` 字段驱动后续动作。

## 子命令

| 子命令 | 用途 |
|---|---|
| `registry [--roots d]... [--write f]` | 扫描技能根目录，产出确定性的注册表快照 |
| `route [--input f]` | 完整路由流水线（校验→规划→自检→决策日志） |
| `verify <decisions.jsonl>` | 校验决策日志的 hash 链（防篡改/截断） |
| `check-self <json>` | 用输出契约校验任意 JSON |

## 工具架构（`tools/osr/`）

| 模块 | 职责 |
|---|---|
| `errors.ts` | 错误码体系 OSR-E001..017（唯一事实源） |
| `types.ts` | 领域类型（镜像 schema） |
| `yaml.ts` | 最小 YAML 子集解析/生成（frontmatter、skill.yaml） |
| `jsonschema.ts` | JSON Schema 2020-12 子集校验器（本库自研，离线可用） |
| `registry.ts` | Skill Registry 索引器：frontmatter+manifest 解析、契约校验、确定性哈希快照 |
| `schema-match.ts` | 输入/输出契约匹配、能力/单位/关键词打分 |
| `policy.ts` | 权限策略引擎（镜像 OpenCode `Permission.evaluate` 语义：末匹配优先） |
| `callgraph.ts` | 调用图与递归深度监控器（星型拓扑审计、循环/重复检测） |
| `budget.ts` | token/成本/时间/重试预算器（先估算后调度） |
| `arbitrate.ts` | 冲突输出仲裁器（认识论等级 + 证据权重；从不静默平均） |
| `decision-log.ts` | hash 链 JSONL 决策审计日志 |
| `planner.ts` | 路由决策引擎（8 道门控 + 计划组装） |
| `service.ts` | 组装输出信封、自检、写日志/工件 |
| `router-cli.ts` | 唯一触碰 stdin/stdout 的适配器 |

## 示例

- [route-micp-biocementation.json](examples/route-micp-biocementation.json) — 化学+渗流+岩土跨领域任务
- [route-high-risk-field.json](examples/route-high-risk-field.json) — 高风险任务强制红队+决策门
- [route-recurse-chain.json](examples/route-recurse-chain.json) — 递归链截断

```bash
bun tools/bin/osr.ts route --input examples/route-recurse-chain.json | bun tools/bin/osr.ts check-self /dev/stdin 2>/dev/null
```

## 测试

```bash
bun test                    # 全部（单元/集成/失败/回归）
bun run typecheck           # tsc 严格类型检查
bun tools/bin/osr.ts check-self <任意输出.json>  # 输出契约校验
```

仓库级约定：本 Skill 自包含，不依赖 `packages/opencode` 的 Effect 测试基建；在 `skills/obsidian-skill-router/` 目录下运行 `bun test`（与仓库"从包目录运行测试"的规则一致）。

## 故障排除

| 现象 | 原因 | 处理 |
|---|---|---|
| `registry` 把本条目标记 `usable:false` | `SKILL.md` frontmatter 缺 `description`，或 `skill.yaml` 契约失败 | 修 frontmatter；`bun tools/bin/osr.ts registry` 复查 |
| `route` 返回 OSR-E006 | 请求能力无注册技能覆盖 | 读取 `capability_gap_spec`，构建/注册新技能 |
| `route` 返回 OSR-E005 | 权限策略拒绝 | 检查 `forbidden_skills` 与 `policy.ts` 默认策略 |
| `route` 返回 OSR-E010/OSR-E011 | 预算/深度超限 | 调大 `constraints` 对应项，或拆分任务 |
| `route` 返回 OSR-E007 | 需人工批准 | 置 `human_approval_state: "approved"`（人工批准后） |
| 决策日志被篡改 | `verify` 报 `hash mismatch` | 定位记录 seq，追查写入方 |

## 限制与边界

- **离线第一**：无网络依赖；不联网完成全部测试。
- **契约优先**：路由依据能力/单位/输入覆盖，绝不按名字相似路由。
- **YAML 子集**：不解析锚点、块标量、流映射；遇到不支持的构造抛 `YAMLParseError`（宁可失败，不可误读）。
- **JSON Schema 子集**：不支持 `$dynamicRef`/远程 `$ref`/`format` 强校验（format 仅注释）。
- **Router 不做领域推理**：不计算反应速率、不解释矿相、不评估岩土性能。
- **版本兼容**：`skill_version` 非 `1.x.y` 或 `controller_version < 1.0.0` 时明确拒绝（OSR-E016）。

## 与 OpenCode 权限模型的关系

本 Skill 的策略引擎镜像 OpenCode `packages/opencode/src/permission/index.ts` 的语义（通配符匹配、**末匹配优先**、缺省 `ask`），确保 Router 产出的计划与运行时实际执行的权限判定一致；Router 自身策略是**更严格的一层**，只能把 `allow` 降为 `ask`，从不升级。


---

> 原 `ZIP-README.md` 已归档至 [`audit/ZIP-README.md`](audit/ZIP-README.md)。
