# micp-modeling-optimizer

MICP 机理建模、参数反演与多目标优化器（Obsidian Plan / Panshi 受治理能力，v1.0.0）。

对 MICP / biocementation 任务提供**经过验证的**定量建模工具链：

- **机理模型构建**：尿素水解动力学（Michaelis–Menten / 一阶）、CaCO3 沉淀动力学（限制性反应物 / 过饱和度驱动）、生物活性衰减（一阶）、孔隙率–渗透率演化（Kozeny–Carman / Verma–Pruess / 幂律）、反应–运移耦合。
- **参数反演**：多起点最小二乘（scipy least_squares 或 stdlib Nelder–Mead 回退）、参数边界、留出/交叉验证、残差诊断、Fisher 信息 + 相关性可识别性分析、profile likelihood。
- **全局敏感性**：Sobol'（Saltelli 2002 采样）一阶/总阶指数；Morris 初筛。
- **DOE 与响应面**：全因子 / CCD / Box–Behnken / LHS 生成；二次响应面 OLS 拟合 + 站稳点 + 推荐下一步实验。
- **贝叶斯优化**：EGO（Jones 1998），GP 平方指数核 + 期望改进（EI）采集。
- **多目标优化**：NSGA-II（Deb 2002），Pareto 前沿 + knee 点 + Monte-Carlo 鲁棒性分析。
- **不确定性**：Monte-Carlo 传播（均匀 / 截断正态），分位数 + 收敛诊断。
- **守恒与数值自检**：6 项化学计量残差；有限性 / 孔隙率界 / 非负性；网格与时间步敏感性。

## 模型目的必须先锁定

`model_specification.purpose` ∈ `EXPLANATION | PREDICTION | CONTROL | OPTIMIZATION | SCALE_UP | PARAMETER_INFERENCE`。
不得把解释模型伪装成预测模型；拟合效果好 ≠ 现场预测有效。缺失目的 / 边界条件 / 参数来源 → **MODEL_BLOCKED**（MMO-E102，逐字段指引）。

## 快速开始

```bash
# 求解一个尿素水解 + 沉淀动力学模型
python tools/modeling.py < examples/01-solve.json

# 参数反演（合成数据）+ 可识别性 + 留出验证
python tools/modeling.py < examples/02-fit.json

# 全管线（solve → fit → sensitivity → multiobjective → robustness → uq）
python tools/modeling.py < examples/03-analyze.json

# 单目标贝叶斯优化
python tools/modeling.py < examples/04-optimize-single.json

# 多目标 NSGA-II
python tools/modeling.py < examples/05-multiobjective.json

# 仅校验输入（dry-run 门）
python tools/modeling.py < examples/06-validate.json
```

stdin = 一个 JSON 对象（`schemas/input.schema.json`）；stdout = 一个 JSON 对象（`schemas/output.schema.json`）；进度写 stderr。exit 0 = 已产出信封（`status` 字段承载结果），2 = 载荷损坏/契约违规，3 = 依赖缺失，4 = 引擎故障。

## 工程包结构

```
SKILL.md                  # 加载契约 + 触发词 + 专业规则
skill.yaml                # OSR registry 清单（capabilities 含裸 token "modeling"）
manifest.json             # 机器清单
README.md                 # 本文件
CHANGELOG.md
prompts/system.md         # 角色提示词
schemas/
  input.schema.json
  output.schema.json
  model-spec.schema.json
  optimization-result.schema.json
tools/
  modeling.py             # stdin/stdout CLI（唯一触碰 stdio 的文件）
  micp/                   # 纯 Python 工具模块
    _common.py  errors.py  kinetics.py  optimizer.py  sensitivity.py
    doe.py  bayesopt.py  multiobjective.py  uncertainty.py
    checks.py  modelspec.py  reporting.py  validate.py  service.py
tests/                    # pytest（10 项强制验收测试 + 单元/集成/失败/回归/router 集成）
evals/                    # cases.yaml + run_evals.py + metrics.md + results/
examples/                 # 可运行的示例载荷（必须真实可跑）
references/sources.md     # 公式与参数的权威来源
work/                     # 自举脚本与对抗测试
audit/                    # 自举产物
```

## 公式与参数来源

所有方程按参考文献原样实现，来源见 `references/sources.md`：

- 尿素水解：Lauchnor et al. 2015（整细胞动力学 K_m=305 mmol/L，一阶拟合 R²=0.99）；Hommel et al. 2015 修订 MICP 模型。
- 沉淀：Palandri & Kharaka 2004 速率定律（PHREEQC MICP 模型采用，k1=1.55e-6 mol m⁻² s⁻¹）；限制性反应物一阶（OPM 姊妹求解器同款）。
- 渗透率–孔隙率：Ebigbo et al. 2012 / Hommel et al. 2015 的 Kozeny–Carman 与 Verma–Pruess（φ_crit=0.108）。
- 化学计量：1 尿素 → 2 NH4+ + 1 碳酸盐；方解石摩尔质量 100.0869 g/mol。

## 与姊妹 Skill 的分工

| 本 Skill | 姊妹 Skill |
|---|---|
| 机理建模 / 反演 / 优化 | `micp-porous-media-transport` 做一维反应–运移求解与无量纲分析 |
| 多目标 Pareto 权衡 | `obsidian-experiment-designer` 做样本量/功效与实验方案 |
| 拟合 + 留出验证 | `micp-data-analyst` 做统计推断 / 效应量 / 数据清洗 |
| 参数来源核查 | `micp-literature-scout` 做文献检索 |

需要协作时返回 `NEED_ADDITIONAL_SKILL`，绝不直接调用其他 Skill。

## 测试与评测

```bash
python -m pytest tests/ -q          # 全部测试（含 bun 驱动的 router 集成，缺 bun 自动跳过）
python evals/run_evals.py           # 7 项指标评测，结果写 evals/results/latest.json
```

10 项强制验收测试（spec §九）：

1. 合成数据反演已知参数（k_ure / k_pre 回收）。
2. 两个高度相关参数 → 识别不可辨识（Fisher 相关 > 0.99）。
3. 同一数据既拟合又验证 → 被阻止（MMO-E101/E102）。
4. 违反质量守恒的模型 → PARTIAL + MMO-E403。
5. 数值不稳定模型 → PARTIAL + MMO-E404。
6. 网格 / 时间步敏感性测试。
7. 单目标与多目标结果比较。
8. 训练场景表现好但留出场景失败 → 过拟合警告。
9. 缺少边界条件 → MODEL_BLOCKED（MMO-E102 + missing_inputs）。
10. 固定种子后重复运行结果一致（M6）。

## 已知限制

- 可识别性为**局部**（Fisher 信息）；profile likelihood 覆盖单参数。
- Sobol' 为点估计无置信区间；代价 N×(d+2)，大 N 前建议 Morris 初筛。
- 内置校准模型当前为 `kinetic_urea`（尿素 + 钙 + 沉淀 + 衰减）；用户自定义模型需代码扩展。
- 多目标优化为 NSGA-II 近似前沿，非精确 Pareto 集；3+ 目标时注意多样性退化。

## License

MIT（项目约定，见仓库根 LICENSE）。
