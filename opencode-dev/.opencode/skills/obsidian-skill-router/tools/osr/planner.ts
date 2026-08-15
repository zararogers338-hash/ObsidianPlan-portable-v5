// Router planner: turns a validated request + registry snapshot into a route
// plan (or a capability-gap / approval / blocked decision).
//
// Pipeline (pure, no I/O except injected snapshot):
//   1. capability & unit prefilter (fail contract: name-similarity never routes)
//   2. per-skill match + rank
//   3. policy gate (deny => blocked; high-risk ask => approval gate)
//   4. callgraph gate (depth / total / cycle / duplicate)
//   5. budget gate (tokens / cost / wall time)
//   6. mode selection (vote / cross_review when conflicts or high risk)
//   7. plan assembly with traceable reasons + budgets
//
// All "hard" rules from the task brief land here as deterministic checks.

import { makeError, type OsError } from "./errors"
import { matchSkill, rankSkills, tokenize, type MatchContext } from "./schema-match"
import type { RegistryEntry, RegistrySnapshot } from "./registry"
import { checkBudget, resolveCaps, FALLBACK_STEP_ESTIMATE, type BudgetCaps } from "./budget"
import { DEFAULT_LIMITS, checkPlan, type CallGraphState } from "./callgraph"
import { DEFAULT_POLICY, evaluateProfile, type PolicyRule } from "./policy"
import { detectConflicts, arbitrate, type Conflict } from "./arbitrate"
import { digestInput } from "./callgraph"
import type {
  RouteRequest,
  RoutePlan,
  RouteStep,
  RouteStatus,
  CapabilityGapSpec,
  ExecutionMode,
  UpstreamOutput,
} from "./types"

export const ROUTER_VERSION = "1.0.0"

export interface RouterOptions {
  policy?: PolicyRule[]
  budgetCaps?: BudgetCaps
  callGraph?: CallGraphState
  now?: () => Date
}

export interface PlanResult {
  status: RouteStatus
  plan?: RoutePlan
  capabilityGap?: CapabilityGapSpec
  errors: OsError[]
  findings: string[]
  assumptions: string[]
  requestedNextSkills: string[]
  guards: string[]
  summary: string
  estTokens: number
  estCostUsd: number
  wallTimeSec: number
}

const RESERVED_CAPABILITY = "routing"

