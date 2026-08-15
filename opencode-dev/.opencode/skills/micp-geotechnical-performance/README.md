# micp-geotechnical-performance (MGE)

评价 MICP（微生物诱导碳酸钙沉淀）生物胶结土体的**工程性能**：强度、刚度、渗透率、变形、抗液化、抗侵蚀与耐久性，并把微观沉淀与宏观性能联系起来，同时给出工程意义判定。

- **版本**：1.0.0（Skill 版本；契约版本见 `schemas/`）
- **层**：Panshi 宪法下的受治理专业能力
- **运行时**：Bun ≥ 1.3（工具层为纯 TypeScript，无外部运行时依赖，离线可测）
- **入口**：`tools/src/cli.ts`

---

## 安装与发现

本 Skill 放在 Obsidian 仓库的 `skills/micp-geotechnical-performance/`。OpenCode 的 Skill 加载器（`packages/opencode/src/skill/index.ts`）扫描 `{skill,skills}/**/SKILL.md`，以 frontmatter 的 `name` + `description` 注册；OSR 注册表索引器（`skills/obsidian-skill-router/tools/osr/registry.ts`）额外解析 `skill.yaml`。

两个加载器都能干净识别本 Skill：

```bash
# 从本目录运行全部测试（含自举评测）
bun test

# 类型检查
bun run typecheck

# 全量检查（typecheck + test）
bun run check
```

---

## 调用示例

### 1. 命令行工具（机器可读）

```bash
# 完整评测管线：schema 校验 → parse → metrics → stats → durability → effect → 自检
bun tools/src/cli.ts evaluate --input examples/01-ucs-strength-comparison.json

# 单个子命令
bun tools/src/cli.ts metrics   --input samples.json   # 应力-应变指标
bun tools/src/cli.ts stats     --input samples.json   # 样本统计 + 空间均匀性
bun tools/src/cli.ts durability --input samples.json  # 耐久循环衰减拟合
bun tools/src/cli.ts effect    --input effect.json    # 效应量 + 安全裕度
bun tools/src/cli.ts check-self output.json           # 校验输出契约
```

退出码：`0` SUCCESS / `2` BLOCKED 或 HUMAN_APPROVAL_REQUIRED / `3` FAILED / `4` 内部自检失败。

### 2. 作为 Controller / Router 的能力

以 `schemas/input.schema.json` 的 envelope 调用（`evaluate` 子命令），返回 `schemas/output.schema.json` 的 envelope。必需字段：`task_id, project_id, request, skill_version, controller_version, timestamp`。请求强度/渗透/耐久评价时需提供 `samples`；缺失 → `BLOCKED` + `MGE-E202`。

---

## 目录结构

```
skills/micp-geotechnical-performance/
├── SKILL.md                 # 角色、触发条件、边界、流程、错误码、版本策略
├── skill.yaml               # OSR 注册表机器元数据
├── package.json / tsconfig.json / bun.lock
├── schemas/
│   ├── input.schema.json    # 严格输入契约（envelope + samples + refs）
│   └── output.schema.json   # 严格输出契约（envelope + 认识论标签）
├── prompts/system.md        # 最小系统提示词（身份、纪律、流程）
├── references/sources.md    # 领域与实现依据（S1–S18，含访问日期与限制）
├── evals/
│   ├── cases.yaml           # 12 个评测用例（正常/缺失/冲突/对抗/边界）
│   └── metrics.md           # 7 项性能指标的测量方法与阈值
├── tests/
│   ├── unit/                # 27 个单元测试（五工具 + 错误码）
│   ├── integration/         # 9 个集成测试（真实 CLI 调用）
│   ├── failure/             # 11 个对抗测试（数值/统计/证据诚实性）
│   ├── regression/          # 9 个回归测试（跨 Skill 契约稳定性）
│   ├── eval/                # 13 个评测测试（含 7 指标）
│   └── bootstrap/           # 4 个自举测试（BT-1..BT-4 固化为验收门）
├── examples/                # 3 个可运行示例
├── tools/src/
│   ├── cli.ts               # 唯一触碰 stdin/stdout 的入口
│   ├── parse.ts             # 岩土试验数据解析器（单位/空值/范围校验）
│   ├── metrics.ts           # 应力-应变指标提取（UCS/E0/E50/BI/条件检查）
│   ├── stats.ts             # 样本统计 + 空间均匀性（MAD 离群点）
│   ├── durability.ts        # 耐久循环衰减拟合（线性/指数/对数）
│   ├── effect.ts            # 效应量 + 安全裕度（Welch t + 精确 p 值）
│   ├── units.ts             # 单位校验与换算（SI 优先）
│   ├── errors.ts            # 错误码体系（MGE-E101..E803）
│   ├── jsonschema.ts        # 零依赖 JSON Schema 2020-12 子集校验器
│   └── yaml.ts              # 零依赖 YAML 子集解析器（与 OSR 同源）
└── CHANGELOG.md
```

