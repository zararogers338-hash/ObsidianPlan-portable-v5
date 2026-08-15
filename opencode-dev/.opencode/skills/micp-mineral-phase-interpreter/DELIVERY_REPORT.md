# micp-mineral-phase-interpreter — 交付报告（v1.1.1，最终核验）

版本：1.1.1（契约 contract_version 1.0）
日期：2026-08-07
状态：**已交付、已装载、已测试、已通过自举与对抗审查、Router 已注册 usable=true**

---

## 1. 仓库与标准识别结果

- **真实项目仓库**：`opencode-src/opencode-dev`（OpenCode 官方源码 fork，bun workspace）。
- **既有 Skill 标准**：`skills/obsidian-skill-router`（TS/Bun）+ `skills/obsidian-state-manager`（Python）为仓库既定约定。本 Skill 遵循 Python 范式（stdin=JSON → stdout=JSON、统一封套、OMM-E### 错误码、tests/evals runner）。
- **OpenCode 加载契约**：loader 从 `SKILL.md` frontmatter 读 `name` + `description`（已在 `packages/opencode/src/skill/index.ts` 验证）。
- **领域来源**：`references/sources.md` 20 项来源全部经在线验证（DOI 解析、CIF 下载、HTTP 状态）；捕获并剔除编造标题 ASTM E2016。

## 2. 版本沿革

| 版本 | 日期 | 内容 |
|---|---|---|
| 1.0.0 | 2026-08-06 | 初始交付：52 测试 + 10 评测 + 7 指标 |
| 1.1.0 | 2026-08-07 | 规格 §七/§八/§九 差距补齐（本会话）：mineral-evidence schema、hashcheck/report 工具、扁平业务字段、跨模态冲突检测、spec-9 必测、skill.yaml 注册修复 |
| 1.1.1 | 2026-08-07 | 两轮对抗审查修复：融合双计数、spectra_parse 自检、未解释峰、重叠报告、诊断带共现组、bridge_evidence 填充、self_check 一致性 |

## 3. 文件清单（最终）

```
skills/micp-mineral-phase-interpreter/
├── SKILL.md                        # 触发/边界/流程/认识论/错误码/停止规则
├── skill.yaml                      # 机器元数据（registry 合规:usable=true）
├── README.md                       # 维护者文档
├── CHANGELOG.md                    # 版本记录（1.0.0→1.1.1）
├── DELIVERY_REPORT.md              # 本报告
├── schemas/
│   ├── input.schema.json           # 输入契约
│   ├── output.schema.json          # 输出契约（含扁平业务字段）
│   └── mineral-evidence.schema.json# 单条矿物证据契约
├── prompts/system.md               # 最小系统提示词
├── tools/mmpi_cli.py               # CLI 入口（stdin/stdout,离线）
├── tools/mmpi/                     # 领域核心（12 模块,纯 stdlib+numpy/scipy）
│   ├── minerals.py                 # 矿物相参考知识库（唯一事实源+诊断带）
│   ├── errors.py                   # OMM-E### 错误码体系
│   ├── models.py                   # 契约类型
│   ├── validate.py                 # 自包含 JSON Schema 校验器
│   ├── xrd.py                      # XRD 峰匹配/背景估计/置信度分级
│   ├── sem.py                      # SEM 颗粒统计/尺度校准/分割审计
│   ├── spectra.py                  # EDS/FTIR/Raman/TGA 解析
│   ├── fuse.py                     # 多模态融合与置信度分级
│   ├── audit.py                    # 自检 + 硬性规则 + 认识论核查
│   ├── hashcheck.py                # SHA-256 图像完整性 + 防篡改哈希链
│   ├── report.py                   # 结构化报告生成器（含 ASCII 峰图）
│   └── service.py                  # action 分派 + 输出封套装配
├── tests/                          # 89 测试
│   ├── unit/test_unit.py           #   29
│   ├── unit/test_additions_v11.py  #   20
│   ├── integration/                #    7
│   ├── failure/                    #   17
│   └── regression/                 #   16
├── evals/                          # 10 用例 + 7 指标 + runner
├── examples/                       # 4 个可运行示例（含 bootstrap_full）
├── references/sources.md           # 领域来源与实现依据
└── audit/                          # 自举日志 + Red Team 审查结果
```

## 4. Skill 输入输出契约

**输入**（`schemas/input.schema.json`，缺字段返回 BLOCKED + 获取方式）：`contract_version, task_id, project_id, request, action, skill_version, timestamp`（必需）+ `samples[], thresholds, evidence_refs, data_refs, upstream_outputs, human_approval_state, dry_run, verify_refs, candidate_output, results`（可选）。

