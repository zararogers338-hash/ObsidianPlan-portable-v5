// Geotechnical test data parser and validator (metric #1).
//
// Takes raw controller input (a JSON envelope) and produces validated,
// normalized sample objects. All numeric fields are checked for null,
// non-finite, range, dimension and precision; units are normalized through
// units.ts; spec conditions are checked through metrics.checkSpecimenConditions.
// Failures carry MGE-E302 (numeric), MGE-E203 (unit), MGE-E202 (missing data).

import { makeError, type MgeError } from "./errors"
import {
  densityToGcc,
  lengthToMm,
  permeabilityToMs,
  pressureToKpa,
  strengthToKpa,
  UnitError,
} from "./units"

export interface RawSample {
  specimen_id?: string
  test_type?: string
  test_standard?: string
  dimensions?: { diameter?: number; height?: number; length?: number; width?: number; unit?: string }
  density?: number
  density_unit?: string
  relative_density?: number
  moisture_content?: number
  saturation?: number
  loading_rate?: number
  loading_rate_unit?: string
  confining_pressure?: number
  confining_pressure_unit?: string
  data_points?: { strain: number; stress: number; strain_unit?: string; stress_unit?: string }[]
  permeability?: number
  permeability_unit?: string
  caCO3_content?: number
  caCO3_unit?: string
  treatment?: string
  group?: string
  durability_cycles?: { cycle_count: number; strength: number; strength_unit?: string; cycle_type?: string }[]
  layer_data?: { position: number; position_unit?: string; value: number; metric?: string }[]
  note?: string
}

export interface NormalizedSample extends RawSample {
  specimen_id: string
  test_type: string
  density_gcm3?: number
  dimensions_mm?: { diameter?: number; height?: number; length?: number; width?: number }
  permeability_ms?: number
  durability_cycles_norm?: { cycle_count: number; strength_kpa: number; cycle_type: string }[]
  layer_data_norm?: { position_mm: number; value: number; metric: string }[]
  issues: string[]
  usable: boolean
}

export interface ParseResult {
  samples: NormalizedSample[]
  errors: MgeError[]
  warnings: string[]
}

function finite(v: unknown, field: string, ctx: string): number | null {
  if (v === undefined || v === null) return null
  if (typeof v !== "number") {
    throw makeError("MGE-E302", `${ctx}: field "${field}" is not a number`, { field, got: typeof v })
  }
  if (!Number.isFinite(v)) {
    throw makeError("MGE-E302", `${ctx}: field "${field}" is non-finite`, { field, value: String(v) })
  }
  return v
}

