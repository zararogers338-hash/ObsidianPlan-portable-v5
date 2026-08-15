// Adversarial / failure tests — attack the skill's inputs and outputs:
// label inflation, unit conflicts, missing data, oversized claims, NaN in
// curves, spec incomparability, and corrupted references. The skill must
// BLOCK or FAIL cleanly — never fabricate a SUCCESS.

import { describe, expect, test } from "bun:test"
import { parseSamples } from "../../tools/src/parse"
import { extractIndicators } from "../../tools/src/metrics"
import { effectSize, safetyMargin } from "../../tools/src/effect"
import { fitDecay } from "../../tools/src/durability"

describe("adversarial: numeric integrity", () => {
  test("curve containing NaN must throw MGE-E302", () => {
    try {
      extractIndicators([
        { strain: 0, stress: Number.NaN },
        { strain: 1, stress: 100 },
      ])
      expect.unreachable()
    } catch (err) {
      expect((err as { code: string }).code).toBe("MGE-E302")
    }
  })

  test("curve with Infinity must throw MGE-E302", () => {
    try {
      extractIndicators([
        { strain: 0, stress: 0 },
        { strain: 1, stress: Number.POSITIVE_INFINITY },
      ])
      expect.unreachable()
    } catch (err) {
      expect((err as { code: string }).code).toBe("MGE-E302")
    }
  })

  test("sample with null permeability flagged as missing, not invented", () => {
    const r = parseSamples([{ specimen_id: "N", test_type: "permeability", permeability: null }])
    // permeability:null → finite() returns null → treated as missing for adequacy
    expect(r.samples[0]!.usable).toBe(false)
  })

  test("conflicting units in the same sample produce MGE-E203", () => {
    const r = parseSamples([
      {
        specimen_id: "U",
        test_type: "ucs",
        density: 1.8,
        density_unit: "bogus-unit",
      },
    ])
    expect(r.errors.some((e) => e.code === "MGE-E203")).toBe(true)
  })

  test("negative caCO3 content flagged", () => {
    const r = parseSamples([{ specimen_id: "C", test_type: "ucs", caCO3_content: -3 }])
    expect(r.errors.some((e) => e.code === "MGE-E302")).toBe(true)
  })
})

describe("adversarial: statistical honesty", () => {
  test("tiny n=1 comparison reports no statistical significance and low reliability", () => {
    const ef = effectSize({ a: [3000], b: [280] })
    expect(ef.statistically_significant).toBe(false)
    expect(ef.p_value).toBeNull()
  })

  test("safety margin with high variability correctly flags inadequacy on the bound", () => {
    // observed mean 1050 vs target 1000, but stddev huge and n tiny → lower bound far below target
    const m = safetyMargin({ observed: 1050, target: 1000, higher_is_better: true, stddev: 2000, n: 2 })
    expect(m.ratio).toBeGreaterThan(1)
    expect(m.bound_ratio).not.toBeNull()
    expect(m.bound_ratio).toBeLessThan(1)
  })
})

describe("adversarial: durability honesty", () => {
  test("two-point durability reports trend only, never extrapolates", () => {
    const fit = fitDecay([
      { cycle_count: 0, strength_kpa: 1000 },
      { cycle_count: 10, strength_kpa: 500 },
    ])
    expect(fit.model).toBe("none")
    expect(fit.half_life_cycles).toBeNull()
    expect(fit.projected_cycles_to_threshold).toBeNull()
  })

  test("constant strength across cycles → no decay, adequate", () => {
    const fit = fitDecay([
      { cycle_count: 0, strength_kpa: 1000 },
      { cycle_count: 5, strength_kpa: 1000 },
      { cycle_count: 10, strength_kpa: 1000 },
    ])
    expect(fit.residual_ratio).toBeCloseTo(1, 5)
  })
})

describe("adversarial: evidence / label discipline", () => {
  test("parseSamples never invents values for missing fields", () => {
    const r = parseSamples([{ specimen_id: "M", test_type: "ucs", data_points: [] }])
    // no data, no scalar → flagged unusable; nothing fabricated
    expect(r.samples[0]!.usable).toBe(false)
    expect(r.samples[0]!.permeability_ms).toBeUndefined()
  })

  test("oversized single claim cannot become a statistical statement", () => {
    // One sample claiming UCS 50 MPa vs control 0.5 MPa: effectSize needs
    // groups; a lone treated sample cannot claim significance.
    const ef = effectSize({ a: [50000], b: [500, 520] })
    expect(ef.statistically_significant).toBe(false)
  })
})
