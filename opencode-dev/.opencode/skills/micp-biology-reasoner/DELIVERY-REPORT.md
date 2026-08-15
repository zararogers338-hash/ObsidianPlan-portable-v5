# micp-biology-reasoner 交付报告

日期：2026-08-06 · skill_version **0.1.0** · contract_version **1.0** · 位置 `.opencode/skills/micp-biology-reasoner`

## 1. 仓库与标准识别结果

- 真实工程仓库：`Desktop/opencode-src/opencode-dev`（OpenCode monorepo 的 OBSIDIAN 改造版，非 git 仓库）。
- **加载契约（原生）**：OpenCode loader 扫描 `{skill,skills}/**/SKILL.md`，frontmatter 须含 `name` + `description`（在 `packages/opencode/src/skill/index.ts` 验证）。
- **工程包约定（项目自定义）**：以 `obsidian-state-manager`（Python，最完整）为模板——`skill.yaml / schemas / prompts / tools / tests / evals / examples / references / CHANGELOG.md`，统一输出封套 12 字段 + 6 认识论标签 + `{缩写}-E###` 错误码。
- **Router 注册（实测发现）**：`obsidian-skill-router/tools/osr/registry.ts` 的 `indexRegistry` 动态索引 `skills/**`，`validateManifest` 要求 `dependencies` 等 8 个键为字符串数组、`version` 为 X.Y.Z。**仓库所有现有 skill 的 `dependencies` 都是对象形式，导致 `usable:false`；本 skill 是当前唯一 `usable:true` 的**。`planner.ts` 已内置 `biology` 能力 token（匹配 `菌株|细菌|微生物|酶活|urease|脲酶|生物过程`），本 skill 声明 `capabilities: ["biology"]` 后可被路由。

## 2. 新增与修改文件清单

**新增 41 个文件**（全部位于 `skills/micp-biology-reasoner/`）：

| 类别 | 文件 |
|---|---|
| 清单 | `SKILL.md`、`skill.yaml`、`README.md`、`CHANGELOG.md`、`.gitignore` |
| 契约 | `schemas/input.schema.json`、`schemas/output.schema.json`（draft-07，additionalProperties:false） |
| 提示词 | `prompts/system.md` |
| 工具 | `tools/micp_bio_reasoner.py`（CLI）+ `tools/micp_bio/{__init__,errors,_common,units,kinetics,analysis,validate,service}.py` |
| 测试 | `tests/{conftest,test_unit,test_integration,test_failure,test_router_integration}.py` |
| 评测 | `evals/{cases.yaml,run.py,metrics.py}` + `evals/results/latest.json` |
| 示例 | `examples/0{1,2,3}-*.json` + `examples/{README.md,run-examples.sh}` |
| 依据 | `references/sources.md`、`references/bootstrap-log.md`、`references/bootstrap-cases/`（4 用例输入+输出） |

## 3. 输入输出契约

- **输入**：`contract_version`（主版本 `1`）、`task_id`、`project_id`、`request`、`action`（analyze/compare/assess/convert/evaluate）、`skill_version`、`timestamp`；领域负载 `strain/culture/conditions/attachments/treatment/baseline/metric_query/records`。缺失关键字段 → BLOCKED + 逐项说明缺失字段、为何关键、如何获得。
- **输出**：统一封套 `status/summary/findings/assumptions/evidence_used/uncertainty/risks/artifacts/requested_next_skills/validation/provenance/errors`；status 枚举含 SUCCESS/PARTIAL/BLOCKED/FAILED/NEED_ADDITIONAL_SKILL/HUMAN_APPROVAL_REQUIRED；findings 带认识论标签。
- **错误码**：MBR-E101…E802（E2xx 证据/单位、E204 OD 冒充活性、E205 非尿素路径套尿素模型、E206 凭菌名推断、E7xx 自检、E8xx 版本）。

## 4. 所造工具及其用途

| 工具 | 用途 | 依赖 |
|---|---|---|
| `tools/micp_bio_reasoner.py` | CLI 入口（stdin JSON → stdout JSON，离线） | 标准库 |
| `errors.py` | MBR-E### 错误码体系（code/retryable/detail/human） | 标准库 |
| `_common.py` | 数值校验：NaN/Inf/范围/分数/单位必填（MBR-E302/E203/E204） | 标准库 |
| `units.py` | 活性归一化（U/mL、U/mL/OD600、U/g CDW、U/CFU）、OD600→CFU（仅显式标定）、量纲检查 | 标准库 |
| `kinetics.py` | 一阶附着/失活拟合、Logistic 生长拟合、敏感性弹性（中心差分） | numpy/scipy |
| `analysis.py` | 批次比较（同 OD 不同活性）、群落策略评估、矛盾数据指标甄别（中英关键词）、盐度证据分级、尿素→铵质量守恒 | 标准库 |
| `validate.py` | input/output schema 校验（jsonschema + 内建回退） | jsonschema（可选） |
| `service.py` | 动作分派、输出封套、自检、契约版本门 | 标准库 |

