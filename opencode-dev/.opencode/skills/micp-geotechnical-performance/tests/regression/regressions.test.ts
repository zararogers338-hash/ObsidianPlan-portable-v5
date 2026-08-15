// Regression tests — lock in previously-fixed bugs and cross-skill contract
// stability (the router's registry indexes our SKILL.md / skill.yaml).

import { describe, expect, test } from "bun:test"
import { parseSamples } from "../../tools/src/parse"
import { extractIndicators, checkSpecimenConditions } from "../../tools/src/metrics"
import { sampleStats } from "../../tools/src/stats"
import { effectSize } from "../../tools/src/effect"
import { promises as fs } from "node:fs"
import path from "node:path"

const ROOT = path.resolve(__dirname, "..", "..")

// --- regression: previously-fixed bugs --------------------------------------

describe("regressions", () => {
  test("outliers use MAD (was: mean-based 2.5σ missed inflated-SD cases)", () => {
    const st = sampleStats([
      { id: "a", value: 100 },
      { id: "b", value: 102 },
      { id: "c", value: 99 },
      { id: "d", value: 300 },
    ])
    expect(st.outliers).toContain("d")
  })

  test("non-finite curve points are rejected (was: silently accepted)", () => {
    try {
      extractIndicators([
        { strain: 0, stress: 0 },
        { strain: 1, stress: Number.NaN },
      ])
      expect.unreachable()
    } catch (err) {
      expect((err as { code: string }).code).toBe("MGE-E302")
    }
  })

  test("null permeability sample is unusable (was: counted as available)", () => {
    const r = parseSamples([{ specimen_id: "N", test_type: "permeability", permeability: null }])
    expect(r.samples[0]!.usable).toBe(false)
  })

  test("evaluate envelope is schema-shaped (regression for MGE-E801)", async () => {
    const { validate } = await import("../../tools/src/jsonschema")
    const schema = JSON.parse(await fs.readFile(path.join(ROOT, "schemas", "output.schema.json"), "utf8")) as Record<string, unknown>
    const envelope = {
      status: "SUCCESS",
      summary: "s",
      findings: [],
      assumptions: [],
      evidence_used: [],
      uncertainty: [],
      risks: [],
      artifacts: [],
      requested_next_skills: [],
      validation: { self_check_passed: true, output_schema_valid: true, tool_calls: [], checks: [] },
      provenance: { skill_version: "1.0.0", controller_version: "1.0.0", data_refs_hash: "", timestamp: "2026-08-06T00:00:00Z" },
      errors: [],
    }
    expect(validate(envelope, schema)).toHaveLength(0)
  })
})

// --- regression: cross-skill contract stability -----------------------------

describe("cross-skill contract", () => {
  test("SKILL.md frontmatter satisfies the loader contract (name + description)", async () => {
    const content = await fs.readFile(path.join(ROOT, "SKILL.md"), "utf8")
    const fm = content.match(/^---\n([\s\S]*?)\n---/)?.[1] ?? ""
    expect(fm).toContain("name: micp-geotechnical-performance")
    expect(fm).toMatch(/description: "/)
    // description must survive the OSR subset parser (no block scalars)
    const { parseYAML } = await import("../../tools/src/yaml")
    const doc = parseYAML(fm)
    expect(doc.name).toBe("micp-geotechnical-performance")
    expect(typeof doc.description).toBe("string")
  })

  test("skill.yaml parses with the OSR subset parser", async () => {
    // Use the same YAML-subset parser the router ships (zero deps).
    const { parseYAML } = await import("../../tools/src/yaml")
    const raw = await fs.readFile(path.join(ROOT, "skill.yaml"), "utf8")
    const doc = parseYAML(raw)
    expect(doc.name).toBe("micp-geotechnical-performance")
    expect(doc.version).toBe("1.0.0")
    expect(doc.entry).toBe("tools/src/cli.ts")
    expect(Array.isArray(doc.capabilities)).toBe(true)
    expect(doc.network).toBe(false)
    // Cross-skill contract: the router's DOMAIN_MAP infers the capability
    // token "geotechnical" for strength/geotech requests, so it must be declared.
    expect((doc.capabilities as string[])).toContain("geotechnical")
  })

  test("output error codes match the MGE-E\\d{3} pattern", () => {
    const { ERROR_SPECS } = require("../../tools/src/errors") as { ERROR_SPECS: Record<string, { code: string }> }
    for (const spec of Object.values(ERROR_SPECS)) {
      expect(spec.code).toMatch(/^MGE-E\d{3}$/)
    }
  })
})

// --- regression: spec-condition and effect stability ------------------------

describe("condition + effect regression", () => {
  test("H/D ratio check tolerates exactly 2.0", () => {
    const issues = checkSpecimenConditions({
      specimen_id: "OK",
      test_type: "ucs",
      dimensions: { diameter: 38, height: 76 },
      density: 1.8,
      saturation: 100,
    })
    expect(issues).toHaveLength(0)
  })

  test("effect size sign is preserved (treated above control → positive d)", () => {
    const ef = effectSize({ a: [3000, 2500, 2300], b: [280, 270, 260] })
    expect(ef.cohens_d).toBeGreaterThan(0)
    expect(ef.improvement_percent).toBeGreaterThan(0)
  })
})
