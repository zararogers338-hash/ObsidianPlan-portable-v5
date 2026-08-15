#!/usr/bin/env bun
/**
 * 便携版打包脚本
 * 把 Bun runtime + 源码 + 依赖 打包成可直接运行的目录
 */
import { spawnSync, execSync } from "child_process"
import { existsSync, mkdirSync, cpSync, writeFileSync, rmSync } from "fs"
import { join } from "path"

const OUT_DIR = "./dist-portable"
const BUN_VERSION = Bun.version

console.log("=== Obsidian Plan 便携版打包工具 ===\n")

// 1. 清理并创建输出目录
if (existsSync(OUT_DIR)) {
  console.log("🧹 清理旧的输出目录...")
  rmSync(OUT_DIR, { recursive: true, force: true })
}
mkdirSync(OUT_DIR, { recursive: true })

// 2. 获取 Bun 可执行文件路径
console.log("📍 定位 Bun 运行时...")
const bunPath = process.execPath
console.log(`   Bun 路径: ${bunPath}`)
console.log(`   Bun 版本: ${BUN_VERSION}`)

// 3. 复制 Bun 可执行文件
console.log("\n📦 复制 Bun 运行时...")
const bunDest = join(OUT_DIR, "bun.exe")
cpSync(bunPath, bunDest)
console.log(`   ✅ ${bunDest}`)

// 4. 复制源码
console.log("\n📦 复制源码...")
const srcDirs = ["src", "test", "skill"]
for (const dir of srcDirs) {
  if (existsSync(dir)) {
    cpSync(dir, join(OUT_DIR, dir), { recursive: true })
    console.log(`   ✅ ${dir}/`)
  }
}

// 5. 重新安装依赖（避免符号链接问题）
console.log("\n📦 安装依赖...")
console.log("   正在运行 bun install（生产模式）...")
const installResult = spawnSync(
  bunDest,
  ["install", "--production", "--frozen-lockfile"],
  {
    cwd: OUT_DIR,
    stdio: "pipe",
    shell: true,
  }
)

if (installResult.status !== 0) {
  console.error("   ❌ 依赖安装失败！")
  console.error(installResult.stderr?.toString() || "")
  process.exit(1)
}
console.log(`   ✅ node_modules/ (生产依赖)`)

// 6. 复制配置文件
console.log("\n📦 复制配置文件...")
const configFiles = ["package.json", "tsconfig.json", "bunfig.toml"]
for (const file of configFiles) {
  if (existsSync(file)) {
    cpSync(file, join(OUT_DIR, file))
    console.log(`   ✅ ${file}`)
  }
}

// 7. 生成启动脚本
console.log("\n📝 生成启动脚本...")

const tuiScript = `@echo off
REM Obsidian Plan - TUI 交互界面
REM 自动生成于 ${new Date().toISOString()}

set OPENCODE_CLAW_GOVERNANCE=1
set OPENCODE_SERVER_PASSWORD=claw-demo

cd /d "%~dp0"

echo ========================================
echo Obsidian Plan - TUI 交互界面
echo ========================================
echo.
echo Claw/Cloud 治理引擎: 已启用
echo HTTP 服务密码: claw-demo
echo.

"%~dp0bun.exe" run --conditions=browser "./src/index.ts" tui

if errorlevel 1 (
    echo.
    echo ❌ 启动失败！请检查错误信息。
    pause
)
`

const serverScript = `@echo off
REM Obsidian Plan - HTTP 服务器
REM 自动生成于 ${new Date().toISOString()}

set OPENCODE_CLAW_GOVERNANCE=1
set OPENCODE_SERVER_PASSWORD=claw-demo

cd /d "%~dp0"

echo ========================================
echo Obsidian Plan - HTTP 服务器
echo ========================================
echo.
echo Claw/Cloud 治理引擎: 已启用
echo HTTP 服务密码: claw-demo
echo 默认端口: 4096
echo.
echo 启动后访问: http://127.0.0.1:4096
echo.

"%~dp0bun.exe" run --conditions=browser "./src/index.ts" serve --port 4096

if errorlevel 1 (
    echo.
    echo ❌ 启动失败！请检查错误信息。
    pause
)
`

