// Effect size and engineering-significance judgment (metric #5).
//
// Computes group-comparison effect sizes (Cohen's d, pooled SD, improvement
// percent), safety margin against engineering thresholds, and the three-state
// judgment: statistically significant / engineering-significant / safety
// margin. Statistical significance is judged from a Welch t-test p-value
// (approximate, dependency-free). Deterministic.

import { mean, stddev, tCritical } from "./stats"

export interface EffectInput {
  /** group A values (e.g. treated), kPa */
  a: number[]
  /** group B values (e.g. control), kPa */
  b: number[]
  /** significance level, default 0.05 */
  alpha?: number
}

export interface EffectResult {
  n_a: number
  n_b: number
  mean_a_kpa: number
  mean_b_kpa: number
  improvement_percent: number // (meanA-meanB)/meanB*100, NaN if meanB==0
  pooled_stddev_kpa: number
  cohens_d: number
  cohens_d_interpretation: "negligible" | "small" | "medium" | "large"
  alpha: number
  p_value: number | null
  statistically_significant: boolean
  confidence_interval_kpa: { lower: number; upper: number } | null
  note: string
}

/** Welch t-test p-value (two-tailed), exact via the t→incomplete-beta link. */
export function welchP(a: number[], b: number[]): { p: number; t: number; df: number } | null {
  const na = a.length
  const nb = b.length
  if (na < 2 || nb < 2) return null
  const ma = mean(a)
  const mb = mean(b)
  const va = stddev(a, 1) ** 2
  const vb = stddev(b, 1) ** 2
  const se = Math.sqrt(va / na + vb / nb)
  if (se === 0) return { p: Number.NaN, t: Number.NaN, df: na + nb - 2 }
  const t = Math.abs((ma - mb) / se)
  const df = (va / na + vb / nb) ** 2 / ((va / na) ** 2 / (na - 1) + (vb / nb) ** 2 / (nb - 1))
  const p = twoTailTPValue(t, df)
  return { p, t, df }
}

/**
 * Two-tailed Student-t survival probability. Uses the identity
 *   p = I_{df/(df+t²)}(df/2, 1/2)
 * with a regularized incomplete beta (Lanczos + continued fraction). Exact
 * and deterministic for all df; no normal approximation.
 */
function twoTailTPValue(t: number, df: number): number {
  if (!Number.isFinite(df) || df <= 0) return Number.NaN
  if (t === 0) return 1
  const x = df / (df + t * t)
  return betai(df / 2, 0.5, x)
}

function logGamma(x: number): number {
  // Lanczos approximation, g=7, 9 coefficients (max rel err ~1e-12)
  const c = [
    0.99999999999980993, 676.5203681218851, -1259.1392167224028, 771.32342877765313,
    -176.61502916214059, 12.507343278686905, -0.13857109526572012, 9.9843695780195716e-6,
    1.5056327351493116e-7,
  ]
  if (x < 0.5) return Math.log(Math.PI) - Math.log(Math.sin(Math.PI * x)) - logGamma(1 - x)
  const z = x - 1
  let a = c[0]!
  const t = z + 7.5
  for (let i = 1; i < 9; i++) a += c[i]! / (z + i)
  return 0.5 * Math.log(2 * Math.PI) + (z + 0.5) * Math.log(t) - t + Math.log(a)
}

function betacf(a: number, b: number, x: number): number {
  const MAXIT = 200
  const EPS = 3e-12
  const FPMIN = 1e-300
  const qab = a + b
  const qap = a + 1
  const qam = a - 1
  let c = 1
  let d = 1 - (qab * x) / qap
  if (Math.abs(d) < FPMIN) d = FPMIN
  d = 1 / d
  let h = d
  for (let m = 1; m <= MAXIT; m++) {
    const m2 = 2 * m
    let aa = (m * (b - m) * x) / ((qam + m2) * (a + m2))
    d = 1 + aa * d
    if (Math.abs(d) < FPMIN) d = FPMIN
    c = 1 + aa / c
    if (Math.abs(c) < FPMIN) c = FPMIN
    d = 1 / d
    h *= d * c
    aa = (-(a + m) * (qab + m) * x) / ((a + m2) * (qap + m2))
    d = 1 + aa * d
    if (Math.abs(d) < FPMIN) d = FPMIN
    c = 1 + aa / c
    if (Math.abs(c) < FPMIN) c = FPMIN
    d = 1 / d
    const del = d * c
    h *= del
    if (Math.abs(del - 1) < EPS) break
  }
  return h
}

