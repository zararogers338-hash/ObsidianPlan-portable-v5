# 交付报告 — micp-instrumentation-qc (Skill v1.0.0)

> 交付日期:2026-08-06 · 部署位置:`.opencode/skills/micp-instrumentation-qc/` · 契约版本 1.0.0

---

## 1. 仓库与标准识别结果

- **仓库根**: `.opencode`(OpenCode monorepo,bun workspace)。本项目是 OpenCode 的 OBSIDIAN 品牌化 fork,`OBSIDIAN-PLAN.md` 记录了 Engine 冻结原则与 Phase 4「科研 Skill 扩展」规划。
- **真实 Skill 标准**: 以仓库内已存在的 `.opencode/skills/obsidian-mission-lock` 为准——`SKILL.md(frontmatter) + manifest.json + schemas/input+output.schema.json + prompts/system.md + tools/ + tests/ + evals/cases.yaml + examples/ + references/sources.md + CHANGELOG.md`。姊妹技能 `micp-ureolysis-chemistry` 证实 Python 工具路径可行。本 Skill 严格映射此标准。
- **skill.yaml 约定**: 目录内已有的 `skill.yaml` 是 Obsidian Plan 项目的机器可读元数据标准(项目自定义约定,注释中说明 OpenCode 原生加载器只读 SKILL.md frontmatter 的 name/description;skill.yaml 供 Obsidian controller / Skill Router / 打包工具消费)。其内容与本实现完全一致(入口 `tools/cli.py`、错误码 `MICQ-E1xxx`、版本策略、评价指标),已核验并纳入交付。
- **工具链**: Python 3.13.9(pytest 8.4.2、jsonschema 4.25、PyYAML 可用)。`tools/` 全部纯 Python 标准库,离线、确定性。
- **治理结构**: Panshi 宪法(`Anru_Constitution_v2_30000.md`)定义 Controller/Router/Skill 星型拓扑、认识论标签、人工批准门、MICP 六层区分与尿素水解质量守恒纪律。本 Skill 的 prompts/system.md 是宪法在该专业域的**最小投影**。

## 2. 新增/修改文件清单

```
.opencode/skills/micp-instrumentation-qc/
├── SKILL.md                     # 身份/触发(6正+4反+4边界)/边界/流程/错误码/版本/指标
├── manifest.json                # 机器可读元数据(v1.0.0,MIT,offline,deterministic)
├── README.md                    # 维护者文档
├── CHANGELOG.md                 # v1.0.0 初始记录
├── schemas/input.schema.json    # 输入契约(信封 + qc_input)
├── schemas/output.schema.json   # 输出契约(6 状态 + qc_report + 认识论标签 + 错误码)
├── prompts/system.md            # 最小系统提示词(不复制宪法)
├── tools/
│   ├── cli.py                   # 唯一 stdin/stdout 入口(7 子命令)
│   ├── _common.py               # 错误码表 + 数值/单位/维度校验
│   ├── calibration.py           # 校准曲线 + LOD/LOQ + k=2 扩展不确定度
│   ├── control_chart.py         # Shewhart + 漂移/超量程/饱和/基线/时间戳
│   ├── sample_chain.py          # 样品链 + Code-39 Modulo-43 条码 + 重复编号
│   ├── integrity.py             # SHA-256 + 追加式哈希链审计日志 + 篡改检测
│   ├── adapters.py              # 仪器导出 CSV/TSV 解析 + 单位归一化
│   └── qc_pipeline.py           # 全管线编排 + 信封校验(必需字段/版本门/schema/evidence)
├── tests/                       # 75 个测试(7 个文件)
├── evals/                       # cases.yaml(12 用例)+ run_evals.py + metrics.md
├── examples/                    # 3 个可运行示例
├── references/                  # sources.md(领域依据)+ instrument-domain.md(可更新知识)
└── audit/                       # 自举测试输入与记录
```

## 3. Skill 输入输出契约

- **输入** (schemas/input.schema.json): 必需 `task_id, project_id, request, skill_version, controller_version, timestamp`;可选 `context, constraints(dry_run/allow_derived_write/output_dir/audit_log), evidence_refs, data_refs, upstream_outputs, requested_output_format(qc_report|qc_plan|integrity_report|calibration_report), risk_level, human_approval_state`;领域载荷 `qc_input{instruments, calibrations, measurements, samples, raw, derived}`。
- **输出** (schemas/output.schema.json): `status`(6 枚举)+ `summary + findings(带认识论标签) + assumptions + evidence_used + uncertainty + risks + artifacts + requested_next_skills + qc_report{overall_passed, pass_rate, instrument_status, sample_flags, analysis_restrictions, retest_items, calibration, control, sample_chain, integrity} + missing_inputs + validation + provenance + errors(MICQ-E1xxx)`。
- **认识论标签**: OBSERVED / REPORTED / CALCULATED / INFERRED / HYPOTHESIS / RECOMMENDATION 强制;OBSERVED/REPORTED 必须带 `source`。

## 4. 所造工具及用途

