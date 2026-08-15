// Bootstrap (self-loading) regression tests — these lock in the exact
// behaviors the Skill discovered during its own self-test runs (BT-1..BT-4).
// They are the acceptance gates for the acceptance criteria in the task spec.

import { describe, expect, test } from "bun:test"
import { effectSize } from "../../tools/src/effect"
import { parseSamples } from "../../tools/src/parse"
import path from "node:path"
import { promises as fs } from "node:fs"

const ROOT = path.resolve(__dirname, "..", "..")
const CLI = path.join(ROOT, "tools", "src", "cli.ts")

async function runEval(input: Record<string, unknown>): Promise<Record<string, unknown>> {
  const file = path.join(ROOT, ".bootstrap-input.tmp.json")
  await fs.writeFile(file, JSON.stringify(input), "utf8")
  const proc = Bun.spawnSync(["bun", CLI, "evaluate", "--input", file], { cwd: ROOT })
  await fs.rm(file, { force: true }).catch(() => {})
  return JSON.parse(proc.stdout.toString("utf8"))
}

function baseReq(overrides: Record<string, unknown>): Record<string, unknown> {
  return {
    task_id: "BT",
    project_id: "PRJ-BOOT",
    skill_version: "1.0.0",
    controller_version: "1.0.0",
    timestamp: "2026-08-06T10:00:00Z",
    risk_level: "medium",
    human_approval_state: "approved",
    ...overrides,
  }
}

const UCS4 = (mpa: number[]) =>
  mpa.map((s) => ({ strain: 0, stress: 0, stress_unit: "MPa" }))
    .concat(mpa.map((s, i) => ({ strain: (i + 1) * 2, stress: s, stress_unit: "MPa" })))

describe("bootstrap BT-1: same mean UCS, different variability", () => {
  test("reports both CVs and non-significance, never a single-UCS verdict", async () => {
    const out = await runEval(
      baseReq({
        request: "方案 A 与方案 B 平均 UCS 相近但离散性不同,请比较。",
        samples: [
          { specimen_id: "A1", test_type: "ucs", group: "A", density: 1.79, data_points: UCS4([1.9, 3.2, 2.7]) },
          { specimen_id: "A2", test_type: "ucs", group: "A", density: 1.78, data_points: UCS4([1.8, 3.1, 2.6]) },
          { specimen_id: "A3", test_type: "ucs", group: "A", density: 1.78, data_points: UCS4([1.8, 3.05, 2.6]) },
          { specimen_id: "B1", test_type: "ucs", group: "B", density: 1.78, data_points: UCS4([1.5, 3.4, 2.9]) },
          { specimen_id: "B2", test_type: "ucs", group: "B", density: 1.78, data_points: UCS4([1.7, 3.0, 2.5]) },
          { specimen_id: "B3", test_type: "ucs", group: "B", density: 1.78, data_points: UCS4([1.4, 2.6, 2.2]) },
        ],
      }),
    )
    expect(out.status).toBe("SUCCESS")
    const g = (out.statistical as { group_means: Record<string, { cv?: number; mean_kpa: number }> }).group_means
    const cvA = g.A?.cv ?? Infinity
    const cvB = g.B?.cv ?? -Infinity
    expect(cvA).toBeLessThan(cvB)
    // Same mean → not statistically significant; p must be a real number, not 1
    expect((out.statistical as { p_value: number }).p_value).toBeGreaterThan(0.5)
  })
})

describe("bootstrap BT-2: strength up, permeability down 3 orders", () => {
  test("engineering_judgment states the orders-of-magnitude tradeoff", async () => {
    const out = await runEval(
      baseReq({
        request: "强度提高但渗透率降三个数量级,评估权衡。",
        samples: [
          { specimen_id: "TR", test_type: "ucs", group: "treated", density: 1.78, permeability: 1e-7, data_points: UCS4([1.8, 3.1, 2.6]) },
          { specimen_id: "CT", test_type: "permeability", group: "control", permeability: 1e-4 },
        ],
      }),
    )
    expect(out.status).toBe("SUCCESS")
    const j = (out.engineering_judgment as { judgment: string }).judgment
    expect(j).toContain("3.0 order(s) of magnitude")
  })
})

describe("bootstrap BT-3: different specimen sizes not directly comparable", () => {
  test("38mm vs 100mm specimens are flagged with a size-effect warning", async () => {
    const out = await runEval(
      baseReq({
        request: "把 38mm 和 100mm 试样的 UCS 直接比较。",
        samples: [
          { specimen_id: "S38", test_type: "ucs", group: "A", dimensions: { diameter: 38, height: 76 }, density: 1.78, data_points: UCS4([1.8, 3.1, 2.6]) },
          { specimen_id: "S100", test_type: "ucs", group: "B", dimensions: { diameter: 100, height: 200 }, density: 1.75, data_points: UCS4([1.5, 2.8, 2.4]) },
        ],
      }),
    )
    expect(out.status).toBe("SUCCESS")
    const samples = (out.performance as { samples: { specimen_id: string; conditions_issues: string[] }[] }).samples
    const s38 = samples.find((s) => s.specimen_id === "S38")!
    expect(s38.conditions_issues.join("; ")).toContain("size effect")
  })
})

describe("bootstrap BT-4: audit of an exaggerated engineering report", () => {
  test("50x claim with n=1 is NOT endorsed: no cohens_d, p=null, low reliability", async () => {
    const out = await runEval(
      baseReq({
        request: "审查报告称 MICP 把强度提升 50 倍,可立即用于高速公路路基。",
        risk_level: "high",
        samples: [
          { specimen_id: "REP-T", test_type: "ucs", group: "report_treated", density: 1.78, data_points: UCS4([8, 15, 12]) },
          { specimen_id: "REP-C", test_type: "ucs", group: "report_control", density: 1.74, data_points: UCS4([0.15, 0.3, 0.28]) },
        ],
      }),
    )
    expect(out.status).toBe("SUCCESS")
    const st = out.statistical as Record<string, unknown>
    expect(st.cohens_d).toBeUndefined() // n=1 per group → not calculable → NOT fabricated
    expect(st.p_value).toBeNull()
    expect(st.statistically_significant).toBe(false)
  })
})
