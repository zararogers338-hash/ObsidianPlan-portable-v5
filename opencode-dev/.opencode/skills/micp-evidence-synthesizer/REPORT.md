# 交付报告 — micp-evidence-synthesizer (MES)

> MICP Evidence Synthesizer｜跨研究证据综合与矛盾解析
> 版本 1.0.0 · 2026-08-06 · 工程状态：**已装载、可调用、已测试、可审计**

---

## 1. 仓库与标准识别结果

- **仓库**：`opencode-src/opencode-dev`（OpenCode monorepo 的 Obsidian/Panshi 改造副本）。
- **Skill 目录标准**：仓库顶层 `skills/` 下已存在 `obsidian-skill-router`（TS）、`obsidian-state-manager`（Python），另有 `.opencode/skills/` 早期版本。本次严格对齐 `skills/` 现行标准：统一输出信封、`skill.yaml` manifest、`evals/` + `tests/` 分层、认识论标签、版本兼容策略。
- **OpenCode 原生 loader 约定**：只读 `SKILL.md` frontmatter 的 `name` + `description`（`packages/opencode/src/skill/index.ts`）。目录名 `micp-evidence-synthesizer` 通过 `^[a-z0-9]+(-[a-z0-9]+)*$` 规则。`skill.yaml` 为 Obsidian 项目自定义扩展 manifest（已在 README §9 说明）。
- **运行时**：Python 3.13.9；`jsonschema`/`pyyaml`/`pytest` 已装但均为**可选依赖**——内建回退校验器保证离线零依赖可用（已用真实 jsonschema 库交叉验证一致）。

## 2. 新增文件清单（37 个文件）

```
skills/micp-evidence-synthesizer/
├── SKILL.md                    角色/触发反触发边界/流程/错误码/权限/版本/指标
├── skill.yaml                  机器可读 manifest
├── README.md                   维护者文档（安装/调用/限制/故障排除/约定说明）
├── CHANGELOG.md                版本历史 + 已知限制
├── schemas/
│   ├── input.schema.json       输入契约（统一信封 + PICO + evidence_cards）
│   └── output.schema.json      输出契约（统一信封 + synthesis 定义）
├── prompts/system.md           最小系统提示词
├── tools/
│   ├── mes_cli.py              stdin→stdout 入口 + --validate-schema
│   └── mes/                    （10 个模块，见 §4）
├── tests/
│   ├── conftest.py             共享 fixture
│   ├── test_unit.py            20+ 单元用例
│   ├── test_integration.py     管道/契约/CLI/确定性
│   ├── test_failure.py         缺失/对抗/损坏输入
│   └── test_regression.py      回归 + 认识论纪律
├── evals/
│   ├── cases.yaml              10 个评测用例
│   ├── metrics.py              7 指标公式与阈值
│   ├── run.py                  离线评测器
│   └── results/                latest.json + bootstrap-*.json（真实运行记录）
├── examples/                   3 个可运行示例
└── references/sources.md       领域与方法学依据（17 条 + 决策记录）
```

## 3. 输入输出契约

**输入**（`schemas/input.schema.json`）：必填 `contract_version, task_id, project_id, request, action, skill_version, timestamp, evidence_cards, pico`；`action` 恒为 `evidence.synthesize`。卡片必含 `ref_id, study_id, study_type, evidence_level`（outcome/reported_effect 由运行时 OES-E102 校验以给出精确字段指引）。`pico` 的 population/intervention/outcome 由运行时 OES-E113 检查并附获取指引。

**输出**（`schemas/output.schema.json`）：统一信封 `status, summary, findings, assumptions, evidence_used, uncertainty, risks, artifacts, requested_next_skills, validation, provenance, errors` + `synthesis`（`pico_framework, comparability_check, evidence_matrix, conflict_matrix, conclusions, synthesis_method, conditions, gaps` + 按需 `meta_analysis, heterogeneity, sensitivity, grade`）。状态枚举 `SUCCESS/PARTIAL/BLOCKED/FAILED/NEED_ADDITIONAL_SKILL/HUMAN_APPROVAL_REQUIRED`。

**认识论标签**：所有重要陈述使用 `OBSERVED/REPORTED/CALCULATED/INFERRED/HYPOTHESIS/RECOMMENDATION`；卡片 `claims` 不自动升级为 OBSERVED；OBSERVED/REPORTED 必须带 `source`。

