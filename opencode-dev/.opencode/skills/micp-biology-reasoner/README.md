# micp-biology-reasoner

**MICP Biology Reasoner｜菌株、生长、脲酶、附着与群落机制**

对 MICP 生物过程的**证据约束**机制推理能力：菌株来源与培养状态、生长曲线与酶活分析、单位转换与活性归一化、附着/失活动力学拟合、敏感性分析、纯培养 vs 原位刺激 vs 混合群落策略评估。本 Skill 是 Obsidian Plan（Panshi 磐石）MICP 能力族的一员。

## 一、安装

放到技能扫描根（本仓库为 `skills/`）下即可。OpenCode loader 通过 `SKILL.md` 的 frontmatter（`name` + `description`）发现；`obsidian-skill-router` 的 registry 索引器读取 `skill.yaml`（见 `../obsidian-skill-router/tools/osr/registry.ts` 的 `validateManifest`）。

依赖：`python3 >= 3.10`，`numpy` + `scipy`（动力学拟合），`jsonschema`（可选，缺失时用内建回退校验器），`pyyaml` + `pytest`（仅 evals/测试）。全部离线可用。

```bash
cd skills/micp-biology-reasoner
python -m pytest tests/ -q          # 57 个测试
python evals/run.py                 # 12 个评测用例 + 7 项指标
bash examples/run-examples.sh       # 3 个可运行示例
```

## 二、调用

CLI 契约：stdin 一个 JSON 输入对象 → stdout 一个 JSON 输出对象；stderr 仅诊断信息。

```bash
python tools/micp_bio_reasoner.py < examples/01-compare-batches.json
```

输入输出契约见 `schemas/`（draft-07，`additionalProperties: false`）。输入需含 `contract_version`（主版本 `1`）、`task_id`、`project_id`、`request`、`action`、`skill_version`、`timestamp`。动作枚举：`analyze` / `compare` / `assess` / `convert` / `evaluate`。

由 Controller / Router 调用时，走统一输出封套；需要其他能力时返回 `requested_next_skills`（如高危场景请求 `obsidian-env-biosafety-audit`），**绝不直接调用其他 Skill**。

## 三、能力边界

**能做**
- 区分 OD600 / CFU / 细胞干重 / 活细胞比例 / 脲酶活性 / 单位体积总活性，并拒绝无标定的互换算（`convert`）。
- 尿素型路径的活性归一化（U/mL、U/mL/OD600、U/g CDW、U/CFU）。
- 一阶附着/失活动力学与 Logistic 生长拟合（`evaluate` / `analyze`），参数敏感性（弹性）分析。
- 同 OD600 不同活性的批次比较，并给出"非组成型脲酶"机制解释。
- 纯培养 vs 原位刺激 vs 混合群落的机制评估，绑定文献证据。

**不做（边界）**
- 化学机理（尿素水解化学动力学、沉淀热力学）→ `micp-ureolysis-chemistry`
- 孔隙尺度运移/流动方程 → `micp-porous-media-transport`
- 矿物相鉴定 → `micp-mineral-phase-interpreter`
- 固化土力学性能 → `micp-geotechnical-performance`
- 生物安全终局结论 → 一律转交环境与生物安全审计 Skill
- 非尿素路径（反硝化、甲烷氧化、碳酸酐酶等）**不套用尿素水解模型**（MBR-E205）
- 凭菌名推断现场性能（MBR-E206）

## 四、错误码

完整清单见 `tools/micp_bio/errors.py`。关键码：

| 码 | 含义 | retryable |
|---|---|---|
| MBR-E101 | 输入 schema 不通过 | 否 |
| MBR-E102 | 必填字段缺失 | 否 |
| MBR-E201/E202 | 证据不可解析 / 不可核验 | 否/是 |
| MBR-E203 | 单位不一致或缺失 | 否 |
| MBR-E204 | OD600 冒充脲酶活性 | 否 |
| MBR-E205 | 非尿素路径套尿素模型 | 否 |
| MBR-E206 | 凭菌名推断现场性能 | 否 |
| MBR-E301/E302 | 上下文损坏 / 数值非有限 | 是/否 |
| MBR-E401/E402 | 工具不可用 / 超时 | 是 |
| MBR-E501/E502 | 权限不足 / 审批未完成 | 否 |
| MBR-E601/E602 | 下游能力缺失 / 上游契约不匹配 | 否 |
| MBR-E701/E702 | 输出 schema / 自检失败 | 否 |
| MBR-E801/E802 | 版本不支持 / 需迁移 | 否 |

## 五、版本兼容

- 输入/输出 schema 破坏性变更 → 主版本（`1.0.0 → 2.0.0`）。
- 新增可选字段 → 次版本。
- 修复实现而不改契约 → 修订版本。
- `skill_version` 不匹配/旧主版本输出 → 显式迁移或 `MBR-E802` 拒绝，绝不静默重解释。
- 当前 `contract_version`：`1.0`。

## 六、测试与评测

- `tests/`：单元（纯函数）、集成（真实 CLI）、失败/对抗（缺失、越界、非 JSON、schema 违规、OD 冒充活性、契约 v2）。
- `evals/cases.yaml`：12 个评测用例（正常/缺失/冲突/对抗/边界），经真实 CLI 执行。
- `evals/metrics.py`：7 项最小性能指标（M1 结构化输出通过率 ≥0.95、M2 工具真实调用率 =1、M3 可追溯率 ≥0.9、M4 缺失输入识别率 =1、M5 对抗拦截率 =1、M6 重复一致性 =1、M7 平均失败恢复时间 ≤2000ms）。结果写 `evals/results/latest.json`。

## 七、故障排除

| 现象 | 原因 | 处理 |
|---|---|---|
| `MBR-E101` + `Additional properties` | 输入含 schema 外字段 | 对照 `schemas/input.schema.json` 删减 |
| `MBR-E203` 活性无单位 | `urease_activity_unit` 缺失 | 补单位（U/mL / mM urea/min / mmol/L/h …） |
| `MBR-E204` OD 作单位 | 把 OD600 当活性单位 | 改为真实酶活单位 |
| `MBR-E205` 非尿素路径 | 对反硝化等套尿素模型 | 设置 `non_ureolytic_pathway` 并改用对应模型 |
| 拟合不收敛 | 数据点不足/退化 | 提供 ≥2 个配对点；检查数据是否单调合理 |

## 八、目录结构

```
skills/micp-biology-reasoner/
├── SKILL.md                 # 触发/边界、流程、错误码、停止条件
├── skill.yaml               # 机器可读 manifest（Router registry 校验）
├── README.md                # 本文档
├── schemas/                 # input/output JSON Schema（draft-07）
├── prompts/system.md        # 最小系统提示词
├── tools/
│   ├── micp_bio_reasoner.py # CLI 入口（stdin→stdout，离线）
│   └── micp_bio/
│       ├── errors.py        # MBR-E### 错误码体系
│       ├── _common.py       # 数值校验（NaN/Inf/范围/单位）
│       ├── units.py         # 活性归一化与单位转换
│       ├── kinetics.py      # 一阶/Logistic 拟合、敏感性弹性
│       ├── analysis.py      # 批次比较/群落/矛盾数据/盐度评估
│       ├── validate.py      # jsonschema + 内建回退
│       └── service.py       # 动作分派与输出封套
├── tests/                   # pytest：单元/集成/失败
├── evals/                   # cases.yaml + metrics.py + run.py
├── examples/                # 3 个可运行示例 + run-examples.sh
├── references/sources.md    # 领域来源与检索限制
└── CHANGELOG.md             # 版本记录
```
