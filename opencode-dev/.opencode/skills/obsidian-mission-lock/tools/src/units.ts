/**
 * Unit & scale consistency checker.
 *
 * Validates that every Quantity in a mission contract:
 *  - uses a known unit from the registry (dimension-typed),
 *  - has a finite, in-range value,
 *  - is dimensionally consistent when compared with sibling metrics
 *    (e.g. "maximize strength" target 5 MPa vs threshold 500 kPa — same
 *    dimension, converted before comparison).
 * Also checks spatial/temporal scale strings against a canonical registry.
 *
 * Offline, deterministic, no external deps. Source of unit knowledge:
 * SI brochure (BIPM) common engineering units — registry is intentionally
 * small and explicit rather than exhaustive; unknown units are flagged,
 * never silently accepted.
 */

import type { Metric, Quantity } from "./types"

export interface UnitIssue {
  severity: "error" | "warning"
  code: string
  message: string
  where: string
}

interface UnitDef {
  dimension: "pressure" | "length" | "time" | "permeability" | "concentration" | "mass" | "temperature" | "dimensionless" | "velocity" | "currency"
  toBase: number // multiply value by toBase to get base SI unit of that dimension
  base: string
}

/** Base units: pressure=Pa, length=m, time=s, permeability=m/s (hydraulic
 *  conductivity convention used in MICP literature, S11), concentration=mol/L,
 *  mass=kg, temperature=K, velocity=m/s, dimensionless=1. */
const UNITS: Record<string, UnitDef> = {
  Pa: { dimension: "pressure", toBase: 1, base: "Pa" },
  kPa: { dimension: "pressure", toBase: 1e3, base: "Pa" },
  MPa: { dimension: "pressure", toBase: 1e6, base: "Pa" },
  GPa: { dimension: "pressure", toBase: 1e9, base: "Pa" },
  bar: { dimension: "pressure", toBase: 1e5, base: "Pa" },
  psi: { dimension: "pressure", toBase: 6894.757, base: "Pa" },
  mm: { dimension: "length", toBase: 1e-3, base: "m" },
  cm: { dimension: "length", toBase: 1e-2, base: "m" },
  m: { dimension: "length", toBase: 1, base: "m" },
  km: { dimension: "length", toBase: 1e3, base: "m" },
  s: { dimension: "time", toBase: 1, base: "s" },
  min: { dimension: "time", toBase: 60, base: "s" },
  h: { dimension: "time", toBase: 3600, base: "s" },
  day: { dimension: "time", toBase: 86400, base: "s" },
  week: { dimension: "time", toBase: 604800, base: "s" },
  month: { dimension: "time", toBase: 2629800, base: "s" },
  year: { dimension: "time", toBase: 31557600, base: "s" },
  "m/s": { dimension: "permeability", toBase: 1, base: "m/s" },
  "cm/s": { dimension: "permeability", toBase: 1e-2, base: "m/s" },
  darcy: { dimension: "permeability", toBase: 9.869e-13, base: "m/s" }, // intrinsic perm., flagged separately
  "mol/L": { dimension: "concentration", toBase: 1, base: "mol/L" },
  "mmol/L": { dimension: "concentration", toBase: 1e-3, base: "mol/L" },
  "g/L": { dimension: "concentration", toBase: NaN, base: "g/L" }, // mass conc. — not convertible to molar without molar mass
  kg: { dimension: "mass", toBase: 1, base: "kg" },
  g: { dimension: "mass", toBase: 1e-3, base: "kg" },
  t: { dimension: "mass", toBase: 1e3, base: "kg" },
  "°C": { dimension: "temperature", toBase: 1, base: "°C" }, // offset handled below
  K: { dimension: "temperature", toBase: 1, base: "K" },
  "%": { dimension: "dimensionless", toBase: 1, base: "%" },
  percent: { dimension: "dimensionless", toBase: 1, base: "percent" },
  ratio: { dimension: "dimensionless", toBase: 1, base: "ratio" },
  "unitless": { dimension: "dimensionless", toBase: 1, base: "unitless" },
  CNY: { dimension: "currency", toBase: 1, base: "CNY" },
  USD: { dimension: "currency", toBase: 1, base: "USD" },
  EUR: { dimension: "currency", toBase: 1, base: "EUR" },
}

