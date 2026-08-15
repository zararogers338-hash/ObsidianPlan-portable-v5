# 本 ZIP 包是什么 / What this ZIP is for

**micp-scaleup-injection-engineer v1.0.1** — MICP Injection Design & Scale-Up Engineer｜
MICP 注入设计与工程尺度放大器

## 用途 (Purpose)

将实验室烧杯、试样、砂柱方案逐级转换为**中型砂柱 → 米级试验 → 场地试验 → 现场施工方案**，
明确哪些参数可相似缩放、哪些**绝不能按体积线性放大**（浓度/孔隙流速/注入压力/轮次/均匀性）。
用于 Obsidian Plan / Panshi（磐石）的 MICP / 生物胶结工程放大方向。

## 包内结构 (Package layout)

- `SKILL.md` — 技能定义：触发/不触发条件、能力边界、放大规则、流程、错误码、版本策略（OpenCode 引擎据此发现本 Skill）
- `skill.yaml` — 机器可读 manifest（Router registry 消费；capabilities 含裸 token `scaleup`）
- `manifest.json` — 机器清单
- `prompts/system.md` — 最小系统提示词（身份、流程、边界、认识论、停止规则）
- `schemas/` — 四份 JSON Schema：input / output / injection-plan / monitoring-plan
- `tools/scaleup.py` — CLI 入口（stdin JSON → stdout JSON，离线、确定性）
- `tools/msi/` — 13 个工具模块（质量平衡、恒流/恒压边界、压力风险、相似性矩阵、注入布局/调度、监测报警、堵塞/均匀性、示踪、阶段门、单位、错误码、自检）+ 编排 service
- `tests/` — 单元/集成/失败/回归/路由集成测试（pytest，81 项，含 10 强制场景 + 16 审查回归）
- `evals/` — 10 个评测用例 + 7 项性能指标（`python evals/run.py`）
- `examples/` — 3 个可运行示例（lab→metre、metre→site、field 审批门）
- `references/sources.md` — 文献溯源（AS2013 / VP2010 / OEGG2017 / Gomez 等，带 DOI/URL）
- `CHANGELOG.md`、`README.md`、`DELIVERY-REPORT.md`
- `work/` — BOOTSTRAP-REPORT（自举案例）+ REVIEW-FIXES-REPORT（三方审查修复）

## 调用方式 (How to call)

```bash
python tools/scaleup.py < input.json > output.json
python -m pytest tests/ -q
python evals/run.py --verbose
```

## 强制行为 (Non-negotiable)

- **现场施工**（`scale_level=field`）→ 任何动作都返回 `HUMAN_APPROVAL_REQUIRED`，要求六项审批
  （岩土工程师批准/环境与生物安全审查/场地法规核验/施工风险评估/废液与氨氮方案/应急预案）。
- **NH₄-N 保守计量**：按注入尿素计（2 NH₄-N/尿素），不低估 1/转化率。
- **阶段门**：门阻塞 → 状态 `PARTIAL`，绝不报 SUCCESS。
- **缺场地渗透率**（site/field）→ `BLOCKED`（MSI-E102）点名缺失字段，绝不编造。
- 所有文献数据可核验，零伪造。
