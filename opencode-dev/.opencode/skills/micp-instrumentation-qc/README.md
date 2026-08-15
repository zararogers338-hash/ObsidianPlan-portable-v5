# micp-instrumentation-qc

**MICP Instrumentation QC | 仪器、标定、采样链与质量控制**

Obsidian Plan / Panshi 研究型工程下的受治理 Skill。为 MICP 研究中的传感器、
力学仪器、水化学仪器、影像设备与采样链提供可追溯、可校准、可审计的数据
QC:校准曲线与不确定度、控制图与漂移检测、样品链与条码、原始/派生数据哈希与
审计日志、仪器数据格式标准化。

- **版本**: 1.0.0 (`contract_version: 1.0.0`)
- **许可**: MIT
- **入口**: `tools/cli.py`(纯 Python 标准库,离线、确定性)
- **加载**: 由 Obsidian Controller / Skill Router 通过 `.opencode/skills/` 加载

## 安装 / 装载

1. 将本目录置于仓库 `.opencode/skills/micp-instrumentation-qc/`
   (或 `.claude/skills/`、`.agents/skills/`)。
2. 依赖:Python ≥ 3.11(`jsonschema`、`PyYAML` 仅用于测试与评测,运行工具不需要)。
3. 校验装载:
   ```bash
   cd skills/micp-instrumentation-qc
   python -m pytest tests/            # 75 个测试
   python evals/run_evals.py          # 12 个评测用例
   ```

## 调用

输入输出为 JSON envelope(契约见 `schemas/input.schema.json` 与
`schemas/output.schema.json`)。工具通过 stdin 读取输入、stdout 返回结果:

```bash
cat input.json | python tools/cli.py qc
```

子命令: `qc`(全管线) / `calibration` / `control` / `sample-chain` /
`integrity` / `adapters` / `check-self`。

示例见 `examples/`。最少调用:

```bash
python tools/cli.py check-self
```

## 工具与用途

| 工具 | 子命令 | 用途 |
|---|---|---|
| `calibration.py` | `calibration` | OLS 校准曲线、LOD/LOQ(3.3σ/S、10σ/S)、扩展不确定度(k=2) |
| `control_chart.py` | `control` | Shewhart 控制图;漂移(7 点同侧/6 点单调)、超量程、饱和、基线异常、时间戳错位 |
| `sample_chain.py` | `sample-chain` | 样品链;Code-39 Modulo-43 条码、重复编号、时间戳对齐 |
| `integrity.py` | `integrity` | 原始/派生 SHA-256、追加式哈希链审计日志、篡改检测 |
| `adapters.py` | `adapters` | 仪器导出 CSV/TSV 解析、单位归一化 |
| `qc_pipeline.py` | `qc` | 全管线编排 + 信封校验(必需字段、版本门、schema) |
| `cli.py` | — | 唯一触碰 stdin/stdout 的入口 |

## 设计原则(高工程状态)

- **纯 stdlib**: `tools/` 零第三方运行时依赖,离线、确定性、可审计。
- **原始数据不可变**: `integrity.py` 哈希原始内容;派生记录必须引用
  `raw_sha256`;审计日志是追加式哈希链。
- **默认安全**: `dry_run=true` 默认;任何数据写入 / 现场 / 实验 / 危险化学品 /
  长期知识写入要求 `human_approval_state == approved`(MICQ-E1007)。
- **错误码**: `MICQ-E1001…E1011`(见 `SKILL.md §6`),`{code,message,retryable,details}`
  人类可读 + 控制器可解析。
- **版本兼容**: 契约破坏性变更 → 主版本+1;新增可选字段 → 次版本;修复 → 修订版本;
  不兼容主版本无迁移即拒绝(MICQ-E1010)。

## 限制与已知边界

- 校准统计是**简化 GUM/分析化学常用公式**,用于 QC 辅助;正式报告须由实验室
  LIMS/计量部门出具。
- 单位归一化按维度进行;摩尔浓度与质量浓度(如 NH4+ 的 mol/L vs mg/L)是**不同
  维度**,需要摩尔质量换算时属于下游分析 Skill,本 Skill 不做。
- 审计哈希链检测篡改与意外修改,但不是对抗攻击者重写整条日志的密码学方案。
- 控制图的均值/标准差在无显式 `qc` 判据时用全体测量估计——单点强离群会抬高
  sd、弱化其自身 z 值;关键判定应提供实验室 QC 判据(mean/sd)。
- 不联网;不执行实验;不修改原始数据;不伪造任何数值。

## 故障排查

| 症状 | 处理 |
|---|---|
| `python tools/cli.py check-self` 报 imports_ok=false | 检查 Python ≥3.11;确认在 `tools/` 目录内运行或 `PYTHONPATH` 含 `tools/` |
| `MICQ-E1001` 大量出现 | 信封缺必需字段;读 `input.schema.json` 的 `required` |
| `MICQ-E1003` | 数值单位跨维度或未识别;核对单位字符串 |
| `MICQ-E1010` | `skill_version` 主版本 != 1 或 `controller_version` < 1.0.0 |
| 评测 `run_evals.py` 失败 | 先跑 `python -m pytest tests/`;若测试通过则评测环境缺 PyYAML |

## 目录结构

```
micp-instrumentation-qc/
├── SKILL.md                # 身份/触发/边界/流程/错误码/版本/指标
├── manifest.json           # 机器可读元数据
├── README.md               # 本文档
├── CHANGELOG.md            # 版本历史
├── schemas/
│   ├── input.schema.json
│   └── output.schema.json
├── prompts/system.md       # 最小系统提示词
├── tools/                  # Python 标准库实现
├── tests/                  # 75 个单元/集成/schema/回归测试
├── evals/                  # 12 个评测用例 + run_evals.py + metrics.md
├── examples/               # 3 个可运行示例
└── references/
    ├── sources.md          # 领域依据与来源
    └── instrument-domain.md# 可更新的仪器域知识
```


---

> 原 `ZIP-README-请先读我.md` 已归档至 [`audit/ZIP-README-请先读我.md`](audit/ZIP-README-请先读我.md)。
