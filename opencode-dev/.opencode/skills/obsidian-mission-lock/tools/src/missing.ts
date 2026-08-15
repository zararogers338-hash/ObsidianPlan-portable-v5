/**
 * Missing-field detector.
 *
 * Given the raw skill input and a (possibly partial) contract draft,
 * determine which fields are missing, WHY each is critical, and HOW to
 * obtain it. Never ends with a bare "insufficient information" — every
 * gap is actionable.
 *
 * Domain hints (S12) extend the generic checklist when MICP tags present.
 */

import type { MissionContract, MissingField, SkillInput } from "./types"

interface Check {
  field: string
  why: string
  how: string
  blocking: boolean
  present: (input: SkillInput, contract: Partial<MissionContract> | undefined) => boolean
}

const CHECKS: Check[] = [
  {
    field: "request",
    why: "The raw natural-language request is the object of the entire delimitation process",
    how: "Controller must pass the user's original request text verbatim",
    blocking: true,
    present: (i) => typeof i.request === "string" && i.request.trim().length > 0,
  },
  {
    field: "task_id",
    why: "Without a unique task ID the contract cannot be versioned, audited, or diffed",
    how: "Controller generates a UUID/ULID at task creation",
    blocking: true,
    present: (i) => typeof i.task_id === "string" && i.task_id.trim().length > 0,
  },
  {
    field: "project_id",
    why: "Contracts are scoped to a project; cross-project reuse without scoping causes silent context bleed",
    how: "Controller's project registry",
    blocking: true,
    present: (i) => typeof i.project_id === "string" && i.project_id.trim().length > 0,
  },
  {
    field: "contract.objectives",
    why: "A mission without decomposed objectives cannot be checked for scope drift later",
    how: "LLM decomposes request into scientific/engineering/decision objectives during lock phase",
    blocking: true,
    present: (_i, c) => Array.isArray(c?.objectives) && c.objectives.length > 0,
  },
  {
    field: "contract.metrics",
    why: "Without measurable metrics there is no success criterion — the mission can never be declared done or failed",
    how: "Derive from request quantities; if none present, mark blocking and ask user for target performance values",
    blocking: true,
    present: (_i, c) => Array.isArray(c?.metrics) && c.metrics.length > 0,
  },
  {
    field: "contract.metrics[].target",
    why: "A metric with no target value is a wish, not a criterion (SMART: must be measurable, S8)",
    how: "User supplies target; or contract marks the metric as UNKNOWN with an explicit plan to determine it",
    blocking: true,
    present: (_i, c) => Array.isArray(c?.metrics) && c.metrics.every((m) => m.target !== undefined),
  },
  {
    field: "contract.failure_thresholds",
    why: "Without failure thresholds, a failing mission burns budget indefinitely",
    how: "Set per-metric minimum-acceptable values or global abort rules",
    blocking: true,
    present: (_i, c) => Array.isArray(c?.failure_thresholds) && c.failure_thresholds.length > 0,
  },
  {
    field: "contract.stop_conditions",
    why: "Stop conditions bound cost and enable clean termination independent of success/failure",
    how: "Budget cap, time cap, max iterations, or evidence-sufficiency condition",
    blocking: true,
    present: (_i, c) => Array.isArray(c?.stop_conditions) && c.stop_conditions.length > 0,
  },
  {
    field: "contract.decision_use",
    why: "The final decision the research informs determines required evidence level and acceptable uncertainty",
    how: "Ask: 'what decision will be made with these results, and by whom?'",
    blocking: true,
    present: (_i, c) => typeof c?.decision_use === "string" && c.decision_use.length > 0,
  },
  {
    field: "contract.spatial_scale",
    why: "Lab/column/field scale changes which physics and which validation methods apply (S9)",
    how: "Extract from request; if absent ask for specimen size or site dimensions",
    blocking: false,
    present: (_i, c) => typeof c?.spatial_scale === "string" && c.spatial_scale.length > 0,
  },
  {
    field: "contract.temporal_scale",
    why: "Duration bounds (curing time, monitoring window) define the experiment matrix and cost",
    how: "Extract from request; if absent ask for target timeframe",
    blocking: false,
    present: (_i, c) => typeof c?.temporal_scale === "string" && c.temporal_scale.length > 0,
  },
  {
    field: "contract.stakeholders",
    why: "Approval gates and success criteria are meaningless without knowing who accepts the result",
    how: "Ask user / project registry; at minimum the requesting party",
    blocking: false,
    present: (_i, c) => Array.isArray(c?.stakeholders) && c.stakeholders.length > 0,
  },
  {
    field: "human_approval_state",
    why: "High-risk missions (field deployment, live bio experiments, hazardous chemicals) require an explicit approval gate before any downstream skill runs",
    how: "Controller sets 'approved' after human review; skill defaults to 'not_required' only for low-risk desk research",
    blocking: false, // blocking only when risk_level is high/critical — evaluated separately
    present: (i) => i.human_approval_state !== undefined,
  },
]