function betai(a: number, b: number, x: number): number {
  if (x <= 0) return 0
  if (x >= 1) return 1
  const bt = Math.exp(logGamma(a + b) - logGamma(a) - logGamma(b) + a * Math.log(x) + b * Math.log(1 - x))
  if (x < (a + 1) / (a + b + 2)) return (bt * betacf(a, b, x)) / a
  return 1 - (bt * betacf(b, a, 1 - x)) / b
}

export function cohensDInterpretation(d: number): EffectResult["cohens_d_interpretation"] {
  const ad = Math.abs(d)
  if (ad < 0.2) return "negligible"
  if (ad < 0.5) return "small"
  if (ad < 0.8) return "medium"
  return "large"
}

/** Compute effect size and statistical significance between two groups. */
export function effectSize(input: EffectInput): EffectResult {
  const { a, b } = input
  const alpha = input.alpha ?? 0.05
  const ma = mean(a)
  const mb = mean(b)
  const sa = stddev(a)
  const sb = stddev(b)
  const na = a.length
  const nb = b.length
  const pooled = Math.sqrt(((na - 1) * sa * sa + (nb - 1) * sb * sb) / Math.max(1, na + nb - 2))
  const d = pooled === 0 ? (ma === mb ? 0 : Number.NaN) : (ma - mb) / pooled
  const improvement = mb !== 0 ? ((ma - mb) / mb) * 100 : Number.NaN

  const wt = welchP(a, b)
  let ci: { lower: number; upper: number } | null = null
  if (wt && Number.isFinite(wt.df)) {
    const t = tCritical(Math.max(1, wt.df), alpha)
    const se = Math.sqrt(sa * sa / na + sb * sb / nb)
    ci = { lower: ma - mb - t * se, upper: ma - mb + t * se }
  }

  return {
    n_a: na,
    n_b: nb,
    mean_a_kpa: ma,
    mean_b_kpa: mb,
    improvement_percent: improvement,
    pooled_stddev_kpa: pooled,
    cohens_d: d,
    cohens_d_interpretation: cohensDInterpretation(d),
    alpha,
    p_value: wt ? wt.p : null,
    statistically_significant: wt ? wt.p <= alpha : false,
    confidence_interval_kpa: ci,
    note: "Welch t-test p-value via exact t→incomplete-beta; df = Welch-Satterthwaite",
  }
}

export interface SafetyMarginInput {
  /** observed performance value (e.g. mean UCS), in the same unit as target */
  observed: number
  /** engineering target/threshold, in the same unit */
  target: number
  /** true if higher observed value is better (e.g. strength); false for permeability */
  higher_is_better: boolean
  /** observed standard deviation (optional; enables margin vs lower/upper bound) */
  stddev?: number
  /** sample size (optional; enables margin on the CI bound) */
  n?: number
}

export interface SafetyMarginResult {
  ratio: number // observed / target (or target / observed for lower-is-better)
  margin_percent: number
  adequate: boolean
  bound_ratio: number | null // ratio computed on the conservative CI bound
  note: string
}

/** Safety margin: how much the observed value exceeds (or falls short of) a threshold. */
export function safetyMargin(input: SafetyMarginInput): SafetyMarginResult {
  const { observed, target, higher_is_better } = input
  if (target <= 0) {
    return { ratio: Number.NaN, margin_percent: Number.NaN, adequate: false, bound_ratio: null, note: "target must be positive" }
  }
  const ratio = higher_is_better ? observed / target : target / observed
  const margin = (ratio - 1) * 100
  let boundRatio: number | null = null
  let note = "no variability given; ratio on point estimate only"
  if (input.stddev !== undefined && input.n !== undefined && input.n >= 2) {
    const se = input.stddev / Math.sqrt(input.n)
    const t = tCritical(input.n - 1, 0.05)
    const bound = higher_is_better ? observed - t * se : observed + t * se
    boundRatio = higher_is_better ? bound / target : target / bound
    note = `ratio computed on 95% ${higher_is_better ? "lower" : "upper"} bound`
  }
  return {
    ratio,
    margin_percent: margin,
    adequate: ratio >= 1,
    bound_ratio: boundRatio,
    note,
  }
}
