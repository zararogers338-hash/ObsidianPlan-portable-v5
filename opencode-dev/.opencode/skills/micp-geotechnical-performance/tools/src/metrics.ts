// Stress–strain curve indicator extraction (metric #2).
//
// Extracts UCS/peak/residual strength, peak strain, initial tangent modulus
// (E0), secant modulus at 50% peak (E50) and brittleness index (BI) from a
// normalized stress–strain point series. Deterministic and dependency-free.

import { normalizeDataPoint, strainToFraction } from "./units"
import { makeError, type MgeError } from "./errors"

export interface DataPointInput {
  strain: number
  stress: number
  strain_unit?: string
  stress_unit?: string
}

export interface CurveIndicators {
  /** peak axial stress in kPa */
  peak_strength_kpa: number
  /** stress at the largest strain in kPa (used as residual proxy) */
  residual_strength_kpa: number
  /** peak strain as fraction (0–1) */
  peak_strain_fraction: number
  /** UCS in kPa (alias of peak_strength for ucs-type tests) */
  ucs_kpa: number
  /** initial tangent modulus in kPa */
  e0_kpa: number
  /** secant modulus at 50% peak stress in kPa */
  e50_kpa: number
  /** brittleness index = 1 - residual/peak (0 ductile, 1 brittle) */
  brittleness_index: number
  /** raw point count */
  n_points: number
  /** normalized working points (stress kPa, strain fraction) */
  points: { stress_kpa: number; strain_fraction: number }[]
}

/** Linear least-squares slope over the first `window` points. */
function initialSlope(
  points: { stress_kpa: number; strain_fraction: number }[],
  window: number,
): number | undefined {
  if (points.length < 2) return undefined
  const use = Math.min(window, points.length)
  const pts = points.slice(0, use)
  // Exclude points at exactly zero strain to avoid a vertical segment.
  const nonZero = pts.filter((p) => p.strain_fraction > 0)
  if (nonZero.length < 2) return undefined
  const n = nonZero.length
  let sx = 0
  let sy = 0
  let sxx = 0
  let sxy = 0
  for (const p of nonZero) {
    sx += p.strain_fraction
    sy += p.stress_kpa
    sxx += p.strain_fraction * p.strain_fraction
    sxy += p.strain_fraction * p.stress_kpa
  }
  const denom = n * sxx - sx * sx
  if (denom === 0) return undefined
  return (n * sxy - sx * sy) / denom
}

/**
 * Extract curve indicators from a stress–strain series.
 *
 * @param points input points (may be in % strain / kPa etc.)
 * @param opts.window number of leading points used for E0 (default 5)
 * @param opts.minPoints minimum acceptable point count (default 2)
 * @param opts.error when the curve is unusable, returns it; if undefined, throws MgeError MGE-E303
 */
