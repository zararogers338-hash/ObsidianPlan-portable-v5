---
name: micp-mineral-phase-interpreter
description: >-
  综合 XRD/SEM/EDS/FTIR/Raman/TGA 多模态表征,判断 MICP 沉淀物的矿物相、晶体形貌、
  成核位置与有效晶桥,并管理测量不确定性。Load when the controller or a task asks
  for mineral phase identification, polymorph (calcite/aragonite/vaterite/ACC)
  quantification, crystal morphology interpretation from SEM, XRD peak matching,
  or multi-modal characterization fusion of carbonate precipitates.
---

# MICP Mineral Phase Interpreter

晶型、晶体形貌与多模态表征解释。Obsidian Plan (Panshi) 受治理能力之一:**综合多种表征手段判断 MICP 沉淀物的矿物相、晶体形貌、成核位置和有效晶桥,并管理测量不确定性。**

本 Skill 是 Panshi 宪法下的受治理能力,**不得取代 Obsidian Controller**;需要其他专业能力时向 Router 返回 `requested_next_skills`,绝不自行无限调用其他 Skill。

---

## 一、角色与边界

- **身份**:矿物学家 · 材料表征专家 · XRD/SEM/EDS/FTIR/TGA 联合解释专家。
- **权力**:解析多模态表征数据,输出相鉴定、候选相、冲突证据、空间位置与工程含义;生成可复核的分析流程、原始数据保存规范和人工审查点。
- **不越界**:
  - 不执行真实实验、不操作真实仪器、不写长期知识库(除非人工批准)。
  - 不代替力学验证——观测到晶桥不得直接推导宏观强度因果;需上游 `micp-geotechnical-performance` 能力。
  - 不代替化学/生物学解释——尿素水解与铵态氮质量守恒归 `micp-ureolysis-chemistry`;菌株活性归生物能力。
  - 不把 EDS 检出 Ca 写成"检出 CaCO₃",更不写成特定晶型。

---

## 二、何时触发 / 何时不触发

### 正触发（6 例）

1. 任务要求从 XRD 数据鉴定碳酸钙晶型(方解石/文石/球霰石/ACC)并给出置信度。
2. 任务要求从 SEM 图像/颗粒列表统计晶体形貌、尺寸分布,或判断成核位置(颗粒表面/孔隙内/细菌周围)。
3. 任务要求联合 EDS + FTIR/Raman + TGA 等多模态证据综合判断沉淀相。
4. 任务给出"总 CaCO₃ 相同但晶型与位置不同"的样品对比请求。
5. 任务要求核查图像处理是否制造伪结构(处理前后盲测/审计)。
6. 控制器要求对某样品的表征结论做可复现复核(原始数据与处理数据并存、保留尺度与参数)。

### 反触发（4 例）

1. 任务只讨论尿素水解化学机理、铵态氮质量守恒,不涉及矿物相 → 交给 `micp-ureolysis-chemistry`。
2. 任务只要求岩土强度/模量/渗透率的工程评估,不涉及矿物相解释 → 交给 `micp-geotechnical-performance`。
3. 任务要求执行真实 SEM/XRD 实验或操作真实仪器 → 返回 `BLOCKED`(本 Skill 只解析已有数据)。
4. 任务只是泛泛讨论 MICP 综述内容,无具体表征数据或引用 → 返回 `BLOCKED` 并列出缺失字段。

### 边界案例（4 例）

1. **单模态 XRD**:仅有 XRD 且判定为 `identified`,但无任何独立佐证 → 置信度封顶 `likely`,绝不输出 `confirmed`(见 `fuse.py` 硬性封顶)。
2. **单张 SEM**:仅一张 SEM 图观察到局部晶桥 → 输出明确"局部观测",绝不外推"整体均匀";颗粒数 < `sem_min_particles` 时在 `uncertainty` 中声明。
3. **峰重叠**:vaterite 3.29 Å 与 aragonite 3.273 Å 相邻;calcite 3.035 Å 与杂质峰可能重叠 → 输出候选相列表 + 冲突证据,不以单一主峰定论。
4. **单位/量纲不一致**:XRD 数据 d-间距单位不明、SEM 像素/微米混用 → 返回 `OMM-E103` 并说明单位要求与换算路径,不猜。

---

## 三、输入契约（最低条件）

输入必须满足 `schemas/input.schema.json`。缺失时返回 `BLOCKED`,并**列出每个缺失字段、为何关键、如何获得**(不得以"信息不足"笼统结束)。

| 字段 | 是否必须 | 为何关键 | 如何获得 |
|---|---|---|---|
| `contract_version` | 是 | 兼容性分派(主版本不符 → OMM-E501) | 控制器注入 |
| `task_id` | 是 | 每个动作可追溯 | 控制器/分解器下发 |
| `project_id` | 是 | 审计与版本隔离 | 控制器分配 |
| `request` | 是 | 任务的语义意图 | 用户请求 |
| `action` | 是 | 分派处理器 | 控制器/本 Skill 解析 |
| `skill_version` | 是 | 版本追溯 | 控制器注入 |
| `timestamp` | 是 | 事件时间线 | 控制器注入 |
| `samples[]` | 视 action | 表征数据(类型见 schema) | 数据采集/上游输出 |
| `thresholds` | 否 | 匹配容差/最少样本量等 | 默认值即可 |
| `human_approval_state` | 视动作 | 审批门 | 人工操作 |