const demoScript = `@echo off
REM Claw 治理引擎演示
REM 自动生成于 ${new Date().toISOString()}

cd /d "%~dp0"

echo ========================================
echo Claw/Cloud 治理引擎演示
echo ========================================
echo.
echo 这个演示会展示 5 类硬拒绝：
echo 1. 预算耗尽 (LEASE_EXHAUSTED)
echo 2. 玉衡禁入 (CONTROL_PLANE_ENTITY_CANNOT_JOIN_CLOUD)
echo 3. 成员互斥 (AGENT_ALREADY_IN_ACTIVE_CLOUD)
echo 4. 派生门 (SPAWN_NOT_PERMITTED)
echo 5. 容量红线 (CAPACITY_HARD_STOP@75)
echo.
pause

"%~dp0bun.exe" run --conditions=browser "./src/index.ts" claw demo

echo.
echo ========================================
echo 演示完成！查看上面的 23 条治理事件
echo ========================================
pause
`

const cliScript = `@echo off
REM Obsidian Plan - 命令行工具
REM 自动生成于 ${new Date().toISOString()}

cd /d "%~dp0"
"%~dp0bun.exe" run --conditions=browser "./src/index.ts" %*
`

writeFileSync(join(OUT_DIR, "启动-TUI.bat"), tuiScript, "utf-8")
writeFileSync(join(OUT_DIR, "启动-Server.bat"), serverScript, "utf-8")
writeFileSync(join(OUT_DIR, "演示-Claw.bat"), demoScript, "utf-8")
writeFileSync(join(OUT_DIR, "obsidian.bat"), cliScript, "utf-8")

console.log(`   ✅ 启动-TUI.bat`)
console.log(`   ✅ 启动-Server.bat`)
console.log(`   ✅ 演示-Claw.bat`)
console.log(`   ✅ obsidian.bat`)