const SCALE_RE = /^\s*(lab|bench|pilot|field|column|batch|mesocosm)?\s*[\w-]*\s*(?:of|@|:)?\s*(\d+(?:\.\d+)?)\s*(mm|cm|m|km)\s*(?:-|to|–)\s*(\d+(?:\.\d+)?)\s*(mm|cm|m|km)\s*$/i
const TIME_RANGE_RE = /(\d+(?:\.\d+)?)\s*(s|min|h|day|week|month|year)s?\s*(?:-|to|–)\s*(\d+(?:\.\d+)?)\s*(s|min|h|day|week|month|year)s?/i

export function lookupUnit(unit: string): UnitDef | undefined {
  return UNITS[unit]
}

export function toBase(q: Quantity): number | null {
  const def = UNITS[q.unit]
  if (!def || Number.isNaN(def.toBase)) return null
  if (q.unit === "°C") return q.value + 273.15 // offset conversion
  return q.value * def.toBase
}

export function sameDimension(a: string, b: string): boolean {
  return UNITS[a]?.dimension !== undefined && UNITS[a]?.dimension === UNITS[b]?.dimension
}

function checkQuantity(q: Quantity, where: string, issues: UnitIssue[]): void {
  const def = UNITS[q.unit]
  if (!def) {
    issues.push({
      severity: "error",
      code: "OML-E1003",
      message: `Unknown unit "${q.unit}" — not in the unit registry; add it explicitly or convert to a registered unit`,
      where,
    })
    return
  }
  if (typeof q.value !== "number" || !Number.isFinite(q.value)) {
    issues.push({
      severity: "error",
      code: "OML-E1003",
      message: `Non-finite or non-numeric value (${String(q.value)}) for unit "${q.unit}"`,
      where,
    })
    return
  }
  if (q.value === 0) {
    // Zero is only legitimate as a genuine threshold (zero-emission target).
    // A zero target for, e.g., cost is unrealistic and must be explicit.
    issues.push({
      severity: "warning",
      code: "OML-E1003",
      message: `Value is exactly 0 ${q.unit} — only legitimate as a genuine zero-threshold (e.g. zero-emission); confirm this is intended, not a placeholder`,
      where,
    })
  }
  if (def.dimension === "dimensionless" && /%|pct/i.test(q.unit)) {
    issues.push({
      severity: "warning",
      code: "OML-E1003",
      message: `Unit "${q.unit}" is dimensionless — prefer explicit "percent" or "ratio" so consumers do not guess magnitude`,
      where,
    })
  }
  if (q.unit === "darcy") {
    issues.push({
      severity: "warning",
      code: "OML-E1003",
      message: `"darcy" measures intrinsic permeability (m²), not hydraulic conductivity (m/s); do not mix with m/s values without fluid properties`,
      where,
    })
  }
  if (def.dimension === "pressure" && q.value < 0) {
    issues.push({ severity: "warning", code: "OML-E1003", message: `Negative pressure/strength value ${q.value} ${q.unit} — negative values are not physically meaningful`, where })
  }
  if (def.dimension === "temperature" && q.unit === "K" && q.value < 0) {
    issues.push({ severity: "error", code: "OML-E1003", message: `Kelvin temperature below absolute zero: ${q.value}`, where })
  }
  if (def.dimension === "time" && q.value < 0) {
    issues.push({ severity: "warning", code: "OML-E1003", message: `Negative time value ${q.value} ${q.unit} — durations must be non-negative`, where })
  }
  if (def.dimension === "length" && q.value < 0) {
    issues.push({ severity: "warning", code: "OML-E1003", message: `Negative length value ${q.value} ${q.unit} — dimensions must be non-negative`, where })
  }
}