## 4. 工具清单

| 工具 | 用途 | 验证 |
|---|---|---|
| `mes_cli.py` | stdin→JSON→stdout 入口；`--validate-schema` | CLI 集成测试通过 |
| `mes/errors.py` | OES 错误码注册表（17 码，唯一事实源） | 单元测试 |
| `mes/models.py` | 信封/标签/层/摘要/摘要工具 | 单元测试 |
| `mes/jsonschema.py` | 内建 draft-07 回退校验器（anyOf/$ref/type 数组） | 与真实 jsonschema 交叉验证一致 |
| `mes/evidence_validate.py` | 卡片校验（必需字段/ref 可核验性/数值有限性/重复检测） | 单元测试 |
| `mes/unit_map.py` | 单位归一化（Pa/kPa/MPa、%、C/K、mol/L、kg/m³；保留原值） | 单元测试 |
| `mes/effect_compute.py` | Hedges' g / Cohen's d / 均差（双臂） | 单元测试 |
| `mes/meta_analyze.py` | 固定效应 + DerSimonian-Laird 随机效应 + I²/τ²/Q + 预测区间 | 单元测试 |
| `mes/heterogeneity_compute.py` | 四类异质性分类 + 13 维可比性检查 | 单元测试 |
| `mes/evidence_map.py` | 证据矩阵 + 矛盾矩阵（方向/量级/单位/显式） | 单元测试 |
| `mes/sensitivity_run.py` | 留一法 + 显式高偏倚剔除 | 回归测试 |
| `mes/grade_assess.py` | GRADE 式五域分级（含 very_serious 双级降级） | 单元测试 |
| `mes/result_check_overgeneralization.py` | 过度概括自检（scope/反例/标签膨胀/全称词） | 单元测试 |
| `mes/service.py` | 编排 + 统一信封 + PARTIAL 语义 + 批准门 + 审计链 | 集成测试 |

## 5. 真实执行的测试与结果

| 套件 | 命令 | 结果 |
|---|---|---|
| 单元测试 | `pytest tests/test_unit.py` | 20+ 通过 |
| 集成测试 | `pytest tests/test_integration.py` | 管道/契约/CLI 通过 |
| 失败测试 | `pytest tests/test_failure.py` | 缺失/对抗/损坏拦截通过 |
| 回归测试 | `pytest tests/test_regression.py` | 单位/效应/meta/敏感性/认识论纪律通过 |
| **全部** | `pytest -q` | **70 passed, 1 skipped** |
| 评测 | `python evals/run.py` | **10/10 用例通过** |
| 静态检查 | `python -m compileall` | OK |
| 交叉验证 | 真实 jsonschema vs 回退校验器 | 3 个示例 input/output 全一致 |

**7 项性能指标**（`evals/results/latest.json`，全部达标）：

| 指标 | 结果 | 阈值 |
|---|---|---|
| 结构化输出通过率 | 1.000 | ≥ 0.95 |
| 工具真实调用率 | 1.000 | = 1.0 |
| 引用/数据可追溯率 | 1.000 | ≥ 0.9 |
| 缺失输入识别率 | 1.000 | = 1.0 |
| 对抗用例拦截率 | 1.000 | = 1.0 |
| 重复运行一致性 | 1.000 | = 1.0 |
| 平均失败恢复轮次 | 0（当前基线） | ≤ 1 |

## 6. 自举测试发现的问题与修复

| 场景 | 结果 | 修复记录 |
|---|---|---|
| S1 两张 CaCO3 相似但强度不同 | **通过** | 证据矩阵 + 矛盾矩阵正确保留两卡差异；`comparability=comparable` 且可合并 |
| S2 不同 UCS 试样尺寸/加载速率 | **通过** | 新增 `specimen_diameter/height/loading_rate` 可比性维度；`meta_analysis=None`（禁止合并）|
| S3 移除高偏倚研究 | **通过** | 高偏倚卡剔除 delta=-4.05；整体不可合并时仍运行 LOO 敏感性 |
| S4 Skill 自答后自攻 | **通过** | 结论全部带 scope/counterexample；无过度概括存活 |