// 8. 生成 README
const readme = `# Obsidian Plan - 便携版

**版本**: ${require("./package.json").version}
**构建时间**: ${new Date().toLocaleString("zh-CN")}
**Bun 版本**: ${BUN_VERSION}
**平台**: Windows x64

---

## 🚀 快速开始

### 1. 启动 TUI 交互界面
双击 \`启动-TUI.bat\`，进入全屏交互界面。

### 2. 启动 HTTP 服务器
双击 \`启动-Server.bat\`，然后访问 http://127.0.0.1:4096
**密码**: \`claw-demo\`

### 3. 查看 Claw 治理演示
双击 \`演示-Claw.bat\`，看 5 类硬拒绝 + 23 条治理事件。

### 4. 命令行使用
\`\`\`cmd
obsidian.bat --help
obsidian.bat claw log
obsidian.bat claw capacity
obsidian.bat run "你的提示词"
\`\`\`

---

## 🛡️ Claw/Cloud 治理引擎

这个版本已接线 **Claw/Cloud 多智能体治理引擎**，特性：

- ✅ **11 条硬不变量**强制执行
- ✅ **75 活跃智能体**容量红线（NORMAL ≤60 / LOCKDOWN 69-74 / HARD_STOP@75）
- ✅ **玉衡禁入**保护（\`obsidian-prompt-amplifier\` 永不加入 Cloud）
- ✅ **成员互斥**（同一 agent 不能同时在两个活跃 Cloud）
- ✅ **禁自审**（任何主体不得最终审查自己）
- ✅ **派生门**（spawn 需控制平面批准）
- ✅ **预算边界**（记账式，超额拒绝下次）
- ✅ **Artifact 保留**（终止 agent 不销毁有效产物）

### 环境变量（可选）

\`\`\`cmd
set OPENCODE_CLAW_GOVERNANCE=1        REM 启用治理（默认 ON）
set OPENCODE_CLAW_HARD_GATE=1         REM 强拦截模式（默认 OFF）
set OPENCODE_SERVER_PASSWORD=<密码>   REM HTTP 服务密码
set OPENCODE_LOG_LEVEL=DEBUG          REM 日志级别
\`\`\`

---

## 📂 目录结构

\`\`\`
dist-portable/
├── bun.exe                  Bun 运行时 (${BUN_VERSION})
├── src/                     源代码 (361 个 TS 文件)
├── node_modules/            依赖包
├── skill/                   25 个 Panshi skill
├── 启动-TUI.bat             一键启动 TUI
├── 启动-Server.bat          一键启动 HTTP 服务
├── 演示-Claw.bat            Claw 治理演示
├── obsidian.bat             命令行入口
└── README.md                本文件
\`\`\`

---

## 🔍 验证治理引擎

### 方法 1：演示脚本
运行 \`演示-Claw.bat\`，你会看到 5 类硬拒绝：
- \`LEASE_EXHAUSTED\` (预算耗尽)
- \`CONTROL_PLANE_ENTITY_CANNOT_JOIN_CLOUD\` (玉衡禁入)
- \`AGENT_ALREADY_IN_ACTIVE_CLOUD\` (成员互斥)
- \`SPAWN_NOT_PERMITTED\` (派生门)
- \`CAPACITY_HARD_STOP\` (容量红线@75)

### 方法 2：TUI 实时查看
1. 双击 \`启动-TUI.bat\`
2. 在 TUI 里输入："派生一个子 agent，让它返回 PONG"
3. 等子 agent 完成
4. 输入 \`/claw log\` 查看治理事件

你会看到：
\`\`\`
[000] cloud.created :: cloud_000001 | purpose: automated spawn
[001] spawn.requested :: cloud_000001 | agent_type: general
[002] spawn.approved :: cloud_000001 | granted_session: ses_xxx
[003] cloud.member.joined :: cloud_000001 | member: ses_xxx
[004] cloud.activated :: cloud_000001 |
[005] cloud.completed :: cloud_000001 | status: success
\`\`\`

这证明"用户让 agent 派生 agent"这个操作，真的经过了 Claw 治理引擎。

---

## ⚙️ 技术细节

- **运行时**: Bun ${BUN_VERSION}（内嵌 JavaScriptCore）
- **语言**: TypeScript 5.x（运行时编译）
- **依赖管理**: workspace + catalog (monorepo)
- **治理引擎**: Effect-based (src/claw/)
- **源文件**: 361 个 .ts + 25 个 skill
- **不变量**: 11 条硬约束（见 src/claw/types.ts）

---

## 🚚 分发说明

**这个文件夹可以直接复制到任何 Windows x64 机器上运行，无需安装依赖。**

必需条件：
- Windows 7+ (推荐 Windows 10/11)
- x64 架构（不支持 ARM64/x86）

不需要：
- ❌ 不需要安装 Node.js
- ❌ 不需要安装 Bun
- ❌ 不需要 \`npm install\` / \`bun install\`
- ❌ 不需要联网（除非使用 LLM 功能）

---

## 📝 已知限制

1. **Per-process 状态**
   治理状态存在进程内存，重启清空。

2. **预算门是记账式**
   LLM 调用先发生，\`spend\` 后置记录。超额会拒绝**下次**调用。

3. **身份是自断言**
   \`AgentRef.agentType\` 来自调用方声明，无加密认证。

4. **仅 Windows x64**
   这个便携版只支持 Windows x64。其他平台需重新打包。

---

## 📄 许可证

MIT License

---

**生成于**: ${new Date().toLocaleString("zh-CN")}
**打包工具**: compile-portable.ts
`

writeFileSync(join(OUT_DIR, "README.md"), readme, "utf-8")
console.log(`   ✅ README.md`)

// 9. 计算大小
console.log("\n📊 统计信息...")
const result = execSync(`powershell -Command "(Get-ChildItem -Path '${OUT_DIR}' -Recurse | Measure-Object -Property Length -Sum).Sum / 1MB"`, {
  encoding: "utf-8",
})
const sizeMB = parseFloat(result.trim()).toFixed(2)

console.log(`   总大小: ${sizeMB} MB`)
console.log(`   Bun 版本: ${BUN_VERSION}`)
console.log(`   目标平台: Windows x64`)

console.log("\n✨ 打包完成！")
console.log(`\n📦 便携版位置: ${OUT_DIR}/`)
console.log(`   - bun.exe (Bun 运行时)`)
console.log(`   - src/ (源代码)`)
console.log(`   - node_modules/ (依赖)`)
console.log(`   - 启动-TUI.bat (一键启动 TUI)`)
console.log(`   - 启动-Server.bat (一键启动 HTTP 服务)`)
console.log(`   - 演示-Claw.bat (Claw 治理演示)`)
console.log(`   - obsidian.bat (命令行入口)`)
console.log(`   - README.md (使用说明)`)
console.log(`\n🚀 现在可以把整个 ${OUT_DIR} 文件夹复制到任何 Windows 机器上运行！`)
console.log(`\n💡 提示: 双击 ${OUT_DIR}/启动-TUI.bat 即可开始使用`)
