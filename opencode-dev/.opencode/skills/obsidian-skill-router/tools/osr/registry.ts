// Skill Registry indexer: scans skill root directories, parses SKILL.md
// frontmatter + optional skill.yaml, validates contracts, and produces a
// deterministic, hash-stamped registry snapshot.
//
// Design rules:
// - Zero external deps; filesystem + yaml/jsonschema subset parsers only.
// - Never throws on a corrupt skill dir: collects REGISTRY_ISSUES instead, so
//   one broken skill cannot take down the router (fail-open for discovery,
//   fail-closed for routing — entries with errors are marked unusable).
// - No network. Discovery is purely local.

import { createHash } from "node:crypto"
import { promises as fs } from "node:fs"
import path from "node:path"
import { parseYAML, YAMLParseError } from "./yaml"

export const REGISTRY_SNAPSHOT_FORMAT = "osr.registry/1"

export interface SkillManifest {
  version?: string
  entry?: string
  risk_tier?: "low" | "medium" | "high" | "critical"
  capabilities?: string[]
  inputs_required?: string[]
  outputs?: string[]
  units?: Record<string, string>
  tool_permissions?: string[]
  network?: boolean
  writes?: string[]
  stop_conditions?: string[]
  compatible_controller?: string
  domain_keywords?: string[]
  dependencies?: string[]
  cost_estimate?: { tokens?: number; usd?: number }
  [key: string]: unknown
}

export interface RegistryEntry {
  name: string
  description: string
  location: string
  dir: string
  manifest?: SkillManifest
  manifest_valid: boolean
  issues: string[]
  usable: boolean
}

export interface RegistrySnapshot {
  format: string
  created_at: string
  roots: string[]
  entries: RegistryEntry[]
  snapshot_id: string
  registry_version: string
}

export interface IndexOptions {
  /** when true, entries with manifest issues are still marked usable (default false) */
  tolerant?: boolean
  /** injectable clock for deterministic tests */
  now?: () => Date
}

export interface IndexResult {
  snapshot: RegistrySnapshot
  issues: { path: string; message: string }[]
}

const NAME_RE = /^[a-z0-9]+(-[a-z0-9]+)*$/

export function sha256Hex(data: string | Buffer): string {
  return createHash("sha256").update(data).digest("hex")
}

export function digestObject(value: unknown): string {
  return sha256Hex(stableStringify(value)).slice(0, 16)
}

export function stableStringify(value: unknown): string {
  if (value === null || typeof value !== "object") return JSON.stringify(value)
  if (Array.isArray(value)) return `[${value.map(stableStringify).join(",")}]`
  const obj = value as Record<string, unknown>
  return `{${Object.keys(obj)
    .sort()
    .map((k) => `${JSON.stringify(k)}:${stableStringify(obj[k])}`)
    .join(",")}}`
}

function parseFrontmatter(content: string): { data: Record<string, unknown>; body: string } {
  const normalized = content.replace(/\r\n/g, "\n")
  if (!normalized.startsWith("---\n")) return { data: {}, body: normalized }
  const end = normalized.indexOf("\n---", 4)
  if (end === -1) return { data: {}, body: normalized }
  const raw = normalized.slice(4, end)
  const data = parseYAML(raw)
  return { data, body: normalized.slice(end + 4) }
}

async function walkSkillDirs(root: string): Promise<string[]> {
  const out: string[] = []
  const queue: string[] = [root]
  while (queue.length > 0) {
    const dir = queue.pop() as string
    let entries
    try {
      entries = await fs.readdir(dir, { withFileTypes: true })
    } catch {
      continue // unreadable dir: skip, surfaced by caller via missing roots check
    }
    const hasSkillFile = entries.some((e) => e.isFile() && e.name === "SKILL.md")
    if (hasSkillFile) {
      out.push(path.join(dir, "SKILL.md"))
      continue // do not descend into a skill package
    }
    for (const e of entries) {
      if (e.isDirectory() && !e.name.startsWith(".") && e.name !== "node_modules") {
        queue.push(path.join(dir, e.name))
      }
    }
  }
  return out.sort()
}

function validateManifest(name: string, manifest: SkillManifest): string[] {
  const issues: string[] = []
  if (manifest.version !== undefined && typeof manifest.version !== "string") {
    issues.push("manifest.version must be a string")
  }
  if (manifest.version !== undefined && !/^\d+\.\d+\.\d+$/.test(String(manifest.version))) {
    issues.push(`manifest.version "${manifest.version}" is not semver X.Y.Z`)
  }
  for (const key of ["capabilities", "inputs_required", "outputs", "tool_permissions", "writes", "stop_conditions", "domain_keywords", "dependencies"] as const) {
    const v = manifest[key]
    if (v !== undefined && (!Array.isArray(v) || v.some((x) => typeof x !== "string"))) {
      issues.push(`manifest.${key} must be an array of strings`)
    }
  }
  if (manifest.risk_tier !== undefined && !["low", "medium", "high", "critical"].includes(manifest.risk_tier)) {
    issues.push(`manifest.risk_tier "${manifest.risk_tier}" not in low|medium|high|critical`)
  }
  if (manifest.network !== undefined && typeof manifest.network !== "boolean") {
    issues.push("manifest.network must be boolean")
  }
  if (manifest.units !== undefined && (typeof manifest.units !== "object" || manifest.units === null || Array.isArray(manifest.units))) {
    issues.push("manifest.units must be an object of string->unit")
  }
  if (name === "obsidian-skill-router" && manifest.capabilities?.includes("routing")) {
    issues.push("skill may not claim the reserved capability 'routing'")
  }
  return issues
}

