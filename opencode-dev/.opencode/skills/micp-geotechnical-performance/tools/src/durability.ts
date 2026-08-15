// Durability-cycle decay fitting (metric #4).
//
// Fits linear / exponential / log models to strength-vs-cycle-count series,
// selects the best by R², and reports residual ratio, per-cycle decay rate,
// half-life in cycles, and projected cycles to reach an engineering
// threshold. Dependency-free and deterministic.

import { makeError } from "./errors"

export interface CyclePoint {
  cycle_count: number
  strength_kpa: number
}

export interface DecayFit {
  cycles: number
  initial_strength_kpa: number
  final_strength_kpa: number
  residual_ratio: number // final / initial (0–1)
  decay_per_cycle: number // mean fractional loss per cycle
  model: "linear" | "exponential" | "log" | "none"
  r_squared: number
  half_life_cycles: number | null
  projected_cycles_to_threshold: number | null // cycles to reach half initial (== half-life for linear/exp)
  parameters: { a?: number; b?: number }
  note: string
}

/** Pearson R² of a candidate fit. */
function rSquared(ys: number[], predicted: number[]): number {
  if (ys.length === 0 || predicted.length !== ys.length) return NaN
  const m = ys.reduce((s, v) => s + v, 0) / ys.length
  let ssTot = 0
  let ssRes = 0
  for (let i = 0; i < ys.length; i++) {
    ssTot += (ys[i]! - m) * (ys[i]! - m)
    ssRes += (ys[i]! - predicted[i]!) * (ys[i]! - predicted[i]!)
  }
  if (ssTot === 0) return NaN
  return 1 - ssRes / ssTot
}

/** Least-squares intercept/slope. */
function linreg(xs: number[], ys: number[]): { a: number; b: number } {
  const n = xs.length
  let sx = 0
  let sy = 0
  let sxx = 0
  let sxy = 0
  for (let i = 0; i < n; i++) {
    sx += xs[i]!
    sy += ys[i]!
    sxx += xs[i]! * xs[i]!
    sxy += xs[i]! * ys[i]!
  }
  const denom = n * sxx - sx * sx
  const b = denom === 0 ? 0 : (n * sxy - sx * sy) / denom
  const a = denom === 0 ? (n > 0 ? sy / n : 0) : (sy - b * sx) / n
  return { a, b }
}

/**
 * Fit decay models to (cycle, strength) pairs.
 *
 * Model selection: try linear S(c)=a+b·c, exponential S(c)=a·exp(b·c),
 * and log S(c)=a+b·ln(c+1). Pick the highest R² ≥ 0 (ties prefer linear).
 * With < 3 points, only report the observed trend; never extrapolate.
 */
export function fitDecay(points: CyclePoint[]): DecayFit {
  if (points.length < 2) {
    throw makeError("MGE-E303", `durability fitting needs at least 2 cycle points, got ${points.length}`, { required: 2, got: points.length })
  }
  const sorted = [...points].sort((a, b) => a.cycle_count - b.cycle_count)
  const xs = sorted.map((p) => p.cycle_count)
  const ys = sorted.map((p) => p.strength_kpa)
  const initial = ys[0]!
  const final = ys[ys.length - 1]!
  const residualRatio = initial !== 0 ? final / initial : NaN
  const totalCycles = xs[xs.length - 1]! - xs[0]!
  const decayPerCycle = totalCycles > 0 && initial !== 0 ? (initial - final) / initial / totalCycles : NaN

  // Always able to report observed trend even without a good model.
  const base: Omit<DecayFit, "model" | "r_squared"> = {
    cycles: sorted.length,
    initial_strength_kpa: initial,
    final_strength_kpa: final,
    residual_ratio: residualRatio,
    decay_per_cycle: decayPerCycle,
    half_life_cycles: null,
    projected_cycles_to_threshold: null,
    parameters: {},
    note: "",
  }

  if (points.length < 3) {
    return {
      ...base,
      model: "none",
      r_squared: NaN,
      note: "fewer than 3 cycle points: trend reported, no extrapolation",
    }
  }

  // Linear
  const lin = linreg(xs, ys)
  const linPred = xs.map((c) => lin.a + lin.b * c)
  const r2Lin = rSquared(ys, linPred)

  // Exponential on positive strengths only
  let r2Exp = NaN
  let expA = NaN
  let expB = NaN
  if (ys.every((v) => v > 0)) {
    const ly = ys.map((v) => Math.log(v))
    const e = linreg(xs, ly)
    expA = Math.exp(e.a)
    expB = e.b
    const expPred = xs.map((c) => expA * Math.exp(expB * c))
    r2Exp = rSquared(ys, expPred)
  }

  // Log: S(c)=a+b·ln(c+1)
  const lx = xs.map((c) => Math.log(c + 1))
  const lg = linreg(lx, ys)
  const lgPred = xs.map((c) => lg.a + lg.b * Math.log(c + 1))
  const r2Log = rSquared(ys, lgPred)

  let model: DecayFit["model"]
  let bestR2: number
  let params: { a: number; b: number } = { a: NaN, b: NaN }
  let halfLife: number | null = null
  let projected: number | null = null

  const candidates: { m: DecayFit["model"]; r2: number; a: number; b: number }[] = [
    { m: "linear", r2: r2Lin, a: lin.a, b: lin.b },
    { m: "exponential", r2: r2Exp, a: expA, b: expB },
    { m: "log", r2: r2Log, a: lg.a, b: lg.b },
  ].filter((c): c is { m: DecayFit["model"]; r2: number; a: number; b: number } => Number.isFinite(c.r2) && c.r2 >= 0)
  candidates.sort((a, b) => b.r2 - a.r2 || (a.m === "linear" ? -1 : 1))

  if (candidates.length === 0) {
    return { ...base, model: "none", r_squared: NaN, note: "no model produced a non-negative R²; trend reported only" }
  }

  const best = candidates[0]!
  model = best.m
  bestR2 = best.r2
  params = { a: best.a, b: best.b }

  if (model === "linear" && best.b < 0) {
    if (best.a > 0) {
      const target = best.a / 2
      projected = (target - best.a) / best.b // cycles to half initial
    }
    halfLife = projected
  } else if (model === "exponential" && best.b < 0) {
    const hl = Math.log(2) / -best.b
    halfLife = hl
    projected = hl
  } else if (model === "log") {
    // solve a + b*ln(c+1) = a/2 => ln(c+1) = -a/(2b)
    if (best.b < 0 && best.a > 0) {
      const inner = -best.a / (2 * best.b)
      if (inner > 0) projected = Math.exp(inner) - 1
      halfLife = projected
    }
  }

  const note = `best model: ${model} (R²=${bestR2.toFixed(3)})`
  return {
    ...base,
    model,
    r_squared: bestR2,
    half_life_cycles: Number.isFinite(halfLife as number) ? (halfLife as number) : null,
    projected_cycles_to_threshold: Number.isFinite(projected as number) ? (projected as number) : null,
    parameters: params,
    note,
  }
}
