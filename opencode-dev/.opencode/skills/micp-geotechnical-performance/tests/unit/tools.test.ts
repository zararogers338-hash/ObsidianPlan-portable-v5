// Unit tests for MGE tools — metrics extraction, unit conversion, statistics,
// durability fitting, effect size, parser validation, error codes.

import { describe, expect, test } from "bun:test"
import { extractIndicators, checkSpecimenConditions } from "../../tools/src/metrics"
import { strengthToKpa, permeabilityToMs, strainToFraction, UnitError, normalizeDataPoint } from "../../tools/src/units"
import { sampleStats, spatialUniformity, tCritical } from "../../tools/src/stats"
import { fitDecay } from "../../tools/src/durability"
import { effectSize, safetyMargin } from "../../tools/src/effect"
import { parseSamples } from "../../tools/src/parse"
import { makeError, ERROR_SPECS } from "../../tools/src/errors"

// --- units.ts ---------------------------------------------------------------

describe("units", () => {
  test("strength conversions", () => {
    expect(strengthToKpa(3.1, "MPa")).toBeCloseTo(3100, 5)
    expect(strengthToKpa(100, "kPa")).toBeCloseTo(100, 5)
    expect(strengthToKpa(1, "bar")).toBeCloseTo(100, 5)
    expect(() => strengthToKpa(1, "furlong")).toThrow(UnitError)
  })

  test("permeability conversions", () => {
    expect(permeabilityToMs(1, "cm/s")).toBeCloseTo(0.01, 10)
    expect(permeabilityToMs(1, "m/d")).toBeCloseTo(1 / 86400, 12)
    expect(permeabilityToMs(1, "m/s")).toBeCloseTo(1, 12)
    expect(() => permeabilityToMs(1, "bogus")).toThrow(UnitError)
  })

  test("strain conversion", () => {
    expect(strainToFraction(3.5, "%")).toBeCloseTo(0.035, 10)
    expect(strainToFraction(0.035, "fraction")).toBeCloseTo(0.035, 10)
    expect(() => strainToFraction(1, "xyz")).toThrow(UnitError)
  })

  test("data point normalization", () => {
    const p = normalizeDataPoint({ strain: 2, stress: 1.5, strain_unit: "%", stress_unit: "MPa" })
    expect(p.stress_kpa).toBeCloseTo(1500, 5)
    expect(p.strain_fraction).toBeCloseTo(0.02, 10)
  })
})

// --- metrics.ts -------------------------------------------------------------

describe("metrics", () => {
  test("extracts UCS, peak strain, E0, E50, BI from a hardening-softening curve", () => {
    const ind = extractIndicators([
      { strain: 0, stress: 0, stress_unit: "MPa" },
      { strain: 1, stress: 1.0, stress_unit: "MPa" },
      { strain: 2, stress: 1.8, stress_unit: "MPa" },
      { strain: 3, stress: 2.4, stress_unit: "MPa" },
      { strain: 4, stress: 2.5, stress_unit: "MPa" }, // peak
      { strain: 5, stress: 2.2, stress_unit: "MPa" },
      { strain: 6, stress: 1.9, stress_unit: "MPa" },
    ])
    expect(ind.ucs_kpa).toBeCloseTo(2500, 3)
    expect(ind.peak_strain_fraction).toBeCloseTo(0.04, 10)
    expect(ind.brittleness_index).toBeCloseTo(1 - 1900 / 2500, 5)
    expect(ind.e0_kpa).toBeGreaterThan(0)
    expect(ind.e50_kpa).toBeGreaterThan(0)
  })

  test("rejects too few data points with MGE-E303", () => {
    try {
      extractIndicators([{ strain: 0, stress: 0 }])
      expect.unreachable()
    } catch (err) {
      const e = err as { code: string }
      expect(e.code).toBe("MGE-E303")
    }
  })

  test("condition check flags wrong H/D ratio and missing density", () => {
    const issues = checkSpecimenConditions({
      specimen_id: "X1",
      test_type: "ucs",
      dimensions: { diameter: 38, height: 152 }, // H/D = 4
      loading_rate: 1.0,
    })
    const joined = issues.join("; ")
    expect(joined).toContain("ratio")
    expect(joined).toContain("density")
  })
})

// --- stats.ts ---------------------------------------------------------------

describe("stats", () => {
  test("sample stats: mean, median, CV, CI, reliability", () => {
    const st = sampleStats([
      { id: "a", value: 100 },
      { id: "b", value: 110 },
      { id: "c", value: 90 },
      { id: "d", value: 105 },
      { id: "e", value: 95 },
    ])
    expect(st.n).toBe(5)
    expect(st.mean).toBeCloseTo(100, 6)
    expect(st.median).toBe(100)
    expect(st.reliability).toBe("high") // n>=5 and cv<0.3
    expect(st.ci95.lower).toBeLessThan(st.mean)
    expect(st.ci95.upper).toBeGreaterThan(st.mean)
  })

  test("low sample size → reliability low", () => {
    const st = sampleStats([{ id: "a", value: 10 }])
    expect(st.reliability).toBe("low")
    expect(st.ci95.lower).toBeNaN()
  })

  test("outliers detected beyond 2.5 stddev", () => {
    const st = sampleStats([
      { id: "a", value: 100 },
      { id: "b", value: 102 },
      { id: "c", value: 99 },
      { id: "d", value: 300 }, // outlier
    ])
    expect(st.outliers).toContain("d")
  })

  test("spatial uniformity: decreasing trend with CV", () => {
    const u = spatialUniformity([
      { position: 10, value: 400 },
      { position: 40, value: 300 },
      { position: 70, value: 250 },
      { position: 90, value: 220 },
    ])
    expect(u.segments).toBe(4)
    expect(u.trend).toBe("decreasing")
    expect(u.segment_cv).toBeGreaterThan(0)
  })

  test("t critical interpolates and falls back to 1.96", () => {
    expect(tCritical(1000000)).toBeCloseTo(1.96, 5)
    expect(tCritical(5)).toBeCloseTo(2.5706, 3)
    expect(tCritical(7)).toBeGreaterThan(2.306)
  })
})