---

## 专业能力

1. **指标区分**：UCS、直剪、三轴、弯拉/劈拉、剪切波刚度、能量指标——按 `test_type` 分派与判据。
2. **四项全报**：平均性能 + 离散性（n、CV、CI）+ 空间均匀性 + 脆性风险（BI/峰值应变）。**单个 UCS 不得代表全部性能。**
3. **微观-宏观关联**：CaCO3 含量与强度关联必须带证据等级（L1 直接观测 … L4 无证据），保留晶体位置（填充 vs 桥接）不确定性。
4. **耐久性**：干湿/冻融/盐/酸/冲刷/循环荷载分别给残余强度比、每周期衰减率、破坏机制；<3 个衰减点只报趋势不外推。
5. **统计 vs 工程显著**：Welch t 检验（精确 p 值）+ Cohen's d + 安全裕度，与 `engineering_thresholds` 对比给三态判定。
6. **审查模式**：审查夸大报告（如"强度提升 50 倍"）时，n=1 不产出统计结论，`cohens_d` 不可算即省略，绝不伪造。

## 触发条件（摘要，完整见 SKILL.md）

- **触发**：UCS/直剪/三轴/拉伸/剪切波试验数据解读；强度-渗透-变形-耐久评价；空间均匀性/脆性风险；报告审查。
- **不触发**：纯化学/生物/矿相/输运过程建模；实验设计与执行；文献综述；无 MICP 语境的一般土力学。
- **边界**：缺 `samples` → BLOCKED + MGE-E202；高风险现场/危险化学品 → HUMAN_APPROVAL_REQUIRED + MGE-E701；尺寸不可比 → 条件警告。

## 错误码

见 `tools/src/errors.ts` 与 SKILL.md §六。`{code, message, retryable, details}` 机器可解析，`message` 人类可读。

## 版本策略

- 破坏性契约变更 → 主版本 +1；新增可选字段 → 次版本 +1；实现修复 → 修订版本 +1。
- 旧版本输出：主版本不匹配且无迁移器 → 明确拒绝 `MGE-E803`。

## 已知限制

- 数值工具零外部依赖（自研统计/单位/schema/yaml），覆盖常用用例；非常规单位（如 `cm²/s` 渗透率）会触发 `MGE-E203`。
- `spatial_uniformity` 仅在提供 `layer_data` 时计算；不可算时输出说明而非编造。
- 三轴有效应力参数（c', φ'）需多级试验数据，本版本支持单级曲线指标；多级包络需扩展。
- 本 Skill 不做生物/化学/矿相/输运建模；需要时返回 `NEED_ADDITIONAL_SKILL`。

## 故障排除

| 现象 | 处理 |
|---|---|
| `bun test` 找不到模块 | 从本 skill 目录运行（仓库规则：测试从包目录执行） |
| `evaluate` 返回 exit 3 + MGE-E101 | 输入缺必填字段；看 `errors[0].details.field_guidance` |
| `evaluate` 返回 exit 2 + MGE-E202 | 请求强度/渗透/耐久评价但无 `samples` |
| 输出未过 `check-self` | 契约损坏；报告到仓库 issue |
| 评测 M1 未达 0.95 | `bun test tests/eval` 看 `EVAL METRICS:` 行 |