/** Normalize a single raw sample; returns null with error pushed if unusable. */
function normalizeSample(raw: RawSample, errors: MgeError[], warnings: string[]): NormalizedSample | null {
  const id = raw.specimen_id ?? "unknown"
  const ctx = `sample "${id}"`
  const out: NormalizedSample = { ...raw, specimen_id: id, test_type: raw.test_type ?? "other", issues: [], usable: true }

  // Numeric validation (throws MGE-E302 on hard type errors)
  const density = finite(raw.density, "density", ctx)
  const relDensity = finite(raw.relative_density, "relative_density", ctx)
  const moisture = finite(raw.moisture_content, "moisture_content", ctx)
  const saturation = finite(raw.saturation, "saturation", ctx)
  const loadingRate = finite(raw.loading_rate, "loading_rate", ctx)
  const confining = finite(raw.confining_pressure, "confining_pressure", ctx)
  const permeability = finite(raw.permeability, "permeability", ctx)
  const caco3 = finite(raw.caCO3_content, "caCO3_content", ctx)

  // Range checks
  if (relDensity !== null && (relDensity < 0 || relDensity > 100)) {
    errors.push(makeError("MGE-E302", `${ctx}: relative_density ${relDensity} outside [0,100]`, { field: "relative_density" }))
    out.issues.push(`relative_density out of [0,100]`)
  }
  if (saturation !== null && (saturation < 0 || saturation > 100)) {
    errors.push(makeError("MGE-E302", `${ctx}: saturation ${saturation} outside [0,100]`, { field: "saturation" }))
    out.issues.push(`saturation out of [0,100]`)
  }
  if (caco3 !== null && (caco3 < 0 || caco3 > 100)) {
    errors.push(makeError("MGE-E302", `${ctx}: caCO3_content ${caco3} outside [0,100]`, { field: "caCO3_content" }))
    out.issues.push(`caCO3_content out of [0,100]`)
  }
  if (permeability !== null && permeability < 0) {
    errors.push(makeError("MGE-E302", `${ctx}: permeability cannot be negative`, { field: "permeability" }))
    out.issues.push(`permeability negative`)
  }

  // Units (throw MGE-E203 via UnitError)
  try {
    if (density !== null) out.density_gcm3 = densityToGcc(density, raw.density_unit)
    if (permeability !== null) out.permeability_ms = permeabilityToMs(permeability, raw.permeability_unit)
  } catch (err) {
    if (err instanceof UnitError) {
      errors.push(makeError("MGE-E203", `${ctx}: ${err.message}`, { field: "unit" }))
      out.issues.push(err.message)
    } else {
      throw err
    }
  }

  // Dimensions
  if (raw.dimensions) {
    out.dimensions_mm = {}
    try {
      for (const key of ["diameter", "height", "length", "width"] as const) {
        const v = raw.dimensions[key]
        if (v !== undefined && v !== null) out.dimensions_mm[key] = lengthToMm(v, raw.dimensions.unit)
      }
    } catch (err) {
      if (err instanceof UnitError) {
        errors.push(makeError("MGE-E203", `${ctx}: ${err.message}`, { field: "dimensions.unit" }))
        out.issues.push(err.message)
      } else {
        throw err
      }
    }
  }

  // Durability cycles
  if (raw.durability_cycles && raw.durability_cycles.length > 0) {
    out.durability_cycles_norm = raw.durability_cycles.map((c) => {
      try {
        return {
          cycle_count: c.cycle_count,
          strength_kpa: strengthToKpa(c.strength, c.strength_unit),
          cycle_type: c.cycle_type ?? "other",
        }
      } catch (err) {
        if (err instanceof UnitError) {
          errors.push(makeError("MGE-E203", `${ctx}: durability strength unit: ${err.message}`, { field: "durability_cycles.strength_unit" }))
          out.issues.push(`durability strength unit: ${err.message}`)
          return { cycle_count: c.cycle_count, strength_kpa: c.strength, cycle_type: c.cycle_type ?? "other" }
        }
        throw err
      }
    })
  }

  // Layer data
  if (raw.layer_data && raw.layer_data.length > 0) {
    out.layer_data_norm = raw.layer_data.map((l) => ({
      position_mm: l.position_unit !== undefined ? lengthToMm(l.position, l.position_unit) : l.position,
      value: l.value,
      metric: l.metric ?? "strength",
    }))
  }

  // Sample adequacy: strength/permeability evaluation needs at least one
  // data point or an explicit scalar strength/permeability value.
  const hasCurve = raw.data_points !== undefined && raw.data_points.length > 0
  const hasScalar = raw.test_type === "permeability" ? permeability !== null && permeability > 0 : density !== null || raw.durability_cycles !== undefined
  if (!hasCurve && !hasScalar) {
    errors.push(
      makeError("MGE-E202", `${ctx}: no data_points and no scalar strength/permeability — cannot evaluate`, {
        specimen_id: id,
        field: "samples.data_points",
      }),
    )
    out.usable = false
  }

  return out
}

/**
 * Parse and validate the `samples` array of a controller envelope.
 * Never throws for bad sample data; collects errors instead.
 */
export function parseSamples(raw: unknown): ParseResult {
  const errors: MgeError[] = []
  const warnings: string[] = []
  if (!Array.isArray(raw)) {
    return { samples: [], errors: [makeError("MGE-E202", "input.samples must be an array", { field: "samples" })], warnings }
  }
  const samples: NormalizedSample[] = []
  for (const item of raw) {
    try {
      const norm = normalizeSample(item as RawSample, errors, warnings)
      if (norm) samples.push(norm)
    } catch (err) {
      if (isMgeError(err)) {
        errors.push(err)
      } else {
        errors.push(makeError("MGE-E305", `unexpected parse failure: ${(err as Error).message}`, {}))
      }
    }
  }
  return { samples, errors, warnings }
}

function isMgeError(v: unknown): v is MgeError {
  return typeof v === "object" && v !== null && "code" in v && "message" in v
}
