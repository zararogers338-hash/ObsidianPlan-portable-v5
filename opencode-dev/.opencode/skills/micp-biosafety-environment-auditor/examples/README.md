# micp-biosafety-environment-auditor 示例

每个示例都是**真实可运行**的完整 CLI 载荷。运行：

```bash
# 运行一个示例并把输出写盘
python tools/mbs_auditor.py --output /tmp/ex1.out.json < examples/01-lab-sand-column-audit.json
# 或直接查看输出
python tools/mbs_auditor.py < examples/01-lab-sand-column-audit.json
```

## 示例清单

| # | 文件 | action | 预期结果 |
|---|---|---|---|
| 1 | `01-lab-sand-column-audit.json` | `audit` | 密闭实验室砂柱：`SUCCESS`（菌株已核验、氮平衡闭合、法规分类已核验、无审批门） |
| 2 | `02-field-injection-audit.json` | `audit` | 现场注浆+地下水接触+未鉴定菌株：`HUMAN_APPROVAL_REQUIRED`（触发多项审批门） |
| 3 | `03-strain-verify.json` | `strain_verify` | 已保藏菌株身份核验 + 生物安全分级 |

## 一键验证

```bash
./examples/run-examples.sh
```