**过程中发现并修复的问题**：
1. `service.py` 中 `payload['constraints']` 在缺失时 KeyError → 改为 `.get() or {}`。
2. output.schema `$ref` 键名大小写不一致（`metaAnalysis` vs `meta_analysis`）→ 统一小写下划线。
3. 回退校验器不支持 `["string","null"]` 类型数组 → 增加 `_type_matches` 联合类型支持。
4. `synthesis`/`meta_analysis`/`sensitivity` 键在错误信封中缺失 → 改 anyOf null + 始终写入。
5. GRADE 对 critical 偏倚只降 1 级 → 增加 `very_serious` 双级降级。
6. 自检词表把"conflicts...not averaged"误判为全称词 → 限定为领域词汇 + 排除方法规则句。
7. 单位不兼容时仍发生合并 → comparability 门强制禁止 pooling。
8. PICO required 在 schema 层拦截（E113 不可达）→ 改为运行时 E113 + 获取指引。
9. action 错误状态映射（FAILED vs BLOCKED）→ 协议故障 FAILED，可修复输入 BLOCKED。
10. eval runner 断言语法不完整（`in str()`/`!=`）→ 扩展求值器。

## 7. 尚未关闭的风险与限制

1. **GRADE 为启发式规则**：非完整 GRADEpro 工具；域评分的"very_serious 双级降级"是简化近似。
2. **卡方 p 值用 Wilson-Hilferty 近似**：精度有限，极端情况下可能与精确值有偏差（已记录）。
3. **回退校验器只覆盖仓库 schema 用到的 draft-07 子集**：未实现 `oneOf`/`allOf`/`format` 等；当前 schema 未用，但未来扩展契约时需同步。
4. **`skill.yaml` 是项目自定义约定**：非 OpenCode 标准；若未来 OpenCode 改变 skill 格式需迁移。
5. **效应量仅支持双臂均差/标准均差**：OR/RR/相关系数目前仅作"reported"记录，不参与合并（输出契约已声明）。
6. **示例中的 DOI 为演示标识**：非真实文献，运行输出不可当作真实系统综述结论（`references/sources.md` §5 已声明）。

## 8. 调用示例

```bash
# 综合两张证据卡（CaCO3 含量相似但强度不同）
python3 tools/mes_cli.py < examples/01-caco3-similar-content.json > out.json

# 校验输入是否符合契约
python3 tools/mes_cli.py --validate-schema < input.json

# 运行全部测试
python3 -m pytest -q

# 运行 10 用例评测 + 7 指标
python3 evals/run.py
```

被 Obsidian Controller / Router 调用时，直接以 JSON 信封交换（stdin→stdout），`skill_version` 由调用方注入。高风险自动链入 `obsidian-red-team` → `obsidian-decision-gate` 审计；现场部署等触发 `HUMAN_APPROVAL_REQUIRED`。

## 9. 版本与演进建议

- **当前**：1.0.0（契约 1.0）。
- **演进建议**：
  1. 接入 Router 注册表快照，与 `obsidian-skill-router` 的 `skills/` 索引互相发现。
  2. 增加 `publication_bias` 漏斗图对称性检查（需 numpy/matplotlib，保持可选）。
  3. 增加 OR/RR 效应量合并路径（临床/环境终点需要）。
  4. 将 GRADE 五域替换为完整 GRADEpro 输出或可导出证据表。
  5. 跨 skill 集成测试：用 `evidence-extractor` 产出的真实卡片端到端跑本 Skill。
- **版本策略**：破坏性契约变更 → 主版本 +1；新增可选字段 → 次版本；实现修复 → 修订版本。旧主版本输出迁移或 `OES-E801` 明确拒绝。

---

**验收对照**（任务书 §九）：论文数量未替代证据质量 ✓；总体结论全部带边界条件 ✓；不可比数据明确隔离（OES-E103/单位门）✓；冲突解释来源不平均掩盖（矛盾矩阵 + type/direction/explanation）✓；可独立运行 + 可被 Router 调用 ✓；缺失输入返回 BLOCKED 而非编造 ✓；需协作返回 NEED_ADDITIONAL_SKILL ✓；结果可追溯可复现可版本化 ✓；测试真实运行 ✓；无 TODO/占位 ✓。
