#!/usr/bin/env bun
/**
 * EXE 打包脚本
 * 用 Bun 的 --compile 把 opencode 打包成单文件可执行程序
 */
import { spawnSync } from "child_process"
import { existsSync, mkdirSync, copyFileSync } from "fs"
import { join } from "path"

const OUT_DIR = "./dist-exe"
const EXE_NAME = "obsidian.exe"

console.log("=== Obsidian EXE 打包工具 ===\n")

// 1. 清理输出目录
if (!existsSync(OUT_DIR)) {
  mkdirSync(OUT_DIR, { recursive: true })
}

console.log("📦 正在编译 TypeScript → EXE...")
console.log(`   入口: src/index.ts`)
console.log(`   输出: ${OUT_DIR}/${EXE_NAME}\n`)

// 2. 调用 Bun compile
const result = spawnSync(
  "bun",
  [
    "build",
    "./src/index.ts",
    "--compile",
    "--minify",
    "--target=bun-windows-x64",
    `--outfile=${OUT_DIR}/${EXE_NAME}`,
  ],
  {
    stdio: "inherit",
    shell: true,
  },
)

if (result.status !== 0) {
  console.error("\n❌ 编译失败！")
  process.exit(1)
}

console.log("\n✅ 编译成功！")
console.log(`\n📍 可执行文件: ${OUT_DIR}/${EXE_NAME}`)

// 3. 生成启动脚本
const launchScript = `@echo off
REM Obsidian Plan - 一键启动脚本
REM 生成时间: ${new Date().toISOString()}

echo ========================================
echo Obsidian Plan - Claw/Cloud 治理引擎
echo ========================================
echo.

REM 设置环境变量
set OPENCODE_CLAW_GOVERNANCE=1
set OPENCODE_SERVER_PASSWORD=claw-demo

REM 启动 TUI（交互模式）
"%~dp0${EXE_NAME}" tui

pause
`

const launchPath = join(OUT_DIR, "启动-Obsidian-TUI.bat")
require("fs").writeFileSync(launchPath, launchScript, "utf-8")
console.log(`📍 启动脚本: ${launchPath}`)

// 4. 生成演示脚本
const demoScript = `@echo off
REM Claw 治理引擎演示脚本

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

"%~dp0${EXE_NAME}" claw demo

echo.
echo ========================================
echo 演示完成！
echo ========================================
pause
`

const demoPath = join(OUT_DIR, "演示-Claw-治理.bat")
require("fs").writeFileSync(demoPath, demoScript, "utf-8")
console.log(`📍 演示脚本: ${demoPath}`)

// 5. 生成 README
const readme = `# Obsidian Plan - 便携版

## 快速开始

1. **启动交互界面**
   双击 \`启动-Obsidian-TUI.bat\`

2. **查看治理演示**
   双击 \`演示-Claw-治理.bat\`

3. **命令行使用**
   \`\`\`cmd
   obsidian.exe --help
   obsidian.exe claw demo
   obsidian.exe serve --port 4096
   \`\`\`

## Claw/Cloud 治理引擎

这个版本已接线 Claw/Cloud 多智能体治理引擎，特性：

- ✅ 11 条硬不变量强制执行
- ✅ 75 活跃智能体容量红线
- ✅ 玉衡（obsidian-prompt-amplifier）禁入保护
- ✅ 成员互斥、禁自审、派生门
- ✅ 预算边界、Artifact 保留

## 环境变量

- \`OPENCODE_CLAW_GOVERNANCE=1\` 启用治理（默认）
- \`OPENCODE_CLAW_HARD_GATE=1\` 强拦截模式
- \`OPENCODE_SERVER_PASSWORD=<密码>\` HTTP 服务密码

## 技术细节

- 构建工具: Bun ${Bun.version}
- 目标平台: Windows x64
- 打包时间: ${new Date().toISOString()}
- 源代码: 361 个 TypeScript 文件

生成于: ${new Date().toLocaleString("zh-CN")}
`

const readmePath = join(OUT_DIR, "README.md")
require("fs").writeFileSync(readmePath, readme, "utf-8")
console.log(`📍 说明文档: ${readmePath}`)

console.log("\n✨ 打包完成！")
console.log(`\n📦 分发包位置: ${OUT_DIR}/`)
console.log(`   - ${EXE_NAME} (主程序)`)
console.log(`   - 启动-Obsidian-TUI.bat (一键启动)`)
console.log(`   - 演示-Claw-治理.bat (演示脚本)`)
console.log(`   - README.md (说明文档)`)
console.log("\n🚀 现在可以把整个 dist-exe 文件夹复制到任何 Windows 机器上运行！")
