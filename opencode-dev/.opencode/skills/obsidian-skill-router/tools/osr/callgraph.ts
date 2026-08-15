// Call-graph and recursion monitor (star topology enforcement).
//
// Obsidian architecture rule: specialist skills never call each other
// directly; every cross-skill need returns to the Router, which is the hub.
// This module tracks the call chain of the CURRENT routing decision and
// rejects plans that would exceed depth / total-call budgets, contain cycles,
// or encode a specialist->specialist edge that bypasses the hub.

import { makeError, type OsError } from "./errors"
import type { CompletedCall } from "./types"

export interface CallGraphLimits {
  maxDepth: number
  maxTotalCalls: number
  maxRetriesPerSkill: number
}

export const DEFAULT_LIMITS: CallGraphLimits = {
  maxDepth: 4,
  maxTotalCalls: 16,
  maxRetriesPerSkill: 2,
}

export interface CallGraphState {
  chain: string[] // current chain from controller down to router
  completed: CompletedCall[]
  limits: CallGraphLimits
}

export interface PlanEdge {
  from: string
  to: string
}

export interface CallGraphCheck {
  ok: boolean
  errors: OsError[]
  projectedDepth: number
  projectedTotalCalls: number
}

export const ROUTER_NAME = "obsidian-skill-router"
export const CONTROLLER_NAME = "obsidian-controller"

export function digestInput(value: unknown): string {
  const s = typeof value === "string" ? value : JSON.stringify(value ?? null)
  let h = 0x811c9dc5
  for (let i = 0; i < s.length; i++) {
    h ^= s.charCodeAt(i)
    h = Math.imul(h, 0x01000193)
  }
  return (h >>> 0).toString(16).padStart(8, "0")
}

/**
 * Check whether invoking `planned` steps is legal given the current chain and
 * completed calls. `planned` is the number of NEW skill invocations in the
 * candidate plan (each plan step counts once; retries are bounded separately).
 */
export function checkPlan(
  state: CallGraphState,
  planned: { skill: string; inputDigest?: string }[],
): CallGraphCheck {
  const errors: OsError[] = []
  const { chain, completed, limits } = state

  // Depth: chain already includes everything above the router; each sequential
  // layer in the plan adds depth. We conservatively assume worst case: plan is
  // a chain (planner flattens parallel branches, so worst-case depth is what
  // the controller will enforce per-branch at execution time).
  const projectedDepth = chain.length + 1 + 1 // router frame + one specialist frame
  if (projectedDepth > limits.maxDepth) {
    errors.push(
      makeError("OSR-E011", `调用深度将超限: 当前链 ${chain.join("→") || "(root)"} + router + 新步骤 = ${projectedDepth} > max_depth ${limits.maxDepth}`, {
        chain,
        projectedDepth,
        maxDepth: limits.maxDepth,
      }),
    )
  }

  // Cycle: a skill already in the current chain must never be re-entered.
  for (const step of planned) {
    if (chain.includes(step.skill)) {
      errors.push(
        makeError("OSR-E011", `检测到递归调用环: ${step.skill} 已在当前调用链 ${chain.join("→")} 中`, {
          chain,
          skill: step.skill,
        }),
      )
    }
  }

  // Total calls
  const projectedTotal = completed.length + planned.length
  if (projectedTotal > limits.maxTotalCalls) {
    errors.push(
      makeError("OSR-E011", `总调用数将超限: 已完成 ${completed.length} + 计划 ${planned.length} = ${projectedTotal} > max_total_calls ${limits.maxTotalCalls}`, {
        completed: completed.length,
        planned: planned.length,
        maxTotalCalls: limits.maxTotalCalls,
      }),
    )
  }

  // Exact duplicate invocation: same skill, same input digest, already completed
  // successfully — re-running wastes budget and signals a loop.
  const completedIndex = new Map<string, CompletedCall>()
  for (const c of completed) {
    if (c.status === "SUCCESS" || c.status === "PARTIAL") {
      completedIndex.set(`${c.skill}#${c.input_digest}`, c)
    }
  }
  const plannedSeen = new Set<string>()
  for (const step of planned) {
    if (!step.inputDigest) continue
    const key = `${step.skill}#${step.inputDigest}`
    if (completedIndex.has(key)) {
      errors.push(
        makeError("OSR-E012", `检测到精确重复调用: ${step.skill} 已以相同输入完成过 (digest ${step.inputDigest})`, {
          skill: step.skill,
          digest: step.inputDigest,
        }),
      )
    }
    if (plannedSeen.has(key)) {
      errors.push(
        makeError("OSR-E012", `计划内部存在对 ${step.skill} 的重复调用 (digest ${step.inputDigest})`, {
          skill: step.skill,
          digest: step.inputDigest,
        }),
      )
    }
    plannedSeen.add(key)
  }

  return {
    ok: errors.length === 0,
    errors,
    projectedDepth,
    projectedTotalCalls: projectedTotal,
  }
}

/**
 * Star-topology check on an explicit edge list (used when auditing a recorded
 * call graph): the only legal edges are controller->router, router->specialist,
 * specialist->router. Any specialist->specialist edge is a bypass.
 */
export function auditEdges(edges: PlanEdge[]): { ok: boolean; violations: { edge: PlanEdge; reason: string }[] } {
  const violations: { edge: PlanEdge; reason: string }[] = []
  for (const edge of edges) {
    const fromRouter = edge.from === ROUTER_NAME || edge.from === CONTROLLER_NAME
    const toRouter = edge.to === ROUTER_NAME || edge.to === CONTROLLER_NAME
    if (!fromRouter && !toRouter) {
      violations.push({ edge, reason: `专业 Skill 直连 ${edge.from}→${edge.to} 绕过 Router(星型拓扑违规)` })
    }
    if (edge.from === edge.to) {
      violations.push({ edge, reason: `自调用环: ${edge.from}→${edge.to}` })
    }
  }
  return { ok: violations.length === 0, violations }
}
