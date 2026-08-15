# MICP Mineral Phase Interpreter

Obsidian Plan (Panshi) 受治理能力 Skill:综合 XRD / SEM / EDS / FTIR / Raman / TGA 多模态表征,判断 MICP 沉淀物的矿物相、晶体形貌、成核位置和有效晶桥,并管理测量不确定性。

## 标准识别(仓库约定)

本 Skill 遵循仓库内已确立的 Skill 约定(由 `obsidian-skill-router` 与 `obsidian-state-manager` 示范):

- **OpenCode 原生加载**:loader 从 `SKILL.md` frontmatter 读 `name` + `description`(已在 `packages/opencode/src/skill/index.ts` 验证)。
- **skill.yaml**:项目扩展清单(contract_version / entry / dependencies / permissions / compatibility)。
- **统一输入输出封套**:`contract_version, task_id, project_id, request, action, skill_version, timestamp` → `status, summary, findings, assumptions, evidence_used, uncertainty, risks, artifacts, requested_next_skills, results, validation, provenance, errors`。
- **认识论标签**:OBSERVED / REPORTED / CALCULATED / INFERRED / HYPOTHESIS / RECOMMENDATION,六选一。
- **错误码**:`OMM-E###`(本 Skill 独立命名空间,分类与 OSR/OSM 对齐:input/dependency/policy/capability/state/internal)。

## 安装

```bash
# 本 Skill 已位于仓库 skills/ 目录,无需安装。
# 运行时依赖:
pip install numpy scipy           # 必需
pip install Pillow                # 图像;缺失时 OMM-E203
pip install scikit-image          # 可选;分割用,有 numpy 回退
pip install pytest pyyaml         # 测试与评测
```

## 调用

```bash
# stdin → stdout,离线
python tools/mmpi_cli.py < examples/interpret_phases_vaterite.json
# 全部 action:
#   interpret.phases / tools.xrd_match / tools.sem_stats / tools.spectra_parse
#   tools.fuse / tools.audit_image / tools.image_hash / tools.report
#   tools.validate / tools.self_check
# tools.image_hash: 计算 SEM 原始图像 SHA-256,比对期望哈希,追加防篡改哈希链(写盘需批准)
# tools.report:     从已完成封套生成结构化报告(含 ASCII XRD 峰图)
```

输入样例见 `examples/`。控制器调用时注入 `contract_version/task_id/project_id/skill_version/timestamp`;数据在 `samples[]` 内联提供(或 `path` 引用)。

## 测试与评测

```bash
python -m pytest tests -q                 # 单元/集成/失败/回归
python evals/run.py                       # 8+ 评测用例 + 最小性能指标,写 evals/results/latest.json
```

指标(M1–M7,定义见 `evals/metrics.py`):结构化输出通过率、工具真实调用率、引用可追溯率、缺失输入识别率、对抗拦截率、重复运行一致性、平均失败恢复时间。

## 目录

```
SKILL.md           触发/边界/流程/认识论/错误码/停止规则
skill.yaml         机器元数据
schemas/           输入输出契约(JSON Schema)
prompts/system.md  最小系统提示词
tools/mmpi_cli.py  CLI 入口
tools/mmpi/        领域核心(纯函数,离线可测)
  minerals.py      矿物相参考知识库(唯一事实源)
  errors.py        错误码体系
  models.py        契约类型
  validate.py      最小 JSON Schema 校验器 + 封套自检
  xrd.py           XRD 峰匹配/拟合
  sem.py           SEM 尺度校准/颗粒统计/分割审计
  spectra.py       EDS/FTIR/Raman/TGA 解析
  fuse.py          多模态证据融合与置信度分级
  audit.py         自检 + 硬性规则 + 认识论核查
  hashcheck.py     SHA-256 图像完整性 + 防篡改哈希链
  report.py        结构化分析报告生成器(含 ASCII 峰图)
  service.py       action 分派与输出封套装配
tests/             单元/集成/失败/回归
evals/             评测用例与指标
examples/          可运行示例
references/        sources.md 领域来源与实现依据
CHANGELOG.md       版本记录
```

## 限制与故障排除

- **vaterite 逐峰强度近似**:ICDD 付费墙,逐峰强度来自二手汇编;匹配以 d-间距为主。勿依赖单一主峰。
- **RRUFF vaterite 样品号未确认**:Raman 参考仅列一般波段。
- **图像分割是轻量实现**:不分离接触晶体、不做 watershed;结果标注为估计并经审计记录。
- **常见错误**:`OMM-E104` = 数值数据问题(NaN/空/越界);`OMM-E204/205/206` = 文件不可解析;`OMM-E101` = 输入缺失字段(详情在 `errors[0].detail.field_guidance`)。

## 维护

- 修改参考数据必须先更新 `tools/mmpi/minerals.py` 与 `references/sources.md`(注明访问日期)。
- 契约破坏性变更 → 主版本提升;可选字段 → 次版本;实现修复 → 修订版本。
- 版本记录见 `CHANGELOG.md`。
