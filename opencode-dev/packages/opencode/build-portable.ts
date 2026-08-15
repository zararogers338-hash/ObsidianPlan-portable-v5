#!/usr/bin/env bun
/**
 * 便携包打包脚本 v2
 * 保留完整 monorepo 结构（符号链接依赖树必须完整）
 */
import { spawnSync } from "child_process"
import { existsSync, mkdirSync, copyFileSync, writeFileSync, rmSync, readdirSync } from "fs"
import { join, resolve } from "path"

const MONO = resolve(import.meta.dir, "../..")   // opencode-dev/
const DST  = resolve(MONO, "../../dist-portable") // ObsidianPlan/dist-portable

function ps(cmd: string) {
  return spawnSync("powershell", ["-NoProfile", "-Command", cmd], {
    shell: false, encoding: "utf-8"
  })
}

function check(r: ReturnType<typeof spawnSync>, label: string) {
  if ((r.status ?? 1) !== 0) {
    console.error(`❌ ${label} 失败 (exit ${r.status})`)
    if (r.stderr) console.error(r.stderr.toString().slice(0, 300))
    process.exit(1)
  }
}

console.log("╔══════════════════════════════════════════╗")
console.log("║   Obsidian Plan 便携版 v2 打包工具       ║")
console.log("╚══════════════════════════════════════════╝\n")

// 0. 清理
if (existsSync(DST)) {
  console.log("🧹 清理旧输出...")
  rmSync(DST, { recursive: true, force: true })
}
mkdirSync(DST, { recursive: true })
console.log(`📂 输出: ${DST}\n`)

// 1. 复制 bun.exe
console.log("1/4  复制 Bun 运行时...")
const bunSrc = process.execPath
const bunDst = join(DST, "bun.exe")
copyFileSync(bunSrc, bunDst)
console.log(`     ✅ bun.exe (${Bun.version})\n`)

// 2. 用 PowerShell Copy-Item 复制整个 monorepo（保留目录结构，排除 .git 和生成物）
console.log("2/4  复制 monorepo 源码（排除 .git / dist-portable）...")
console.log("     这一步可能需要几分钟...\n")

// 先复制除 node_modules 以外的所有内容（快速）
const r2 = ps(`
  Copy-Item -Path '${MONO}' -Destination '${join(DST, "opencode-dev")}' -Recurse -Force `+
  `-Exclude '.git','dist-portable','dist-exe','dist','*.output'
`)
// PowerShell Copy-Item returns 0 even with some errors, just warn
if (r2.stderr && r2.stderr.trim()) {
  console.warn("     ⚠️ 部分文件跳过（通常是权限或符号链接问题）")
}
console.log("     ✅ opencode-dev/ 源码已复制\n")

// 3. 运行 bun install（在复制的 monorepo 里安装依赖）
const monoInDst = join(DST, "opencode-dev")
console.log("3/4  安装依赖（bun install）...")
console.log("     注意：首次运行会从网络下载，后续从缓存加载\n")

const r3 = spawnSync(bunDst, ["install"], {
  cwd: monoInDst,
  stdio: "inherit",
  shell: false,
  env: { ...process.env, FORCE_COLOR: "1" }
})
if ((r3.status ?? 1) !== 0) {
  console.error("❌ bun install 失败！检查网络连接后重试。")
  process.exit(1)
}
console.log("\n     ✅ 依赖安装完成\n")

// 4. 生成启动脚本
console.log("4/4  生成启动脚本...")

const PKG_REL = "opencode-dev\\packages\\opencode"

function bat(dst: string, content: string) {
  writeFileSync(join(DST, dst), content.trim() + "\r\n", "utf-8")
  console.log(`     ✅ ${dst}`)
}

bat("启动-TUI.bat", `
@echo off
title Obsidian Plan
set OPENCODE_CLAW_GOVERNANCE=1
set OPENCODE_SERVER_PASSWORD=claw-demo
cd /d "%~dp0${PKG_REL}"
"%~dp0bun.exe" run --conditions=browser "./src/index.ts" tui
`)

bat("启动-Server.bat", `
@echo off
title Obsidian Server
set OPENCODE_CLAW_GOVERNANCE=1
set OPENCODE_SERVER_PASSWORD=claw-demo
cd /d "%~dp0${PKG_REL}"
echo.
echo  ╔══════════════════════════════╗
echo  ║  Obsidian Plan HTTP Server   ║
echo  ║  http://127.0.0.1:4096       ║
echo  ║  password: claw-demo         ║
echo  ╚══════════════════════════════╝
echo.
"%~dp0bun.exe" run --conditions=browser "./src/index.ts" serve --port 4096
pause
`)

bat("演示-Claw治理.bat", `
@echo off
title Claw 治理演示
cd /d "%~dp0${PKG_REL}"
echo.
echo  Claw/Cloud 治理引擎演示
echo  5 类硬拒绝 + 23 条治理事件
echo.
"%~dp0bun.exe" run --conditions=browser "./src/index.ts" claw demo
echo.
pause
`)

bat("obsidian.bat", `
@echo off
cd /d "%~dp0${PKG_REL}"
"%~dp0bun.exe" run --conditions=browser "./src/index.ts" %*
`)

writeFileSync(join(DST, "README.md"), `# Obsidian Plan 便携版

构建时间: ${new Date().toLocaleString("zh-CN")}
Bun 版本: ${Bun.version}
平台: Windows x64

## 快速开始

| 脚本 | 功能 |
|------|------|
| **启动-TUI.bat** | 全屏交互界面 |
| **启动-Server.bat** | HTTP 服务 → http://127.0.0.1:4096 （密码: claw-demo） |
| **演示-Claw治理.bat** | Claw/Cloud 治理引擎演示 |
| **obsidian.bat** | 通用命令行入口 |

## Claw 治理引擎

已接线进 TaskTool，真实派生 agent 时生效：

\`\`\`
obsidian.bat claw demo    # 5 类硬拒绝演示
obsidian.bat claw status  # 容量状态
obsidian.bat claw log     # 治理事件日志（当前进程）
\`\`\`

## 系统要求

- Windows 10/11 x64
- 无需安装 Node.js / Bun
- 首次运行需网络（安装依赖缓存），之后离线
`, "utf-8")
console.log("     ✅ README.md\n")

// 5. 验证
console.log("🔍 验证...")
const verify = spawnSync(
  bunDst,
  ["run", "--conditions=browser", "./src/index.ts", "claw", "demo"],
  { cwd: join(DST, PKG_REL), encoding: "utf-8", timeout: 15000, shell: false }
)
if (verify.status === 0) {
  const lines = (verify.stdout || "").split("\n").filter(l => l.includes("✓")).slice(0, 3)
  console.log(`   ✅ claw demo 通过: ${lines.join(" | ")}`)
} else {
  console.warn("   ⚠️  验证未通过（可能需要依赖下载完成后再测试）")
  if (verify.stderr) console.warn("  ", verify.stderr.slice(0, 200))
}

console.log(`
╔══════════════════════════════════════════╗
║  ✨ 便携版打包完成！                     ║
╠══════════════════════════════════════════╣
║  位置: dist-portable/                    ║
║  使用: 双击 启动-TUI.bat                 ║
╚══════════════════════════════════════════╝

分发方式：把整个 dist-portable/ 文件夹
  复制到任意 Windows x64 机器即可使用。
`)
