// Sample-level statistics and spatial uniformity (metric #3).
//
// Computes sample size, mean/median/stddev/CV, t-distribution confidence
// interval, outlier flags and — when per-segment (layer) data is present —
// the spatial uniformity coefficient (segment CV). Dependency-free and
// deterministic.

import { makeError } from "./errors"

/** Critical t values (two-tailed) for common degrees of freedom at α=0.05. */
const T95: Record<number, number> = {
  1: 12.7062,
  2: 4.3027,
  3: 3.1824,
  4: 2.7764,
  5: 2.5706,
  6: 2.4469,
  7: 2.3646,
  8: 2.3060,
  9: 2.2622,
  10: 2.2281,
  12: 2.1788,
  15: 2.1314,
  20: 2.0860,
  25: 2.0595,
  30: 2.0423,
  40: 2.0211,
  60: 2.0003,
  120: 1.9799,
  1_000_000: 1.96,
}

/** Approximate two-tailed critical t for a given df (interpolates the table). */
export function tCritical(df: number, alpha = 0.05): number {
  const tail = alpha / 2
  // One-tailed critical value lookup via two-tail table is not direct; we use
  // a normal approximation for tail 0.025 with small-df correction.
  if (tail === 0.025) {
    if (df <= 0) return 1.96
    if (df >= 1_000_000) return 1.96
    const keys = Object.keys(T95)
      .map(Number)
      .sort((a, b) => a - b)
    // interpolate between bracketing table rows
    let lo = keys[0]!
    let hi = keys[keys.length - 1]!
    for (const k of keys) {
      if (k <= df) lo = k
      if (k >= df) {
        hi = k
        break
      }
    }
    const tLo = T95[lo]!
    const tHi = T95[hi]!
    if (lo === hi) return tLo
    const f = (df - lo) / (hi - lo)
    return tLo + f * (tHi - tLo)
  }
  return 1.96
}

export function mean(values: number[]): number {
  if (values.length === 0) return NaN
  let s = 0
  for (const v of values) s += v
  return s / values.length
}

export function median(values: number[]): number {
  if (values.length === 0) return NaN
  const sorted = [...values].sort((a, b) => a - b)
  const mid = Math.floor(sorted.length / 2)
  if (sorted.length % 2 === 1) return sorted[mid]!
  return (sorted[mid - 1]! + sorted[mid]!) / 2
}

export function stddev(values: number[], ddof = 1): number {
  if (values.length < 2) return NaN
  const m = mean(values)
  let s = 0
  for (const v of values) s += (v - m) * (v - m)
  return Math.sqrt(s / (values.length - ddof))
}

export function coefficientOfVariation(values: number[]): number {
  const m = mean(values)
  if (m === 0 || !Number.isFinite(m)) return NaN
  return stddev(values) / m
}

export interface SampleStats {
  n: number
  mean: number
  median: number
  stddev: number
  cv: number
  ci95: { lower: number; upper: number }
  outliers: string[]
  reliability: "high" | "medium" | "low"
}

/**
 * Compute descriptive statistics for a list of (id, value) pairs.
 * Outliers: modified z-score using median + MAD (robust, standard for small
 * samples that a mean-based 2.5σ rule misses when one outlier inflates the SD).
 */
export function sampleStats(pairs: { id: string; value: number }[]): SampleStats {
  const values = pairs.map((p) => p.value)
  const n = values.length
  const m = mean(values)
  const sd = stddev(values)
  const cv = coefficientOfVariation(values)

  let ci: { lower: number; upper: number } = { lower: NaN, upper: NaN }
  if (n >= 2 && Number.isFinite(sd)) {
    const t = tCritical(n - 1, 0.05)
    const se = sd / Math.sqrt(n)
    ci = { lower: m - t * se, upper: m + t * se }
  }

  const outliers: string[] = []
  if (n >= 3) {
    const med = median(values)
    const mad = median(values.map((v) => Math.abs(v - med)))
    if (mad > 0) {
      for (const p of pairs) {
        // modified z-score: 0.6745 * (x - median) / MAD; |z| > 3.5 flags outlier
        const z = (0.6745 * (p.value - med)) / mad
        if (Math.abs(z) > 3.5) outliers.push(p.id)
      }
    }
  }

  const reliability = n >= 5 && cv < 0.3 ? "high" : n >= 3 ? "medium" : "low"

  return { n, mean: m, median: median(values), stddev: sd, cv, ci95: ci, outliers, reliability }
}

export interface SegmentSummary {
  segments: number
  segment_cv: number
  trend: "increasing" | "decreasing" | "flat" | "unknown"
  note: string
}

/**
 * Spatial uniformity from per-segment (layer) measurements along a specimen
 * or column. Segment CV is the coefficient of variation across segment means
 * (lower = more uniform). Trend: monotonic increase/decrease in value with
 * position, else flat/unknown.
 */
export function spatialUniformity(segments: { position: number; value: number }[]): SegmentSummary {
  if (segments.length < 2) {
    return { segments: segments.length, segment_cv: NaN, trend: "unknown", note: "insufficient segments (<2) for spatial uniformity" }
  }
  const cv = coefficientOfVariation(segments.map((s) => s.value))
  const sorted = [...segments].sort((a, b) => a.position - b.position)
  let inc = 0
  let dec = 0
  for (let i = 1; i < sorted.length; i++) {
    if (sorted[i]!.value > sorted[i - 1]!.value) inc++
    else if (sorted[i]!.value < sorted[i - 1]!.value) dec++
  }
  const trend: SegmentSummary["trend"] = inc === sorted.length - 1 ? "increasing" : dec === sorted.length - 1 ? "decreasing" : "flat"
  return {
    segments: segments.length,
    segment_cv: cv,
    trend,
    note: `segment CV ${(cv * 100).toFixed(1)}%; values ${trend} with position`,
  }
}

export function needMoreThan(values: number[], min: number): never {
  throw makeError("MGE-E303", `need at least ${min} values for this statistic, got ${values.length}`, { required: min, got: values.length })
}
