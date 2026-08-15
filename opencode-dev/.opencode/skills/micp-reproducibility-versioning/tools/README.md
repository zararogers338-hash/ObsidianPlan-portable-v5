# tools/mrv — micp-reproducibility-versioning 工具集

纯 Python 3.10+ 标准库，离线、确定性、无硬编码路径。所有工具通过
stdin/stdout JSON 信封通信，进度写 stderr。

## 信封

```
success: {"ok": true,  "tool": <name>, "version": "1.0.0", "result": {...}}
failure: {"ok": false, "tool": <name>, "version": "1.0.0",
          "error": {"code": <MRV-E###|E_*>, "message": <human>,
                    "retryable": <bool>, "details": {...}}}
```

Exit codes: 0 成功; 2 输入/校验; 3 图/契约; 4 内部错误。

## 模块

| 模块 | 职责 |
|---|---|
| `_common.py` | 信封、canonical JSON、SHA-256、目录指纹、路径安全、类型守卫 |
| `_jsonschema.py` | draft 2020-12 子集验证器（可审计，无第三方依赖） |
| `errors.py` | MRV-E1xx…E9xx 错误码唯一事实源 |
| `hashing.py` | 文件/目录哈希、数据清单生成器、原始数据写保护检查 |
| `envinfo.py` | 环境采集、git 检测/指纹回退、依赖锁定（被动检测）、版本兼容、迁移 |
| `seed.py` | 随机种子管理（splitmix64 + PCG32，确定性） |
| `provenance.py` | 追加式哈希链 provenance 记录器 |
| `diff.py` | JSON 深比较 + 哈希比对差异报告 |
| `checkers.py` | 产物污染检测（provenance 链 / 锁文件漂移 / manifest 完整性） |
| `manifest.py` | Reproduction Manifest 构建与落盘 |
| `reproduce.py` | 一键复现流水线 |
| `service.py` | 全管线编排（校验→版本门→前置→调度→自检） |
| `cli.py` | stdin/stdout 入口 |

## 确定性纪律

- 工具输出中的所有时间戳派生自输入 `timestamp` 字段，绝不使用墙钟；
- 哈希全部来自真实文件内容（CALCULATED），绝不来自缓存；
- 同输入重复运行逐字节一致。

## 无硬编码路径

`root` 缺省为当前工作目录；任何文件读写都经 `_common.safe_join` 校验不越界。
