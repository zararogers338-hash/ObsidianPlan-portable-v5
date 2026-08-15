# CHANGELOG

## 1.0.1 — 2026-08-07

**三方审查修复**（Red Team / Environment Auditor / Decision Gate，全部阻断项已修）：

### 安全语义
- **阶段门修复**：当前门按实际数据评估（此前恒 BLOCKED）；门阻塞 → 状态降为 `PARTIAL`，
  不再对超压/氨氮超限计划报 SUCCESS。
- **NH4-N 保守计量**：按注入尿素计（2 NH4-N/尿素），不再低估 1/转化率；
  eff=0.12 时氨氮标记从假安全修正为 8.3× 超限。
- **中央现场审批门**：`handle()` 对所有动作强制六项审批，封死 11 个动作的绕过路径。
- **监测停工信号** → 状态 `PARTIAL`（不再 SUCCESS）。
- **缺氨氮限值**不再静默伪造 50 mg/L；`limit_missing`/`limit_status` 明确标记。
- **地下水羽流**读数（`groundwater_nh4`/`groundwater_ec`）→ 停工+围堵。

### 数值正确性
- 反算注入流量传入 material_balance/schedule（时长不再为 0）。
- 调度停留时间 = `len(phases)-1` 间隙（此前 2× 且含幻影相位）。
- tracer 零注入浓度/NaN → 诚实判定，不崩溃。
- 均匀性随尺度衰减（pilot 0 / metre .15 / site .30 / field .45）。

### 测试
- `tests/test_review_fixes.py`：16 项回归锁定全部修复。
- 81 pytest 全绿；10 eval 全绿；7 指标全绿。

---

## 1.0.0 — 2026-08-07

**初始交付**：MICP 注入设计与工程尺度放大器。

### 核心能力
- 实验室→中试→米级→场地→现场 逐级放大管线（`action=scaleup`）。
- 相似性矩阵与**不可相似因素清单**（浓度/流速/轮次绝不按体积线性放大）。
- 关键无量纲参数：Péclet、Damköhler、Ca 数、反应时间/输运时间关系。
- 质量平衡：孔隙体积、菌液/胶结液体积、尿素/钙摩尔、CaCO₃、NH₄⁺。
- 恒流/恒压边界检查、注入压力 vs 地层允许压力/水力劈裂判据。
- 注入布局（井网/分区）、注入调度（顺序/脉冲/停留/轮次/冲洗）。
- 监测计划（逐参数位置/频率/设备/阈值/报警/停工/保存）与实时报警模块。
- 堵塞风险（入口堵塞/优先流）、示踪突破分析、均匀性指标。
- 阶段门决策模板 + 停工/回退条件。
- 现场施工强制 `HUMAN_APPROVAL_REQUIRED` + 六项审批清单。

### 契约与工程包
- `schemas/`：input / output / injection-plan / monitoring-plan 四份 JSON Schema。
- 统一输出信封：基础 17 字段 + 领域 12 字段（scale_level … environmental_requirements）。
- 错误码 `MSI-E101…E802`；认识论标签 6 种；版本门 major==1。
- `skill.yaml` capabilities 含裸 token `scaleup`，适配 obsidian-skill-router registry。

### 工具
- `tools/scaleup.py`：stdin/stdout 入口，信封 `{ok,tool,version,result|error}`，exit 0/2/3/4。
- `tools/msi/`：纯 Python 计算内核（stdlib，scipy/numpy 可选增强）。

### 测试与评测
- pytest 测试：单元/集成/失败/回归 + Router 注册集成（bun）。
- 强制 10 场景：5cm→1m 柱、米级→场地、恒流vs恒压、非均质双层、注入口堵塞、超压、氨氮超标、优先流旁路、缺渗透率 BLOCKED、监测触发停工回退。
- eval 7 指标：结构化输出/真实调用/可追溯/缺失识别/对抗拦截/重复一致/恢复轮次。
- 自举：实验室柱试→米级试验完整放大案例（真实调用全部工具）。

### 注册
- `obsidian-skill-router` registry 扫描 `skills/**/SKILL.md` 命中，`usable=true`。
- `planner.ts` DOMAIN_MAP 已含 `scaleup` token 映射，可被路由覆盖。
- **Router 注册集成（2026-08-07）**：扩展现有 `scaleup` DOMAIN_MAP 正则，覆盖
  `注浆|grouting|质量平衡|注入压力|监测计划|米级试验|场地试验|井网|示踪|停工`，
  使注浆设计/注入设计类请求正确路由到本 Skill（此前会误路由到 literature-scout）。
  Router 自身 90 测试全绿。