工具工程要求全部满足：复用成熟依赖（numpy/scipy 仅拟合）、超时（CLI subprocess 均有 timeout）、错误分类（统一 MbrError）、日志（stderr 诊断）、离线降级（jsonschema 缺失时用内建回退）、数值检查（_common.py 统一入口）、无密钥、dry-run 语义（`evaluate`/`assess` 只读）、类型标注+注释。

## 5. 真实执行过的测试与结果

| 套件 | 命令 | 结果 |
|---|---|---|
| 单元/集成/失败 | `python -m pytest tests/ -q` | **59 passed** |
| Router 集成 | `tests/test_router_integration.py`（bun 驱动真实 planner） | **1 passed**（registry usable:true + 路由命中） |
| 评测 | `python evals/run.py` | **12/12 全过，7 项指标全过** |
| 示例 | `bash examples/run-examples.sh` | **3 个示例全部 SUCCESS** |
| 静态检查 | `python -m pyflakes ...` | 清理后仅 1 处必要 `import jsonschema`（可用性检测） |
| 编译 | `python -m compileall -q tools tests evals` | 通过 |

7 项最小性能指标实测：M1 结构化输出通过率 **1.000**（≥0.95）、M2 工具真实调用率 **1.000**（=1）、M3 可追溯率 **1.000**（≥0.9）、M4 缺失输入识别率 **1.000**（=1）、M5 对抗拦截率 **1.000**（=1）、M6 重复一致性 **1.000**（=1）、M7 平均失败恢复时间 **768ms**（≤2000ms）。

## 6. 自举测试中发现的问题及修复

4 个自举用例（spec §八.1–4）+ 5 项红队攻击（§八.6）全部通过。发现并修复：

1. **schema 缺口**：`analyze` 的 `records` 字段是矛盾数据检测核心输入但未声明 → 补入 input schema。
2. **中文缺口**：`analyze_contradictory_data` 只匹配英文 "activity"，中文"酶活/活性/比活"声称不命中 → 修复为多语言关键词，补单元测试锁定。
3. **Router 集成缺口**：`skill.yaml` 的 `dependencies` 对象形式触发 `usable:false` → 改字符串数组 + `dependencies_detail`；并声明 `capabilities/inputs_required/domain_keywords` 使生物请求可路由。

完整记录见 `references/bootstrap-log.md`。

## 7. 尚未关闭的风险与限制

1. **敏感性分析为局部线性占位**：`evaluate` 的 `sensitivity` 用 `linear_scale` 标量模型估计弹性；真实模型函数需调用方经工具接口注入（JSON 无法携带函数）。
2. **高盐结论依赖待核验文献**：`references/sources.md` 条目 #10 的具体盐度数值未读到原文，相关结论标记 REPORTED 且注明需核验。
3. **附着/失活为一阶近似**：非线性吸附需扩展（sources.md #11 注明）。
4. **Router 生态不一致**：仓库其余 9 个 skill 因 manifest 格式均 `usable:false`；本 skill 虽可路由，但跨能力组合（如 chemistry+biology）可能因伙伴 skill 不可用而退化为 capability_gap。建议后续统一修复各 skill.yaml 的 `dependencies` 形式。
5. **尿素水解模型边界**：`non_ureolytic_pathway` 字段已入 schema 并触发 MBR-E205，但非尿素路径自身的建模（反硝化、甲烷氧化）不在本 skill 能力内，需 `requested_next_skills` 转交。

## 8. 调用示例

```bash
# 比较两个批次（同 OD 不同活性）
python tools/micp_bio_reasoner.py < examples/01-compare-batches.json

# 高盐菌株适配性（证据分级）
python tools/micp_bio_reasoner.py < examples/02-salinity-assessment.json

# 生物刺激 vs 强化策略
python tools/micp_bio_reasoner.py < examples/03-treatment-strategy.json
```

Router 端到端（已验证）：`buildPlan` 将"评估菌株在不同培养条件下的脲酶活性与比活，并比较两个批次的酶活"路由到 `micp-biology-reasoner`。

## 9. 版本号与后续演进建议

- 当前版本 **0.1.0**（初始交付）。schema 新增 `records/culture.id/culture.name/conditions.measured_at_salinity/metric_query 扩展` 均为向后兼容可选字段，不升主版本。
- **演进建议**：
  1. 修复仓库其余 skill 的 `skill.yaml` `dependencies` 形式，统一 `usable:true`，释放跨能力组合路由。
  2. 敏感性分析接入真实模型函数接口（如 `metric_query.sensitivity.model_ref` 引用上游拟合产物）。
  3. 补 `micp-ureolysis-chemistry` 与 `micp-porous-media-transport` 的跨 skill 联合评测（本 skill 已在 `requested_next_skills` 预留协作钩子）。
  4. 引入正式 CI（本仓库无 CI 基础设施，已用 pytest + bun + 脚本建立最小可行版）。
