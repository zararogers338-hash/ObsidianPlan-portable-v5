// Shared domain types for obsidian-skill-router.
// These mirror schemas/input.schema.json and schemas/output.schema.json;
// the JSON Schemas are the contract, these types are the implementation.

export type EpistemicLabel =
  | "OBSERVED"
  | "REPORTED"
  | "CALCULATED"
  | "INFERRED"
  | "HYPOTHESIS"
  | "RECOMMENDATION"

export type RiskLevel = "low" | "medium" | "high" | "critical"

export type ApprovalState = "not_required" | "pending" | "approved" | "rejected"

export type RouteStatus =
  | "SUCCESS"
  | "PARTIAL"
  | "BLOCKED"
  | "FAILED"
  | "NEED_ADDITIONAL_SKILL"
  | "HUMAN_APPROVAL_REQUIRED"

export type ExecutionMode = "sequential" | "parallel" | "vote" | "cross_review" | "primary_support"

export type OutputFormat = "route_plan" | "capability_gap_spec" | "conflict_report" | "audit_report"

export interface Ref {
  ref_id: string
  uri?: string
  media_type?: string
  note?: string
}

export interface UpstreamOutput {
  skill: string
  task_node: string
  output_ref?: Ref
  output?: Record<string, unknown>
  summary?: string
}

export interface BudgetOverride {
  max_depth?: number
  max_total_calls?: number
  max_retries_per_skill?: number
  max_parallel?: number
  max_tokens_total?: number
  max_cost_usd_total?: number
  max_wall_time_sec?: number
}

export interface Constraints {
  max_depth?: number
  max_total_calls?: number
  max_retries_per_skill?: number
  max_parallel?: number
  max_tokens_total?: number
  max_cost_usd_total?: number
  max_wall_time_sec?: number
  forbidden_skills?: string[]
  required_skills?: string[]
  deadline?: string
  budget?: BudgetOverride
}

export interface RouterContext {
  task_graph?: Record<string, unknown>
  memory_refs?: Ref[]
  call_chain?: string[]
  completed_calls?: CompletedCall[]
  prior_decisions?: Record<string, unknown>[]
  environment?: Record<string, unknown>
  [key: string]: unknown
}

export interface CompletedCall {
  skill: string
  input_digest: string
  status: RouteStatus | string
  tokens_used?: number
  cost_usd_used?: number
  retries_used?: number
  depth?: number
  output_summary?: string
}

export interface RouteRequest {
  task_id: string
  project_id: string
  request: string
  context?: RouterContext
  constraints?: Constraints
  evidence_refs?: Ref[]
  data_refs?: Ref[]
  upstream_outputs?: UpstreamOutput[]
  requested_output_format?: OutputFormat
  risk_level?: RiskLevel
  human_approval_state?: ApprovalState
  skill_version: string
  controller_version: string
  timestamp: string
}

export interface LabeledStatement {
  statement: string
  label: EpistemicLabel
}

export interface RouteStep {
  step_id: string
  skill: string
  reason: string
  input_summary: string
  expected_artifacts: string[]
  budget: {
    est_tokens: number
    est_cost_usd: number
    max_retries: number
    timeout_sec: number
  }
  depends_on: string[]
  approval_required: boolean
  permission_request: {
    tools: string[]
    network: boolean
    writes: string[]
  }
}

export interface RoutePlan {
  plan_id: string
  mode: ExecutionMode
  steps: RouteStep[]
  guards: string[]
  total_budget: {
    est_tokens: number
    est_cost_usd: number
    max_wall_time_sec: number
  }
}

export interface CapabilityGapSpec {
  missing_capability: string
  required_inputs: string[]
  required_outputs: string[]
  required_tools: string[]
  domain_context: string
  suggested_name: string
  risk_notes: string
}

export interface ValidationReport {
  self_check_passed: boolean
  output_schema_valid: boolean
  checks: { name: string; passed: boolean; detail?: string }[]
}

export interface Provenance {
  registry_snapshot_id: string
  decision_log_ref: string
  router_version: string
  registry_version: string
}

export interface RouteResponse {
  status: RouteStatus
  summary: string
  findings: LabeledStatement[]
  assumptions: LabeledStatement[]
  evidence_used: Ref[]
  uncertainty: string[]
  risks: string[]
  artifacts: Ref[]
  requested_next_skills: string[]
  route_plan?: RoutePlan
  capability_gap_spec?: CapabilityGapSpec
  validation: ValidationReport
  provenance: Provenance
  errors: import("./errors").OsError[]
}