/** Infer the capability tokens a request demands from text + upstream outputs. */
export function inferCapabilities(req: RouteRequest): string[] {
  const caps: string[] = []
  const tokens = tokenize(req.request)
  const UPSTREAM_HINTS: Record<string, string> = {
    "ureolysis-chemistry": "chemistry",
    "mineral-phase-interpreter": "mineral_phase",
    "porous-media-transport": "transport",
    "geotechnical-performance": "geotechnical",
    "literature-scout": "literature",
    "evidence-extractor": "evidence",
    "evidence-synthesizer": "synthesis",
    "knowledge-graph-steward": "knowledge_graph",
    "hypothesis-forge": "hypothesis",
    "biology-reasoner": "biology",
    "experiment-designer": "experiment",
    "instrumentation-qc": "qc",
    "data-analyst": "data_analysis",
    "modeling-optimizer": "modeling",
    "scaleup-injection-engineer": "scaleup",
    "biosafety-environment-auditor": "biosafety",
    "lca-technoeconomic": "lca",
    "reproducibility-versioning": "reproducibility",
    "task-decomposer": "decomposition",
    "state-manager": "state",
    "red-team": "red_team",
    "decision-gate": "decision_gate",
  }
  for (const uo of req.upstream_outputs ?? []) {
    const hint = UPSTREAM_HINTS[uo.skill]
    if (hint && !caps.includes(hint)) caps.push(hint)
  }
  const DOMAIN_MAP: [string, RegExp][] = [
    ["chemistry", /尿素水解|urea\s*hydrolysis|ureoly|化学|沉淀|calcite\s*precip|水解/i],
    ["mineral_phase", /(矿物相|calcite|方解石|矿相|vaterite|球霰石|aragonite|文石)/i],
    ["transport", /(渗流|多孔介质|porous|渗透|advection|扩散|diffus|水力梯度|hydraulic)/i],
    ["geotechnical", /(岩土|geotech|固结|强度|strength|模量|模量|承载|bearing|压实|stabilization)/i],
    ["biology", /(菌株|细菌|bacteri|微生物|酶活|urease|脲酶|生物过程)/i],
    ["literature", /(文献|综述|literature|检索|scout|search\s+paper)/i],
    ["evidence", /(证据|提取|抽取|extract|页码|DOI)/i],
    ["synthesis", /(综合|综述合成|synthesize|meta-analy)/i],
    ["knowledge_graph", /(知识图谱|knowledge\s*graph|图谱|实体|entity)/i],
    ["hypothesis", /(假设|假说|hypothes)/i],
    ["experiment", /(实验设计|试验方案|设计实验|实验方案|trial\s*design)/i],
    ["qc", /(质检|qc|质控|检测|测量不确定度|instrument)/i],
    ["data_analysis", /(数据分析|统计|regression|拟合|时序|time\s*series)/i],
    ["modeling", /(建模|数值模拟|数值|numerical|simulation|优化|optimiz)/i],
    ["scaleup", /(放大|规模化|scale-?up|现场注入|注入参数|injection\s*design)/i],
    ["biosafety", /(生物安全|biosafety|环境影响|氨气泄漏|ammonia\s*emission|安全评估)/i],
    ["lca", /(全生命周期|LCA|成本|经济|技术经济|techno-?economic|碳)/i],
    ["reproducibility", /(复现|可复现|reproducib|版本|version|归档)/i],
    ["decomposition", /(拆解|分解任务|decompos|子任务|任务分解)/i],
    ["state", /(状态|state|进度|持久化|persist)/i],
    ["red_team", /(红队|对抗|攻击|red\s*team|挑刺)/i],
    ["decision_gate", /(决策门|审批|go\/no-go|go-no-go|人工放行|放行决策)/i],
    ["biosafety_ammonia", /(氨|铵|ammon)/i],
    ["mass_balance", /(质量守恒|物料平衡|mass\s*balance|质量平衡)/i],
  ]
  for (const [cap, re] of DOMAIN_MAP) {
    if (re.test(req.request)) caps.push(cap)
  }
  if (req.request.toLowerCase().includes("氨") || /ammon/i.test(req.request)) {
    caps.push("biosafety_ammonia", "mass_balance")
  }
  return Array.from(new Set(caps))
}

/**
 * Derived capabilities never independently gate coverage: they are secondary
 * concerns served by a skill that covers a primary capability (e.g. a
 * chemistry skill covers biosafety_ammonia/mass_balance; a biosafety skill
 * covers ammonia emission). Treating them as hard requirements would turn a
 * well-covered task into a false CAPABILITY_GAP.
 */
const DERIVED_CAPABILITIES = new Set(["biosafety_ammonia", "mass_balance"])

/** Capabilities that must actually be covered by the composed plan. */
export function coverageRequirements(caps: string[]): string[] {
  return caps.filter((c) => !DERIVED_CAPABILITIES.has(c))
}

/** Unit expectations carried by upstream outputs of a known skill. */
export function inferExpectedUnits(req: RouteRequest): Record<string, string> {
  const units: Record<string, string> = {}
  for (const uo of req.upstream_outputs ?? []) {
    const out = uo.output as Record<string, unknown> | undefined
    const val = out?.["value"]
    if (typeof val === "number") {
      const u = out?.["unit"]
      if (typeof u === "string" && u.trim() !== "") {
        // map the upstream skill's domain to a unit expectation key
        const key = unitKeyForSkill(uo.skill)
        if (key && units[key] === undefined) units[key] = u
      }
    }
  }
  return units
}