| 工具 | 用途 |
|---|---|
| `calibration.py` | OLS 线性校准、残差 sd、R²、LOD=3.3σ/S、LOQ=10σ/S、反向预测扩展不确定度(k=2, GUM 线性反演) |
| `control_chart.py` | Shewhart \|z\|≥3→OUT_OF_CONTROL、≥2→WARNING;7 点同侧/6 点单调→漂移;超量程/饱和/基线异常/时间戳错位 |
| `sample_chain.py` | 采样链、Code-39 Modulo-43 条码生成与校验、重复编号与时间戳对齐检测 |
| `integrity.py` | 原始/派生 SHA-256、追加式哈希链审计日志、篡改检测(链断裂定位) |
| `adapters.py` | 仪器导出 CSV/TSV 自动分隔符解析、表头单位提取、单位归一化 |
| `qc_pipeline.py` | 信封校验 + 六步管线(单位→evidence→标定→控制图→样品链→完整性)→ QC 报告 |
| `cli.py` | 子命令分发(qc/calibration/control/sample-chain/integrity/adapters/check-self) |

## 5. 真实执行过的测试与结果

| 套件 | 结果 |
|---|---|
| `python -m pytest tests/` | **75 passed**(单元 44 + 集成 11 + schema 11 + 管线 9), 1.45s |
| `python evals/run_evals.py` | **12/12 passed**(normal 5 / missing 2 / conflict 3 / adversarial 2 / boundary 1) |
| `python tools/cli.py check-self` | imports_ok=true, 11 个错误码齐全 |
| examples/ 1–3 真实运行 | qc_plan 3 台仪器 PASS;标定 r2=0.99986 + 漂移拦截(s3 OUT_OF_CONTROL + 重测);integrity 原始哈希生成 |
| 自举测试 1–4 | 见 §6 |
| 审计日志哈希链 | 追加 2 条验证通过;篡改后 broken_at=0 |

**性能指标**(evals/metrics.md, 全部达标): 结构化输出通过率 12/12(≥0.95);工具真实调用率 =1.0(子进程真实执行,无 mock);引用可追溯率(伪造 data_ref 被 MICQ-E1002 拦截);缺失输入识别率 =1.0(CASE-04/05 逐字段拒绝);对抗拦截率 =1.0(CASE-09/10 无非法 SUCCESS);重复运行一致性 =1.0(同输入两次输出逐字节一致);平均失败恢复时间 = 0 轮(本交付全部通过)。

## 6. 自举测试中发现的问题及修复

| 问题 | 修复 |
|---|---|
| 审计日志哈希链自引用 bug(`entry_hash` 参与自身哈希,永远校验失败) | `sha256_of(exclude="entry_hash")`;`entry_index` 移到哈希前 |
| `qc_pipeline` 空 `qc_input` 静默「通过」 | 增加 MICQ-E1001 逐字段缺失门(why/how/blocking) |
| `data_refs/evidence_refs` 是信封级字段,未进入 evidence 检查 | `run()` 内线程化到 `qc_input`,evidence 门生效 |
| 信封校验错误只放 `envelope_errors`,控制器难解析 | 同步镜像到顶层 `errors` |
| adapters 表头小写化丢失 `mg/L` 原样 | 保留原表头二次匹配单位 |
| 控制图单点离群会抬高全局 sd 弱化自身 z | 判定应给显式 qc(mean/sd);测试改用固定判据 |
| 标定完美拟合时 LOD/LOQ=0 | 明确为合法(无残差→无穷精密度)并在测试注明 |
| 时间戳错位未翻转 overall_passed | 加入管线门 |
| 其余为测试期望笔误(条码校验位、y_sample 命名等) | 已修正 |

## 7. 尚未关闭的风险与限制

1. 校准统计为**简化 GUM/分析化学公式**,QC 辅助用途;正式计量报告须由实验室 LIMS/计量部门出具。
2. 摩尔浓度 vs 质量浓度(mol/L vs mg/L)是**不同维度**;需摩尔质量的换算交给下游分析 Skill,本 Skill 不猜分子量。
3. 控制图在无显式 QC 判据时用全体测量估计 mean/sd——单点强离群会削弱自身 z 值;文档已写明关键判定应提供实验室判据。
4. 审计哈希链检测篡改与意外修改,**非对抗性密码学方案**(可被重写整条日志的攻击者绕过)。
5. 条码 Modulo-43 是弱校验,不替代正式标签规范。
6. 版本门当前只接受 `skill_version` 主版本 1;跨主版本迁移器尚未实现(符合契约的「无迁移即拒绝」策略)。

## 8. 调用示例

```bash
# 从 skill 目录
python tools/cli.py check-self
cat examples/example-2-calibration-drift.json | python tools/cli.py qc
# 全量验证
python -m pytest tests/ && python evals/run_evals.py
```

Controller 以 JSON envelope 调用 `qc` 子命令即得完整 `qc_report`;输出通过 output.schema.json 校验。

## 9. 版本号与后续演进建议

- **当前**: 1.0.0(契约 1.0.0)。
- **演进建议**:
  - 0.x→1.x 已按约定;后续契约破坏性变更(改字段/枚举/错误码)→ 主版本+1;新增可选字段 → 次版本;实现修复 → 修订版本。
  - 建议下一步:接入 Obsidian Router 的 `instrumentation-qc` 槽位做端到端注册测试;为摩尔浓度换算与尿素质量守恒校核提供受治理的下游 Skill 协作(NEED_ADDITIONAL_SKILL)。
  - 建议为正式研究建立「期间核查(ISQ)」数据集并把控制图判据改为基于方法验证结果,而非估计值。
  - `audit/` 目录已启用,长周期研究建议把审计日志归档到版本库外存储。
