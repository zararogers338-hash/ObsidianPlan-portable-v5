# Obsidian Plan Portable v5

面向 Windows 的便携式 MICP（微生物诱导碳酸盐沉淀）研究工作台。项目以 OpenCode 源码为基础，集成 Panshi 研究规范、MICP 专项 Agent/Skill、研究文档以及一键安装与启动脚本。

> 本仓库是独立定制项目，与 OpenCode 官方团队没有隶属关系。

## 主要内容

- **Windows 一键运行**：根目录提供 `install.bat` 与 `start-obsidian.bat`。
- **研究型多 Agent 配置**：覆盖文献检索、证据抽取、实验设计、数据分析、矿相解释、反应运移、工程性能、LCA/TEA、风险审计等 MICP 工作流。
- **Panshi 研究规范**：强调证据溯源、单位检查、不确定性标注、红队审查与决策门控。
- **完整 OpenCode 工作区**：源码位于 `opencode-dev/`，由 Bun workspace 管理。
- **随附资料与样例产物**：研究文档位于 `opencode-dev/docs/`，示例产物位于 `opencode-dev/artifacts/`。

## 环境要求

- Windows 10/11
- PowerShell
- 网络连接（首次安装 Bun 和项目依赖时使用）
- 至少一个可用的模型服务 API Key

## 快速开始

### 1. 配置模型密钥

默认模型配置使用 DeepSeek。请在当前终端或 Windows 用户环境中设置密钥，不要把真实密钥写入仓库：

```powershell
$env:DEEPSEEK_API_KEY = "YOUR_DEEPSEEK_API_KEY"
```

如需启用 Exa 的自有额度，可选设置：

```powershell
$env:EXA_API_KEY = "YOUR_EXA_API_KEY"
```

若希望长期保存，可在 Windows 的“环境变量”设置中添加同名用户变量。

### 2. 安装依赖

双击：

```text
install.bat
```

脚本会检查 Bun；若本机尚未安装，会尝试通过 `winget` 或 Bun 官方安装脚本完成安装，然后在 `opencode-dev/` 中执行 `bun install`。

### 3. 启动

双击：

```text
start-obsidian.bat
```

启动器会检查源码、Bun 与依赖，然后在 Windows Terminal（如可用）或命令提示符的新窗口中运行终端界面。错误信息会记录到根目录的 `obsidian-launch.log`。

## 命令行方式

也可以在 PowerShell 中手动运行：

```powershell
cd .\opencode-dev
bun install
bun run --cwd packages/opencode --conditions=browser src/index.ts
```

## 目录结构

```text
.
├─ install.bat                   # 一键安装 Bun 与依赖
├─ start-obsidian.bat            # Windows 启动入口
├─ _start_obsidian.cmd           # 启动辅助脚本
└─ opencode-dev/
   ├─ opencode.json              # Panshi/MICP Agent 与模型配置
   ├─ .opencode/skills/          # 专项 Skill
   ├─ docs/                      # 研究规范与使用文档
   ├─ artifacts/                 # 示例产物
   ├─ packages/opencode/         # CLI/TUI 核心
   └─ packages/                  # OpenCode monorepo 其他包
```

## 配置说明

核心配置文件为 `opencode-dev/opencode.json`：

- 默认模型：`deepseek/deepseek-chat`
- DeepSeek 密钥：从 `DEEPSEEK_API_KEY` 环境变量读取
- Exa 搜索：由 `OPENCODE_ENABLE_EXA=1` 开启；自有密钥从 `EXA_API_KEY` 环境变量读取
- Skill 路径：`opencode-dev/.opencode/skills`

要切换模型或服务商，请编辑 `opencode-dev/opencode.json`，并继续使用 `{env:VARIABLE_NAME}` 引用密钥。

## 安全提示

- 不要提交 API Key、访问令牌、密码或 `.env` 文件。
- 本仓库的 `.gitignore` 已排除常见本地凭据文件与运行日志。
- 首次运行会从外部下载 Bun 和 npm 依赖；建议先阅读脚本并在可信网络环境中执行。
- 研究输出应复核原始证据、实验边界和统计假设；生成内容不替代实验验证或专业评审。

## 开发与检查

在 `opencode-dev/` 下可使用：

```powershell
bun install
bun run typecheck
bun run lint
```

仓库根目录的便携启动流程主要面向 Windows；OpenCode monorepo 的其他开发方式请参阅 [`opencode-dev/README.zh.md`](opencode-dev/README.zh.md) 与 [`opencode-dev/CONTRIBUTING.md`](opencode-dev/CONTRIBUTING.md)。

## 许可证与致谢

OpenCode 源码采用 MIT License，详见 [`opencode-dev/LICENSE`](opencode-dev/LICENSE)。本项目保留了上游版权与许可证文件，并在其基础上加入 Panshi/MICP 研究配置、文档和 Windows 便携脚本。
