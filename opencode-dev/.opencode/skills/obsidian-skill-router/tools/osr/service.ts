// OSR service: composes validation → planning → output assembly → self-check
// → decision log into one callable. Pure of transport; the CLI adapter in
// router-cli.ts owns stdin/stdout and filesystem paths.

import { promises as fs } from "node:fs"
import path from "node:path"
import { validatePayload } from "./schema-match"
import { buildPlan, ROUTER_VERSION, type PlanResult } from "./planner"
import { indexRegistry, loadSnapshot, type RegistrySnapshot } from "./registry"
import { DecisionLog, recordHash, type DecisionRecord } from "./decision-log"
import { makeError, type OsError } from "./errors"
import { digestInput } from "./callgraph"
import { validate, type SchemaNode, type ValidationIssue } from "./jsonschema"
import type {
  RouteRequest,
  RouteResponse,
  LabeledStatement,
  Provenance,
  Ref,
  ValidationReport,
} from "./types"

export interface ServiceOptions {
  /** pre-built registry snapshot (preferred in tests); otherwise built from roots */
  snapshot?: RegistrySnapshot
  registryRoots?: string[]
  /** where decision logs are appended */
  logDir?: string
  /** where plan artifacts are written */
  artifactDir?: string
  /** decision log disabled (tests that must not touch disk) */
  disableLog?: boolean
  /** injectable clock */
  now?: () => Date
}

export interface ServiceResult {
  response: RouteResponse
  logEntry?: DecisionRecord
  artifactPath?: string
}

let inputSchemaCache: SchemaNode | undefined
let outputSchemaCache: SchemaNode | undefined

async function loadInputSchema(): Promise<SchemaNode> {
  if (!inputSchemaCache) {
    const p = path.resolve(__dirname, "..", "..", "schemas", "input.schema.json")
    inputSchemaCache = JSON.parse(await fs.readFile(p, "utf8")) as SchemaNode
  }
  return inputSchemaCache
}

async function loadOutputSchema(): Promise<SchemaNode> {
  if (!outputSchemaCache) {
    const p = path.resolve(__dirname, "..", "..", "schemas", "output.schema.json")
    outputSchemaCache = JSON.parse(await fs.readFile(p, "utf8")) as SchemaNode
  }
  return outputSchemaCache
}

export interface ValidatedInput {
  valid: boolean
  issues: ValidationIssue[]
}

export async function validateInput(raw: unknown): Promise<ValidatedInput> {
  const schema = await loadInputSchema()
  const { valid, issues } = validatePayload(raw, schema)
  return { valid, issues }
}

export async function validateOutputAsync(raw: unknown): Promise<{ valid: boolean; issues: ValidationIssue[] }> {
  const schema = await loadOutputSchema()
  return validatePayload(raw, schema)
}

export async function ensureOutputSchemaLoaded(): Promise<void> {
  await loadOutputSchema()
}

export function validateOutput(raw: unknown): { valid: boolean; issues: ValidationIssue[] } {
  if (!outputSchemaCache) return { valid: false, issues: [{ path: "", message: "output schema not loaded (call ensureOutputSchemaLoaded first)" }] }
  return validatePayload(raw, outputSchemaCache)
}

function missingFieldGuidance(field: string): string {
  const guidance: Record<string, string> = {
    task_id: "任务节点标识;由 Task Decomposer 分配,用于决策日志锚点与预算记账",
    project_id: "项目/实验标识;来自项目注册,选择决策日志文件",
    request: "要路由的自然语言任务;由 Mission Lock 产生的任务合同中的 request 字段",
    skill_version: "本 Skill(obsidian-skill-router)版本;由 SKILL.md frontmatter 声明",
    controller_version: "调用方 Obsidian Controller 版本;由控制器的版本常量注入",
    timestamp: "ISO 8601 时间戳;由控制器调用时注入",
  }
  return guidance[field] ?? "该字段由 Obsidian Controller 或上游能力按统一输入契约提供"
}

