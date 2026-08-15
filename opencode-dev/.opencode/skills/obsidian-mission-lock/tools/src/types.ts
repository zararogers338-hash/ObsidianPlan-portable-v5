/**
 * Shared types for obsidian-mission-lock tools.
 * Mirrors schemas/input.schema.json and schemas/output.schema.json.
 * Keep in sync: schemas are the contract; these types are the implementation view.
 */

export type EpistemicLabel =
  | "OBSERVED"
  | "REPORTED"
  | "CALCULATED"
  | "INFERRED"
  | "HYPOTHESIS"
  | "RECOMMENDATION"

export const EPISTEMIC_LABELS: readonly EpistemicLabel[] = [
  "OBSERVED",
  "REPORTED",
  "CALCULATED",
  "INFERRED",
  "HYPOTHESIS",
  "RECOMMENDATION",
]

export type Status =
  | "SUCCESS"
  | "PARTIAL"
  | "BLOCKED"
  | "FAILED"
  | "NEED_ADDITIONAL_SKILL"
  | "HUMAN_APPROVAL_REQUIRED"

export const STATUS_VALUES: readonly Status[] = [
  "SUCCESS",
  "PARTIAL",
  "BLOCKED",
  "FAILED",
  "NEED_ADDITIONAL_SKILL",
  "HUMAN_APPROVAL_REQUIRED",
]

export type RiskLevel = "low" | "medium" | "high" | "critical"

export type ApprovalState = "not_required" | "pending" | "approved" | "rejected"

/** A physical quantity with explicit unit. All numeric measurements in the
 *  contract must use this shape — bare numbers are rejected by design. */
export interface Quantity {
  value: number
  unit: string
}

export interface Metric {
  name: string
  target?: Quantity
  threshold?: Quantity
  direction: "maximize" | "minimize" | "maintain" | "report"
  current?: Quantity
  source?: string
}

export interface Statement {
  text: string
  label: EpistemicLabel
  source?: string
}

export interface Objective {
  id: string
  statement: string
  kind: "scientific" | "engineering" | "decision"
  depends_on: string[]
}

export interface MissionContract {
  task_id: string
  contract_version: string
  title: string
  mission_type: "research" | "engineering" | "decision" | "mixed"
  objectives: Objective[]
  primary_objective_id: string
  secondary_objective_ids: string[]
  explicit_exclusions: string[]
  metrics: Metric[]
  success_criteria: string[]
  failure_thresholds: string[]
  stop_conditions: string[]
  human_approval_gates: string[]
  stakeholders: string[]
  spatial_scale?: string
  temporal_scale?: string
  decision_use: string
  statements: Statement[]
  assumptions: Statement[]
  unknowns: string[]
  risks: Statement[]
  evidence_gaps: string[]
  domain_tags: string[]
}

/** Input envelope from the controller (see schemas/input.schema.json). */
export interface SkillInput {
  task_id: string
  project_id: string
  request: string
  context?: Record<string, unknown>
  constraints?: Record<string, unknown>
  evidence_refs?: string[]
  data_refs?: string[]
  upstream_outputs?: unknown[]
  requested_output_format?: "json" | "yaml" | "markdown"
  risk_level?: RiskLevel
  human_approval_state?: ApprovalState
  skill_version: string
  controller_version?: string
  timestamp: string
  prior_contract?: MissionContract
}

/** Output envelope to the controller (see schemas/output.schema.json). */
export interface SkillOutput {
  status: Status
  summary: string
  findings: Statement[]
  assumptions: Statement[]
  evidence_used: string[]
  uncertainty: { level: "low" | "medium" | "high"; notes: string }
  risks: Statement[]
  artifacts: { path: string; kind: string; description: string }[]
  requested_next_skills: { skill: string; reason: string; required_inputs: string[] }[]
  validation: {
    schema_passed: boolean
    self_check_passed: boolean
    tool_calls: { tool: string; ok: boolean; note?: string }[]
  }
  provenance: {
    skill: string
    skill_version: string
    contract_version: string
    timestamp: string
    tools_used: string[]
  }
  errors: { code: string; message: string; retryable: boolean; details?: Record<string, unknown> }[]
  contract?: MissionContract
  conflict_matrix?: ConflictEntry[]
  missing_inputs?: MissingField[]
  clarification_questions?: string[]
}

export interface ConflictEntry {
  id: string
  between: string[]
  kind: "metric-metric" | "constraint-constraint" | "metric-constraint" | "goal-contradiction" | "domain-blindspot"
  description: string
  severity: "hard" | "soft"
  resolution: "unresolved" | "human_decision_required" | "relaxed"
}

export interface MissingField {
  field: string
  why_critical: string
  how_to_obtain: string
  blocking: boolean
}
