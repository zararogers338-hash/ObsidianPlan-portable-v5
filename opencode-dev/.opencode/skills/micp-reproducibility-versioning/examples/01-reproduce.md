# 示例 1 — 完整复现（reproduce）

对 MICP UCS 实验做完整复现：创建 manifest、锁定环境、记录输入、执行、保存产物、重跑比较。
输入 `root` 指向含 `data/raw/ucs.csv`（只读）的项目树。

```json
{
  "task_id": "ex-01",
  "project_id": "panshi-ucs-demo",
  "request": "完整复现 UCS 分析：创建 reproduction manifest、锁定依赖环境、记录输入输出哈希、重跑比较",
  "action": "reproduce",
  "root": "C:/projects/ucs-experiment",
  "skill_version": "1.0.0",
  "controller_version": "obsidian-ctl-0.1.0",
  "timestamp": "2026-08-07T10:00:00Z",
  "risk_level": "medium",
  "human_approval_state": "not_required",
  "seed_policy": "reuse",
  "random_seed": 20260807,
  "parameters": {"curing_temp_c": 25, "reagent_mm": 0.5, "batch": "B01"},
  "commands": [
    {"id": "compute-means", "cmd": "python analysis/compute_means.py",
     "cwd": ".", "expected_outputs": ["data/processed/summary.csv"]},
    {"id": "render-chart", "cmd": "python analysis/render_chart.py",
     "cwd": ".", "expected_outputs": ["reports/ucs_chart.png"]}
  ],
  "constraints": {"timeout_sec": 300}
}
```

预期结果：
- `status: SUCCESS`
- `reproduction_manifest`：记录 git/fingerprint 身份、skill/controller/宪法/schema 版本、依赖锁、OS、运行时、工具、种子、参数摘要、输入/输出哈希
- `data_lineage`：raw → 命令 → 产物 的完整跳链
- `reproducibility_checks` 全部通过
- manifest 落盘 `provenance/reproduction-manifest.json`，归档于 `provenance/manifests/`
- provenance 事件追加至 `provenance/provenance.log`
- 再次运行同一请求：`differences` 为 identical，`identical_to_previous: true`

> 若 `data/raw` 下存在可写文件 → `BLOCKED` + `MRV-E501`（原始数据写保护）。