function unitKeyForSkill(skill: string): string | undefined {
  const map: Record<string, string> = {
    "micp-ureolysis-chemistry": "ammonia_conc",
    "micp-mineral-phase-interpreter": "calcite_mass",
    "micp-porous-media-transport": "permeability",
    "micp-geotechnical-performance": "strength",
  }
  return map[skill]
}

function findBestCandidate(
  entries: RegistryEntry[],
  ctx: MatchContext,
  req: RouteRequest,
): { covered: RegistryEntry[]; best?: RegistryEntry; matches: ReturnType<typeof matchSkill>[]; errors: OsError[] } {
  const errors: OsError[] = []
  const usable = entries.filter((e) => e.usable)
  const ranked = rankSkills(usable, ctx, req.request)
  const matches = ranked

  // Multi-skill composition: for each required capability, pick the best
  // usable skill that covers it AND has no unit conflict. This is how a
  // cross-domain task (chemistry + transport + geotechnical + mineral) routes
  // to the correct combined specialist set rather than one arbitrary skill.
  const covered: RegistryEntry[] = []
  const seen = new Set<string>()
  for (const cap of ctx.requiredCapabilities) {
    const candidate = matches.find(
      (m) =>
        m.unitConflicts.length === 0 &&
        m.coveredCapabilities.includes(cap) &&
        !seen.has(m.entry.name),
    )
    if (candidate) {
      covered.push(candidate.entry)
      seen.add(candidate.entry.name)
    }
  }
  // A single skill may cover several caps; still pick the overall best single
  // candidate to anchor the plan when nothing was covered per-capability.
  if (covered.length === 0) {
    const top = matches.find((m) => m.score > 0 && m.unitConflicts.length === 0)
    if (top) covered.push(top.entry)
  }
  if (covered.length === 0) {
    const anyUsable = usable.length > 0
    if (!anyUsable) {
      errors.push(makeError("OSR-E014", "注册表中没有任何可用(usable)技能条目", { entries: entries.length }))
    } else {
      errors.push(makeError("OSR-E006", "注册表中没有技能覆盖所需能力组合", {
        requiredCapabilities: ctx.requiredCapabilities,
      }))
    }
    return { covered, matches, errors }
  }
  // Anchor = the composition's best single skill (for reason reporting).
  const anchorMatch = matches.find((m) => m.entry.name === covered[0]?.name)
  return { covered, best: anchorMatch?.entry ?? covered[0], matches, errors }
}

/** True when every inferred capability has at least one covering skill. */
function allCapabilitiesCovered(ctx: MatchContext, matches: ReturnType<typeof matchSkill>[]): string[] {
  const missing: string[] = []
  for (const cap of ctx.requiredCapabilities) {
    const covered = matches.some((m) => m.unitConflicts.length === 0 && m.coveredCapabilities.includes(cap))
    if (!covered) missing.push(cap)
  }
  return missing
}

function buildCapabilityGap(
  ctx: MatchContext,
  missing: string[],
  req: RouteRequest,
  bestName: string | undefined,
): CapabilityGapSpec {
  return {
    missing_capability: missing.join(","),
    required_inputs: ["task_id", "project_id", "request", "context", "evidence_refs", "data_refs"].filter((i) =>
      ctx.availableInputs.includes(i),
    ),
    required_outputs: ["status", "summary", "findings", "evidence_used", "uncertainty", "risks", "provenance", "errors"],
    required_tools: ["read", "bash", "websearch", "schema_validate"],
    domain_context: req.request.slice(0, 400),
    suggested_name: `micp-${missing[0]?.replace(/_/g, "-") ?? "capability"}`,
    risk_notes: `未注册能力: ${missing.join(", ")}${bestName ? `; 最接近候选 ${bestName} 覆盖不完整` : ""}`,
  }
}

