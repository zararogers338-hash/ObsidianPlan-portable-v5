# micp-experiment-designer

**MICP Experiment Designer | 可复现、可证伪的实验设计与 SOP**

将 Hypothesis Card(或结构化设计请求)转化为可执行、可复现、有对照、有统计效力、有停止条件的实验方案与 SOP,并输出机器可读信封供 Obsidian Controller / Router 消费。

- **仓库约定对齐**:本 skill 遵循 Obsidian Plan 自定义 Skill 工程包约定(以 `obsidian-mission-lock` 为基准,见 `references/sources.md` S15)。此约定为项目自定义标准,非 OpenCode 官方强制格式。
- **运行时**:Python ≥ 3.10(纯标准库,可选 scipy 增强),离线、确定性(相同输入 → 相同输出)。

---

## 安装与调用

### 1. 放置目录

将整个 `micp-experiment-designer/` 目录放入任一处被发现的位置(OpenCode skill 发现逻辑,见 `references/sources.md` S1):

```
.opencode/skills/micp-experiment-designer/
```

或项目级 `skills/` 目录。

### 2. 由控制器/Router 调用

Controller 以 JSON 信封调用,stdin 传入、stdout 返回:

```bash
cat <<'EOF' | python skills/micp-experiment-designer/tools/cli.py
{
  "tool": "doe_power",
  "payload": {
    "design": {
      "kind": "two_group_means",
      "delta": 1.5,
      "sigma": 2.0,
      "alpha": 0.05,
      "two_sided": true
    }
  }
}
EOF
```

或直接运行单个工具:

```bash
python skills/micp-experiment-designer/tools/doe_power.py < design.json
```

### 3. 作为 Skill agent 被装载

OpenCode agent 按 `name` 加载本 skill(`SKILL.md` 正文注入对话);同目录附属文件以绝对路径列出。`SKILL.md` 的 Procedure 段驱动流程:真实运行 5 个工具,禁止口头假装。

---

## 工具清单

| 工具 | 入口 | 用途 |
|---|---|---|
| `doe_power` | `tools/doe_power.py` | DOE 与样本量/功效:两样本 t、两比例、ANOVA;有限预算下给出可达功效与取舍 |
| `randomizer` | `tools/randomizer.py` | 可复现随机化(complete/blocked)+ 实验编号生成(种子记录、校验和) |
| `quantity_calc` | `tools/quantity_calc.py` | 材料/试剂用量与单位计算(摩尔质量、质量浓度、稀释 C₁V₁=C₂V₂) |
| `sop_check` | `tools/sop_check.py` | SOP 生成 + 结构一致性检查(对照/重复/端点/排除/停止/MICP 铵守恒) |
| `preregister` | `tools/preregister.py` | 预注册摘要 + 原始数据表模板 |
| `validate` | `tools/validate.py` | 输入/输出 schema 校验(自检 + 预检) |

所有工具共用 `tools/_common.py` 的信封协议(exit 0/2/3/4),数值经 `unit_validate.py` 量纲校验。

---

## 目录结构

```
micp-experiment-designer/
├── SKILL.md                 ← 身份、触发条件、流程、错误码、工具权限、性能指标、版本策略
├── manifest.json            ← 机器可读元数据(版本、入口、工具、权限、离线/确定性)
├── README.md                ← 本文
├── CHANGELOG.md             ← 版本记录
├── schemas/
│   ├── input.schema.json    ← 控制器输入信封契约
│   └── output.schema.json   ← 输出信封契约(状态、设计、SOP、预注册、校验、出处、错误)
├── prompts/
│   └── system.md            ← 最小系统提示词(不复制 Panshi 宪法)
├── tools/
│   ├── cli.py               ← 统一入口
│   ├── _common.py           ← 信封协议、数值守卫、错误分类
│   ├── unit_validate.py     ← 量纲引擎(SI + MICP 单位)
│   ├── jsonschema_subset.py ← 最小 JSON-Schema(draft 2020-12)子集校验器
│   ├── doe_power.py
│   ├── randomizer.py
│   ├── quantity_calc.py
│   ├── sop_check.py
│   ├── preregister.py
│   └── validate.py
├── evals/
│   ├── cases.yaml           ← ≥8 评测用例(正常/缺失/冲突/对抗/边界)
│   └── metrics.md           ← 最小性能指标与测量方法
├── examples/                ← 可运行输入信封
├── references/
│   └── sources.md           ← 外部依据(访问日期、用途、关键限制)
└── audit/                   ← 自测日志(运行后生成)
```

---

## 运行测试

```bash
cd skills/micp-experiment-designer

# 单元测试(含失败/回归)
python -m unittest discover -s tests -p "test_*.py" -v

# 自举评测(用 SKILL.md + tools 真实执行 4 个自举测试)
python evals/run_evals.py

# 手工冒烟
echo '{"tool":"doe_power","payload":{"design":{"kind":"two_group_means","delta":1.5,"sigma":2.0}}}' | python tools/cli.py
```

测试全部离线运行;不需要 scipy 也能通过(数值路径自动降级为文档化的正态近似)。

---

## 版本兼容策略

- **主版本**:输入/输出 schema 破坏性变更。旧版本输出无迁移即拒绝(`OED-E1010`)。
- **次版本**:新增可选字段,旧消费者仍可接受。
- **修订版本**:修复实现但不改契约。

## 已知限制 / 故障排除

- **scipy 未安装**:`doe_power` 的两样本/两比例走正态近似(文档化);ANOVA 需要 scipy(非中心 F 分布),未安装时报 `OED-E1004`(可重试),建议 `pip install scipy`。
- **单位表**:`unit_validate.py` 的白名单只覆盖 MICP/DOE 常用单位;未知单位报 `E_UNIT_UNKNOWN`,不静默假设。需要新增单位时编辑 `_UNITS` 表并补测试。
- **样板温度**:`C`/`K` 不可用于复合单位表达式(仿射尺度不满足乘法),这是有意为之。
- **确定性**:工具为纯函数,不含时间/熵;时间戳仅出现在 `preregister` 的 `generated_at`(作为字段,不影响确定性契约字段之外的行为)。
- **不联网**:所有测试离线。网络来源仅用于 `references/sources.md` 文档依据,不参与运行时行为。


---

> 原 `README-先读我.md` 已归档至 [`audit/README-先读我.md`](audit/README-先读我.md)。