export function extractIndicators(
  points: DataPointInput[],
  opts: { window?: number; minPoints?: number; error?: MgeError } = {},
): CurveIndicators {
  const window = opts.window ?? 5
  const minPoints = opts.minPoints ?? 2

  if (points.length < minPoints) {
    const err = opts.error ?? makeError("MGE-E303", `need at least ${minPoints} data points, got ${points.length}`, { required: minPoints, got: points.length })
    throw err
  }

  // Numeric integrity: reject non-finite stress/strain before any computation.
  for (let i = 0; i < points.length; i++) {
    const p = points[i]!
    if (typeof p.stress !== "number" || !Number.isFinite(p.stress)) {
      throw makeError("MGE-E302", `data point ${i} has non-finite stress: ${String(p.stress)}`, { index: i, field: "data_points.stress" })
    }
    if (typeof p.strain !== "number" || !Number.isFinite(p.strain)) {
      throw makeError("MGE-E302", `data point ${i} has non-finite strain: ${String(p.strain)}`, { index: i, field: "data_points.strain" })
    }
  }

  const normalized = points.map((p) => normalizeDataPoint(p))
  const sorted = normalized
    .map((p) => ({ stress_kpa: p.stress_kpa, strain_fraction: p.strain_fraction }))
    .sort((a, b) => a.strain_fraction - b.strain_fraction)

  let peak = sorted[0]!
  for (const p of sorted) {
    if (p.stress_kpa > peak.stress_kpa) peak = p
  }
  const peakStress = peak.stress_kpa
  const peakStrain = peak.strain_fraction
  const last = sorted[sorted.length - 1]!
  const residual = last.stress_kpa

  const e0 = initialSlope(sorted, window)
  // E50: secant modulus from origin to the point at 50% of peak stress.
  let e50: number | undefined
  if (peakStress > 0) {
    const half = peakStress / 2
    // Find first point at or above half peak; interpolate strain linearly.
    let e50Strain: number | undefined
    for (let i = 0; i < sorted.length; i++) {
      const p = sorted[i]!
      if (p.stress_kpa >= half) {
        if (i === 0) {
          e50Strain = p.strain_fraction
        } else {
          const prev = sorted[i - 1]!
          const t = (half - prev.stress_kpa) / (p.stress_kpa - prev.stress_kpa || 1)
          e50Strain = prev.strain_fraction + t * (p.strain_fraction - prev.strain_fraction)
        }
        break
      }
    }
    e50 = e50Strain !== undefined && e50Strain > 0 ? half / e50Strain : undefined
  }

  const brittlenessIndex = peakStress > 0 ? 1 - residual / peakStress : 0

  return {
    peak_strength_kpa: peakStress,
    residual_strength_kpa: residual,
    peak_strain_fraction: peakStrain,
    ucs_kpa: peakStress,
    e0_kpa: e0 ?? NaN,
    e50_kpa: e50 ?? NaN,
    brittleness_index: brittlenessIndex,
    n_points: sorted.length,
    points: sorted,
  }
}

/**
 * Condition checks for specimen comparability (metric #1 and #4).
 * Returns issues as human-readable strings; empty array means comparable.
 */
export function checkSpecimenConditions(specimen: {
  specimen_id: string
  test_type?: string
  dimensions?: { diameter?: number; height?: number; length?: number; width?: number; unit?: string }
  density?: number
  density_unit?: string
  relative_density?: number
  loading_rate?: number
  loading_rate_unit?: string
  confining_pressure?: number
  confining_pressure_unit?: string
  moisture_content?: number
  saturation?: number
}): string[] {
  const issues: string[] = []
  const id = specimen.specimen_id
  const d = specimen.dimensions

  if (d) {
    if (d.diameter !== undefined && d.height !== undefined) {
      const ratio = d.height / d.diameter
      if (ratio < 1.5 || ratio > 2.5) {
        issues.push(`${id}: height/diameter ratio ${ratio.toFixed(2)} outside 1.5–2.5 (UCS end effects)`)
      }
    }
    if (d.diameter !== undefined && d.diameter < 30) {
      issues.push(`${id}: diameter ${d.diameter} mm < 30 mm (representativeness of coarse sand)`)
    }
  }

  if (specimen.density === undefined && specimen.relative_density === undefined) {
    issues.push(`${id}: neither density nor relative_density provided; density-controlled comparison not possible`)
  }

  if (specimen.moisture_content === undefined && specimen.saturation === undefined) {
    issues.push(`${id}: neither moisture_content nor saturation provided; saturation affects UCS substantially`)
  }

  if (specimen.test_type === "ucs" && specimen.loading_rate !== undefined) {
    const rate = specimen.loading_rate
    const unit = specimen.loading_rate_unit ?? "mm/min"
    if (unit === "mm/min" && rate > 1.5) {
      issues.push(`${id}: loading rate ${rate} mm/min high for UCS (ASTM D2166 allows 0.5–1%/min axial strain)`)
    }
  }

  return issues
}

/** Convenience: strain to percent for reporting. */
export function strainPercent(fraction: number): number {
  return fraction * 100
}

export { strainToFraction }
