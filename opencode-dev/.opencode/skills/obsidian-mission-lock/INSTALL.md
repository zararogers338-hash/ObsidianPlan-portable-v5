# Obsidian Mission Lock — 技能安装包

**中文名称**:Obsidian Mission Lock｜研究任务定界与使命锁定
**版本**:1.0.0(contract schema v1.0.0)
**角色**:Obsidian Plan(Panshi 磐石研究核心)下的**受治理能力**——把模糊自然语言研究诉求压缩为可执行、可验证、可终止、可审计的**任务合同**,并阻止范围漂移、目标偷换与模糊成功标准。

## 这个包是干什么用的

- **输入**:一段自然语言研究/工程诉求(尤其中文 MICP/生物矿化/矿物智能方向)+ 控制器信封。
- **输出**:机器可读的**任务合同**(主/次目标、指标与阈值、成功/失败/停止条件、排除项、审批门、带认识论标签的陈述)+ 冲突矩阵 + 缺失缺口清单,状态机:SUCCESS / PARTIAL / BLOCKED / FAILED / NEED_ADDITIONAL_SKILL / HUMAN_APPROVAL_REQUIRED。
- **行为**:不给配方、不静默消解冲突、不编造数据、缺失即 UNKNOWN+BLOCKED。

## 快速安装(标准 Skill 格式)

OpenCode 原生 skill 格式:`SKILL.md`(YAML frontmatter:`name` + `description`)+ 同目录附属文件。放到任一发现路径即可被 `skill` 工具加载:

```bash
# 项目级(任意项目下)
cp -r obsidian-mission-lock 你的项目/.opencode/skills/
# 或全局
cp -r obsidian-mission-lock ~/.claude/skills/
```

要求:`bun >= 1.3`(工具脚本入口 `tools/src/cli.ts`)。**离线、确定性、无第三方依赖,无需 `bun install`。**

## 自检(必跑)

```bash
cd obsidian-mission-lock
bun test tools/tests/unit.test.ts      # 32 项单元/回归测试
bun run tools/tests/evals-runner.ts    # 10 用例 + 8 项性能指标(阈值:结构化输出≥95%、工具真实调用100%、可追踪100%、对抗拦截≥90%)
bun run tools/tests/bootstrap.ts       # 26 项自举测试(以 Skill 身份执行 4 个场景)
```

## 目录说明

```
obsidian-mission-lock/
├── SKILL.md               # 主 Skill:触发/反触发/边界、错误码、性能指标、版本策略、流程
├── manifest.json          # 机器可读元数据(版本/依赖/入口/权限/工具)
├── README.md              # 维护者手册(安装/调用/故障排查)
├── CHANGELOG.md           # 变更记录
├── prompts/system.md      # 最小系统提示词(不复制 Panshi 宪法)
├── schemas/               # 输入/输出信封 JSON Schema(控制器契约)
├── tools/src/             # 确定性工具库(校验/单位/冲突/缺失/diff/错误码,无依赖)
├── tools/tests/           # 单元测试 + evals runner + 自举测试
├── evals/cases.yaml       # 10 个评测用例(正常/缺失/冲突/对抗/边界)
├── examples/              # 5 个可运行示例(含漂移对比对)
├── references/sources.md  # 来源与依据(S1–S5 仓库机制 / S6–S8 方法学 / S9–S13 MICP 领域)
└── audit/                 # 自举与验收日志
```

## 调用契约(Obsidian Controller 管道)

```bash
echo '<input.json>' | bun run tools/src/cli.ts lock   # 全流程
bun run tools/src/cli.ts validate --input contract.json
bun run tools/src/cli.ts diff --before v1.json --after v2.json  # 目标偷换检测
```
退出码:0=SUCCESS/PARTIAL, 2=BLOCKED/审批待办/漂移临界, 3=FAILED。详见 `README.md`。

## 版权与依据

MIT。领域依据见 `references/sources.md`(OpenCode 机制、ISO/IEC/IEEE 29148 术语、MICP 综述文献 DOI)。本包不含任何密钥。
