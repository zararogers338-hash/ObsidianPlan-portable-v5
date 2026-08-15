# CHANGELOG

所有时间使用本地日期;版本遵循 [SKILL.md#version-policy](SKILL.md#version-policy)。

## [1.0.0] — 2026-08-06

初始交付。

### 新增

- `SKILL.md`:触发/反触发/边界案例(6 正 / 4 反 / 4 边界)、错误码表、性能指标、版本策略、工具权限、流程。
- `manifest.json`:机器可读元数据(v1.0.0, contract v1.0.0, OpenCode >= 1.18, bun >= 1.3)。
- `schemas/input.schema.json`:控制器输入信封契约(5 必填 + 12 可选字段)。
- `schemas/output.schema.json`:输出信封契约(6 状态 + 合同/冲突矩阵/缺口/校验/溯源/错误)。
- `prompts/system.md`:最小系统提示词(身份/流程/边界/认识论/停止规则,不复制宪法)。
- `tools/src/`(无第三方依赖,离线确定性):
  - `cli.ts` — stdin→stdout 入口,子命令 `lock|validate|diff|units`,退出码 0/2/3。
  - `validate.ts` — 输入信封校验 + 合同 schema 校验 + 版本兼容策略(含 `requiredBump`)。
  - `units.ts` — 单位注册表、量纲一致性、目标/阈值方向反转、时间范围、有限值/空值检查。
  - `conflicts.ts` — 指标对 / 约束对 / MICP 领域盲点三层冲突检测(铵质量守恒、尿素路径与非尿素路径禁混用)。
  - `missing.ts` — 缺失字段检测(通用 + MICP 专项 + 高风险审批门)。
  - `diff.ts` — 合同版本差异比较与目标偷换检测(主目标切换/成功标准弱化/排除项与审批门移除 → critical 告警)。
  - `errors.ts` — 10 个错误码 OML-E1001~E1010,机器可读 + 人读双语。
- `tests/unit.test.ts`:库层单元/失败/回归测试。
- `tests/evals-runner.ts` + `evals/cases.yaml`:≥8 评测用例,覆盖正常/缺失/冲突/对抗/边界;实现性能指标测量。
- `tests/bootstrap.ts`:4 个自举场景(以 Skill 身份执行,验证工具真实调用与输出契约)。
- `examples/`:5 个可运行示例(含漂移对比对)。
- `references/sources.md`:13 条来源记录(S1–S5 仓库机制, S6–S8 方法学, S9–S13 MICP 领域)。
- `audit/`:自举与验收日志。

### 已验证

- `bun run tools/src/cli.ts lock` 在「提高MICP效果」「冲突需求」两个手工样例上真实运行,输出经 `output.schema.json` 校验。
- 漂移检测:主目标切换 + 成功标准删除 + 排除项/审批门移除全部触发 critical 告警。

### 已知限制(登记,不作假关闭)

- LLM 语义层(目标分解/标签分类)无法被单元测试覆盖,由自举测试以 Skill 身份验证。
- OpenCode `skill` 工具对附属文件只列出前 10 个(源码 S2);若 `references/` 文件增多需注意。
- 中文路径/Windows 下 `bun run` 的 shebang 场景未经 CI 验证(本地已验证可用)。
