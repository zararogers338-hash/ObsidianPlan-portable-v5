# Examples

本目录的示例是**真实可运行**的（不是空壳）：直接喂给 CLI 即可复现评测场景与自举决策。

## 运行方式

```bash
# 完整决策门评估（PILOT_READY → DEPLOYABLE 自举决策）
python tools/odg/cli.py service < examples/example-bootstrap.json

# 各子命令
python tools/odg/cli.py score      < examples/example-bootstrap.json   # 12 维度评分
python tools/odg/cli.py blockers   < examples/example-bootstrap.json   # 阻断检查
python tools/odg/cli.py mcda       < examples/example-bootstrap.json   # 多准则分析
python tools/odg/cli.py risk       < examples/example-bootstrap.json   # 风险-收益矩阵
python tools/odg/cli.py memo       < examples/example-bootstrap.json   # Decision Memo
python tools/odg/cli.py transition < examples/example-bootstrap.json   # 状态转换请求
python tools/odg/cli.py expiry     < examples/example-bootstrap.json   # 到期复审
python tools/odg/cli.py validate   < examples/example-bootstrap.json   # schema 校验
```

## 文件

- `example-bootstrap.json` — 完整模拟 MICP 道路加固部署项目，包含 Mission Lock、
  Evidence Cards、证据综合、Hypothesis Card、实验结果（强度/氨排放 + QC + 统计）、
  模型验证、中试放大方案（监测/停工/回退）、环境审计、LCA、Reproducibility、
  Red Team 报告、法规状态、人类审批状态。期望输出：`SUCCESS / PASS / DEPLOYABLE`。

## 期望输出（example-bootstrap.json）

```
status:            SUCCESS
decision:          PASS
current_state:     PILOT_READY
proposed_state:    DEPLOYABLE
blocking_items:    []
```
