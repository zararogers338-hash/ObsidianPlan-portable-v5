/**
 * Minimal output-envelope validator.
 *
 * Validates the shape of a SkillOutput against the machine contract
 * (schemas/output.schema.json) without a JSON-Schema engine. Checks the
 * structural invariants the controller and downstream skills rely on.
 * Offline, deterministic.
 */

import { STATUS_VALUES, type SkillOutput } from "./types"

export interface OutputValidation {
  ok: boolean
  issues: string[]
}

export function validateOutputEnvelope(o: unknown): OutputValidation {
  const issues: string[] = []
  if (typeof o !== "object" || o === null) {
    return { ok: false, issues: ["output must be an object"] }
  }
  const out = o as Record<string, unknown>

  if (!STATUS_VALUES.includes(out.status as never)) {
    issues.push(`status must be one of ${STATUS_VALUES.join("|")}; got ${String(out.status)}`)
  }
  if (typeof out.summary !== "string" || out.summary.length === 0) {
    issues.push("summary must be a non-empty string")
  }
  if (typeof out.validation !== "object" || out.validation === null) {
    issues.push("validation object is required")
  } else {
    const v = out.validation as Record<string, unknown>
    if (typeof v.schema_passed !== "boolean") issues.push("validation.schema_passed must be boolean")
    if (typeof v.self_check_passed !== "boolean") issues.push("validation.self_check_passed must be boolean")
    if (!Array.isArray(v.tool_calls)) issues.push("validation.tool_calls must be an array")
  }
  if (typeof out.provenance !== "object" || out.provenance === null) {
    issues.push("provenance object is required")
  } else {
    const p = out.provenance as Record<string, unknown>
    if (typeof p.skill !== "string") issues.push("provenance.skill required")
    if (typeof p.skill_version !== "string") issues.push("provenance.skill_version required")
    if (typeof p.contract_version !== "string") issues.push("provenance.contract_version required")
    if (!Array.isArray(p.tools_used)) issues.push("provenance.tools_used must be an array")
  }
  if (out.errors !== undefined && !Array.isArray(out.errors)) issues.push("errors must be an array")

  // Optional structural checks on optional-but-consumed fields
  if (out.conflict_matrix !== undefined) {
    if (!Array.isArray(out.conflict_matrix)) issues.push("conflict_matrix must be an array")
    else
      for (const c of out.conflict_matrix as Record<string, unknown>[]) {
        if (typeof c.severity !== "string") issues.push("conflict.severity required")
        if (!Array.isArray(c.between) || c.between.length < 2) issues.push("conflict.between must be a 2+ array")
      }
  }
  if (out.missing_inputs !== undefined) {
    if (!Array.isArray(out.missing_inputs)) issues.push("missing_inputs must be an array")
    else
      for (const m of out.missing_inputs as Record<string, unknown>[]) {
        if (typeof m.field !== "string") issues.push("missing.field required")
        if (typeof m.blocking !== "boolean") issues.push("missing.blocking must be boolean")
      }
  }
  if (out.contract !== undefined && typeof out.contract !== "object") issues.push("contract must be an object")

  return { ok: issues.length === 0, issues }
}
