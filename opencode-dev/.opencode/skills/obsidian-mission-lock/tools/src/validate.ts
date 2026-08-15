/**
 * Contract schema validator.
 *
 * Hand-rolled, dependency-free validator against the mission-contract
 * contract (schemas/output.schema.json#/$defs/contract). We do NOT pull a
 * full JSON-Schema engine: the contract is fixed and small, and a
 * purpose-built validator gives better error messages with zero deps and
 * full offline determinism. The .schema.json files remain the human/controller
 * readable contract; this module is its executable twin. Any drift between
 * the two is caught by tests/test-contract.ts.
 */

import { EPISTEMIC_LABELS, type MissionContract } from "./types"

export interface ValidationIssue {
  path: string
  message: string
}

const SEMVER_RE = /^\d+\.\d+\.\d+$/

function isStr(v: unknown): v is string {
  return typeof v === "string" && v.length > 0
}

function isStrArray(v: unknown): boolean {
  return Array.isArray(v) && v.every((x) => typeof x === "string")
}

function validateQuantity(v: unknown, path: string, issues: ValidationIssue[]): void {
  if (typeof v !== "object" || v === null) {
    issues.push({ path, message: "expected Quantity object {value, unit}" })
    return
  }
  const q = v as Record<string, unknown>
  if (typeof q.value !== "number" || !Number.isFinite(q.value)) {
    issues.push({ path: `${path}.value`, message: "value must be a finite number (NaN/Infinity rejected)" })
  }
  if (!isStr(q.unit)) {
    issues.push({ path: `${path}.unit`, message: "unit must be a non-empty string" })
  }
}

function validateStatement(v: unknown, path: string, issues: ValidationIssue[]): void {
  if (typeof v !== "object" || v === null) {
    issues.push({ path, message: "expected Statement object {text, label}" })
    return
  }
  const s = v as Record<string, unknown>
  if (!isStr(s.text)) issues.push({ path: `${path}.text`, message: "text must be a non-empty string" })
  if (!EPISTEMIC_LABELS.includes(s.label as never)) {
    issues.push({
      path: `${path}.label`,
      message: `label must be one of ${EPISTEMIC_LABELS.join("|")}; got ${JSON.stringify(s.label)}`,
    })
  }
  // Epistemic discipline: INFERRED/HYPOTHESIS/RECOMMENDATION must not masquerade
  // as OBSERVED — enforced semantically at review time; here we require that
  // OBSERVED/REPORTED statements name a source so they're auditable.
  if ((s.label === "OBSERVED" || s.label === "REPORTED") && !isStr(s.source)) {
    issues.push({
      path: `${path}.source`,
      message: `${String(s.label)} statements must cite a source (instrument, dataset, or reference)`,
    })
  }
}

