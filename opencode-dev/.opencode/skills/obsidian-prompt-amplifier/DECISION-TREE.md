# Obsidian 调动决策树 — DECISION-TREE

> 第 25 号 `obsidian-prompt-amplifier` 的指挥逻辑。
> 决策树定义"AI 如何调动 25 个 Skill 组成的计算系统":什么条件下、按什么顺序、何时升级、何时停止。
> 一切以《Panshi Constitution v1.0》解释为准;本树不凌驾于宪法。

---

## 总览

```
NODE 0 入口判定
NODE 1 任务分类 + 宪法检查
NODE 2 复杂度评分 → 运行模式
NODE 3 泛化层主 Skill 激活(按分类)
NODE 4 审门映射(按产出类型强制)
NODE 5 专项层升级触发(执行中命中才拉)
NODE 6 循环与停止控制
NODE 7 状态落地
```

---

## NODE 0 — 入口判定

```
请求进入
├─ 非实质任务(闲聊/简单问答/非研究)→ RAPID_TRIAGE,直接答,不打机器
└─ 实质任务(研究/实验/数据/模型/工程/战略)→ 进入 NODE 1
```

**判定规则**: 任务需要检索、推理、设计、计算、评价、审查、决策中任意一项,即视为实质任务。

---

## NODE 1 — 任务分类 + 宪法检查

```
实质任务
├─ 任务分类(可多类):
│    literature / mechanism / experiment / data / model /
│    engineering / environment / strategy
├─ 宪法冲突检测:
│    命中"跳过红队/决策门/环境/批准""编造数据""把假设写成事实""直接部署"
│    → CONSTITUTIONAL_CONFLICT,退回修正,不采纳冲突部分
├─ 人类批准触发:
│    真实实验/现场部署/环境释放/危险化学品
│    → 标记 HUMAN_APPROVAL_REQUIRED(采纳强化提示词不豁免)
└─ 通过 → 进入 NODE 2
```

---

## NODE 2 — 复杂度评分 → 运行模式

按宪法附录 B 七维(学科/数据来源/风险/尺度/建模/决策影响/不确定性)各 0—3 分,总分 0—21。

| 总分 | 运行模式 | 子智能体规模 |
|---|---:|---:|
| 0—4 | `FOCUSED_RESEARCH` | 3—5 |
| 5—8 | `DEEP_RESEARCH` | 6—10 |
| 9—13 | `FULL_RESEARCH_CYCLE` | 11—17 |
| 14+ | `OBSIDIAN_TOTAL_MOBILIZATION` | 18—24 |

模式决定编组深度。≥ DEEP 必须过 Red Team + Decision Gate。

---

## NODE 3 — 泛化层主 Skill 激活(按分类)

12 泛化 Skill 承担标准研究循环。按分类激活主 Skill,不默认全部调用:

| 分类 | 激活的主 Skill | 说明 |
|---|---|---|
| `literature` | `micp-literature-scout` → `micp-evidence-extractor` | 检索 → 抽取,顺序执行 |
| `mechanism` | `micp-biology-reasoner` / `micp-ureolysis-chemistry` / `micp-porous-media-transport` | 按问题侧重点选 1—3 |
| `experiment` | `micp-experiment-designer` | 设计 → SOP |
| `data` | `micp-data-analyst` | 分析 |
| `model` | `micp-modeling-optimizer` | 建模 |
| `engineering` | `micp-geotechnical-performance` | 性能评价 |
| `environment` | `micp-biosafety-environment-auditor` | 环境审计 |
| `strategy` | `obsidian-mission-lock` + `obsidian-task-decomposer` | 定界 + 拆解 |

**固定顺序规则**:

- 任何模式先过 `obsidian-mission-lock`(定界);
- ≥ DEEP 模式加 `obsidian-task-decomposer`(拆解);
- 涉及实验 → 先 `micp-experiment-designer` 后 `micp-instrumentation-qc`;
- 涉及数据 → 先 `micp-instrumentation-qc` 后 `micp-data-analyst`(QC 先于分析);
- 涉及多来源证据 → 先 `micp-evidence-extractor` 后 `micp-evidence-synthesizer`;
- 建模型 → 先明确边界条件,缺边界返回 `MODEL_BLOCKED`。

---

## NODE 4 — 审门映射(按产出类型强制)

6 审 Skill 是门控,不是并列产出者。**任何正式产出按类型强制过门**,与复杂度分数无关(低复杂度产出的正式结论同样过门):

