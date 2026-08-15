# DELIVERY REPORT — micp-reproducibility-versioning v1.0.0

**MICP 可复现性、数据溯源与版本治理器** — 2026-08-07

## 1. 交付物

| 物 | 位置 | 状态 |
|---|---|---|
| Skill 包 | `skills/micp-reproducibility-versioning/` | ✅ 完整工程包 |
| 安装 zip | `skills/micp-reproducibility-versioning-v1.0.0.zip` | ✅ 44 文件 / 108,689 B |
| Router 注册 | `skill.yaml` capabilities 含裸 token `reproducibility` | ✅ usable=true |

## 2. 工程包清单

- `SKILL.md`（frontmatter: name/description + 使命/触发/边界/流程/错误码/权限/指标/版本策略）
- `skill.yaml`（OSR registry 消费；所有列表字段为字符串数组；`units` 为对象——registry 契约允许）
- `manifest.json`（人类可读包元数据）
- `README.md`、`CHANGELOG.md`、`prompts/system.md`、`references/sources.md`
- `schemas/`：`input.schema.json`、`output.schema.json`、`reproduction-manifest.schema.json`、`provenance-event.schema.json`（draft 2020-12，与自研子集验证器兼容）
- `tools/mrv/`：13 个纯 stdlib Python 模块 + CLI
- `tests/`：78 测试（单元/场景/失败/回归/schema 子集/router 集成）
- `evals/`：12 用例 + `run_evals.py`（M1–M7）+ `metrics.md` + `bootstrap/`
- `examples/`：3 个真实可运行示例

## 3. 核心能力（工具集）

| 工具 | 实现 | 强制场景 |
|---|---|---|
| 文件/目录哈希 | `_common.sha256_file/dir_fingerprint` | 确定性、排除治理元数据 |
| 数据清单生成器 | `hashing.manifest_main` | 分层 + SHA-256 + 写保护 |
| Reproduction Manifest 生成器 | `manifest.build_manifest` | 12 必填块 + 归档 |
| 环境信息采集器 | `envinfo.collect_environment` | OS/运行时/工具/锁/git/指纹 |
| 依赖导出与锁定 | `envinfo.lock_main` | 被动检测，绝不执行包管理器 |
| 随机种子管理器 | `seed.resolve_seed` | splitmix64 + PCG32 |
| 输入输出 provenance 记录器 | `provenance.record_main` | 追加式哈希链防篡改 |
| 版本兼容检查器 | `envinfo.compat_main` | semver 主/次/修 + 矩阵 |
| Schema 迁移器 | `envinfo.migrate_main` | 迁移链 + 主版本拒绝 |
| 结果差异比较器 | `diff.diff_main` | JSON 深比较 + 哈希比对 |
| 一键复现脚本 | `reproduce.reproduce_main` | 完整循环 + 自动基线 |
| CI 复现检查 | `evals/run_evals.py` + bootstrap | 12 用例 + 自举循环 |
| 原始数据写保护检查 | `hashing.check_raw_main` | MRV-E501 门 |
| 产物污染检测 | `checkers.pollution_main` | provenance 链/锁漂移/manifest 完整性 |

## 4. 验证结果（真实运行）

### 4.1 测试 — `python -m pytest tests/` — **78 passed**
覆盖 SKILL.md 八的 **10 个强制场景**：
1. ✅ 全新临时环境最小示例（`TestScenario1FreshEnvironment`）
2. ✅ 修改参数追踪受影响结果（参数摘要变化 + lineage 追踪）
3. ✅ 修改原始数据被阻止/报警（MRV-E501 + 污染检测）
4. ✅ 依赖升级导致结果变化（requirements.txt 哈希漂移 → dependency_drift）
5. ✅ 随机种子缺失（默认 0 确定性 / require 拒绝）
6. ✅ Schema 主版本不兼容（compat 拒绝 + migrate 无链拒绝 + skill 版本门 MRV-E801）
7. ✅ 中途崩溃后恢复（失败命令无部分 manifest；恢复后成功）
8. ✅ 同一输入重复运行结果一致（manifest/hashes 逐字节一致 + identical_to_previous）
9. ✅ 外部数据源不可用时使用快照（data/external 快照纳入输入；快照缺失 → 污染报警）
10. ✅ 文件被手工覆盖后检测哈希变化（manifest_mismatch + provenance_tamper）

### 4.2 评测 — `python evals/run_evals.py` — **M1–M7 全 PASS**
```
structured_output_pass_rate      1.000  (≥0.95) PASS
tool_invocation_rate             1.000  (=1.0)  PASS
evidence_traceability_rate       1.000  (≥0.9)  PASS
missing_input_detection_rate     1.000  (=1.0)  PASS
adversarial_interception_rate    1.000  (=1.0)  PASS
repeat_run_consistency           1.000  (=1.0)  PASS
（12 用例，5.6s，离线确定性）
```

### 4.3 自举复现 — `python evals/bootstrap/run_bootstrap.py` — **BOOTSTRAP PASS**
真实执行完整循环并落盘到 `evals/bootstrap/results/`：
```
[1] reproduce run A (fresh tree)      → manifest rm-645538b3a93316ad
[2] rerun same tree                   → manifest identical=true, identical_to_previous=true
[3] fresh clone (run B)               → input hashes equal=true, output hashes equal=true
[4] diff report (A baseline vs B)     → identical=true, 0 differences
[5] red-team scan                     → 写保护完好/raw 全覆盖/锁文件存在/版本完整
                                        high: 项目非 git（指纹身份，回滚手动）
                                        low:  requirements.txt 未入 manifest
```

### 4.4 Router 注册 — bun 实测
```
usable: true, manifest_valid: true, issues: []
plan.status: SUCCESS
steps: ["micp-reproducibility-versioning"]
routed: true
```
复现性请求（含「复现」「manifest」「溯源」「版本」）由 `planner.ts` 的 `reproducibility`
裸能力 token 正确路由到本 Skill。

## 5. 已知限制

- **仓库 `opencode-dev` 非 git 仓库**：所有版本身份退化为内容指纹（`fp_` + 64hex），
  git_commit 为 None；已作为 high 风险在每次 reproduce 输出中上报，建议 `git init`。
- **依赖锁定为被动检测**：不执行 pip/pnpm/bun/npm，只哈希现存锁文件 + 枚举导入面；
  `lock` 生成的是确定性锁文档而非包管理器锁文件。
- **`data/` 分层目录仓库根未建立**：本 Skill 在调用方 `root` 下按需适配；若在仓库根
  运行 reproduce 会以仓库根为 root（其 data/ 缺失时 raw 门自动通过）。
- **Windows 写保护依赖文件系统属性**：`os.chmod(S_IREAD)` 在 NTFS 生效；POSIX 用 mode 位。
- **模型/Prompt 版本**：需调用方在 `versions.model/prompt` 显式声明；缺省未记录。
- **constitution_version 缺省 1.0.0**：Panshi 宪法真实版本应由 Controller 注入。

## 6. 后续建议

- `git init` 仓库并对 skills/ 做首次提交，使后续 manifest 记录真实 commit。
- 将 `obsidian-ctl` 版本（`obsidian-ctl-0.1.0` 格式）经 Controller 统一注入。
- 把 24-Skill 系列中已交付的 micp-* 包统一纳入一次仓库级 reproduce（由本 Skill 治理）。
