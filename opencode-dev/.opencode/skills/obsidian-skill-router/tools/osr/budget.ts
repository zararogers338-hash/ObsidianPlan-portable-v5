// Budget accountant: tokens, cost, wall time and retry caps for routing plans.
//
// The router estimates before scheduling and refuses plans whose estimate
// exceeds configured budgets (fail before spend, not after). All arithmetic
// guards against NaN/Infinity and negative values — a corrupt estimate must
// produce OSR-E010/E017, never a silent pass.

import { makeError, type OsError } from "./errors"

export interface BudgetCaps {
  maxTokensTotal: number
  maxCostUsdTotal: number
  maxWallTimeSec: number
  maxRetriesPerSkill: number
}

export const DEFAULT_CAPS: BudgetCaps = {
  maxTokensTotal: 200_000,
  maxCostUsdTotal: 5.0,
  maxWallTimeSec: 1800,
  maxRetriesPerSkill: 2,
}

export interface StepEstimate {
  skill: string
  estTokens: number
  estCostUsd: number
  timeoutSec: number
  maxRetries: number
}

export interface BudgetCheck {
  ok: boolean
  errors: OsError[]
  totals: { tokens: number; costUsd: number; wallTimeSec: number }
}

function finiteNonNegative(v: unknown): v is number {
  return typeof v === "number" && Number.isFinite(v) && v >= 0
}

/** Default per-skill estimates when a manifest declares no cost_estimate. */
export const FALLBACK_STEP_ESTIMATE = { tokens: 20_000, costUsd: 0.15, timeoutSec: 300 } as const

export function checkBudget(
  steps: StepEstimate[],
  caps: BudgetCaps,
  alreadySpent: { tokens: number; costUsd: number } = { tokens: 0, costUsd: 0 },
): BudgetCheck {
  const errors: OsError[] = []
  let tokens = alreadySpent.tokens
  let costUsd = alreadySpent.costUsd
  let wallTimeSec = 0

  if (!finiteNonNegative(alreadySpent.tokens) || !finiteNonNegative(alreadySpent.costUsd)) {
    errors.push(makeError("OSR-E017", "已花费预算读数非法(NaN/负数),无法继续预算核算", { alreadySpent }))
    return { ok: false, errors, totals: { tokens: 0, costUsd: 0, wallTimeSec: 0 } }
  }

  for (const step of steps) {
    if (!finiteNonNegative(step.estTokens) || !finiteNonNegative(step.estCostUsd) || !finiteNonNegative(step.timeoutSec)) {
      errors.push(
        makeError("OSR-E017", `技能 ${step.skill} 的成本估计非法(非有限值或负值)`, {
          skill: step.skill,
          estTokens: step.estTokens,
          estCostUsd: step.estCostUsd,
          timeoutSec: step.timeoutSec,
        }),
      )
      continue
    }
    if (step.maxRetries > caps.maxRetriesPerSkill) {
      errors.push(
        makeError("OSR-E010", `技能 ${step.skill} 重试次数 ${step.maxRetries} 超过 max_retries_per_skill ${caps.maxRetriesPerSkill}`, {
          skill: step.skill,
          maxRetries: step.maxRetries,
        }),
      )
    }
    // worst case per step: (1 + retries) * estimate
    const retries = Math.min(step.maxRetries, caps.maxRetriesPerSkill)
    tokens += step.estTokens * (1 + retries)
    costUsd += step.estCostUsd * (1 + retries)
    wallTimeSec = Math.max(wallTimeSec, step.timeoutSec) // parallel-safe: wall time is the critical path
  }

  if (tokens > caps.maxTokensTotal) {
    errors.push(
      makeError("OSR-E010", `token 预算将超限: 估计 ${Math.round(tokens)} > max_tokens_total ${caps.maxTokensTotal}`, {
        estimated: Math.round(tokens),
        cap: caps.maxTokensTotal,
      }),
    )
  }
  if (costUsd > caps.maxCostUsdTotal) {
    errors.push(
      makeError("OSR-E010", `成本预算将超限: 估计 $${costUsd.toFixed(4)} > max_cost_usd_total $${caps.maxCostUsdTotal}`, {
        estimated: Number(costUsd.toFixed(4)),
        cap: caps.maxCostUsdTotal,
      }),
    )
  }
  if (wallTimeSec > caps.maxWallTimeSec) {
    errors.push(
      makeError("OSR-E010", `时间预算将超限: 关键路径 ${wallTimeSec}s > max_wall_time_sec ${caps.maxWallTimeSec}s`, {
        estimated: wallTimeSec,
        cap: caps.maxWallTimeSec,
      }),
    )
  }

  return {
    ok: errors.length === 0,
    errors,
    totals: { tokens: Math.round(tokens), costUsd: Number(costUsd.toFixed(6)), wallTimeSec },
  }
}

/** Merge constraint overrides over defaults; ignores invalid (non-finite/negative) overrides. */
export function resolveCaps(overrides?: Partial<BudgetCaps>): BudgetCaps {
  const caps = { ...DEFAULT_CAPS }
  if (!overrides) return caps
  for (const key of Object.keys(caps) as (keyof BudgetCaps)[]) {
    const v = overrides[key]
    if (finiteNonNegative(v) && v > 0) caps[key] = v
  }
  return caps
}