/** Build a FAILED envelope for unparseable/corrupt input; must still pass output schema. */
export async function buildInvalidInputResponse(
  raw: unknown,
  issues: ValidationIssue[],
): Promise<RouteResponse> {
  const missing = new Set<string>()
  for (const issue of issues) {
    const m = /missing required property "([^"]+)"/.exec(issue.message)
    const field = m?.[1]
    if (field) missing.add(field)
  }
  const errorDetails: Record<string, unknown> = {
    issues: issues.slice(0, 20),
    missing_fields: Array.from(missing),
    field_guidance: Object.fromEntries(
      Array.from(missing).map((f) => [f, missingFieldGuidance(f)]),
    ),
  }
  const err = makeError("OSR-E001", "输入未通过 input.schema.json 校验", errorDetails)
  const errors = [err]
  const summary =
    Array.from(missing).length > 0
      ? `输入缺少必需字段: ${Array.from(missing).join(", ")};各字段获取方式见 errors[0].details.field_guidance`
      : `输入未通过 schema 校验(${issues.length} 处问题)`
  return {
    status: "FAILED",
    summary,
    findings: [{ statement: summary, label: "OBSERVED" }],
    assumptions: [],
    evidence_used: [],
    uncertainty: [],
    risks: [],
    artifacts: [],
    requested_next_skills: [],
    validation: {
      self_check_passed: true,
      output_schema_valid: true,
      checks: [{ name: "input_schema", passed: false, detail: issues.slice(0, 10).map((i) => i.message).join("; ") }],
    },
    provenance: {
      registry_snapshot_id: "n/a",
      decision_log_ref: "n/a",
      router_version: ROUTER_VERSION,
      registry_version: "n/a",
    },
    errors,
  }
}

function labelize(statements: string[]): LabeledStatement[] {
  return statements.map((statement) => ({ statement, label: "OBSERVED" as const }))
}

function buildSelfCheck(
  response: RouteResponse,
  outValidation: { valid: boolean; issues: ValidationIssue[] },
): ValidationReport {
  const checks: ValidationReport["checks"] = []
  checks.push({ name: "output_schema", passed: outValidation.valid, detail: outValidation.issues[0]?.message })
  checks.push({ name: "status_non_empty", passed: response.status.length > 0 })
  checks.push({ name: "summary_non_empty", passed: response.summary.length > 0 })
  checks.push({ name: "errors_codes_valid", passed: response.errors.every((e) => /^OSR-E\d{3}$/.test(e.code)) })
  const hasProvenance = Boolean(response.provenance.registry_snapshot_id && response.provenance.router_version)
  checks.push({ name: "provenance_present", passed: hasProvenance })
  const selfCheckPassed = checks.every((c) => c.passed)
  return { self_check_passed: selfCheckPassed, output_schema_valid: outValidation.valid, checks }
}

export interface RouteOutcome {
  status: "route" | "blocked" | "capability_gap" | "approval_required" | "failed"
}

