

--- 来源: ZIP_README.md ---

# micp-data-analyst — 这是什么包

**用途**：Obsidian Plan（Panshi 磐石）研究系统的受治理专业 Skill——「MICP Data Analyst｜数据清洗、统计推断与可视化」。它把 MICP 实验/模拟数据转化为可追溯清洗、统计推断、效应量评估、不确定性量化与工程可视化，并严格遵守认识论标签与伪重复纪律。

**版本**：1.0.0 · 交付日期：2026-08-06 · 许可证：MIT

## 这个 zip 包含什么

完整的 Skill 工程包（35 个文件，已通过全部验收）：

| 内容 | 说明 |
|---|---|
| `SKILL.md` | OpenCode 可加载入口（frontmatter name/description）+ 7 正触发/4 反触发/4 边界 + 流程 + 错误码 + 版本策略 |
| `skill.yaml` | 机器可读清单（OSR 注册表用）：能力、单位、权限、network:false、risk_tier |
| `prompts/system.md` | 最小系统提示词（身份/边界/认识论/停止规则/MICP 守则） |
| `schemas/` | 严格输入/输出契约（draft 2020-12，additionalProperties:false） |
| `tools/micp/` | 纯 Python 3.10+ 标准库工具（cli.py 入口：service/qc/stats/validate），离线、确定性、信封契约 |
| `tests/` | 38 个测试全部通过（pytest，离线） |
| `evals/` | 10 用例 × 7 性能指标全 PASS（run_evals.py）+ 5 场景自举测试（run_bootstrap.py） |
| `examples/` | 3 个可运行示例 |
| `references/sources.md` | 方法学与 MICP 领域来源、访问日期、局限 |
| `CHANGELOG.md` | 版本记录与策略 |
| `DELIVERY_REPORT.md` | 完整交付报告（验收状态/工具/测试/自举/风险/演进建议） |

## 怎么用

```bash
# 解压到仓库 Skill 根目录
cd opencode-src/opencode-dev/skills/
unzip micp-data-analyst-skill-v1.0.0.zip

# 完整管线（伪重复检测 + 统计 + 效应量 + 工程判定）
cd micp-data-analyst
python tools/micp/cli.py service < examples/01-clean-infer.json

# 测试与评测（全部离线）
python -m pytest tests/
python evals/run_evals.py
python evals/bootstrap/run_bootstrap.py
```

要求：Python ≥ 3.10（无第三方依赖，纯标准库）。

## 验收状态

- ✅ 38/38 单元/集成/失败/回归测试
- ✅ 7/7 评测指标（结构化输出通过率、工具真实调用率、证据可追溯率、缺失输入识别率、对抗拦截率、重复一致性）
- ✅ 5/5 自举测试（伪重复、显著但微小效应、异常值敏感性、重复一致性、对抗审查）
- ✅ Obsidian Skill Router 注册表扫描 `usable=true`
- ✅ ruff 静态检查全绿

详见包内 `DELIVERY_REPORT.md`。