**输出**（`schemas/output.schema.json`）：19 个封套字段 + 扁平业务字段（`candidate_phases / confirmed_phases / rejected_phases / unexplained_features / reflection_overlaps / morphology / spatial_distribution / bridge_evidence`）。

**status 枚举**：SUCCESS / PARTIAL / BLOCKED / FAILED / NEED_ADDITIONAL_SKILL / HUMAN_APPROVAL_REQUIRED。
**认识论标签**：OBSERVED / REPORTED / CALCULATED / INFERRED / HYPOTHESIS / RECOMMENDATION。

## 5. 工具清单

| 工具 | 用途 | 关键特性 |
|---|---|---|
| `interpret.phases` | 全流程多模态解释 | 四级区分、扁平字段、冲突检测、接触比估算 |
| `tools.xrd_match` | XRD 峰匹配 | d-间距主指纹、背景滚动百分位、可评估峰评分、vaterite 区间覆盖、单峰禁 identified |
| `tools.sem_stats` | SEM 颗粒统计 | 像素↔微米、样本量阈值、非代表外推警告 |
| `tools.spectra_parse` | EDS/FTIR/Raman/TGA 解析 | 证据边界显式化（EDS 只证明含 Ca） |
| `tools.fuse` | 多模态融合 | 诊断带共现组佐证、confirmed/likely/candidate/weak 分级、XRD 单模态封顶 |
| `tools.audit_image` | 图像处理审计 | ImageAuditLog 参数全记录 |
| `tools.image_hash` | 图像完整性 | SHA-256 + 期望哈希比对 + 防篡改哈希链（写盘需批准） |
| `tools.report` | 分析报告 | 结论/证据/不确定性/风险 + ASCII XRD 峰图 |
| `tools.validate` / `tools.self_check` | 契约校验/自检 | 与活体路径一致的 context 派生 |

## 6. 真实执行过的测试和结果

- **单元测试**（`tests/unit`）：49 通过（29 原 + 20 新增 hashcheck/report/扁平字段）。
- **集成测试**（`tests/integration`）：7 通过。经真实 CLI subprocess。
- **失败测试**（`tests/failure`）：17 通过（10 原 + 7 spec-9 必测）。
- **回归测试**（`tests/regression`）：16 通过（含两轮对抗审查修复的 10 个回归 + 6 个原回归）。
- **合计 89 通过**（`python -m pytest tests -q`）。
- **评测**（`evals/run.py`）：**10/10 用例通过，7/7 指标达标**（M1 结构化输出 1.0、M2 工具真实调用 1.0、M3 可追溯 1.0、M4 缺失输入识别 1.0、M5 对抗拦截 1.0、M6 重复一致 1.0、M7 恢复时间达标）。
- 示例：4 个全部可运行且通过 schema + 自检。

## 7. 规格 §九 十项必测覆盖

| # | 必测 | 覆盖位置 |
|---|---|---|
| 1 | XRD 峰重叠 | eval-04 + `reflection_overlaps`（aragonite 3.273 vs vaterite 3.29）+ 回归测试 |
| 2 | 仅单个候选峰 | `test_single_candidate_peak_not_overclaimed`（单峰禁 identified） |
| 3 | 方解石+球霰石混合相 | `test_calcite_vaterite_mixture_detects_both` |
| 4 | SEM 单局部视野 | eval-08 + `test_sem_stats_basic`（样本量警告） |
| 5 | 图像缺尺度尺 | `test_missing_scale_bar_flagged_uncalibrated` |
| 6 | XRD 与 FTIR 冲突 | `test_xrd_ftir_conflict_surfaces_candidates_not_certainty` |
| 7 | CaCO3 高但接触沉淀少 | `test_high_caco3_low_contact_precipitation` |
| 8 | 原始/处理图像哈希检查 | `tests/unit/test_additions_v11.py`（hashcheck 篡改检出 + 链校验） |
| 9 | 不相关矿物数据 | `test_unrelated_mineral_input_no_fabrication`（FeS2 → 无碳酸钙伪造） |
| 10 | 数据库不可用降级 | `test_database_unavailable_degrades`（OMM-E204） |

## 8. 自举验证（本会话执行）

`audit/bootstrap_log.json` 记录 4 步全链路：
1. **interpret.phases**：bootstrap_full.json（calcite+vaterite 混合 + SEM 30 颗粒 + EDS + TGA + FTIR）→ `SUCCESS`，`confirmed=['vaterite']`，`candidate=['calcite','aragonite']`，`rejected=['acc']`，自检通过。
2. **tools.report**：从封套生成报告 → winner vaterite，ASCII 峰图。
3. **tools.validate**：封套校验 `valid=true`。
4. **tools.self_check**：复检通过（修复一致性 bug 后）。

