# CHANGELOG

## 1.1.1 — 2026-08-07

对抗审查修复(独立审查实例对磁盘代码实证复现 4 阻断 + 3 次要缺陷,全部关闭)。

### 修复
- 融合双计数缺陷(阻断#2):`fuse_all` 把主反射同时计为次反射,导致 XRD 主峰 + 支持峰 + 形貌即可达 `confirmed`。现按 `primary_matched` 扣除,次反射数 = 匹配峰数 − (primary 命中 ? 1 : 0);XRD+形貌单独不再达 confirmed。
- `tools.spectra_parse` 自检必败(阻断#3):OBSERVED 发现缺少 `source` → OMM-E601。现为每条 EDS/FTIR 发现附加 `source = "<MODALITY> 谱(sample_id=…)"`。
- 未解释峰静默消失(阻断#4):33.0° 等未匹配峰不再从输出消失——`_collect_unexplained` 接收原始检测峰列表,逐峰报告未归属特征。
- 单张 SEM 硬性规则死代码(次要#5):`single_sem_image_used` 现由 interpret.phases 在存在 sem_image/sem_particle_list 样本时置位,审计器的 single_sem_no_homogeneity 规则真正可达。
- primary 在扫描窗口外时 score 虚高(次要#6):match_profile 在无 primary 可评估时附加"主反射不在扫描窗口内,score 仅基于支持反射"注释。
- 晶型参考峰重叠未显式报告(次要#7):`reflection_overlaps` 字段检测不同晶型 d-窗重叠(如 aragonite 3.273 vs vaterite 3.29)并附 HYPOTHESIS 发现。
- FTIR 共享 v4 带误作 calcite 佐证(对抗审查次要发现):`DIAGNOSTIC_FTIR_BANDS` 改为**共现组**结构——calcite 需 [712, 874] 成对、aragonite 需 [854, 700] 或 [854, 713] 成对;单个 713 命中(aragonite 双峰)不再使 calcite 达 confirmed。
- `sem_stats` 被结果块覆盖(本会话自举复现):`interpret.phases` 循环里 `setdefault("sem_stats")` 写入后,整块 `env["results"] = {...}` 覆盖丢失该键,导致颗粒充足时 `bridge_evidence` 与 `spatial_distribution` 缺失。现用局部变量 `sem_stats_acc` 累积并合并。
- `tools.self_check` 与活体路径自检不一致(本会话自举复现):复检路径不传 context,`no_fabrication` 硬规则把含内联样本的封套误报为"无证据"。现从 candidate 的 `results._has_samples / single_sem_image_used` 派生与 `_finalize` 相同的 context。
- `_estimate_contact_ratio`(新增):颗粒充足时按间距阈值估算几何接触候选比例,`bridge_evidence` 恒声明 `engineering_contribution_claimed=false`(矿物证据不替代力学验证)。

### 新增
- `tests/regression/test_adversarial_fixes.py`:8 个针对上述缺陷的回归测试,全部通过。
- `tests/regression/test_adversarial_fixes.py`:追加 bridge_evidence 填充与 self_check 一致性 2 个回归测试(共 10 个)。

## 1.1.0 — 2026-08-07

规格 §七/§八/§九 差距补齐(审计驱动)。

### 新增
- `schemas/mineral-evidence.schema.json`:单条矿物证据结构化契约(phase/modality/observed/reference/deviation/confidence/epistemic_label/spatial_position)。
- `tools/mmpi/hashcheck.py` + `tools.image_hash` action:SEM 原始图像 SHA-256 完整性校验、期望哈希比对、防篡改哈希链(JSONL 追加式,prev_hash 链,篡改可检出),默认 dry-run、写盘需人工批准(规格 §九 test #8)。
- `tools/mmpi/report.py` + `tools.report` action:结构化分析报告生成器(结论/证据摘要/不确定性/风险/ASCII XRD 峰图),纯重排不新增数据(规格 §七)。
- 输出封套扁平业务字段(规格 §八):`candidate_phases/confirmed_phases/rejected_phases/unexplained_features/morphology/spatial_distribution/bridge_evidence`,四级结论严格区分。
- 跨模态冲突检测:`interpret.phases` 检测 XRD-identified 与 FTIR/Raman 特异带支持之间的冲突,写入 `uncertainty` 并附 INFERRED 声明(规格 §五)。
- FTIR 佐证必须命中多晶型特异带(`DIAGNOSTIC_FTIR_BANDS`:calcite 874 / aragonite 854+700 / vaterite 745);共享碳酸盐带(712/713、874/877、1086)不计入相位佐证。
- 规格 §九 必测补齐:`tests/failure/test_spec_nine.py`(7 用例,覆盖 T2 单候选峰/T3 方解石球霰石混合相/T5 缺尺度尺/T6 XRD-FTIR 冲突/T7 高CaCO3低接触沉淀/T9 不相关矿物/T10 数据库不可用降级)。
- skill.yaml 修复:Router registry `dependencies` 改为字符串数组,`capabilities/inputs_required/outputs/tool_permissions/writes/stop_conditions/domain_keywords` 全部合规 → `usable=true`。

### 修复
- `xrd.py` verdict 硬性约束:匹配峰数 `< min_peaks` 时禁止 `identified`(规格 §四.2"不得仅凭单个峰武断识别矿物相",T2 触发)。
- 融合层佐证判定:FTIR 共享带不再作为晶型确认佐证(T6 触发:calcite 误 confirmed)。

## 1.0.0 — 2026-08-06

初始交付。

### 新增
- 完整 Skill 工程包:SKILL.md、skill.yaml、schemas(input/output)、prompts/system.md、README、references/sources.md、CHANGELOG。
- 工具层 `tools/mmpi/`:
  - `minerals.py` 矿物相参考知识库(calcite/aragonite/vaterite/ACC,XRD 峰、形貌、FTIR/Raman/TGA)。
  - `errors.py` OMM-E### 错误码体系(18 码,六类)。
  - `validate.py` 自包含 JSON Schema 校验器 + 封套自检。
  - `xrd.py` XRD 峰匹配/背景估计/置信度分级。
  - `sem.py` SEM 颗粒统计/尺度校准/分割审计(ImageAuditLog)。
  - `spectra.py` EDS/FTIR/Raman/TGA 解析(证据边界显式化)。
  - `fuse.py` 多模态融合与置信度分级(confirmed/likely/candidate/weak)。
  - `audit.py` 认识论标签核查 + 专业硬性规则 + schema 自检。
  - `service.py` action 分派 + 统一输出封套。
- CLI `tools/mmpi_cli.py`:stdin=JSON → stdout=JSON,离线,可装载。

### 关键领域依据(见 references/sources.md)
- ICDD 卡片号 05-0586(calcite)/41-1475(aragonite)/33-0268(vaterite)经 Sanjuan et al. 2019 实证交叉确认。
- ASTM E2016(编造标题,实为工业丝网标准)被验证器拦截,未引用;改用 ASTM E766-14(2019)。
- vaterite 晶系竞争(P63/mmc vs C2/c)已在参考数据注释中说明,匹配以 d-间距为主。

### 已知限制
- vaterite 逐峰强度为近似(ICDD 付费墙);RRUFF vaterite 样品号未确认。
- 图像分割为轻量实现(不分离接触晶体),结果经审计记录。
