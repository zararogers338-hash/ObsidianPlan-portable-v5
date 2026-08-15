# obsidian-mission-lock

**Obsidian Mission Lock | 研究任务定界与使命锁定**

把模糊的自然语言研究诉求压缩为可执行、可验证、可终止、可审计的**任务合同**,并阻止范围漂移、目标偷换与成功标准模糊。`obsidian-mission-lock` 是 Panshi 研究核心下的受治理能力。

## 安装

复制本目录到任意 OpenCode skill 发现路径(见 [references/sources.md](references/sources.md) S1–S4):

```bash
# 项目级(向上冒泡到 git worktree)
cp -r .opencode/skills/obsidian-mission-lock <你的项目>/.opencode/skills/
# 或全局
cp -r .opencode/skills/obsidian-mission-lock ~/.claude/skills/
```

- 运行时要求:`bun >= 1.3`(工具脚本入口 `tools/src/cli.ts`)。
- 不依赖网络;所有工具离线、确定性运行。
- 无需 `bun install` —— 工具库只依赖标准库 + Bun 内置 API。

## 调用

### 由 agent 装载(SKILL.md 机制)

OpenCode agent 在系统提示的 `<available_skills>` 中看到本 Skill,按需调用 `skill({ name: "obsidian-mission-lock" })`。SKILL.md 正文注入对话,`tools/`、`schemas/`、`references/` 以绝对路径给出。

### 由 Obsidian Controller 管道调用(CLI)

信封(`schemas/input.schema.json`)经 stdin 或 `--input` 传入,输出信封(`schemas/output.schema.json`)写 stdout:

```bash
bun run tools/src/cli.ts lock --input input.json      # 全流程
bun run tools/src/cli.ts validate --input contract.json  # 只校验合同
bun run tools/src/cli.ts diff --before v1.json --after v2.json  # 漂移检测
bun run tools/src/cli.ts units --input contract.json  # 只做单位/尺度检查
```

退出码:`0`=SUCCESS/PARTIAL,`2`=BLOCKED/HUMAN_APPROVAL_REQUIRED/漂移临界,`3`=FAILED。

### 一个最小调用

```bash
echo '{"task_id":"t-1","project_id":"p-1","request":"提高MICP效果","skill_version":"1.0.0","timestamp":"2026-08-06T10:00:00Z"}' \
  | bun run tools/src/cli.ts lock
```

预期:`status: BLOCKED`,`missing_inputs` 列出 9 个阻断缺口(如 `contract.metrics[].target`、`micp.pathway`、`micp.matrix`、`micp.performance_metric`)——Skill 不会直接给"效果提升方案"。

## 示例

- [examples/vague-micp-request.json](examples/vague-micp-request.json) — 模糊诉求 → BLOCKED + 缺口清单
- [examples/conflicting-requirements.json](examples/conflicting-requirements.json) — 冲突诉求 → BLOCKED + 冲突矩阵
- [examples/locked-mission.json](examples/locked-mission.json) — 完整合同 → SUCCESS,供下游消费
- [examples/drift-before.json](examples/drift-before.json) / [examples/drift-after.json](examples/drift-after.json) — 漂移对比

## 测试与评测

```bash
bun test tools/tests/unit.test.ts        # 单元/失败/回归(库层)
bun run tools/tests/evals-runner.ts      # evals 评测(8+ 用例,含指标阈值)
bun run tools/tests/bootstrap.ts         # 自举场景测试(以 Skill 身份)
```

测试全部离线;不写网络。评测指标与阈值定义见 [SKILL.md](SKILL.md#performance-indicators) 与 [evals/cases.yaml](evals/cases.yaml)。

## 契约摘要

- **输入**(必填):`task_id`、`project_id`、`request`、`skill_version`、`timestamp`;可选:`context`、`constraints`、`evidence_refs`、`data_refs`、`upstream_outputs`、`risk_level`、`human_approval_state` 等。
- **输出** `status ∈ {SUCCESS, PARTIAL, BLOCKED, FAILED, NEED_ADDITIONAL_SKILL, HUMAN_APPROVAL_REQUIRED}`,携带 `contract`、`conflict_matrix`、`missing_inputs`、`validation`、`provenance`、`errors`。
- **认识论标签**:OBSERVED / REPORTED / CALCULATED / INFERRED / HYPOTHESIS / RECOMMENDATION;OBSERVED 与 REPORTED 必须带 `source`。
- **版本策略**:合同 schema 破坏性变更 → 主版本提升,无迁移即拒绝(OML-E1010);新增可选字段 → 次版本;实现修复 → 修订版本。见 [SKILL.md](SKILL.md#version-policy)。

## 故障排查

| 症状 | 原因 | 处理 |
|---|---|---|
| `exit 3` + `OML-E1009` | 输入非 JSON 或为空 | 检查信封与 stdin/`--input` |
| `exit 3` + `OML-E1010` | caller 声明的 `skill_version` 与本地构建不兼容且无迁移 | 用 manifest 中的版本更新信封 `skill_version`,或注册迁移 |
| `exit 2` + `status: BLOCKED` | 硬冲突或阻断缺口 | 读 `conflict_matrix` / `missing_inputs`,补材料或人工决策 |
| `exit 2` + `HUMAN_APPROVAL_REQUIRED` | `risk_level ≥ high` 但未批准 | 人工审批后把 `human_approval_state` 置 `approved` |
| 工具脚本报错 | bun 版本过旧 | 升到 `bun >= 1.3` |

## 限制

- 语义分解(目标/依赖/标签分类)由装载 SKILL.md 的 LLM 层完成;CLI 只做确定性校验。两者必须组合使用,不能只用 CLI 生成合同。
- `references/sources.md` 中的数值区间(如强度提升 30–65%)是软性合理性参考,不是硬约束。
- 网络来源均为 2026-08-06 检索结果;领域结论以原始文献为准。

## 维护者

- 实现:TypeScript + Bun,无第三方依赖(便于离线/审计)。
- 目录约定:修改合同 schema 前先读 [SKILL.md](SKILL.md#version-policy) 与 `CHANGELOG.md`。
- 变更任何工具行为后必须重跑 `tools/tests/unit.test.ts` 与 `tools/tests/evals-runner.ts`。
- 本目录不包含任何密钥;凭据只经环境变量或 controller 传入。
