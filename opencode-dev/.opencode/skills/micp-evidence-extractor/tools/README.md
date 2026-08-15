# tools/mee — 纯 Python 工具集

所有工具为纯标准库（>=3.10），离线、确定性、超时防护。stdin JSON → stdout JSON
信封：

```
success: {"ok": true,  "tool": <name>, "version": "1.0.0", "result": {...}}
failure: {"ok": false, "tool": <name>, "version": "1.0.0",
          "error": {"code": <MEE-E###>, "message": <human>, "retryable": <bool>,
                    "details": {...}}}
```

退出码：0 成功；2 输入/校验；3 图/契约；4 内部。进度与日志写 stderr。
`MEE_TOOL_TIMEOUT`（秒）限定长耗时抽取，默认 120s。

## 子命令（cli.py）

| 子命令 | 模块 | 用途 |
|---|---|---|
| `service` | service.py | 完整抽取管线 |
| `adapters` | adapters.py | PDF/HTML/Markdown/CSV/JSON 解析 |
| `doi` | doi.py | DOI 结构校验 + 元数据一致性 |
| `units` | units.py | 单位规范化 + 量纲 + 防混淆 |
| `extract` | extract.py | 表/正文/图候选抽取 |
| `validate` | card_check.py | 卡片 schema + 不变量校验 |
| `isolation` | isolation.py | 组/时间点隔离检查 |
| `conflict` | conflict.py | 重复值 + 内部矛盾 |
| `export` | exporter.py | JSON/YAML/CSV 导出 |
| `digitize` | digitizer.py | 图数字化接口 |
| `check-self` | service.py | 输出信封自检 |

## 模块职责

- `_common.py`：信封、`run_tool`、`timed_guard`（POSIX SIGALRM / 软截止）、日志、类型守卫。
- `errors.py`：MEE-E101…E900 错误码（唯一事实源）。
- `models.py`：领域常量（STATUSES、EPISTEMIC_TAGS、ACQUISITION_MODES、
  PLACEHOLDER_MODES、SCALES、SYSTEM_KINDS、MEDIA_KINDS、DOC_TYPES）。
- `_jsonschema.py`：JSON Schema draft 2020-12 子集校验器（$ref 递归、allOf/anyOf/oneOf/not）。
- `adapters.py`：源解析。PDF 内置流级文本恢复（zlib），损坏/密码 → MEE-E303。
- `doi.py`：离线结构校验 + 伪造启发式；`verify_dois(..., online=True, fetcher=...)`
  支持注入在线运输（默认离线）。
- `units.py`：单位规范化（canonical 目标）；上下文消歧 `M`（摩尔/米）、`mM`（毫摩尔/毫米）；
  `classify_role` + `detect_distinct_conflation` 保证 OD600/CFU/细胞浓度/活细胞比/
  脲酶活性绝不互换。
- `quantity.py`：`reported()`/`placeholder()`/`with_binding()`；占位值不参与算术；
  DIGITIZED_FROM_FIGURE 必须携带 `digitization.error_estimate`。
- `extract.py`：表逐行逐列候选（表头时间点识别）、正文条件/结果候选、图数字化候选。
- `card_check.py`：每卡过 evidence-card schema + 不变量（组引用、占位、估读误差、
  认识论、防混淆）。
- `isolation.py`：GROUP_UNRESOLVED/TIME_UNRESOLVED/GROUP_SMEAR/SCALE_MIX。
- `conflict.py`：DUPLICATE_VALUE/CONTRADICTION/METHODS_RESULTS_CONFLICT。
- `exporter.py`：JSON（排序紧凑）、YAML（stdlib 手写发射器）、CSV（逐 quantity 一行）。
- `digitizer.py`：`estimate_reading_error(px/unit)`（2px 保守带）、`prepare_digitization`。

## 设计规则

- 确定性：同输入逐字节一致（无未播种随机、无 wall-clock 进入输出值）。
- 离线：无网络调用；DOI 在线核验需调用方注入 fetcher。
- 防御：任何输入都返回结构化信封，绝不 traceback 到 stdout。
- 无密钥/凭证：代码中不出现任何凭据。