export async function route(raw: unknown, opts: ServiceOptions = {}): Promise<ServiceResult> {
  const now = opts.now ?? (() => new Date())
  await ensureOutputSchemaLoaded()
  const { valid, issues } = await validateInput(raw)
  if (!valid) {
    const response = await buildInvalidInputResponse(raw, issues)
    const outValidation = validateOutput(response)
    response.validation = buildSelfCheck(response, outValidation)
    return { response }
  }
  const req = raw as RouteRequest

  let snapshot: RegistrySnapshot
  let registryIssues: { path: string; message: string }[] = []
  if (opts.snapshot) {
    snapshot = opts.snapshot
  } else if (opts.registryRoots && opts.registryRoots.length > 0) {
    const built = await indexRegistry(opts.registryRoots)
    snapshot = built.snapshot
    registryIssues = built.issues
  } else {
    const response = await buildInvalidInputResponse(raw, [
      { path: "", message: "no registry snapshot or roots provided" },
    ])
    response.status = "FAILED"
    response.errors.push(makeError("OSR-E004", "未提供注册表快照或注册表根目录,无法路由", {}))
    return { response }
  }

  const planResult: PlanResult = buildPlan(req, snapshot, { now })

  const errors: OsError[] = [...planResult.errors]
  for (const rIssue of registryIssues.slice(0, 10)) {
    errors.push(makeError("OSR-E014", `注册表问题: ${rIssue.path} — ${rIssue.message}`, {}))
  }

  const status = planResult.status
  const evidenceUsed: Ref[] = [
    ...(req.evidence_refs ?? []),
    ...(req.data_refs ?? []),
    ...(req.upstream_outputs ?? []).map((uo) => uo.output_ref).filter((r): r is Ref => Boolean(r)),
  ]

  const provenance: Provenance = {
    registry_snapshot_id: snapshot.snapshot_id,
    decision_log_ref: "n/a",
    router_version: ROUTER_VERSION,
    registry_version: snapshot.registry_version,
  }

  let logEntry: DecisionRecord | undefined
  let logRef = "n/a"
  if (!opts.disableLog && opts.logDir && req.project_id) {
    try {
      const log = await DecisionLog.open(opts.logDir, req.project_id)
      logEntry = await log.append({
        ts: now().toISOString(),
        project_id: req.project_id,
        task_id: req.task_id,
        decision: mapStatusToDecision(status),
        input_digest: digestInput({ task_id: req.task_id, request: req.request.slice(0, 200) }),
        summary: planResult.summary,
        reasons: planResult.findings.slice(0, 8),
        budget: { est_tokens: planResult.estTokens, est_cost_usd: planResult.estCostUsd },
        planned_skills: planResult.plan?.steps.map((s) => s.skill) ?? [],
        registry_snapshot_id: snapshot.snapshot_id,
        router_version: ROUTER_VERSION,
      })
      provenance.decision_log_ref = logRef = log.file
    } catch (err) {
      errors.push(makeError("OSR-E017", `决策日志写入失败: ${(err as Error).message}`, {}))
    }
  }
  // deterministic log ref even when disabled (tests)
  if (opts.disableLog) {
    provenance.decision_log_ref = `disabled:${req.project_id ?? "anonymous"}`
  }

  let artifactPath: string | undefined
  if (planResult.plan && opts.artifactDir) {
    try {
      await fs.mkdir(opts.artifactDir, { recursive: true })
      artifactPath = path.join(opts.artifactDir, `${req.project_id}.${req.task_id}.plan.json`)
      await fs.writeFile(artifactPath, JSON.stringify(planResult.plan, null, 2) + "\n", "utf8")
      const planRef: Ref = { ref_id: `artifact:${req.task_id}:plan`, uri: artifactPath, media_type: "application/json", note: "route plan" }
      // planRef appended to response below via response construction
    } catch (err) {
      errors.push(makeError("OSR-E017", `计划工件写入失败: ${(err as Error).message}`, {}))
    }
  }

  const response: RouteResponse = {
    status,
    summary: planResult.summary,
    findings: labelize(planResult.findings),
    assumptions: labelize(planResult.assumptions),
    evidence_used: evidenceUsed,
    uncertainty: status === "SUCCESS" ? [`估计值基于注册表 cost_estimate 与回退常数,非实测`] : [],
    risks: [],
    artifacts: planResult.plan && artifactPath ? [{ ref_id: `artifact:${req.task_id}:plan`, uri: artifactPath, media_type: "application/json", note: "route plan" }] : [],
    requested_next_skills: planResult.requestedNextSkills,
    route_plan: planResult.plan,
    capability_gap_spec: planResult.capabilityGap,
    validation: { self_check_passed: false, output_schema_valid: false, checks: [] },
    provenance,
    errors,
  }

  const outValidation = validateOutput(response)
  response.validation = buildSelfCheck(response, outValidation)

  return { response, logEntry, artifactPath }
}

function mapStatusToDecision(status: string): DecisionRecord["decision"] {
  switch (status) {
    case "SUCCESS":
      return "route"
    case "NEED_ADDITIONAL_SKILL":
      return "capability_gap"
    case "HUMAN_APPROVAL_REQUIRED":
      return "approval_required"
    case "BLOCKED":
      return "blocked"
    default:
      return "failed"
  }
}
