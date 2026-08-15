# CHANGELOG

所有时间使用本地日期;版本遵循 [SKILL.md#version-policy](SKILL.md#version-policy)。

## [1.0.0] — 2026-08-06

初始交付。

### 新增

- `SKILL.md`:触发/反触发/边界案例(6 正 / 4 反 / 4 边界)、错误码表(19 码,MUC-E1xxx/E2xxx/E3xxx/E4xxx)、性能指标表、版本策略、工具权限、流程。
- `manifest.json` + `skill.yaml`:机器可读元数据(v1.0.0, contract v1.0.0, OpenCode >= 1.18, Python >= 3.10),双格式镜像项目内两种既有约定。
- `schemas/input.schema.json`:控制器输入信封契约(5 必填 + 12 可选 + 直派 tool/params)。
- `schemas/output.schema.json`:输出信封契约(6 状态 + calculation/findings/assumptions/evidence/uncertainty/risks/artifacts/requested_next_skills/validation/provenance/errors)。
- `prompts/system.md`:最小系统提示词(身份/流程/边界/认识论/停止规则,不复制宪法)。
- `tools/muc/`(标准库,离线确定性,可选 numpy/scipy):
  - `errors.py` — 19 个错误码,机器可读 + 人读双语,retryable 语义。
  - `units.py` — 维度引擎(SI 基量纲)、单位注册表、摩尔/质量浓度区分、非有限/越界检查。
  - `constants.py` — 平衡常数(pKa1/pKa2/log Ksp calcite/aragonite/vaterite/ACC/pKa NH4/pKw/log KH CO2)带 van't Hoff 温度修正,全部带 S# 来源。
  - `activity.py` — Davies 活度系数模型(A=0.509,I≲0.5 M)。
  - `speciate.py` — 闭式碳酸盐平衡、固定 pH 或碱度求 pH、SI(活度修正)。
  - `kinetics.py` — 脲酶 Michaelis-Menten/Haldane、一阶、Vmax(脲酶单位)、Arrhenius、pH 因子。
  - `balance.py` — 元素(N/C/Ca)与电荷守恒检查、尿素水解化学计量。
  - `simulate.py` — 耦合批处理 ODE(RK4):尿素水解 + 碳酸盐 + 沉淀;区分 `kinetic_precipitated` 与 `equilibrium_bound_precipitable`。
  - `sens.py` — OAT 敏感性 + RSS 不确定度传播。
  - `phreeqc.py` — PHREEQC deck 生成 / 执行 / 结果解析;离线降级。
- `tools/cli.py`:stdin→stdout 入口,子命令 `balance|speciate|simulate|fit|sens|units|phreeqc-in|phreeqc-run|validate|version`,支持信封内 `tool`+`params` 直派,退出码 0/2/3。
- `tests/test_engine.py`:52 项单元/集成/失败/回归测试。
- `tests/run_evals.py` + `evals/cases.yaml`:12 项评测用例(正常/缺失/冲突/对抗/边界),实现 7 项性能指标测量与阈值。
- `tests/bootstrap.py`:4 个自举场景(以 Skill 身份执行真实工具,输出经输出信封契约校验)。
- `examples/`:3 个可运行示例。
- `references/sources.md`:35 条来源记录(S1–S5 仓库机制, S20–S24 水化学, S25–S35 MICP 领域),含常量-来源映射表。
- `audit/bootstrap.json`:自举测试日志。

### 已验证

- 52 项单元测试通过;12 项评测用例 21/21 加权通过,7 项指标全部达阈值(结构化输出 1.0、工具调用 1.0、对抗拦截 1.0、可复现 1.0 等)。
- 4 项自举场景全部通过,其中反向守恒核对(尿素 N → NH4,Ca → Ca+固体)残差为 0。
- 示例:钙平衡、pH 9.0 胶结液 SI、0.5 M 尿素批处理模拟均真实运行。

### 已知限制(登记,不作假关闭)

- 沉淀速率常数与比表面积是模型参数,必须按体系标定(`CALIBRATION_REQUIRED`);默认值仅作演示。
- 批处理闭式模型;现场输运需接入输运能力(参考文献 S31),本 Skill 不冒充。
- PHREEQC 为可选外部工具;未安装时 `phreeqc-run` 降级返回 deck 与 MUC-E3001。
- 高离子强度(I>0.5 M)Davies 模型越界,输出标 PARTIAL 并注明不确定性。
- **[AUTH]** 教科书来源(如 S21/S22/S23)DOI 未逐条在线复核;数值以 S20/S24 等实测为准。