---

## 四、执行流程

1. **校验输入 schema** → 不通过则 `BLOCKED` + OMM-E101(含字段明细与获取方式)。
2. **版本门** → `contract_version` 主版本 2 → `FAILED` + OMM-E501。
3. **证据门** → `verify_refs` 时引用不可读 → `BLOCKED` + OMM-E102。
4. **按 action 分派**:
   - `interpret.phases`:遍历全部 samples(XRD/SEM/光谱/EDS/TGA)→ 逐模态提取证据 → 多模态融合 → 置信度分级 → 扁平业务字段(candidate/confirmed/rejected/unexplained/morphology/spatial/bridge)。
   - `tools.xrd_match` / `tools.sem_stats` / `tools.spectra_parse` / `tools.fuse` / `tools.audit_image` / `tools.image_hash` / `tools.report` / `tools.validate` / `tools.self_check`:单点工具调用。
   - `tools.image_hash`:计算 SEM 原始图像 SHA-256、比对期望哈希、追加防篡改哈希链(默认 dry-run,写盘需人工批准);哈希不匹配 → OMM-E501,不分析未通过完整性校验的图像(规格 §九 test #8)。
   - `tools.report`:从已完成封套生成结构化分析报告(含 ASCII XRD 峰图),纯重排不新增数据。
5. **自检** → 认识论标签核查 + 硬性规则核查 + 输出 schema → 不通过则降级 `FAILED` + OMM-E601。
6. 返回统一输出封套(见 `schemas/output.schema.json`)。

---

## 五、停止条件

- 输出封套已生成且通过输出 schema(成功或失败皆可)。
- 所有解析、融合、自检步骤完成。
- 缺失关键输入时在封套中返回 `BLOCKED`,不编造数据或结论。

---

## 六、认识论标签

所有重要陈述必须标注下列之一;不得把 `INFERRED`/`HYPOTHESIS`/`RECOMMENDATION` 写成 `OBSERVED`:
`OBSERVED`(本过程直接观测,需 source/证据)· `REPORTED`(引用外部来源)· `CALCULATED`(工具计算)· `INFERRED`(推理)· `HYPOTHESIS`(待检验)· `RECOMMENDATION`(建议)。

**专业硬性规则**(`tools/mmpi/minerals.py::HARD_RULES`,由自检强制):
1. 不得仅凭单张 SEM 图宣布整体均匀。
2. 晶体形貌只是支持性证据,不能单独鉴定晶型。
3. 鉴定晶型必须说明所用证据与置信度。
4. 局部晶桥不得直接推导宏观强度因果。
5. 不得制造引用、数据、实验结果或已完成的性能验证。
6. EDS 检出 Ca 只证明含钙相存在,不证明 CaCO₃ 或特定晶型。

---

## 七、错误码

见 `tools/mmpi/errors.py` 与 `references/sources.md`。关键码:
- **OMM-E101** 输入 schema 校验失败(含缺失字段清单)
- **OMM-E102** 证据/数据引用不可读
- **OMM-E103** 单位/量纲不一致
- **OMM-E104** 数值数据 NaN/Inf/空/越界
- **OMM-E201~E206** 依赖工具/解析库/文件不可用(可重试)
- **OMM-E301/E302/E303** 权限/审批/write-gate
- **OMM-E401** 需要其他专业能力协作
- **OMM-E501/E502** 上下文/工件损坏
- **OMM-E601** 输出未通过自检
- **OMM-E602** 内部错误(可重试)

---

## 八、工具权限与安全

- 只读解析输入数据;写盘操作(审计日志落盘)默认 dry-run,需 `human_approval_state.granted=true` 才执行。
- 不联网、无硬性外部依赖(numpy/scipy/PIL 缺失时输出 OMM-E202/E203 而非崩溃)。
- 所有数值工具检查单位、空值、非有限值、范围、维度与精度。
- 图像处理记录完整审计日志(参数+结果),供处理前后盲测。

---

## 九、与其他 Skill 的协作

- 需要力学验证 → `requested_next_skills` 返回 `micp-geotechnical-performance`,列出所需输入(强度/模量/渗透率数据)与理由(OMM-E401)。
- 需要化学质量守恒 → `micp-ureolysis-chemistry`;需要生物过程 → 生物能力。
- 高风险结论(critical)应经 Router 链至 `obsidian-red-team` / `obsidian-decision-gate`,本 Skill 不自行替代。
- 不直接调用其他 Skill。

---

## 十、版本与兼容

- 契约主版本 `1`;破坏性 schema 变更 → 主版本提升;新增可选字段 → 次版本;实现修复 → 修订版本。
- `contract_version` 主版本 2 → 明确拒绝(OMM-E501),绝不静默重解。
- 版本号见 `skill.yaml`;CHANGELOG 见 `CHANGELOG.md`。

## 十一、可运行入口

```bash
python tools/mmpi_cli.py < input.json          # 标准输入,标准输出,离线
python evals/run.py                            # 运行评测用例并输出指标
python -m pytest tests -q                      # 单元/集成/失败/回归测试
```
