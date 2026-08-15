# micp-instrumentation-qc — 安装包使用说明

**本 zip 是什么**:MICP Instrumentation QC 技能的完整工程包(Skill v1.0.0)。
**它是干嘛用的**:为 MICP(微生物诱导碳酸盐沉淀)研究中的仪器、标定、采样链与
数据质量控制提供可调用、可测试、可审计的工具链——校准曲线与不确定度、控制图与
漂移检测、样品链与条码、原始/派生数据哈希与审计日志、仪器数据格式标准化。

## 快速安装

```bash
# 1. 解压后把整个 micp-instrumentation-qc 目录放到仓库的 skills 目录
#    (Obsidian/OpenCode 工程的加载目录)
cp -r micp-instrumentation-qc <repo>/.opencode/skills/

# 2. 验证
cd <repo>/.opencode/skills/micp-instrumentation-qc
python -m pytest tests/            # 应输出 75 passed
python evals/run_evals.py          # 应输出 12/12 passed
```

## 调用

输入输出为 JSON envelope(契约见 `schemas/`)。工具读 stdin、写 stdout:

```bash
python tools/cli.py check-self                     # 自检
cat examples/example-1-qc-plan.json | python tools/cli.py qc   # 生成 QC 计划
cat examples/example-2-calibration-drift.json | python tools/cli.py qc  # 标定+漂移检查
cat examples/example-3-integrity.json | python tools/cli.py integrity   # 数据完整性
```

子命令: `qc | calibration | control | sample-chain | integrity | adapters | check-self`。

## 关键保证

- **原始数据不可变**:任何修正只能生成派生数据;原始内容 SHA-256 哈希 + 追加式
  审计日志,篡改立即被发现。
- **QC 失败不静默进入分析**:OUT_OF_CONTROL/OVER_RANGE/SATURATION/DRIFT/重复编号/
  时间戳错位都会标记 `retest_items` + `analysis_restrictions`。
- **默认安全**:数据写入需 `human_approval_state == approved`;工具全部离线、
  确定性、纯 Python 标准库,零第三方运行时依赖。
- **认识论标签**:所有陈述必须标注 OBSERVED / REPORTED / CALCULATED / INFERRED /
  HYPOTHESIS / RECOMMENDATION,禁止把推断/假设写成观测。

## 目录

```
micp-instrumentation-qc/
├── SKILL.md / manifest.json / README.md / CHANGELOG.md
├── schemas/     输入/输出 JSON Schema 契约
├── prompts/     system.md 最小系统提示词
├── tools/       7 个 Python 工具(纯 stdlib)
├── tests/       75 个单元/集成/schema/回归测试
├── evals/       12 个评测用例 + run_evals.py + metrics.md
├── examples/    3 个可运行示例
├── references/  领域依据(sources.md)+ 可更新知识(instrument-domain.md)
└── audit/       自举测试记录与输入
```

详见解压后的 `README.md` 与 `DELIVERY-REPORT.md`。