export async function indexRegistry(roots: string[], opts: IndexOptions = {}): Promise<IndexResult> {
  const now = opts.now ?? (() => new Date())
  const issues: { path: string; message: string }[] = []
  const entries: RegistryEntry[] = []
  const seen = new Map<string, string>()

  for (const root of roots) {
    let stat
    try {
      stat = await fs.stat(root)
    } catch {
      issues.push({ path: root, message: "registry root not readable" })
      continue
    }
    if (!stat.isDirectory()) {
      issues.push({ path: root, message: "registry root is not a directory" })
      continue
    }
    const files = await walkSkillDirs(root)
    for (const file of files) {
      const dir = path.dirname(file)
      let content: string
      try {
        content = await fs.readFile(file, "utf8")
      } catch (err) {
        issues.push({ path: file, message: `SKILL.md unreadable: ${(err as Error).message}` })
        continue
      }
      let fm: Record<string, unknown>
      try {
        fm = parseFrontmatter(content).data
      } catch (err) {
        if (err instanceof YAMLParseError) {
          issues.push({ path: file, message: `frontmatter YAML invalid: ${err.message}` })
          continue
        }
        throw err
      }
      const name = fm.name
      if (typeof name !== "string" || name === "") {
        issues.push({ path: file, message: "frontmatter missing required string field `name`" })
        continue
      }
      if (!NAME_RE.test(name) || name.length > 64) {
        issues.push({ path: file, message: `skill name "${name}" violates ^[a-z0-9]+(-[a-z0-9]+)*$ (max 64)` })
        continue
      }
      if (path.basename(dir) !== name) {
        issues.push({ path: file, message: `skill name "${name}" does not match directory "${path.basename(dir)}"` })
        continue
      }
      if (seen.has(name)) {
        issues.push({ path: file, message: `duplicate skill name "${name}" (first seen at ${seen.get(name)})` })
        continue
      }
      const description = typeof fm.description === "string" ? fm.description : ""

      let manifest: SkillManifest | undefined
      let manifestValid = true
      const manifestIssues: string[] = []
      const manifestPath = path.join(dir, "skill.yaml")
      try {
        const raw = await fs.readFile(manifestPath, "utf8")
        try {
          manifest = parseYAML(raw) as SkillManifest
          manifestIssues.push(...validateManifest(name, manifest))
        } catch (err) {
          manifestValid = false
          manifestIssues.push(err instanceof YAMLParseError ? `skill.yaml invalid: ${err.message}` : String(err))
        }
      } catch {
        // no skill.yaml: allowed, but the skill is second-class for routing
      }
      if (manifestIssues.length > 0) manifestValid = false

      const usable = description.length > 0 && (opts.tolerant === true || manifestValid)
      if (description.length === 0) {
        manifestIssues.push("missing frontmatter description (opencode filters such skills out of the model surface)")
      }
      seen.set(name, file)
      entries.push({
        name,
        description,
        location: file,
        dir,
        manifest,
        manifest_valid: manifestValid,
        issues: manifestIssues,
        usable,
      })
    }
  }

  entries.sort((a, b) => a.name.localeCompare(b.name))
  const fingerprint = stableStringify(
    entries.map((e) => ({ name: e.name, location: e.location, manifest: e.manifest ?? null, usable: e.usable })),
  )
  const snapshot: RegistrySnapshot = {
    format: REGISTRY_SNAPSHOT_FORMAT,
    created_at: now().toISOString(),
    roots: roots.map((r) => path.resolve(r)),
    entries,
    snapshot_id: `reg_${sha256Hex(fingerprint).slice(0, 16)}`,
    registry_version: sha256Hex(fingerprint).slice(0, 12),
  }
  return { snapshot, issues }
}

export async function writeSnapshot(snapshot: RegistrySnapshot, file: string): Promise<void> {
  await fs.mkdir(path.dirname(file), { recursive: true })
  await fs.writeFile(file, JSON.stringify(snapshot, null, 2) + "\n", "utf8")
}

export async function loadSnapshot(file: string): Promise<RegistrySnapshot> {
  const raw = await fs.readFile(file, "utf8")
  const parsed = JSON.parse(raw) as RegistrySnapshot
  if (parsed.format !== REGISTRY_SNAPSHOT_FORMAT) {
    throw new Error(`unsupported registry snapshot format: ${String(parsed.format)}`)
  }
  if (!Array.isArray(parsed.entries)) throw new Error("registry snapshot missing entries array")
  return parsed
}
