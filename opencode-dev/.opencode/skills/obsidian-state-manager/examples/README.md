# 调用示例

本目录每个示例都是**可直接运行**的完整输入 JSON；用以下命令执行：

```bash
python tools/state_manager.py --store "$(mktemp -d)" < examples/01-init.json
```

每个示例的 `"project_id"` 各自独立，可单独运行；示例之间不共享状态。

## 01-init.json — 初始化一个研究流

创建一个状态流，落到 OPEN。返回 `status=SUCCESS`、`state=OPEN`、`provenance.head_revision=1`。

## 02-lifecycle.json — 从 OPEN 推进到 HYPOTHESIS_BUILDING

演示证据守卫：先 `state.transition` 到 `SCOPED`、`EVIDENCE_GATHERING`，再 `evidence.attach` 登记一条带 `sha256` 的证据，随后 `state.transition` 到 `HYPOTHESIS_BUILDING`。若在无证据时尝试，会得到 `OSM-E306 GUARD_UNSATISFIED`。

## 03-recover.json — 中断恢复（断点续跑）

先 `task.checkpoint` 登记已完成工作项，然后用 `task.resume_plan` 提交候选工作；内容未变的工作项会被判定为 `already_done` 而不重复执行（验收门槛 §九.3）。
