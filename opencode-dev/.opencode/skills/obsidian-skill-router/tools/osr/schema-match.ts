// Input/output schema matching between the router request and skill
// contracts. Two layers:
//
// 1. validatePayload(): structural JSON-Schema validation of router I/O.
// 2. compatibility checks: capability coverage, required-input coverage,
//    domain keyword overlap, and unit compatibility across chained steps.
//
// Matching is contract-based, never name-based: a skill named like the task
// but lacking declared capabilities/units must NOT score (acceptance gate §9.4).

import { validate, type SchemaNode, type ValidationIssue } from "./jsonschema"
import type { RegistryEntry } from "./registry"
import type { RouteRequest } from "./types"

export interface MatchContext {
  /** capability tokens the task requires (derived from request text + upstream needs) */
  requiredCapabilities: string[]
  /** input fields the router can actually supply to a skill step */
  availableInputs: string[]
  /** unit expectations inferred from upstream outputs, keyed by capability */
  expectedUnits?: Record<string, string>
}

export interface SkillMatch {
  entry: RegistryEntry
  score: number
  coveredCapabilities: string[]
  missingCapabilities: string[]
  missingInputs: string[]
  unitConflicts: { key: string; expected: string; declared: string }[]
  reason: string
}

export function validatePayload(value: unknown, schema: SchemaNode): { valid: boolean; issues: ValidationIssue[] } {
  const issues = validate(value, schema)
  return { valid: issues.length === 0, issues }
}

const STOPWORDS = new Set([
  "the", "a", "an", "and", "or", "of", "to", "in", "for", "on", "with", "is", "are", "be",
  "的", "与", "和", "或", "在", "对", "为", "是", "了", "将", "并", "及", "其", "中", "上",
])

export function tokenize(text: string): string[] {
  return text
    .toLowerCase()
    .split(/[^a-z0-9一-鿿]+/u)
    .map((t) => t.trim())
    .filter((t) => t.length >= 2 && !STOPWORDS.has(t))
}

/**
 * Score one registry entry against the match context.
 * score = 3*capabilityCoverage + 2*inputCoverage + 1*keywordOverlap - 4*unitConflicts
 * A skill with a unit conflict or zero capability coverage is excluded by the
 * caller; score only ranks the survivors.
 */
export function matchSkill(entry: RegistryEntry, ctx: MatchContext, requestText: string): SkillMatch {
  const manifest = entry.manifest ?? {}
  const declared = new Set(manifest.capabilities ?? [])
  const covered = ctx.requiredCapabilities.filter((c) => declared.has(c))
  const missing = ctx.requiredCapabilities.filter((c) => !declared.has(c))

  const declaredInputs = new Set(manifest.inputs_required ?? [])
  const missingInputs = (manifest.inputs_required ?? []).filter((i) => !ctx.availableInputs.includes(i))
  const inputCoverage = declaredInputs.size === 0 ? 1 : (declaredInputs.size - missingInputs.length) / declaredInputs.size

  const unitConflicts: { key: string; expected: string; declared: string }[] = []
  if (ctx.expectedUnits && manifest.units) {
    for (const [key, expected] of Object.entries(ctx.expectedUnits)) {
      const declaredUnit = manifest.units[key]
      if (declaredUnit !== undefined && declaredUnit !== expected) {
        unitConflicts.push({ key, expected, declared: declaredUnit })
      }
    }
  }

  const reqTokens = new Set(tokenize(requestText))
  const keywords = [...(manifest.domain_keywords ?? []), ...tokenize(entry.description)]
  const overlap = keywords.filter((k) => reqTokens.has(k.toLowerCase())).length
  const keywordScore = keywords.length === 0 ? 0 : Math.min(1, overlap / Math.min(5, keywords.length))

  const capabilityScore = ctx.requiredCapabilities.length === 0 ? 1 : covered.length / ctx.requiredCapabilities.length
  // 单位冲突是硬否决:即使能力/输入/关键词全命中,分数也必须 ≤ 0(契约优先,验收门槛 §9.4)。
  const unitPenalty = unitConflicts.length > 0 ? -1000 : 0
  const score =
    3 * capabilityScore + 2 * inputCoverage + 1 * keywordScore + unitPenalty - (entry.usable ? 0 : 100)

  const reason = [
    `capabilities ${covered.length}/${ctx.requiredCapabilities.length}`,
    `inputs ${declaredInputs.size - missingInputs.length}/${declaredInputs.size}`,
    `keywords ${overlap}`,
    unitConflicts.length > 0 ? `UNIT CONFLICT x${unitConflicts.length}` : "units ok",
  ].join("; ")

  return { entry, score, coveredCapabilities: covered, missingCapabilities: missing, missingInputs, unitConflicts, reason }
}

/**
 * Rank all usable entries. Callers must treat entries with score<=0 or any
 * unit conflict as non-candidates.
 */
export function rankSkills(entries: RegistryEntry[], ctx: MatchContext, requestText: string): SkillMatch[] {
  return entries
    .map((e) => matchSkill(e, ctx, requestText))
    .sort((a, b) => b.score - a.score || a.entry.name.localeCompare(b.entry.name))
}

/** Structural check that a value satisfies a skill's declared required inputs. */
export function checkSkillInputs(entry: RegistryEntry, availableInputs: string[]): { ok: boolean; missing: string[] } {
  const required = entry.manifest?.inputs_required ?? []
  const missing = required.filter((r) => !availableInputs.includes(r))
  return { ok: missing.length === 0, missing }
}
