// OSR CLI adapter: the only file with process/stdout/stderr access.
// Reads a JSON object from stdin (or --input FILE), emits the RouteResponse
// envelope to stdout, and returns a stable exit code:
//   0 SUCCESS / NEED_ADDITIONAL_SKILL / HUMAN_APPROVAL_REQUIRED (soft statuses)
//   2 FAILED / BLOCKED (hard statuses)
//   3 OSR-E001 input schema invalid
//   4 internal/unexpected (including broken output self-check)

import { createRequire } from "node:module"
import { promises as fs } from "node:fs"
import path from "node:path"

const require = createRequire(import.meta.url)
const pkg = require("../../package.json") as { name: string; version: string }
export const CLI_VERSION = pkg.version

import { route, validateOutput } from "./service"

async function readStdin(): Promise<string> {
  return new Promise((resolve, reject) => {
    const chunks: Buffer[] = []
    process.stdin.on("data", (c: Buffer) => chunks.push(c))
    process.stdin.on("end", () => resolve(Buffer.concat(chunks).toString("utf8")))
    process.stdin.on("error", reject)
  })
}

async function main(): Promise<number> {
  const args = process.argv.slice(2)
  let raw: unknown
  if (args.includes("--input")) {
    const idx = args.indexOf("--input")
    const file = args[idx + 1]
    if (!file) {
      process.stderr.write("--input requires a file path\n")
      return 4
    }
    raw = JSON.parse(await fs.readFile(path.resolve(file), "utf8"))
  } else {
    const text = await readStdin()
    if (text.trim() === "") {
      process.stderr.write("empty stdin; provide a JSON object per input.schema.json\n")
      return 4
    }
    raw = JSON.parse(text)
  }

  const defaults: Record<string, unknown> = {
    requested_output_format: "route_plan",
    risk_level: "medium",
    human_approval_state: "not_required",
  }
  if (typeof raw === "object" && raw !== null && !Array.isArray(raw)) {
    for (const [k, v] of Object.entries(defaults)) {
      if (!(k in (raw as Record<string, unknown>))) (raw as Record<string, unknown>)[k] = v
    }
  }

  const projectRoot = path.resolve(__dirname, "..", "..")
  const registryRoots = [path.join(projectRoot, "..", "..", ".opencode", "skills"), path.join(projectRoot, "..", "..", "skills")]
  const logDir = path.join(projectRoot, "logs", "decisions")
  const artifactDir = path.join(projectRoot, "state", "plans")

  const result = await route(raw, { registryRoots, logDir, artifactDir })
  const response = result.response
  process.stdout.write(JSON.stringify(response, null, 2) + "\n")

  const outValidation = validateOutput(response)
  if (!outValidation.valid) {
    process.stderr.write(`OUTPUT SELF-CHECK FAILED: ${outValidation.issues.map((i) => i.message).join("; ")}\n`)
    return 4
  }
  if (response.validation && !response.validation.self_check_passed) {
    process.stderr.write(
      `SELF-CHECK FAILED: ${response.validation.checks.filter((c) => !c.passed).map((c) => c.name).join(", ")}\n`,
    )
    return 4
  }

  switch (response.status) {
    case "FAILED":
    case "BLOCKED":
      return 2
    default:
      return 0
  }
}

main()
  .then((code) => {
    process.exitCode = code
  })
  .catch((err) => {
    process.stderr.write(`OSR CLI fatal: ${(err as Error).stack ?? String(err)}\n`)
    process.exitCode = 4
  })