| 产出类型 | 强制审门 | 门控含义 |
|---|---|---|
| 科学结论(任何) | `obsidian-red-team` → `obsidian-decision-gate` | 反证通过 → 判状态 |
| 数据结论 | `micp-instrumentation-qc` 前置 → 再 `micp-data-analyst` | QC 失败数据不得进分析 |
| 多来源证据合并 | `micp-evidence-synthesizer` | 条件对齐、矛盾检测 |
| 声称"可复现/已验证" | `micp-reproducibility-versioning` | 哈希/Manifest/环境锁定 |
| 涉及工程/现场 | `micp-biosafety-environment-auditor` | 菌株/氨氮/废液/法规 |
| 涉及环境/低碳声明 | `micp-lca-technoeconomic` | 功能单位/系统边界/清单 |

**审门时序**:

```
产出 → (QC 若涉数据) → (Synthesizer 若合并证据) → (Environment 若涉工程/现场)
     → Red Team → 修 → 复验 → Decision Gate
```

Red Team 阻断时状态不得升级;Decision Gate 判 `REJECTED/OPEN/SUPPORTED/VALIDATED/PILOT_READY/DEPLOYABLE/SUSPENDED/EXPIRED`。

---

## NODE 5 — 专项层升级触发(执行中命中才拉)

6 专项 Skill 不是默认调用,是**执行中命中条件才升级**:

| 触发条件 | 升级调用 | 作用 |
|---|---|---|
| 多 Skill 协同 / 权限冲突 / `CAPABILITY_GAP` | `obsidian-skill-router` | 编组、权限、预算仲裁 |
| 长任务 / 上下文耗尽 / 进程中断 | `obsidian-state-manager` | 先 checkpoint 再恢复 |
| 写长期记忆 / 跨项目复用 | `micp-knowledge-graph-steward` | 实体/关系/证据边 |
| 出现 XRD / SEM / EDS 表征数据 | `micp-mineral-phase-interpreter` | 晶型/形貌多模态解释 |
| 实验室 → 现场外推 | `micp-scaleup-injection-engineer` | 相似矩阵/压力/井网/监测 |
| 成本 / 碳 / 资源比较 | `micp-lca-technoeconomic` | 功能单位/清单/敏感性 |

**升级规则**: 命中即拉,拉完仍须过 NODE 4 对应审门。专项层产出不得绕过审层。

---

## NODE 6 — 循环与停止控制

```
正式结论 → Red Team
├─ BLOCKING 发现 → 修复 → 复验
│    ├─ 复验通过 → Decision Gate
│    └─ 两轮无进展 → Decision Gate 降级(不得无限重试,宪法§65 每 Skill 重试≤2)
├─ 通过 → Decision Gate 判状态
└─ 低复杂度直接产出 → 仍过 Decision Gate(可不经 Red Team,视模式)
```

**停止条件(宪法 §66,命中任一即停或暂停)**:

- 目标已满足;
- 成功/失败阈值触发;
- 关键输入缺失;
- 人类批准缺失;
- 工具不可用且无可靠降级;
- 证据不足;
- 预算耗尽;
- 连续两轮无新增信息;
- 同一 Skill 重复失败;
- Red Team 发现阻断项;
- 环境/安全风险不可接受;
- 任务超出系统能力。

**停止时必须输出完整恢复点**(当前状态/已完成/未完成/已确认事实/未决冲突/下一步),不得只说"无法继续"。

---

## NODE 7 — 状态落地

```
过门结论
├─ 沉积 → micp-knowledge-graph-steward(实体/证据边,版本化)
├─ 归档 → micp-reproducibility-versioning(数据/代码/环境锁定)
├─ 失败 → Failure Ledger(宪法 §30:负结果必须记录)
└─ 报告 → 统一研究报告模板(宪法第十八编)
```

长期知识写入须满足:来源可追溯、单位明确、过 QC、过 Red Team、状态 ≥ `SUPPORTED`、人类批准。

---

## 与宪法对应关系

| 决策树节点 | 宪法依据 |
|---|---|
| NODE 0 入口判定 | §67 Step 1—2 |
| NODE 1 分类/宪法检查 | §67 Step 2、§72 |
| NODE 2 复杂度评分 | §9、附录 B |
| NODE 3 泛化层激活 | 附录 A、§49 |
| NODE 4 审门映射 | §11、§28、§29 |
| NODE 5 专项层升级 | §50 六小组、附录 F |
| NODE 6 循环停止 | §29、§65、§66 |
| NODE 7 状态落地 | §30、§62、附录 H |

---

## 最小可用子集(上下文受限时)

上下文有限时(宪法附录 L),决策树至少保留:

1. NODE 0(是否实质任务);
2. NODE 2(复杂度 → 模式);
3. NODE 4(审门映射——这是防越级的核心);
4. NODE 6 停止条件(防止失控)。

其余节点按任务动态装载。
