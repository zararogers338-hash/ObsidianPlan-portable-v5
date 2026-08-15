// Integration tests — invoke the real CLI (`bun tools/src/cli.ts <sub>`)
// with real JSON inputs and assert on machine-readable output and exit codes.

import { describe, expect, test } from "bun:test"
import path from "node:path"
import { promises as fs } from "node:fs"
import os from "node:os"

const ROOT = path.resolve(__dirname, "..", "..")
const CLI = path.join(ROOT, "tools", "src", "cli.ts")

async function run(subcommand: string, input: unknown): Promise<{ stdout: string; exit: number }> {
  const dir = await fs.mkdtemp(path.join(os.tmpdir(), "mge-it-"))
  const file = path.join(dir, "input.json")
  await fs.writeFile(file, JSON.stringify(input), "utf8")
  const proc = Bun.spawnSync(["bun", CLI, subcommand, "--input", file], { cwd: ROOT })
  const stdout = proc.stdout.toString("utf8")
  await fs.rm(dir, { recursive: true, force: true }).catch(() => {})
  return { stdout, exit: proc.exitCode }
}

const SAMPLE = {
  specimen_id: "A1",
  test_type: "ucs",
  dimensions: { diameter: 38, height: 76 },
  density: 1.78,
  saturation: 100,
  caCO3_content: 12.5,
  data_points: [
    { strain: 0, stress: 0, stress_unit: "MPa" },
    { strain: 1, stress: 0.9, stress_unit: "MPa" },
    { strain: 2, stress: 1.8, stress_unit: "MPa" },
    { strain: 3, stress: 2.6, stress_unit: "MPa" },
    { strain: 4, stress: 3.1, stress_unit: "MPa" },
    { strain: 5, stress: 2.8, stress_unit: "MPa" },
  ],
}

describe("cli parse", () => {
  test("returns usable samples with zero errors", async () => {
    const { stdout, exit } = await run("parse", { samples: [SAMPLE] })
    expect(exit).toBe(0)
    const d = JSON.parse(stdout)
    expect(d.samples).toHaveLength(1)
    expect(d.samples[0]!.usable).toBe(true)
    expect(d.errors).toHaveLength(0)
  })

  test("missing data_points → MGE-E202 and exit 3", async () => {
    const { stdout, exit } = await run("parse", { samples: [{ specimen_id: "X", test_type: "ucs" }] })
    expect(exit).toBe(3)
    expect(JSON.parse(stdout).errors.some((e: { code: string }) => e.code === "MGE-E202")).toBe(true)
  })
})

describe("cli metrics", () => {
  test("extracts UCS in kPa from MPa input", async () => {
    const { stdout, exit } = await run("metrics", { samples: [SAMPLE] })
    expect(exit).toBe(0)
    const d = JSON.parse(stdout)
    expect(d.samples[0]!.indicators.ucs_kpa).toBeCloseTo(3100, 3)
  })
})

describe("cli stats", () => {
  test("groups by sample.group with per-group stats", async () => {
    const input = {
      samples: [
        { ...SAMPLE, specimen_id: "A1", group: "treated" },
        { ...SAMPLE, specimen_id: "A2", group: "treated" },
        { ...SAMPLE, specimen_id: "A3", group: "treated" },
        { ...SAMPLE, specimen_id: "B1", group: "control", data_points: SAMPLE.data_points.map((p) => ({ ...p, stress: p.stress / 10 })) },
        { ...SAMPLE, specimen_id: "B2", group: "control", data_points: SAMPLE.data_points.map((p) => ({ ...p, stress: p.stress / 10 })) },
        { ...SAMPLE, specimen_id: "B3", group: "control", data_points: SAMPLE.data_points.map((p) => ({ ...p, stress: p.stress / 10 })) },
      ],
    }
    const { stdout, exit } = await run("stats", input)
    expect(exit).toBe(0)
    const d = JSON.parse(stdout)
    expect(Object.keys(d.groups).sort()).toEqual(["control", "treated"])
    expect(d.groups.treated.n).toBe(3)
  })

  test("computes spatial uniformity from layer_data", async () => {
    const input = {
      samples: [
        {
          ...SAMPLE,
          specimen_id: "COL1",
          layer_data: [
            { position: 10, value: 420 },
            { position: 40, value: 380 },
            { position: 70, value: 350 },
            { position: 90, value: 310 },
          ],
        },
      ],
    }
    const { stdout, exit } = await run("stats", input)
    expect(exit).toBe(0)
    const d = JSON.parse(stdout)
    expect(d.spatial_uniformity.trend).toBe("decreasing")
    expect(d.spatial_uniformity.segment_cv).toBeGreaterThan(0)
  })
})

describe("cli durability", () => {
  test("fits decay and reports residual ratio", async () => {
    const input = {
      samples: [
        {
          specimen_id: "D1",
          test_type: "ucs",
          durability_cycles: [
            { cycle_count: 0, strength: 3000 },
            { cycle_count: 5, strength: 2100 },
            { cycle_count: 10, strength: 1600 },
            { cycle_count: 20, strength: 1200 },
          ],
        },
      ],
    }
    const { stdout, exit } = await run("durability", input)
    expect(exit).toBe(0)
    const d = JSON.parse(stdout)
    expect(d.fits[0]!.fit.residual_ratio).toBeCloseTo(0.4, 3)
    expect(d.fits[0]!.fit.r_squared).toBeGreaterThan(0.9)
  })
})

describe("cli effect", () => {
  test("computes effect size and safety margin", async () => {
    const { stdout, exit } = await run("effect", {
      a: [3000, 2500, 2300],
      b: [280, 270, 260],
      observed: 2600,
      target: 1000,
      higher_is_better: true,
      stddev: 380,
      n: 3,
    })
    expect(exit).toBe(0)
    const d = JSON.parse(stdout)
    expect(d.effect.cohens_d_interpretation).toBe("large")
    expect(d.effect.improvement_percent).toBeGreaterThan(800)
    expect(d.safety_margin.adequate).toBe(true)
  })
})

describe("cli evaluate (full pipeline)", () => {
  test("valid envelope → SUCCESS with schema-shaped output", async () => {
    const input = {
      task_id: "T-IT1",
      project_id: "PRJ-IT",
      request: "评估强度与耐久",
      skill_version: "1.0.0",
      controller_version: "1.0.0",
      timestamp: "2026-08-06T10:00:00Z",
      constraints: { engineering_thresholds: { target: 1000 } },
      samples: [SAMPLE],
    }
    const { stdout, exit } = await run("evaluate", input)
    expect(exit).toBe(0)
    const d = JSON.parse(stdout)
    expect(d.status).toBe("SUCCESS")
    expect(d.validation.self_check_passed).toBe(true)
    expect(d.validation.tool_calls.length).toBeGreaterThanOrEqual(3) // parse+metrics+stats (single group, no durability)
    expect(d.performance.samples[0]!.ucs.value).toBeCloseTo(3100, 3)
  })

  test("missing required envelope field → FAILED with MGE-E101", async () => {
    const { stdout, exit } = await run("evaluate", { request: "没有 task_id" })
    expect(exit).toBe(3)
    const d = JSON.parse(stdout)
    expect(d.status).toBe("FAILED")
    expect(d.errors[0]!.code).toBe("MGE-E101")
    expect(Object.keys(d.errors[0]!.details.field_guidance).length).toBeGreaterThan(0)
  })
})
