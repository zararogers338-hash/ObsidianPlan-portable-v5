============================================================================
 obsidian-decision-gate v1.0.0 — Skill 工程包 (黑曜石证据成熟度与工程决策门)
============================================================================

这个 zip 是 Obsidian Plan(黑曜石计划)研究工程下的受治理 Skill 工程包:

  obsidian-decision-gate
  Obsidian Decision Gate｜黑曜石证据成熟度与工程决策门

用途:
  - 综合 Mission Lock 指标、Evidence Card、证据综合、Hypothesis Card、
    实验结果、数据 QC、统计、模型验证、岩土性能、工程放大方案、生物安全
    与环境审计、LCA 与成本、Reproducibility、Red Team 发现和人类审批状态
  - 决定研究路线进入 9 态状态体系之一:REJECTED / OPEN /
    EVIDENCE_GATHERING / SUPPORTED / VALIDATED / PILOT_READY /
    DEPLOYABLE / SUSPENDED / EXPIRED
  - 12 决策维度评分(最小维度门槛,非加权总分)
  - 13 条机器强制阻断规则 B1-B13;状态转换白名单(非法跳跃 ODG-E305 硬拒绝)
  - 人类审批门 B10(scope/revision 匹配,链上 APPROVAL_GRANTED)
  - 输出正式 Decision Memo 与状态转换请求(state-manager 执行)
  - 核心铁律:科学有效 ≠ 可工程部署;证据不足不得包装成"基本通过"

安装:
  - 复制 obsidian-decision-gate/ 目录到任意 OpenCode skill 发现路径:
      .opencode/skills/  (项目级)
      ~/.claude/skills/  (全局)
      skills/           (opencode-dev 仓库级)
  - 要求 python >= 3.10(jsonschema 可选,缺省带内建回退校验);全离线可运行。
  - Router 注册:obsidian-skill-router planner.ts 已预留 decision_gate 能力
    token,high/critical 风险强制 obsidian-red-team → obsidian-decision-gate
    审计链;注册表扫描 usable=true。

验收状态(v1.0.0, 2026-08-07):
  - 54 项 pytest 测试通过(12 强制场景 + 对抗复审 8 项 + 机器机制;
    Python 3.11/3.13 双版本验证)
  - 12 项评测用例全过,M1-M7 指标全部达阈值
  - 自举决策:PILOT_READY → DEPLOYABLE PASS/SUCCESS,12 维度全达标
  - 对抗复审 6 类失败模式攻击全防御(证据不足放行/过度保守/忽略成功指标/
    阻断遗漏/科学误当部署/绕过审批)
  - Router 集成 5/5 通过,全量 90 测试无回归

完整说明见包内 README.md 与 SKILL.md;交付报告见 DELIVERY-REPORT.md。
============================================================================
