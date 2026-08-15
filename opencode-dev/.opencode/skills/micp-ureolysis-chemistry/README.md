# micp-ureolysis-chemistry

**MICP Ureolysis Chemistry | 尿素水解、碳酸盐平衡与反应动力学**

让尿素-脲解 MICP 化学可计算、可守恒、单位一致、可复现:尿素水解动力学、碳酸盐平衡、钙消耗、过饱和、成核倾向与铵副产物。`micp-ureolysis-chemistry` 是 Panshi 研究核心下的受治理能力,不取代 Obsidian Controller。

## 安装

复制本目录到任意 OpenCode skill 发现路径(见 [references/sources.md](references/sources.md) S1–S5):

```bash
# 项目级
cp -r .opencode/skills/micp-ureolysis-chemistry <你的项目>/.opencode/skills/
# 或全局
cp -r .opencode/skills/micp-ureolysis-chemistry ~/.claude/skills/
```

- 运行时要求:`python >= 3.10`。推荐 `numpy` / `scipy`(检测到即用于数值求解;缺失时标准库路径仍可运行)。
- 不依赖网络;所有工具离线、确定性运行。
- PHREEQC 为可选外部工具(用于交叉验证);未安装时 `phreeqc-run` 返回结构化 MUC-E3001 并附带生成的 deck,`phreeqc-in` 完全离线可用。

## 调用

### 由 agent 装载(SKILL.md 机制)

OpenCode agent 在系统提示的 `<available_skills>` 中看到本 Skill,按需调用 `skill({ name: "micp-ureolysis-chemistry" })`。SKILL.md 正文注入对话,`tools/`、`schemas/`、`references/` 以绝对路径给出。

### 由 Obsidian Controller 管道调用(CLI)

信封(`schemas/input.schema.json`)经 stdin 或 `--input` 传入。带 `tool` + `params` 时机器直派:

```bash
python tools/cli.py --input envelope.json            # 信封内 tool+params 派发
python tools/cli.py balance  < envelope.json          # 显式子命令
python tools/cli.py speciate < envelope.json
python tools/cli.py simulate < envelope.json
python tools/cli.py fit      < envelope.json
python tools/cli.py sens     < envelope.json
python tools/cli.py units    < envelope.json
python tools/cli.py phreeqc-in  < envelope.json
python tools/cli.py phreeqc-run < envelope.json
python tools/cli.py version
```

退出码:`0`=成功,`2`=阻断(审批门),`3`=失败(不可处理/内部错误)。输出为严格 JSON 信封 `{ok, tool, version, result|error}`。

### 一个最小调用

```bash
echo '{"tool":"speciate","params":{"ph":9.0,"c_total":0.05,"ca_total":0.05,"cl_total":0.1}}' \
  | python tools/cli.py speciate
```

预期:`ok: true`,`si_calcite ≈ 3.54`,说明该 50 mM 钙液在 pH 9.0 下显著过饱和。

## 示例

- [examples/calcium-balance-check.json](examples/calcium-balance-check.json) — 钙质量守恒检查(0.02 液相 + 0.03 固相 = 0.05 总钙 → 通过)
- [examples/speciate-cementation-fluid.json](examples/speciate-cementation-fluid.json) — 胶结液 pH 9.0 碳酸盐平衡 + SI
- [examples/simulate-batch-kinetics.json](examples/simulate-batch-kinetics.json) — 0.5 M 尿素 + 0.5 M CaCl₂ 批处理 2 小时:区分平衡可沉淀量与有限时间实际沉淀量

运行:`python tools/cli.py --input examples/<file>.json`

## 测试与评测

```bash
python -m unittest tests.test_engine      # 52 项单元/集成/失败/回归(库层)
python tests/run_evals.py                 # 12 项评测用例 + 7 项性能指标阈值
python tests/bootstrap.py                 # 4 个自举场景(以 Skill 身份执行真实工具)
```

测试全部离线;不写网络。评测指标与阈值定义见 [SKILL.md](SKILL.md#performance-indicators) 与 [evals/cases.yaml](evals/cases.yaml)。

## 契约摘要

- **输入**(必填):`task_id`、`project_id`、`request`、`skill_version`、`timestamp`;可选:`context`(pathway/matrix/species/simulation)、`constraints`、`evidence_refs`、`data_refs`、`risk_level`、`human_approval_state`、`tool` + `params`(机器直派)。
- **输出** `status ∈ {SUCCESS, PARTIAL, BLOCKED, FAILED, NEED_ADDITIONAL_SKILL, HUMAN_APPROVAL_REQUIRED}`,携带 `calculation`、`findings`(每项带认识论标签)、`assumptions`、`evidence_used`、`uncertainty`、`risks`、`artifacts`、`requested_next_skills`、`validation`、`provenance`、`errors`。
- **认识论标签**:OBSERVED / REPORTED / CALCULATED / INFERRED / HYPOTHESIS / RECOMMENDATION;OBSERVED 与 REPORTED 必须带 S# source。
- **版本策略**:schema 破坏性变更 → 主版本提升,无迁移即拒绝(MUC-E1010);新增可选字段 → 次版本;实现修复 → 修订版本。见 [SKILL.md](SKILL.md#version-policy)。

## 故障排查

| 症状 | 原因 | 处理 |
|---|---|---|
| `exit 3` + `MUC-E1009` | 输入非 JSON 或为空 | 检查信封与 stdin/`--input` |
| `exit 3` + `MUC-E1010` | caller 声明的 `skill_version` 不兼容 | 更新信封 `skill_version` 或注册迁移 |
| `exit 2` + `MUC-E2002/E2003` | 质量/电荷不守恒 | 读 `calculation.elemental`/`charge`,修正数据;守恒失败时不得继续给工程建议 |
| `exit 3` + `MUC-E1001` | 信封缺 `tool` 或 `tool` 非法 | 检查直派信封 |
| `phreeqc-run` 返回 MUC-E3001 | PHREEQC 未安装 | 离线降级:使用生成的 deck 或安装 PHREEQC 并设 `PHREEQC_BIN` |
| 高离子强度警告 | I > 0.5 M,Davies 活度模型越界 | 输出标 PARTIAL,注明不确定性 |

## 限制

- 批处理闭式模型;流动/输运(现场尺度)需接入 `simulate` 之外的输运能力(S31),本 Skill 不冒充。
- 沉淀速率常数、比表面积是模型参数,必须按体系标定(CALIBRATION_REQUIRED),不当作测量值。
- 单一 SI 不等于晶体产率;产率只能来自 `simulate` 的动力学积分或明确标注的平衡上界。
- 非尿素路径(反硝化/EICP)不得套用本模型。

## 维护者

- 实现:Python 3,标准库 + 可选 numpy/scipy。目录约定:修改 schema 前先读 [SKILL.md](SKILL.md#version-policy) 与 `CHANGELOG.md`。
- 变更任何工具行为后必须重跑 `tests/test_engine.py`、`tests/run_evals.py` 与 `tests/bootstrap.py`。
- 本目录不包含任何密钥;凭据只经环境变量或 controller 传入。