**自举发现并修复的真实缺陷**：
- `sem_stats` 被 `env["results"]` 整块覆盖 → bridge_evidence 恒空 → 局部变量累积修复。
- `tools.self_check` 复检路径无 context → 含内联样本封套误报 no_fabrication → 派生 context 修复。

## 9. Red Team 对抗审查（本会话执行）

`audit/redteam_audit.json` 记录 6 项攻击面复测，**全部 PASS**：
1. 候选相未误写确认相（XRD id + 仅共享带 → 封顶 candidate）。
2. 局部图像未外推整体（样本量不足警告）。
3. 峰重叠显式报告（reflection_overlaps）。
4. 数据库不可用拒绝（OMM-E204，不伪造匹配）。
5. 晶桥工程贡献不替代力学验证（`engineering_contribution_claimed=false`）。
6. 多模态强佐证才 confirmed（vaterite confirmed 需 XRD primary + FTIR 745 + EDS + TGA）。

并行对抗审查实例另复现并修复 4 阻断 + 3 次要缺陷（详见 CHANGELOG 1.1.1），全部有回归测试锁定。

## 10. Router 注册结果（实测）

```
bun tools/bin/osr.ts registry
  micp-mineral-phase-interpreter  usable=True  manifest_valid=True  version=1.1.1  network=False
  caps=['mineral_phase','characterization','evidence_fusion','uncertainty_management']
  inputs_required=['task_id','project_id','request','context','evidence_refs','data_refs','upstream_outputs']
bun tools/bin/osr.ts route --input ...    # 请求含"XRD/方解石/球霰石/SEM 形貌"
  status=SUCCESS  已路由组合: micp-mineral-phase-interpreter (锚定,评分 6.00)
cross-domain:  mineral_phase + geotechnical → sequential 组合路由成功
```

planner.ts `DOMAIN_MAP` 的 `mineral_phase` token（`矿物相|calcite|方解石|矿相|vaterite|球霰石|aragonite|文石`）与本 skill.yaml 的 `capabilities: [mineral_phase,...]` 精确匹配。

## 11. 调用示例

```bash
# 完整多模态解释
python tools/mmpi_cli.py < examples/bootstrap_full.json
# 单点 XRD 匹配
python tools/mmpi_cli.py < examples/xrd_match_calcite.json
# 单张 SEM 边界案例
python tools/mmpi_cli.py < examples/single_sem_boundary.json
# 图像哈希校验（规格 §九 test #8）
python tools/mmpi_cli.py < <(echo '{"...action":"tools.image_hash",...}')
# 测试与评测
python -m pytest tests -q
python evals/run.py
```

## 12. 尚未关闭的风险和限制

- **vaterite 逐峰强度近似**：ICDD 付费墙，逐峰强度来自二手汇编；匹配以 d-间距为主，勿依赖单一主峰。
- **RRUFF vaterite 样品号未确认**：Raman 参考仅列一般波段。
- **图像分割为轻量实现**：不分离接触晶体、不做 watershed；结果标注为估计并经审计记录；`audit_image` 离线不支持内联位图（真实分割需文件路径）。
- **TGA/FTIR 晶型区分力有限**：TGA 不能独立区分三晶型；FTIR 共享带不计佐证（诊断带共现组已收敛）。
- **接触比估算为几何近似**：仅基于颗粒质心距离，不分离接触晶体；晶桥有效性必须力学验证。
- **AMCSD 条目未验证**：不使用，以 COD 替代。

## 13. 后续演进建议

1. 支持真实 XRD 文件解析（`.xy/.xrdml/.raw`）替代内联数组（现为 OMM-E204 明确拒绝路径，预留）。
2. 接入 ICDD 实测峰强库或 COD CIF 计算峰，替换二手强度汇编。
3. 增加 Rietveld/PONKCS 定量接口（引 Chung 1974、Scarlett & Madsen 2006）。
4. 图像分割升级（watershed 分离接触晶体），保留审计链。
5. 与 `micp-geotechnical-performance` 建立晶桥→强度的上游证据契约（`bridge_evidence.engineering_contribution_claimed` 现恒为 false 待力学验证）。

---

**完成定义已达**：Skill 已被 OpenCode 加载（SKILL.md frontmatter 合规）、可被调用（CLI 可装载）、被审计（自检+审计日志）、通过验收（89 测试 + 10 评测 + 7 指标 + 自举 + 对抗审查）、Router 已注册 `usable=true` 并成功路由。
