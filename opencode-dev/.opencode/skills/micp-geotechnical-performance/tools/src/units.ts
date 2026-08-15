// Unit validation and conversion for MGE.
//
// The skill accepts SI-priority units. Conversion tables are deliberately
// small and deterministic so the whole skill is offline-testable. Unknown
// units raise a UnitError that callers map to MGE-E203 (unit incompatible).

export class UnitError extends Error {
  constructor(message: string) {
    super(message)
    this.name = "UnitError"
  }
}

// --- dimension groups -------------------------------------------------------

/** strength-like: kPa base. */
const STRENGTH_TO_KPA: Record<string, number> = {
  pa: 0.001,
  kpa: 1,
  mpa: 1000,
  gpa: 1e6,
  psi: 6.894757,
  ksf: 47.88026,
  kgf_cm2: 98.0665,
  bar: 100,
}

/** modulus-like: kPa base. */
const MODULUS_TO_KPA: Record<string, number> = STRENGTH_TO_KPA

/** permeability-like: m/s base. */
const PERMEABILITY_TO_MS: Record<string, number> = {
  "m/s": 1,
  "cm/s": 0.01,
  "mm/s": 0.001,
  "m/d": 1 / 86400,
  "cm/d": 1 / 8640000,
  darcy: 9.869233e-7,
  "md": 9.869233e-10,
  "ft/d": 3.52778e-6,
}

/** density-like: g/cm3 base. */
const DENSITY_TO_GCC: Record<string, number> = {
  "g/cm3": 1,
  "kg/m3": 0.001,
  "kg/dm3": 1,
  "t/m3": 1,
}

/** length-like: mm base. */
const LENGTH_TO_MM: Record<string, number> = {
  mm: 1,
  cm: 10,
  m: 1000,
  in: 25.4,
  ft: 304.8,
}

/** pressure for confining stress: kPa base. */
const PRESSURE_TO_KPA: Record<string, number> = STRENGTH_TO_KPA

/** strain: dimensionless, normalized so 1 = 100% (i.e. % becomes 0.01). */
export function strainToFraction(value: number, unit?: string): number {
  if (unit === undefined || unit === "" || unit === "%") return value / 100
  if (unit === "fraction" || unit === "frac" || unit === "-") return value
  if (unit === "‰" || unit === "permille") return value / 1000
  throw new UnitError(`unknown strain unit "${unit}" (expected %, fraction or ‰)`)
}

export function fractionToStrain(fraction: number, unit: string): number {
  if (unit === "%" || unit === "" || unit === undefined) return fraction * 100
  if (unit === "fraction" || unit === "-") return fraction
  if (unit === "‰") return fraction * 1000
  throw new UnitError(`unknown strain unit "${unit}"`)
}

/** Convert a strength value to kPa. Throws UnitError for unknown units. */
export function strengthToKpa(value: number, unit?: string): number {
  if (unit === undefined || unit === "" || unit === "kpa") return value
  const key = unit.toLowerCase()
  const factor = STRENGTH_TO_KPA[key]
  if (factor === undefined) throw new UnitError(`unknown strength unit "${unit}"`)
  return value * factor
}

/** Convert a modulus value to kPa. */
export function modulusToKpa(value: number, unit?: string): number {
  return strengthToKpa(value, unit)
}

/** Convert a permeability value to m/s. Throws UnitError for unknown units. */
export function permeabilityToMs(value: number, unit?: string): number {
  if (unit === undefined || unit === "" || unit === "m/s") return value
  const key = unit.toLowerCase()
  const factor = PERMEABILITY_TO_MS[key]
  if (factor === undefined) throw new UnitError(`unknown permeability unit "${unit}"`)
  return value * factor
}

/** Convert a density value to g/cm3. */
export function densityToGcc(value: number, unit?: string): number {
  if (unit === undefined || unit === "" || unit === "g/cm3") return value
  const key = unit.toLowerCase()
  const factor = DENSITY_TO_GCC[key]
  if (factor === undefined) throw new UnitError(`unknown density unit "${unit}"`)
  return value * factor
}

/** Convert a length value to mm. */
export function lengthToMm(value: number, unit?: string): number {
  if (unit === undefined || unit === "" || unit === "mm") return value
  const key = unit.toLowerCase()
  const factor = LENGTH_TO_MM[key]
  if (factor === undefined) throw new UnitError(`unknown length unit "${unit}"`)
  return value * factor
}

/** Convert a pressure/confining value to kPa. */
export function pressureToKpa(value: number, unit?: string): number {
  return strengthToKpa(value, unit)
}

export interface StressStrainNormalized {
  stress_kpa: number
  strain_fraction: number
}

/** Normalize a stress–strain data point into kPa + fraction. */
export function normalizeDataPoint(point: {
  strain: number
  stress: number
  strain_unit?: string
  stress_unit?: string
}): StressStrainNormalized {
  return {
    stress_kpa: strengthToKpa(point.stress, point.stress_unit),
    strain_fraction: strainToFraction(point.strain, point.strain_unit),
  }
}

/**
 * Format a strength value back into a requested display unit (kPa default).
 * Used only for reporting; computations are always done in base units.
 */
export function formatStrength(kpa: number, unit = "kPa"): { value: number; unit: string } {
  const key = unit.toLowerCase()
  const factor = STRENGTH_TO_KPA[key]
  if (factor === undefined) return { value: kpa, unit: "kPa" }
  return { value: kpa / factor, unit }
}

export function formatPermeability(ms: number, unit = "m/s"): { value: number; unit: string } {
  const key = unit.toLowerCase()
  const factor = PERMEABILITY_TO_MS[key]
  if (factor === undefined) return { value: ms, unit: "m/s" }
  return { value: ms / factor, unit }
}
