

--- 来源: README_USE_THIS.txt ---

============================================================================
 obsidian-red-team v1.0.0 — Skill 工程包 (Obsidian Red Team 科学反证与对抗审查器)
============================================================================

这个 zip 是 Obsidian Plan(黑曜石计划)研究工程下的受治理 Skill 工程包:

  obsidian-red-team
  黑曜石科学反证与对抗审查器(强制审计 Skill)

用途(全系统强制对抗审查门):
  - 对结论做十维主动攻击:来源真实性/认识论越级/数值与单位/实验设计/
    统计分析/MICP 专业机制/模型/工程放大/环境与安全/决策
  - 输出五级严重度发现(INFO/MINOR/MAJOR/CRITICAL/BLOCKING),每条含
    具体证据、最强反例、可执行修复、可复验验证方法
  - 存在 BLOCKING 时阻止状态升级:SUPPORTED→VALIDATED→PILOT_READY→DEPLOYABLE
  - 只提交发现与判定,绝不修改主结论或数据(只读,network:false)

安装:
  - 复制 obsidian-red-team/ 目录到任意 OpenCode skill 发现路径:
      skills/          (仓库根,Router 动态扫描)
      .opencode/skills/ (项目级)
      ~/.claude/skills/ (全局)
  - 要求 python >= 3.10(纯标准库,无第三方依赖);离线可运行。
  - Router 集成:skill.yaml capabilities 含裸 token `red_team`,risk_tier=critical;
    高风险(high/critical)请求由 obsidian-skill-router 强制
    obsidian-red-team → obsidian-decision-gate 审计链。
  - State Manager 集成:UNDER_REVIEW→VALIDATED 与 VALIDATED→DEPLOYABLE
    已增加 requires_review_pass 守卫(本 Skill verdict=fail 时机器拒绝升级)。

验收状态(v1.0.0, 2026-08-07):
  - 68 项单元/集成/失败/回归/自举测试通过
  - 15 项强制对抗案例全部被拦截(伪造论文/DOI不匹配/OD600当脲酶/CaCO3当晶桥/
    伪重复/缺对照/p显著效应极小/违反质量守恒/同数据校准验证/小柱推现场/
    强度升渗透降/氨氮超限/法规未核验/阻断未关闭升级/越权写知识库)
  - 7 项性能指标(M1-M7)全部达阈值,其中对抗拦截率 M5=1.0
  - Router registry usable=true;State Manager 升级门 3/3 集成测试通过
  - 自举:审查 micp-evidence-synthesizer 方法学 + 自我复检,
    暴露并修复"遗漏最强反例"gap 后重跑全绿

完整说明见包内 README.md、SKILL.md、DELIVERY-REPORT.md。
============================================================================
