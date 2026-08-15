import path from "node:path"
import fs from "node:fs/promises"
import os from "node:os"

// OBSIDIAN 数据目录: Windows %LOCALAPPDATA%/obsidian, 其他平台遵循 xdg 规范
export function dataDir(): string {
  if (process.platform === "win32") {
    const base = process.env.LOCALAPPDATA || path.join(os.homedir(), "AppData", "Local")
    return path.join(base, "obsidian")
  }
  const base = process.env.XDG_DATA_HOME || path.join(os.homedir(), ".local", "share")
  return path.join(base, "obsidian")
}

export function configDir(): string {
  if (process.platform === "win32") {
    const base = process.env.APPDATA || path.join(os.homedir(), "AppData", "Roaming")
    return path.join(base, "obsidian")
  }
  const base = process.env.XDG_CONFIG_HOME || path.join(os.homedir(), ".config")
  return path.join(base, "obsidian")
}

const DEFAULT_CONFIG = `{
  "model": "anthropic/claude-sonnet-4.5",
  "theme": "obsidian"
}
`

const DEFAULT_BACKENDS = `{
  "$schema": "https://obsidian.dev/backends.schema.json",
  "default": "",
  "backends": {}
}
`

const DEFAULT_TUI = `{
  "theme": "obsidian"
}
`

// 首次运行检测 + 初始化: 返回 true 表示发生了首跑(数据目录此前不存在)
export async function ensureFirstRun(): Promise<boolean> {
  const data = dataDir()
  const config = configDir()

  const dataExists = await fs
    .stat(data)
    .then(() => true)
    .catch(() => false)
  if (dataExists) return false

  await fs.mkdir(data, { recursive: true })
  await fs.mkdir(path.join(data, "log"), { recursive: true })
  await fs.mkdir(config, { recursive: true })

  // 写入默认配置(仅在不存在时)
  const configFile = path.join(config, "obsidian.json")
  const backendsFile = path.join(config, "obsidian.backends.jsonc")
  const tuiFile = path.join(config, "tui.json")

  await fs.writeFile(configFile, DEFAULT_CONFIG, { flag: "wx" }).catch(() => {})
  await fs.writeFile(backendsFile, DEFAULT_BACKENDS, { flag: "wx" }).catch(() => {})
  await fs.writeFile(tuiFile, DEFAULT_TUI, { flag: "wx" }).catch(() => {})

  return true
}

// Windows 双击 exe 场景: cwd 是 exe 所在目录, 尝试切到用户的项目目录(或家目录)
// 编译产物构建期注入 OPENCODE_WORKER_PATH(裸标识符被 define 替换); dev 模式该标识符未定义 → 跳过, 避免破坏源码运行
declare const OPENCODE_WORKER_PATH: string | undefined
export async function fixCwd(): Promise<string | undefined> {
  if (process.platform !== "win32") return
  if (typeof OPENCODE_WORKER_PATH !== "string") return // dev 模式(源码运行)
  const exeDir = process.cwd()
  const home = os.homedir()
  if (exeDir === home) return
  // exe 通常装在 Downloads/或 Program Files, 双击时从这里启动没有意义
  try {
    process.chdir(home)
    return home
  } catch {
    return
  }
}
