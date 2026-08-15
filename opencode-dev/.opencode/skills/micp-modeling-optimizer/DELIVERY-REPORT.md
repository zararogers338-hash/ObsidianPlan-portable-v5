# micp-modeling-optimizer — DELIVERY-REPORT

Skill `micp-modeling-optimizer` v1.0.0（MICP 机理建模、参数反演与多目标优化器）交付于
2026-08-07。

## 1. 仓库与标准识别结果

真实工程仓库：`.opencode`。OpenCode loader 契约
`{skill,skills}/**/SKILL.md` + frontmatter `name`+`description` 已验证。工程包约定以
`micp-data-analyst` / `micp-porous-media-transport` 为模板：skill.yaml / schemas /
prompts / tools / tests / evals / examples / references / CHANGELOG.md，统一输出封套
（contract_version/skill/skill_version/status/summary/.../errors）+ 6 认识论标签 +
`{前缀}-E###` 错误码（本 skill 用 `MMO-E1xx..E8xx`）。

Router 注册实测：`skills/obsidian-skill-router/tools/osr/registry.ts` 的
`validateManifest`（capabilities/inputs_required/outputs/tool_permissions/writes/
stop_conditions/domain_keywords/dependencies **均须字符串数组**）；`planner.ts`
DOMAIN_MAP 将 `建模|数值模拟|数值|numerical|simulation|优化|optimiz` 映射为裸能力
`modeling`。本 skill 的 `skill.yaml` 声明 `capabilities: ["modeling", ...]`，
`bun run indexRegistry` 实测 **usable=true, manifest_valid=true, issues=[]**，建模请求
`buildPlan` 直接路由命中。

## 2. 新增文件清单（41 个）

| 类别 | 文件 |
|---|---|
| 契约 | SKILL.md, skill.yaml, manifest.json, README.md, CHANGELOG.md, prompts/system.md |
| schemas | input.schema.json, output.schema.json, model-spec.schema.json, optimization-result.schema.json |
| tools | tools/modeling.py, tools/README.md, tools/micp/{_common,errors,kinetics,optimizer,sensitivity,doe,bayesopt,multiobjective,uncertainty,checks,modelspec,reporting,validate,service,__init__}.py |
| tests | conftest.py, test_acceptance.py, test_unit.py, test_integration.py, test_failure.py, test_regression.py |
| evals | cases.yaml, run_evals.py, metrics.py, metrics.md, results/latest.json |
| examples | 01-solve / 02-fit / 03-analyze / 04-optimize-single / 05-multiobjective / 06-validate + README |
| references | sources.md, bootstrap-log.md |
| work | run_bootstrap.py, red_team.py, bootstrap-cases/*, bootstrap-summary.json, redteam-summary.json |
| audit | bootstrap/ 产物 |

## 3. 输入输出契约

输入（input.schema.json）：`contract_version/task_id/project_id/request/action/
skill_version/controller_version/timestamp` 必填；`model_specification`（model-spec
schema）、`calibration`、`optimization`、`sensitivity`、`uncertainty`、`doe`、
`constraints`（含 `random_seed`）为领域负载。

输出（output.schema.json）：统一封套 12 字段 + `model_purpose/model_specification/
equations/parameters/parameter_sources/identifiability/calibration/sensitivity/
optimization_results/pareto_candidates/uncertainty_analysis/doe_report/
model_output/conservation/numerical/mass_balance`。status 枚举 6 态；BLOCKED 必须带
`missing_inputs`（逐字段指引）。错误码段位：E1xx 输入 / E2xx 证据单位 / E3xx 上下文 /
E4xx 数值 / E5xx 权限 / E6xx 下游 / E7xx 自检 / E8xx 版本。

## 4. 所造工具及其用途

| 模块 | 用途 | 依赖 |
|---|---|---|
| kinetics.py | 速率模型 + 闭式隐式欧拉求解器 + 质量平衡 | stdlib |
| optimizer.py | ODE、多起点最小二乘、Fisher/profile 可识别性、CV/留出 | stdlib/scipy |
| sensitivity.py | Sobol'(Saltelli 2002) + Morris | stdlib |
| doe.py | 全因子/CCD/Box-Behnken/LHS + 二次响应面 | stdlib |
| bayesopt.py | EGO（GP+EI）贝叶斯优化 | stdlib/numpy |
| multiobjective.py | NSGA-II + MC 鲁棒性 | stdlib |
| uncertainty.py | 种子化 MC UQ（均匀/截断正态） | stdlib |
| checks.py | 守恒 6 项 / 数值稳定 / 网格步长敏感 | stdlib |
| modelspec.py | 模型规范校验（MODEL_BLOCKED）/ 拟合政策 / 报告组装 | stdlib |
| reporting.py | 内联 SVG/HTML 可视化（离线） | stdlib |
| validate.py | JSON-Schema（jsonschema 或内置子集回退） | stdlib/jsonschema |
| service.py | action 分派 / 信封 / 自检 / 状态映射 | stdlib |
| modeling.py | stdin/stdout CLI | stdlib |

确定性：全部随机过程固定 seed；同输入逐字节一致（M6）。离线：numpy/scipy/jsonschema
为可选加速，均有标准库回退。

## 5. 真实执行过的测试与结果

| 套件 | 命令 | 结果 |
|---|---|---|
| 全部测试 | `python -m pytest tests/ -q` | **65 passed**（含 bun 驱动的 router 集成 1 passed） |
| 评测 | `python evals/run_evals.py` | 10/10 用例通过；M1–M7 全绿 |
| 自举 | `python work/run_bootstrap.py` | 5/5 SUCCESS（反演回收真参数） |
| 红队 | `python work/red_team.py` | 5/5 攻击被拦截 |
| 示例 | 6 个 examples 全部 | SUCCESS + schema True |
| Router | bun indexRegistry + buildPlan | usable=true；建模请求路由命中 |

M1=1.000 / M2=1.000 / M3=1.000 / M4=1.000 / M5=1.000 / M6=1.000 / M7≈309ms。

## 6. 自举测试中发现的问题及修复

见 `references/bootstrap-log.md`：批次质量平衡键、Fisher 闭包变量泄漏、NSGA-II rank
赋值、BLOCKED 信封缺 missing_inputs、YAML 科学计数法解析、model_purpose None、
过拟合阈值收紧。全部为真实缺陷，修复后全绿。

## 7. 尚未关闭的风险与限制

1. 可识别性为**局部**（Fisher 信息）；profile likelihood 覆盖单参数。
2. Sobol' 为点估计无置信区间；代价 N×(d+2)，大 N 前建议 Morris 初筛。
3. 内置校准模型当前为 `kinetic_urea`；用户自定义模型需代码扩展。
4. NSGA-II 为近似前沿；3+ 目标时多样性可能退化。
5. 沉淀 `saturation_driven` 采用固定 Ksp 简化；未做温度/离子强度修正。

## 8. 调用示例

```bash
cd skills/micp-modeling-optimizer
python tools/modeling.py < examples/01-solve.json
python tools/modeling.py < examples/03-analyze.json   # 全管线
python tools/modeling.py schema                        # 打印输入 schema
python tools/modeling.py selfcheck out.json            # 输出自检
```

Router 端到端已验证：`buildPlan` 对建模请求返回 SUCCESS 且 steps 含
`micp-modeling-optimizer`。

## 9. 版本号与后续演进建议

当前 1.0.0（contract major 1）。演进建议：PHREEQC 级地球化学耦合、温度/离子强度
Ksp 修正、profile-likelihood 多参数扩展、用户自定义模型注册接口。