export function buildPlan(req: RouteRequest, snapshot: RegistrySnapshot, opts: RouterOptions = {}): PlanResult {
  const now = opts.now ?? (() => new Date())
  const entries = snapshot.entries
  const reqCaps = inferCapabilities(req)
  const expectedUnits = inferExpectedUnits(req)
  const upstreamInputs = new Set((req.upstream_outputs ?? []).map((u: UpstreamOutput) => u.skill))
  const availableInputs = [
    "task_id",
    "project_id",
    "request",
    "context",
    "evidence_refs",
    "data_refs",
    "upstream_outputs",
    ...Array.from(upstreamInputs),
  ]
  const ctx: MatchContext = {
    requiredCapabilities: coverageRequirements(reqCaps),
    availableInputs,
    expectedUnits: Object.keys(expectedUnits).length > 0 ? expectedUnits : undefined,
  }

  // Gate 1 — reserved capability must never be routed (router can't route itself).
  if (reqCaps.includes(RESERVED_CAPABILITY)) {
    return {
      status: "FAILED",
      errors: [makeError("OSR-E005", "请求要求路由能力本身(Reserved capability 'routing'),Router 不调度自身", {})],
      findings: [],
      assumptions: [],
      requestedNextSkills: [],
      guards: [],
      summary: "拒绝把路由职责下发给任何技能",
      estTokens: 0,
      estCostUsd: 0,
      wallTimeSec: 0,
    }
  }

  // Gate 2 — forbidden / required skills.
  const forbidden = req.constraints?.forbidden_skills ?? []
  const required = req.constraints?.required_skills ?? []
  const forbiddenBlocked = forbidden.filter((f) => reqCaps.some((c) => c === f || c.includes(f)))
  if (forbiddenBlocked.length > 0) {
    return {
      status: "BLOCKED",
      errors: [
        makeError("OSR-E005", `约束禁止调用技能: ${forbiddenBlocked.join(", ")}`, { forbidden: forbiddenBlocked }),
      ],
      findings: [],
      assumptions: [],
      requestedNextSkills: [],
      guards: [],
      summary: "请求所需的技能被 constraints.forbidden_skills 明确禁止",
      estTokens: 0,
      estCostUsd: 0,
      wallTimeSec: 0,
    }
  }

  // Gate 3 — matching (multi-skill composition).
  const { covered, best, matches, errors } = findBestCandidate(entries, ctx, req)
  const missingCaps = allCapabilitiesCovered(ctx, matches)
  if (covered.length === 0 || missingCaps.length > 0) {
    const gap = buildCapabilityGap(ctx, missingCaps.length > 0 ? missingCaps : ctx.requiredCapabilities, req, matches[0]?.entry.name)
    return {
      status: "NEED_ADDITIONAL_SKILL",
      capabilityGap: gap,
      errors,
      findings: [],
      assumptions: [],
      requestedNextSkills: [gap.suggested_name],
      guards: [],
      summary: `能力缺口: ${gap.missing_capability} 未被任何注册技能覆盖;已生成技能需求说明`,
      estTokens: 0,
      estCostUsd: 0,
      wallTimeSec: 0,
    }
  }
  const bestMatch = best ? matches.find((m) => m.entry.name === best.name) : undefined

  // Gate 4 — policy (network/writes/tools/risk) for EVERY covered skill.
  const policy = opts.policy ?? DEFAULT_POLICY
  const deniedSkills: { skill: string; denials: { permission: string; pattern: string }[] }[] = []
  for (const skillEntry of covered) {
    const manifest = skillEntry.manifest ?? {}
    const profile = {
      tools: (manifest.tool_permissions as string[] | undefined) ?? ["read"],
      network: (manifest.network as boolean | undefined) ?? false,
      writes: (manifest.writes as string[] | undefined) ?? [],
    }
    const decision = evaluateProfile(profile, policy, { riskLevel: req.risk_level ?? "medium", skillName: skillEntry.name })
    if (!decision.allowed) {
      deniedSkills.push({ skill: skillEntry.name, denials: decision.denials.map((d) => ({ permission: d.permission, pattern: d.pattern })) })
    }
  }
  if (deniedSkills.length > 0) {
    return {
      status: "BLOCKED",
      errors: [
        makeError("OSR-E005", `以下技能被权限策略拒绝: ${deniedSkills.map((d) => d.skill).join(", ")}`, {
          denials: deniedSkills,
        }),
      ],
      findings: [],
      assumptions: [],
      requestedNextSkills: [],
      guards: [],
      summary: `权限策略拒绝调度: ${deniedSkills.map((d) => d.skill).join(", ")}`,
      estTokens: 0,
      estCostUsd: 0,
      wallTimeSec: 0,
    }
  }

  // Gate 5 — risk gating: high/critical requires red-team + decision-gate chaining.
  const risk = req.risk_level ?? "medium"
  const guards: string[] = []
  const chained: string[] = []
  if (risk === "high" || risk === "critical") {
    const redTeam = entries.find((e) => e.name === "obsidian-red-team")
    const decisionGate = entries.find((e) => e.name === "obsidian-decision-gate")
    if (!redTeam || !decisionGate) {
      return {
        status: "BLOCKED",
        errors: [
          makeError(
            "OSR-E006",
            `风险等级 ${risk} 强制要求 obsidian-red-team 与 obsidian-decision-gate 审计链路,但注册表中缺少: ${[
              !redTeam ? "obsidian-red-team" : "",
              !decisionGate ? "obsidian-decision-gate" : "",
            ].filter(Boolean).join(", ")}`,
            { risk },
          ),
        ],
        findings: [],
        assumptions: [],
        requestedNextSkills: [],
        guards: [],
        summary: `风险等级 ${risk} 的强制审计技能缺失,拒绝直接调度`,
        estTokens: 0,
        estCostUsd: 0,
        wallTimeSec: 0,
      }
    }
    guards.push(`风险(risk=${risk}): 强制审计 obsidian-red-team → obsidian-decision-gate`)
    chained.push("obsidian-red-team", "obsidian-decision-gate")
  }

  // Gate 6 — conflict detection from upstream outputs (drives cross_review).
  const conflicts = detectConflictsFromUpstreams(req.upstream_outputs ?? [])
  const unresolved = conflicts.filter((c) => c.kind !== "value_mismatch" || arbitrate(c).type === "escalate")
  if (unresolved.length > 0) {
    guards.push(`上游输出存在未消解冲突 ${unresolved.length} 处: 强制 cross_review 模式`)
  }

  // Gate 7 — callgraph.
  const callLimits = {
    maxDepth: req.constraints?.max_depth ?? DEFAULT_LIMITS.maxDepth,
    maxTotalCalls: req.constraints?.max_total_calls ?? DEFAULT_LIMITS.maxTotalCalls,
    maxRetriesPerSkill: req.constraints?.max_retries_per_skill ?? DEFAULT_LIMITS.maxRetriesPerSkill,
  }
  const chain = req.context?.call_chain ?? []
  const composed = covered.map((e) => e.name)
  const plannedSkills = [...composed, ...chained.filter((s) => !composed.includes(s))]
  const planned = plannedSkills.map((s) => ({ skill: s, inputDigest: digestInput({ task_id: req.task_id, skill: s }) }))
  // Budget caps: translate snake_case constraints to the camelCase BudgetCaps.
  const rawCaps = req.constraints?.budget ?? req.constraints
  const caps = opts.budgetCaps ?? resolveCaps({
    maxTokensTotal: rawCaps?.max_tokens_total,
    maxCostUsdTotal: rawCaps?.max_cost_usd_total,
    maxWallTimeSec: rawCaps?.max_wall_time_sec,
    maxRetriesPerSkill: rawCaps?.max_retries_per_skill,
  })
  const cg = checkPlan(
    {
      chain,
      completed: req.context?.completed_calls ?? [],
      limits: callLimits,
    },
    planned,
  )
  if (!cg.ok) {
    return {
      status: "BLOCKED",
      errors: cg.errors,
      findings: [],
      assumptions: [],
      requestedNextSkills: [],
      guards,
      summary: "调用图预算检查未通过",
      estTokens: 0,
      estCostUsd: 0,
      wallTimeSec: 0,
    }
  }

  // Gate 8 — budget.
  const stepEstimates = plannedSkills.map((s) => {
    const e = entries.find((x) => x.name === s)
    const ce = e?.manifest?.cost_estimate as { tokens?: number; usd?: number } | undefined
    return {
      skill: s,
      estTokens: typeof ce?.tokens === "number" ? ce.tokens : FALLBACK_STEP_ESTIMATE.tokens,
      estCostUsd: typeof ce?.usd === "number" ? ce.usd : FALLBACK_STEP_ESTIMATE.costUsd,
      timeoutSec: FALLBACK_STEP_ESTIMATE.timeoutSec,
      maxRetries: callLimits.maxRetriesPerSkill,
    }
  })
  const spent = {
    tokens: (req.context?.completed_calls ?? []).reduce((a, c) => a + (c.tokens_used ?? 0), 0),
    costUsd: (req.context?.completed_calls ?? []).reduce((a, c) => a + (c.cost_usd_used ?? 0), 0),
  }
  const budget = checkBudget(stepEstimates, caps, spent)
  if (!budget.ok) {
    return {
      status: "BLOCKED",
      errors: budget.errors,
      findings: [],
      assumptions: [],
      requestedNextSkills: [],
      guards,
      summary: "预算核算未通过,拒绝调度(避免先消耗再超限)",
      estTokens: budget.totals.tokens,
      estCostUsd: budget.totals.costUsd,
      wallTimeSec: budget.totals.wallTimeSec,
    }
  }

  // Approval gate: high-risk + any covered skill needing approval (network/write).
  // Approval gate: high/critical risk ALWAYS requires human approval before
  // any specialist runs (Panshi constitution: field deployment / biological
  // experiments / hazardous chemistry / long-term knowledge writes are
  // human-approval-gated). Pending or not_required → HUMAN_APPROVAL_REQUIRED.
  const approvalState = req.human_approval_state ?? "not_required"
  if ((risk === "high" || risk === "critical") && approvalState !== "approved") {
    return {
      status: "HUMAN_APPROVAL_REQUIRED",
      errors: [
        makeError(
          "OSR-E007",
          `风险等级 ${risk} 强制人工批准,当前 human_approval_state=${approvalState};批准通过前不得调度任何技能`,
          { risk, approvalState, skills: plannedSkills },
        ),
      ],
      findings: [],
      assumptions: [],
      requestedNextSkills: [],
      guards,
      summary: `等待人工批准后才能调度高风险任务(${risk});计划技能: ${plannedSkills.join(", ")}`,
      estTokens: 0,
      estCostUsd: 0,
      wallTimeSec: 0,
    }
  }

  // Assemble plan.
  const mode: ExecutionMode = unresolved.length > 0 ? "cross_review" : risk === "high" || risk === "critical" ? "cross_review" : plannedSkills.length > 1 ? "sequential" : "sequential"
  const steps: RouteStep[] = plannedSkills.map((s, i) => {
    const e = entries.find((x) => x.name === s)
    const ce = e?.manifest?.cost_estimate as { tokens?: number; usd?: number } | undefined
    const estTokens = typeof ce?.tokens === "number" ? ce.tokens : FALLBACK_STEP_ESTIMATE.tokens
    const estCostUsd = typeof ce?.usd === "number" ? ce.usd : FALLBACK_STEP_ESTIMATE.costUsd
    const m = matches.find((x) => x.entry.name === s)
    const dependsOn = i === 0 ? [] : [plannedSkills[i - 1] ?? ""]
    const sManifest = e?.manifest ?? {}
    const sProfile = {
      tools: (sManifest.tool_permissions as string[] | undefined) ?? ["read"],
      network: (sManifest.network as boolean | undefined) ?? false,
      writes: (sManifest.writes as string[] | undefined) ?? [],
    }
    return {
      step_id: `step-${i + 1}-${s}`,
      skill: s,
      reason: m ? m.reason : `风险${risk}强制审计链`,
      input_summary: `task_id=${req.task_id}; 上游输入: ${Array.from(upstreamInputs).join(", ") || "无"}`,
      expected_artifacts: (e?.manifest?.outputs as string[] | undefined) ?? [s],
      budget: {
        est_tokens: estTokens,
        est_cost_usd: estCostUsd,
        max_retries: callLimits.maxRetriesPerSkill,
        timeout_sec: FALLBACK_STEP_ESTIMATE.timeoutSec,
      },
      depends_on: dependsOn,
      // Approved high/critical runs carry approved state into every step; medium/low need none.
      approval_required: (risk === "high" || risk === "critical"),
      permission_request: { tools: sProfile.tools, network: sProfile.network, writes: sProfile.writes },
    }
  })

  const plan: RoutePlan = {
    plan_id: `plan_${digestInput({ task_id: req.task_id, steps: plannedSkills.join(","), ts: now().toISOString() })}`,
    mode,
    steps,
    guards,
    total_budget: {
      est_tokens: budget.totals.tokens,
      est_cost_usd: budget.totals.costUsd,
      max_wall_time_sec: budget.totals.wallTimeSec,
    },
  }

  const composedNames = plannedSkills.join(", ")
  const findings = [
    `组合路由: ${composedNames}${best ? ` (锚定 ${best.name},评分 ${bestMatch?.score.toFixed(2) ?? "n/a"})` : ""}`,
    ...(chained.length > 0 ? [`强制审计链: ${chained.join(" → ")}`] : []),
    ...(unresolved.length > 0 ? [`上游冲突 ${unresolved.length} 处,采用 cross_review 模式`] : []),
  ]
  const assumptions = [
    `识别到能力请求: ${reqCaps.join(", ") || "未从请求文本识别出显式能力"}`,
    `可用输入字段: ${availableInputs.join(", ") || "无"}`,
    `单位预期: ${Object.keys(expectedUnits).length > 0 ? JSON.stringify(expectedUnits) : "无上游单位约束"}`,
  ]

  return {
    status: "SUCCESS",
    plan,
    errors: [],
    findings,
    assumptions,
    requestedNextSkills: plannedSkills.filter((s) => s !== best?.name),
    guards,
    summary: `已路由组合: ${composedNames}${chained.length > 0 ? ` (审计链 ${chained.join("→")})` : ""},模式=${mode}`,
    estTokens: budget.totals.tokens,
    estCostUsd: budget.totals.costUsd,
    wallTimeSec: budget.totals.wallTimeSec,
  }
}

function detectConflictsFromUpstreams(upstreams: UpstreamOutput[]): Conflict[] {
  const items: {
    skill: string
    subject: string
    value: string
    label: "OBSERVED" | "CALCULATED" | "REPORTED" | "INFERRED" | "HYPOTHESIS" | "RECOMMENDATION"
    evidence_refs?: string[]
    unit?: string
  }[] = []
  for (const uo of upstreams) {
    const out = uo.output as Record<string, unknown> | undefined
    const subject = uo.task_node
    if (!subject || !out) continue
    const value = out["value"]
    const summary = typeof out["summary"] === "string" ? out["summary"] : uo.summary
    if (typeof value === "string" || typeof value === "number") {
      items.push({
        skill: uo.skill,
        subject,
        value: String(value),
        label: (out["label"] as never) ?? "REPORTED",
        evidence_refs: Array.isArray(out["evidence_refs"]) ? (out["evidence_refs"] as string[]) : undefined,
        unit: typeof out["unit"] === "string" ? out["unit"] : undefined,
      })
    } else if (summary) {
      items.push({ skill: uo.skill, subject, value: summary.slice(0, 200), label: "REPORTED" })
    }
  }
  return detectConflicts(items)
}
