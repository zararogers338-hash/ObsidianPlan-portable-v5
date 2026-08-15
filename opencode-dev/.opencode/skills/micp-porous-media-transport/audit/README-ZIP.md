# micp-porous-media-transport — Skill 交付包

**中文名称：MICP Porous Media Transport｜菌液、溶质、沉淀与堵塞耦合**

本压缩包是一个可直接装载、调用、测试、审计的 **Obsidian Plan（黑曜石计划 / Panshi 磐石）Skill 工程包**，按项目真实 Skill 标准交付（与 `obsidian-skill-router`、`obsidian-state-manager` 等已有 Skill 一致）。

## 它是干什么用的

分析 **MICP（微生物诱导碳酸钙沉淀）** 中细胞、尿素、钙离子与碳酸钙沉淀在多孔介质中的**迁移、反应、截留与渗透率演化**，并解释/预测**空间不均匀性**（入口堵塞、旁路流、渗透率—孔隙率关系）。

## 安装方法（放入仓库）

解压后把 `micp-porous-media-transport/` 目录放到仓库的 `skills/` 下（OpenCode 原生加载器按 `{skill,skills}/**/SKILL.md` 自动发现）：

```
opencode-dev/skills/micp-porous-media-transport/
```

## 快速验证

```bash
cd skills/micp-porous-media-transport
python tools/transport.py < examples/01-sand-column-analyze.json   # 正常模拟
python tools/transport.py < examples/02-inlet-clogging.json        # 入口堵塞
python tools/transport.py < examples/03-head-vs-flux.json          # 恒流 vs 恒压
python -m pytest tests/ -q                                         # 54 项测试
python evals/run.py --verbose                                      # 8 评测用例 + 7 项指标
```

## 包内容（标准 Skill 结构）

| 路径 | 内容 |
|---|---|
| `SKILL.md` | 触发/不触发/边界案例、能力边界、输入输出契约、错误码表、性能指标、版本策略 |
| `skill.yaml` | 机器可读清单（入口、依赖、权限、兼容性） |
| `schemas/input.schema.json` / `output.schema.json` | 严格输入/输出契约（draft 2020-12） |
| `prompts/system.md` | 最小系统提示词 |
| `tools/transport.py` + `tools/micp/` | CLI 适配器 + 求解器/校验器/无量纲/堵塞/守恒/日志 9 个模块 |
| `tests/` | 单元/集成/失败/回归共 54 项（pytest） |
| `evals/` | 8 个评测用例 + 7 项性能指标 |
| `examples/` | 3 个可运行示例 |
| `references/sources.md` | 领域依据（带证据等级，无伪造引用） |
| `CHANGELOG.md` | 版本记录 |

## 关键能力

- **1D 反应运移求解器**：迎风对流 + 中心弥散 + 尿素水解（Michaelis-Menten，隐式 Euler）+ 沉淀（限速反应物 1:1 消耗）+ Kozeny-Carman 孔隙率/渗透率反馈。
- **恒流 vs 恒压边界**：恒压逐时间步由入口渗透率重解 Darcy 速度，堵塞→流量骤降可见。
- **无量纲分析**：Pe / Da / rDa，输运/反应主导分类。
- **质量守恒**：尿素/钙/铵/碳酸盐化学计量守恒、网格敏感性、有限性与 CFL 检查。
- **MODEL_BLOCKED**：缺失孔隙率/流量等关键边界条件时返回 BLOCKED + 逐字段指引，绝不编造。
- **离线、确定性、纯 stdlib**，无联网依赖。

## 验收状态（2026-08-06）

- 测试：54/54 通过（单元 + 集成 + 失败 + 回归）。
- 评测：8/8 用例通过，7 项指标全部达标（结构化输出通过率 1.0、工具真实调用率 1.0、可追溯率 1.0、缺失输入识别率 1.0、对抗拦截率 1.0、重复一致性 1.0、恢复轮次 0）。
- 已通过 OpenCode 加载器契约检查（frontmatter name+description）。

## 版本与许可

- 版本：1.0.0；契约版本：1.0；MIT（项目仓库约定）。
- 维护：Panshi / Obsidian Plan。