function checkMetric(m: Metric, where: string, issues: UnitIssue[]): void {
  if (m.target) checkQuantity(m.target, `${where}.target`, issues)
  if (m.threshold) checkQuantity(m.threshold, `${where}.threshold`, issues)
  if (m.current) checkQuantity(m.current, `${where}.current`, issues)

  // Cross-field dimensional consistency within one metric
  const fields: [string, Quantity | undefined][] = [
    ["target", m.target],
    ["threshold", m.threshold],
    ["current", m.current],
  ]
  const present = fields.filter((f): f is [string, Quantity] => f[1] !== undefined)
  for (let i = 0; i < present.length; i++) {
    for (let j = i + 1; j < present.length; j++) {
      const [nameA, qa] = present[i]
      const [nameB, qb] = present[j]
      if (!sameDimension(qa.unit, qb.unit)) {
        issues.push({
          severity: "error",
          code: "OML-E1003",
          message: `Metric "${m.name}": ${nameA} (${qa.unit}) and ${nameB} (${qb.unit}) have different dimensions`,
          where,
        })
      }
    }
  }

  // Sanity: target vs threshold ordering when direction is declared
  if (m.target && m.threshold && sameDimension(m.target.unit, m.threshold.unit)) {
    const t = toBase(m.target)
    const th = toBase(m.threshold)
    if (t !== null && th !== null) {
      if (m.direction === "maximize" && th > t) {
        issues.push({
          severity: "error",
          code: "OML-E1003",
          message: `Metric "${m.name}" (maximize): failure threshold (${m.threshold.value} ${m.threshold.unit}) exceeds target (${m.target.value} ${m.target.unit}) — inverted success/failure band`,
          where,
        })
      }
      if (m.direction === "minimize" && th < t) {
        issues.push({
          severity: "error",
          code: "OML-E1003",
          message: `Metric "${m.name}" (minimize): failure threshold (${m.threshold.value} ${m.threshold.unit}) is below target (${m.target.value} ${m.target.unit}) — inverted success/failure band`,
          where,
        })
      }
    }
  }
}

/** Check a scale string like "column 50 mm - 1 m" or "field 10 m - 100 m". */
export function checkSpatialScale(scale: string, where: string, issues: UnitIssue[]): void {
  const m = SCALE_RE.exec(scale)
  if (!m) {
    issues.push({
      severity: "warning",
      code: "OML-E1003",
      message: `Spatial scale "${scale}" is free-form; prefer "<regime> <min> <unit> - <max> <unit>" (e.g. "column 50 mm - 1 m") for machine checking`,
      where,
    })
    return
  }
  const lo = parseFloat(m[2]) * (UNITS[m[3]]?.toBase ?? NaN)
  const hi = parseFloat(m[4]) * (UNITS[m[5]]?.toBase ?? NaN)
  if (!Number.isFinite(lo) || !Number.isFinite(hi)) {
    issues.push({ severity: "error", code: "OML-E1003", message: `Spatial scale "${scale}" contains unknown units`, where })
    return
  }
  if (lo > hi) {
    issues.push({
      severity: "error",
      code: "OML-E1003",
      message: `Spatial scale "${scale}" is inverted (lower bound ${m[2]} ${m[3]} > upper bound ${m[4]} ${m[5]})`,
      where,
    })
  }
}

export function checkTemporalScale(scale: string, where: string, issues: UnitIssue[]): void {
  const m = TIME_RANGE_RE.exec(scale)
  if (!m) {
    issues.push({
      severity: "warning",
      code: "OML-E1003",
      message: `Temporal scale "${scale}" is free-form; prefer "<min> <unit> - <max> <unit>" (e.g. "28 day - 90 day")`,
      where,
    })
    return
  }
  const lo = parseFloat(m[1]) * (UNITS[m[2]]?.toBase ?? NaN)
  const hi = parseFloat(m[3]) * (UNITS[m[4]]?.toBase ?? NaN)
  if (Number.isFinite(lo) && Number.isFinite(hi) && lo > hi) {
    issues.push({
      severity: "error",
      code: "OML-E1003",
      message: `Temporal scale "${scale}" is inverted`,
      where,
    })
  }
}

/** Full contract-level unit check. */
export function checkContractUnits(contract: {
  metrics: Metric[]
  spatial_scale?: string
  temporal_scale?: string
}): UnitIssue[] {
  const issues: UnitIssue[] = []
  contract.metrics.forEach((m, i) => checkMetric(m, `metrics[${i}] (${m.name})`, issues))
  if (contract.spatial_scale) checkSpatialScale(contract.spatial_scale, "spatial_scale", issues)
  if (contract.temporal_scale) checkTemporalScale(contract.temporal_scale, "temporal_scale", issues)
  return issues
}