// --- durability.ts ----------------------------------------------------------

describe("durability", () => {
  test("fits log decay and reports residual ratio", () => {
    const fit = fitDecay([
      { cycle_count: 0, strength_kpa: 3000 },
      { cycle_count: 5, strength_kpa: 2100 },
      { cycle_count: 10, strength_kpa: 1600 },
      { cycle_count: 20, strength_kpa: 1200 },
    ])
    expect(fit.residual_ratio).toBeCloseTo(0.4, 5)
    expect(fit.model).toBe("log")
    expect(fit.r_squared).toBeGreaterThan(0.9)
    expect(fit.half_life_cycles).not.toBeNull()
  })

  test("two points → trend only, no extrapolation", () => {
    const fit = fitDecay([
      { cycle_count: 0, strength_kpa: 1000 },
      { cycle_count: 5, strength_kpa: 800 },
    ])
    expect(fit.model).toBe("none")
    expect(fit.projected_cycles_to_threshold).toBeNull()
  })

  test("insufficient points throws MGE-E303", () => {
    try {
      fitDecay([{ cycle_count: 0, strength_kpa: 1000 }])
      expect.unreachable()
    } catch (err) {
      expect((err as { code: string }).code).toBe("MGE-E303")
    }
  })
})

// --- effect.ts --------------------------------------------------------------

describe("effect", () => {
  test("large improvement, statistical significance, Cohen d interpretation", () => {
    const ef = effectSize({ a: [3000, 2500, 2300], b: [280, 270, 260] })
    expect(ef.improvement_percent).toBeGreaterThan(800)
    expect(ef.cohens_d_interpretation).toBe("large")
    // Massive separation (d≈8) → Welch t-test is statistically significant
    expect(ef.statistically_significant).toBe(true)
    expect(ef.p_value).toBeLessThan(0.01)
  })

  test("clear separation is statistically significant with adequate n", () => {
    const ef = effectSize({
      a: Array.from({ length: 20 }, (_, i) => 300 + i * 2),
      b: Array.from({ length: 20 }, (_, i) => 200 + i * 2),
    })
    expect(ef.statistically_significant).toBe(true)
    expect(ef.confidence_interval_kpa).not.toBeNull()
  })

  test("safety margin adequate when observed above target", () => {
    const m = safetyMargin({ observed: 1500, target: 1000, higher_is_better: true })
    expect(m.ratio).toBeCloseTo(1.5, 6)
    expect(m.adequate).toBe(true)
  })

  test("safety margin inadequate when observed below target", () => {
    const m = safetyMargin({ observed: 800, target: 1000, higher_is_better: true })
    expect(m.adequate).toBe(false)
  })
})

// --- parse.ts ---------------------------------------------------------------

describe("parse", () => {
  test("parses valid samples and normalizes units", () => {
    const r = parseSamples([
      {
        specimen_id: "A1",
        test_type: "ucs",
        density: 1.8,
        permeability: 2.5e-5,
        permeability_unit: "cm/s",
        data_points: [{ strain: 1, stress: 2 }],
      },
    ])
    expect(r.samples).toHaveLength(1)
    expect(r.errors).toHaveLength(0)
    const s = r.samples[0]!
    expect(s.permeability_ms).toBeCloseTo(2.5e-7, 15)
  })

  test("rejects non-finite density with MGE-E302", () => {
    const r = parseSamples([{ specimen_id: "B", test_type: "ucs", density: Number.NaN }])
    expect(r.errors.some((e) => e.code === "MGE-E302")).toBe(true)
  })

  test("rejects negative saturation with MGE-E302", () => {
    const r = parseSamples([{ specimen_id: "C", test_type: "ucs", saturation: -5 }])
    expect(r.errors.some((e) => e.code === "MGE-E302")).toBe(true)
  })

  test("rejects unknown unit with MGE-E203", () => {
    const r = parseSamples([{ specimen_id: "D", test_type: "ucs", density: 1.8, density_unit: "stones" }])
    expect(r.errors.some((e) => e.code === "MGE-E203")).toBe(true)
  })

  test("flags sample with no data as unusable (MGE-E202)", () => {
    const r = parseSamples([{ specimen_id: "E", test_type: "ucs" }])
    expect(r.samples[0]!.usable).toBe(false)
    expect(r.errors.some((e) => e.code === "MGE-E202")).toBe(true)
  })

  test("non-array samples → MGE-E202", () => {
    const r = parseSamples("not-an-array")
    expect(r.errors.some((e) => e.code === "MGE-E202")).toBe(true)
  })
})

// --- errors.ts --------------------------------------------------------------

describe("errors", () => {
  test("every error code has a spec with retryable flag", () => {
    for (const code of Object.keys(ERROR_SPECS)) {
      expect(ERROR_SPECS[code as keyof typeof ERROR_SPECS].retryable).toBeTypeOf("boolean")
    }
  })

  test("makeError stamps retryable from spec", () => {
    const e = makeError("MGE-E301", "tool unavailable")
    expect(e.retryable).toBe(true) // dependency errors are retryable
    const f = makeError("MGE-E101", "schema fail")
    expect(f.retryable).toBe(false)
  })
})
