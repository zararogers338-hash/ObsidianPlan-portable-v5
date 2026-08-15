#!/usr/bin/env bun
// osr.ts — top-level CLI for the obsidian-skill-router tool suite.
//
// Subcommands (all offline-capable):
//   registry --build [--roots a --roots b] [--write <file>]
//       Scan skill roots and print a deterministic registry snapshot.
//   route [--input <file.json>]
//       Route a request (stdin JSON object or --input file) through the full
//       validation → planning → self-check pipeline.
//   verify <decisions.jsonl>
//       Verify the hash chain of a decision log.
//   check-self <json-file>
//       Validate a JSON file against output.schema.json (self-check helper).

import { promises as fs } from "node:fs"
import path from "node:path"
import { indexRegistry, loadSnapshot, REGISTRY_SNAPSHOT_FORMAT } from "../osr/registry"
import { verifyChain } from "../osr/decision-log"
import { validate } from "../osr/jsonschema"

const HERE = path.resolve(__dirname, "..", "..")
const DEFAULT_ROOTS = [
  path.resolve(HERE, "..", "..", ".opencode", "skills"),
  path.resolve(HERE, "..", "..", "skills"),
]

async function main(): Promise<number> {
  const [cmd, ...rest] = process.argv.slice(2)
  if (!cmd) {
    process.stderr.write(usage())
    return 1
  }
  switch (cmd) {
    case "registry": {
      const args = rest
      const roots: string[] = []
      for (let i = 0; i < args.length; i++) {
        if (args[i] === "--roots") {
          roots.push(path.resolve(args[i + 1] ?? ""))
          i++
        }
      }
      const writeIdx = args.indexOf("--write")
      const writeFile = writeIdx >= 0 ? path.resolve(args[writeIdx + 1] ?? "") : undefined
      const targets = roots.length > 0 ? roots : DEFAULT_ROOTS
      const { snapshot, issues } = await indexRegistry(targets)
      if (issues.length > 0) {
        for (const issue of issues) process.stderr.write(`registry issue: ${issue.path}: ${issue.message}\n`)
      }
      if (writeFile) {
        await fs.mkdir(path.dirname(writeFile), { recursive: true })
        await fs.writeFile(writeFile, JSON.stringify(snapshot, null, 2) + "\n", "utf8")
        process.stdout.write(`registry snapshot written: ${writeFile} (${snapshot.entries.length} entries, id ${snapshot.snapshot_id})\n`)
      } else {
        process.stdout.write(JSON.stringify(snapshot, null, 2) + "\n")
      }
      return issues.some((i) => i.message.includes("duplicate") || i.message.includes("not readable")) ? 1 : 0
    }
    case "route": {
      const inputIdx = rest.indexOf("--input")
      let raw: unknown
      if (inputIdx >= 0) {
        raw = JSON.parse(await fs.readFile(path.resolve(rest[inputIdx + 1] ?? ""), "utf8"))
      } else {
        const text = await new Promise<string>((resolve, reject) => {
          const chunks: Buffer[] = []
          process.stdin.on("data", (c: Buffer) => chunks.push(c))
          process.stdin.on("end", () => resolve(Buffer.concat(chunks).toString("utf8")))
          process.stdin.on("error", reject)
        })
        raw = JSON.parse(text)
      }
      const { route } = await import("../osr/service")
      const logDir = path.join(HERE, "logs", "decisions")
      const artifactDir = path.join(HERE, "state", "plans")
      const result = await route(raw, { registryRoots: DEFAULT_ROOTS, logDir, artifactDir })
      process.stdout.write(JSON.stringify(result.response, null, 2) + "\n")
      return ["FAILED", "BLOCKED"].includes(result.response.status) ? 2 : 0
    }
    case "verify": {
      const file = rest[0]
      if (!file) {
        process.stderr.write("verify requires a decision log path\n")
        return 1
      }
      const result = await verifyChain(path.resolve(file))
      process.stdout.write(JSON.stringify(result, null, 2) + "\n")
      return result.ok ? 0 : 1
    }
    case "check-self": {
      const file = rest[0]
      if (!file) {
        process.stderr.write("check-self requires a JSON file path\n")
        return 1
      }
      const schema = JSON.parse(
        await fs.readFile(path.join(HERE, "schemas", "output.schema.json"), "utf8"),
      ) as Record<string, unknown>
      const value = JSON.parse(await fs.readFile(path.resolve(file), "utf8"))
      const issues = validate(value, schema)
      if (issues.length > 0) {
        for (const issue of issues) process.stderr.write(`${issue.path}: ${issue.message}\n`)
        return 1
      }
      process.stdout.write("output schema: OK\n")
      return 0
    }
    default:
      process.stderr.write(usage())
      return 1
  }
}

function usage(): string {
  return `osr — obsidian-skill-router tool suite v1.0.0
  registry --build [--roots <dir>]... [--write <file.json>]   scan skill roots
  route [--input <file.json>]                                 route a request (stdin default)
  verify <decisions.jsonl>                                    verify a decision log chain
  check-self <json-file>                                      validate JSON against output schema
`
}

main().then((code) => {
  process.exitCode = code
})