export function validateContract(c: unknown): { ok: boolean; issues: ValidationIssue[] } {
  const issues: ValidationIssue[] = []
  if (typeof c !== "object" || c === null) {
    return { ok: false, issues: [{ path: "$", message: "contract must be an object" }] }
  }
  const k = c as Record<string, unknown>

  if (!isStr(k.task_id)) issues.push({ path: "$.task_id", message: "required non-empty string" })
  if (!isStr(k.contract_version) || !SEMVER_RE.test(k.contract_version)) {
    issues.push({ path: "$.contract_version", message: "required semver string (e.g. 1.0.0)" })
  }
  if (!isStr(k.title)) issues.push({ path: "$.title", message: "required non-empty string" })
  if (!["research", "engineering", "decision", "mixed"].includes(k.mission_type as string)) {
    issues.push({ path: "$.mission_type", message: "must be research|engineering|decision|mixed" })
  }

  if (!Array.isArray(k.objectives) || k.objectives.length === 0) {
    issues.push({ path: "$.objectives", message: "must be a non-empty array" })
  } else {
    const ids = new Set<string>()
    k.objectives.forEach((o, i) => {
      if (typeof o !== "object" || o === null) {
        issues.push({ path: `$.objectives[${i}]`, message: "expected object" })
        return
      }
      const ob = o as Record<string, unknown>
      if (!isStr(ob.id)) issues.push({ path: `$.objectives[${i}].id`, message: "required" })
      else if (ids.has(ob.id)) issues.push({ path: `$.objectives[${i}].id`, message: `duplicate objective id "${ob.id}"` })
      else ids.add(ob.id)
      if (!isStr(ob.statement)) issues.push({ path: `$.objectives[${i}].statement`, message: "required" })
      if (!["scientific", "engineering", "decision"].includes(ob.kind as string)) {
        issues.push({ path: `$.objectives[${i}].kind`, message: "must be scientific|engineering|decision" })
      }
      if (!isStrArray(ob.depends_on)) issues.push({ path: `$.objectives[${i}].depends_on`, message: "must be string[]" })
    })
    // referential integrity
    if (isStr(k.primary_objective_id) && !ids.has(k.primary_objective_id)) {
      issues.push({ path: "$.primary_objective_id", message: `references unknown objective "${k.primary_objective_id}"` })
    }
    if (Array.isArray(k.secondary_objective_ids)) {
      k.secondary_objective_ids.forEach((id, i) => {
        if (!ids.has(id as string)) {
          issues.push({ path: `$.secondary_objective_ids[${i}]`, message: `references unknown objective "${String(id)}"` })
        }
      })
    }
    k.objectives.forEach((o, i) => {
      const deps = (o as { depends_on?: string[] }).depends_on ?? []
      deps.forEach((d, j) => {
        if (!ids.has(d)) {
          issues.push({ path: `$.objectives[${i}].depends_on[${j}]`, message: `references unknown objective "${d}"` })
        }
      })
    })
  }

  if (!isStr(k.primary_objective_id)) issues.push({ path: "$.primary_objective_id", message: "required" })
  if (!isStrArray(k.secondary_objective_ids)) issues.push({ path: "$.secondary_objective_ids", message: "must be string[]" })
  if (!isStrArray(k.explicit_exclusions) || (k.explicit_exclusions as string[]).length === 0) {
    issues.push({ path: "$.explicit_exclusions", message: "at least one explicit exclusion is required — a mission that excludes nothing will drift" })
  }
  if (!isStrArray(k.success_criteria) || (k.success_criteria as string[]).length === 0) {
    issues.push({ path: "$.success_criteria", message: "at least one success criterion required" })
  }
  if (!isStrArray(k.failure_thresholds) || (k.failure_thresholds as string[]).length === 0) {
    issues.push({ path: "$.failure_thresholds", message: "at least one failure threshold required" })
  }
  if (!isStrArray(k.stop_conditions) || (k.stop_conditions as string[]).length === 0) {
    issues.push({ path: "$.stop_conditions", message: "at least one stop condition required" })
  }
  if (!isStrArray(k.human_approval_gates)) issues.push({ path: "$.human_approval_gates", message: "must be string[]" })
  if (!isStrArray(k.stakeholders)) issues.push({ path: "$.stakeholders", message: "must be string[]" })
  if (!isStrArray(k.unknowns)) issues.push({ path: "$.unknowns", message: "must be string[] (may be empty only if contract.explicit_exclusions covers scope)" })
  if (!isStrArray(k.evidence_gaps)) issues.push({ path: "$.evidence_gaps", message: "must be string[]" })
  if (!isStrArray(k.domain_tags)) issues.push({ path: "$.domain_tags", message: "must be string[]" })
  if (!isStr(k.decision_use)) issues.push({ path: "$.decision_use", message: "required — what decision this research informs" })

  if (!Array.isArray(k.metrics) || (k.metrics as unknown[]).length === 0) {
    issues.push({ path: "$.metrics", message: "must be a non-empty array — every mission needs at least one measurable metric (success threshold)" })
  } else {
    k.metrics.forEach((m, i) => {
      if (typeof m !== "object" || m === null) {
        issues.push({ path: `$.metrics[${i}]`, message: "expected object" })
        return
      }
      const me = m as Record<string, unknown>
      if (!isStr(me.name)) issues.push({ path: `$.metrics[${i}].name`, message: "required" })
      if (!["maximize", "minimize", "maintain", "report"].includes(me.direction as string)) {
        issues.push({ path: `$.metrics[${i}].direction`, message: "must be maximize|minimize|maintain|report" })
      }
      if (me.target !== undefined) validateQuantity(me.target, `$.metrics[${i}].target`, issues)
      if (me.threshold !== undefined) validateQuantity(me.threshold, `$.metrics[${i}].threshold`, issues)
      if (me.current !== undefined) validateQuantity(me.current, `$.metrics[${i}].current`, issues)
    })
  }

  if (!Array.isArray(k.statements)) issues.push({ path: "$.statements", message: "must be an array" })
  else (k.statements as unknown[]).forEach((s, i) => validateStatement(s, `$.statements[${i}]`, issues))
  if (!Array.isArray(k.assumptions)) issues.push({ path: "$.assumptions", message: "must be an array" })
  else (k.assumptions as unknown[]).forEach((s, i) => validateStatement(s, `$.assumptions[${i}]`, issues))
  if (!Array.isArray(k.risks)) issues.push({ path: "$.risks", message: "must be an array" })
  else (k.risks as unknown[]).forEach((s, i) => validateStatement(s, `$.risks[${i}]`, issues))

  return { ok: issues.length === 0, issues }
}

/** Version compatibility: same major → compatible; different major → needs
 *  migration. Returns the bump type required when moving old→new. */
export function requiredBump(oldV: string, newV: string): "major" | "minor" | "patch" | "none" | "invalid" {
  const p = (v: string) => v.split(".").map((x) => parseInt(x, 10))
  if (!SEMVER_RE.test(oldV) || !SEMVER_RE.test(newV)) return "invalid"
  const [a1, b1, c1] = p(oldV)
  const [a2, b2, c2] = p(newV)
  if (a1 !== a2) return "major"
  if (b1 !== b2) return "minor"
  if (c1 !== c2) return "patch"
  return "none"
}

/** Whether output produced under contract_version `from` can be consumed by
 *  a downstream expecting `to`. Policy: same major = accept (minor/patch are
 *  additive/fix); different major = reject unless a migration is registered. */
export function isVersionCompatible(from: string, to: string, migrations: string[] = []): boolean {
  if (!SEMVER_RE.test(from) || !SEMVER_RE.test(to)) return false
  if (from.split(".")[0] === to.split(".")[0]) return true
  return migrations.includes(`${from}->${to}`)
}
