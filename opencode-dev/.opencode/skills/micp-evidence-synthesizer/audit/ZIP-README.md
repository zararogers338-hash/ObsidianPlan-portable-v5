# 本 ZIP 包是什么 / What this ZIP is for

**micp-evidence-synthesizer v1.0.0** — MICP Evidence Synthesizer｜跨研究证据综合与矛盾解析
(MICP 微生物诱导碳酸钙沉积 研究项目的跨研究证据综合专业能力)

## 用途 (Purpose)

将多个 **Evidence Card（证据卡）** 综合为**条件化结论**，识别研究之间可比性、异质性、
冲突来源和证据缺口，**避免简单多数投票**。用于 Obsidian Plan / Panshi（磐石）研究
核心的 MICP / 生物胶结方向。

## 包内结构 (Package layout)

- `SKILL.md` — 技能定义：触发/不触发条件、能力边界、流程、错误码、版本策略（OpenCode 引擎据此发现本 Skill）
- `skill.yaml` — 机器可读 manifest（Obsidian 控制器 / 打包 / CI 使用）
- `prompts/system.md` — 最小系统提示词（身份、流程、边界、认识论、停止规则）
- `schemas/input.schema.json` + `output.schema.json` — 严格输入/输出契约
- `tools/mes_cli.py` — CLI 入口（stdin JSON → stdout JSON，离线、确定性）
- `tools/mes/` — 9 个真实工具模块（卡片校验、单位归一、效应量、meta 合并、异质性、证据/矛盾矩阵、敏感性、GRADE、过度概括自检）+ 编排 service
- `tests/` — 单元/集成/失败/回归测试（pytest，71 项）
- `evals/` — 10 个评测用例 + 7 项性能指标（`python evals/run.py`）
- `examples/` — 3 个可运行示例（CaCO3 相似/尺寸不可合并/高偏倚敏感性）
- `references/sources.md` — 实现与领域依据
- `CHANGELOG.md`、`README.md`

## 调用方式 (How to call)

```bash
python tools/mes_cli.py < input.json > output.json
```

输入需满足 `schemas/input.schema.json`（必填：`contract_version, task_id, project_id,
request, action=evidence.synthesize, skill_version, timestamp, pico, evidence_cards`）。

## 运行测试与评测 (Test & evals)

```bash
python -m pytest -q        # 单元/集成/失败/回归测试
python evals/run.py        # 10 评测用例 + 7 项性能指标
```

## 验收状态 (Acceptance status)

- 单元/集成/失败/回归测试：**70 passed, 1 skipped**
- 评测用例：**10/10 通过**；结构化输出通过率 1.0、工具真实调用率 1.0、
  可追溯率 1.0、缺失输入识别率 1.0、对抗拦截率 1.0、重复运行一致性 1.0
- Obsidian Router registry 契约：**通过**
- 全程离线、无网络、无密钥、无写入（dry_run 时零写入）