/** MICP-specific checks, applied only when domain_tags include micp-related tags. */
const MICP_CHECKS: Check[] = [
  {
    field: "micp.pathway",
    why: "Ureolytic vs non-ureolytic pathways have different stoichiometry, kinetics, and risk profiles (S13); models are not interchangeable",
    how: "Declare in context.pathway: 'ureolysis' | 'denitrification' | 'eicp' | 'other'; if undecided, scope a pathway-selection sub-study",
    blocking: true,
    present: (i) => typeof i.context?.pathway === "string",
  },
  {
    field: "micp.matrix",
    why: "Porous-medium type (sand/clay/rock fracture/concrete) governs injectability, retention, and which transport model applies (S12)",
    how: "Specify soil/rock type, gradation or fracture aperture in context.matrix",
    blocking: true,
    present: (i) => i.context?.matrix !== undefined,
  },
  {
    field: "micp.performance_metric",
    why: "MICP 'effectiveness' is meaningless until bound to a measurable engineering property (UCS, permeability, stiffness, durability) — see S11 for typical ranges",
    how: "Choose metric + target + unit; typical UCS gains 30–65%, permeability reductions 1–2 orders of magnitude (S11) as reasonableness reference only",
    blocking: true,
    present: (i, c) => Array.isArray(c?.metrics) && c.metrics.length > 0,
  },
  {
    field: "micp.environmental_constraints",
    why: "Ureolytic MICP emits NH₄⁺ (S10); sites with discharge limits must declare them before pathway selection",
    how: "Provide discharge/groundwater nitrogen limits in constraints, or state explicitly that none apply",
    blocking: false,
    present: (i) => i.constraints !== undefined && Object.keys(i.constraints).some((k) => /ammonia|nitrogen|nh4|discharge|emission|氨|氮|排放/i.test(k)),
  },
  {
    field: "micp.nitrogen_balance",
    why: "Ureolysis produces 2 mol NH₄⁺ per mol urea (S10); a contract that declares the urea pathway without addressing nitrogen mass conservation (in risks, metrics, or mitigations) has a mass-balance blind spot",
    how: "Add an explicit nitrogen/ammonium tracking item to contract.risks or contract.metrics (e.g. risk 'NH₄⁺ accumulation in effluent', or metric 'NH₄⁺ concentration, target ≤ discharge limit')",
    blocking: false,
    present: (i, c) => {
      const pathwayIsUrea = typeof i.context?.pathway === "string" && /urea|ureolysis|水解/i.test(i.context.pathway)
      const domainIsUrea = Array.isArray(c?.domain_tags) && c.domain_tags.some((t) => /urea|ureolysis|水解|尿素/i.test(t))
      const isUrea = pathwayIsUrea || domainIsUrea
      if (!isUrea) return true // non-urea pathway → check not applicable
      const tracked = [...(c?.risks ?? []), ...(c?.metrics ?? []), ...(c?.statements ?? [])]
      return /ammonia|ammonium|nh4|nitrogen|氨|铵|氮/i.test(JSON.stringify(tracked))
    },
  },
]

const MICP_TAG_RE = /micp|biocement|carbonate|calcite|urease|ureolysis|微生物|矿化|碳酸钙/i

export function isMicpDomain(input: SkillInput, contract?: Partial<MissionContract>): boolean {
  const text = [
    input.request,
    ...(contract?.domain_tags ?? []),
    JSON.stringify(input.context ?? {}),
  ].join(" ")
  return MICP_TAG_RE.test(text)
}

export function detectMissingFields(input: SkillInput, contract?: Partial<MissionContract>): MissingField[] {
  const active = isMicpDomain(input, contract) ? [...CHECKS, ...MICP_CHECKS] : CHECKS
  const missing = active
    .filter((c) => !c.present(input, contract))
    .map((c) => ({ field: c.field, why_critical: c.why, how_to_obtain: c.how, blocking: c.blocking }))

  // Approval gate is blocking when risk is high/critical
  if ((input.risk_level === "high" || input.risk_level === "critical") && input.human_approval_state !== "approved") {
    const existing = missing.find((m) => m.field === "human_approval_state")
    if (existing) {
      existing.blocking = true
      existing.why_critical = `Risk level is ${input.risk_level}: proceeding without completed human approval violates the approval-gate rule`
    } else {
      missing.push({
        field: "human_approval_state",
        why_critical: `Risk level is ${input.risk_level}: an explicit human approval gate is mandatory before the contract can be released to execution skills`,
        how_to_obtain: "Controller routes the draft contract to a human reviewer; sets human_approval_state='approved' on acceptance",
        blocking: true,
      })
    }
  }
  return missing
}
