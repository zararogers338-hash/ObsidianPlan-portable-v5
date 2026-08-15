// Permission policy engine for routing decisions.
//
// Mirrors the semantics of opencode's own permission evaluator
// (packages/opencode/src/permission/index.ts: `evaluate` picks the LAST rule
// matching both permission and pattern; default action when nothing matches
// is "ask") so that plans this router emits agree with the runtime that will
// execute them.
//
// The router's own policy is an additional, stricter layer: it can downgrade
// an "allow" to "ask" (never upgrades). Risk gating (red-team / decision-gate
// for high risk) lives in planner.ts; this module answers the single
// question: may skill S run with its declared tool/network/write profile
// under policy P at risk level R?

export type PolicyAction = "allow" | "ask" | "deny"

export interface PolicyRule {
  permission: string // e.g. "skill", "bash", "edit", "network", "write"
  pattern: string // glob, "*" matches everything
  action: PolicyAction
}

export interface PermissionProfile {
  tools: string[]
  network: boolean
  writes: string[]
}

export interface PolicyDecision {
  allowed: boolean
  requires_approval: boolean
  denials: { permission: string; pattern: string; reason: string }[]
  approvals: { permission: string; pattern: string }[]
}

const DEFAULT_ACTION: PolicyAction = "ask"

function wildcardMatch(pattern: string, value: string): boolean {
  if (pattern === "*") return true
  const escaped = pattern.replace(/[.+^${}()|[\]\\]/g, "\\$&").replace(/\*/g, ".*").replace(/\?/g, ".")
  return new RegExp(`^${escaped}$`).test(value)
}

/** Last matching rule wins, mirroring opencode's Permission.evaluate. */
export function evaluate(permission: string, pattern: string, rules: PolicyRule[]): PolicyAction {
  const rule = rules.findLast((r) => wildcardMatch(r.permission, permission) && wildcardMatch(r.pattern, pattern))
  return rule?.action ?? DEFAULT_ACTION
}

/**
 * Evaluate a skill's declared permission profile against a policy ruleset.
 * Router-added invariant: at risk_level high/critical, any "ask" requires a
 * human approval gate before the step may be scheduled (surfaced via
 * requires_approval); a "deny" is absolute at every risk level.
 */
export function evaluateProfile(
  profile: PermissionProfile,
  rules: PolicyRule[],
  opts: { riskLevel: string; skillName: string },
): PolicyDecision {
  const denials: PolicyDecision["denials"] = []
  const approvals: PolicyDecision["approvals"] = []

  const check = (permission: string, pattern: string) => {
    const action = evaluate(permission, pattern, rules)
    if (action === "deny") {
      denials.push({ permission, pattern, reason: `policy denies ${permission} ${pattern} for ${opts.skillName}` })
    } else if (action === "ask") {
      approvals.push({ permission, pattern })
    }
  }

  for (const tool of profile.tools) check(tool, "*")
  check("skill", opts.skillName)
  if (profile.network) check("network", "*")
  for (const w of profile.writes) check("write", w)

  return {
    allowed: denials.length === 0,
    requires_approval: approvals.length > 0,
    denials,
    approvals,
  }
}

export const DEFAULT_POLICY: PolicyRule[] = [
  { permission: "*", pattern: "*", action: "allow" },
  { permission: "network", pattern: "*", action: "ask" },
  { permission: "write", pattern: "kb/**", action: "ask" },
  { permission: "write", pattern: "state/**", action: "ask" },
  { permission: "bash", pattern: "*", action: "ask" },
  { permission: "skill", pattern: "*", action: "allow" },
]
