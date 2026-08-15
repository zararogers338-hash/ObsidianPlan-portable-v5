/**
 * obsidian-mission-lock — unit / regression / failure tests (bun:test).
 *
 * Covers the deterministic library layer. No network. Runs offline.
 * Run: bun test tools/tests/unit.test.ts
 */

import { describe, expect, test } from "bun:test"
import { detectAllConflicts } from "../src/conflicts"
import { diffContracts } from "../src/diff"
import { ERROR_CODES, MissionLockError } from "../src/errors"
import { detectMissingFields } from "../src/missing"
import type { MissionContract, SkillInput } from "../src/types"
import { checkContractUnits } from "../src/units"
import { isVersionCompatible, requiredBump, validateContract } from "../src/validate"

/** Minimal but schema-valid contract used to build variants. */
function baseContract(overrides: Partial<MissionContract> = {}): MissionContract {
  return {
    task_id: "t-1",
    contract_version: "1.0.0",
    title: "base mission",
    mission_type: "research",
    objectives: [
      { id: "O1", statement: "Determine X", kind: "scientific", depends_on: [] },
      { id: "O2", statement: "Engineer Y", kind: "engineering", depends_on: ["O1"] },
    ],
    primary_objective_id: "O1",
    secondary_objective_ids: ["O2"],
    explicit_exclusions: ["field work"],
    metrics: [{ name: "yield", direction: "maximize", target: { value: 90, unit: "%" } }],
    success_criteria: ["yield >= 90%"],
    failure_thresholds: ["yield < 50% after 10 rounds"],
    stop_conditions: ["90 day cap"],
    human_approval_gates: [],
    stakeholders: ["PI"],
    decision_use: "go/no-go on scale-up",
    statements: [{ text: "X increases Y", label: "HYPOTHESIS" }],
    assumptions: [],
    unknowns: [],
    risks: [],
    evidence_gaps: [],
    domain_tags: ["micp"],
    ...overrides,
  }
}

function inputFor(request: string, extra: Partial<SkillInput> = {}): SkillInput {
  return {
    task_id: "t-1",
    project_id: "p-1",
    request,
    skill_version: "1.0.0",
    timestamp: "2026-08-06T10:00:00Z",
    ...extra,
  }
}

// ---------------------------------------------------------------------------
// validate.ts
// ---------------------------------------------------------------------------

describe("contract schema validation", () => {
  test("accepts a valid contract", () => {
    const v = validateContract(baseContract())
    expect(v.ok).toBe(true)
    expect(v.issues).toEqual([])
  })

  test("rejects a contract with no metrics", () => {
    const v = validateContract(baseContract({ metrics: [] }))
    expect(v.ok).toBe(false)
    expect(v.issues.map((i) => i.path)).toContain("$.metrics")
  })

  test("rejects bare numeric target without unit", () => {
    // @ts-expect-error deliberate malformed input
    const bad = baseContract({ metrics: [{ name: "m", direction: "maximize", target: { value: 5 } }] })
    const v = validateContract(bad)
    expect(v.ok).toBe(false)
    expect(v.issues.some((i) => i.path.includes("unit"))).toBe(true)
  })

  test("rejects non-finite numeric target", () => {
    const v = validateContract(baseContract({ metrics: [{ name: "m", direction: "maximize", target: { value: Number.NaN, unit: "%" } }] }))
    expect(v.ok).toBe(false)
  })

  test("rejects missing primary_objective_id reference", () => {
    const v = validateContract(baseContract({ primary_objective_id: "O9" }))
    expect(v.ok).toBe(false)
  })

  test("rejects contract without stop conditions", () => {
    const v = validateContract(baseContract({ stop_conditions: [] }))
    expect(v.ok).toBe(false)
  })
})

describe("version compatibility policy", () => {
  test("requiredBump: breaking major / additive minor / fix patch / identical none", () => {
    expect(requiredBump("1.0.0", "2.0.0")).toBe("major")
    expect(requiredBump("1.0.0", "1.1.0")).toBe("minor")
    expect(requiredBump("1.0.0", "1.0.1")).toBe("patch")
    expect(requiredBump("1.0.0", "1.0.0")).toBe("none")
  })

  test("requiredBump: missing/invalid version is invalid", () => {
    expect(requiredBump("", "1.0.0")).toBe("invalid")
    expect(requiredBump("nope", "1.0.0")).toBe("invalid")
  })

  test("isVersionCompatible: same major ok, cross major without migration rejected", () => {
    expect(isVersionCompatible("1.4.2", "1.0.0", [])).toBe(true)
    expect(isVersionCompatible("2.0.0", "1.0.0", [])).toBe(false)
    expect(isVersionCompatible("2.0.0", "1.0.0", ["2.0.0->1.0.0"])).toBe(true)
    expect(isVersionCompatible("0.9.0", "1.0.0", [])).toBe(false)
  })
})

// ---------------------------------------------------------------------------
// units.ts
// ---------------------------------------------------------------------------

describe("unit and scale checking", () => {
  test("passes when a maintain metric's target matches current", () => {
    const c = baseContract({
      metrics: [
        { name: "permeability", direction: "maintain", current: { value: 0.001, unit: "m/s" }, target: { value: 0.001, unit: "m/s" } },
      ],
    })
    const issues = checkContractUnits(c)
    expect(issues.filter((i) => i.severity === "error")).toHaveLength(0)
  })

  test("flags unit mismatch between current and target", () => {
    const c = baseContract({
      metrics: [
        { name: "permeability", direction: "maintain", current: { value: 0.001, unit: "m/s" }, target: { value: 3.6, unit: "m/h" } },
      ],
    })
    const issues = checkContractUnits(c)
    expect(issues.filter((i) => i.severity === "error").length).toBeGreaterThan(0)
  })

  test("flags dimensionless metric using unit '%' — must use 'percent'", () => {
    const c = baseContract({ metrics: [{ name: "m", direction: "maximize", target: { value: 90, unit: "%" } }] })
    const issues = checkContractUnits(c)
    expect(issues.filter((i) => i.severity === "warning").some((i) => i.where.includes("m"))).toBe(true)
  })

  test("flags zero target for minimize unless genuine zero-threshold", () => {
    const c = baseContract({ metrics: [{ name: "cost", direction: "minimize", target: { value: 0, unit: "CNY" } }] })
    const issues = checkContractUnits(c)
    expect(issues.filter((i) => i.severity === "warning").some((i) => i.message.includes("zero"))).toBe(true)
  })

  test("flags negative target value", () => {
    const c = baseContract({ metrics: [{ name: "m", direction: "maximize", target: { value: -5, unit: "MPa" } }] })
    const issues = checkContractUnits(c)
    expect(issues.filter((i) => i.severity === "warning").some((i) => i.message.includes("negative"))).toBe(true)
  })

  test("flags direction inversion when maximize target is below threshold", () => {
    const c = baseContract({
      metrics: [
        {
          name: "strength",
          direction: "maximize",
          target: { value: 2, unit: "MPa" },
          threshold: { value: 5, unit: "MPa" },
        },
      ],
    })
    const issues = checkContractUnits(c)
    expect(issues.filter((i) => i.severity === "error").some((i) => i.message.includes("inverted"))).toBe(true)
  })
})

// ---------------------------------------------------------------------------
// conflicts.ts
// ---------------------------------------------------------------------------

describe("conflict detection", () => {
  test("detects the strength-vs-permeability MICP trade-off as hard", () => {
    const c = baseContract({
      metrics: [
        { name: "UCS strength", direction: "maximize", target: { value: 5, unit: "MPa" } },
        { name: "permeability", direction: "maintain", current: { value: 0.001, unit: "m/s" }, target: { value: 0.001, unit: "m/s" } },
      ],
    })
    const conflicts = detectAllConflicts({ metrics: c.metrics, constraints: {}, domain_tags: ["micp"], risks: [], statements: [] })
    const hard = conflicts.filter((x) => x.severity === "hard")
    expect(hard.some((x) => x.between.includes("UCS strength") && x.between.includes("permeability"))).toBe(true)
  })

  test("flags urea pathway + zero ammonium emission as a domain blindspot", () => {
    const conflicts = detectAllConflicts({
      metrics: [],
      constraints: { pathway: "urea hydrolysis", ammonium_emission: "zero NH4 emission" },
      domain_tags: ["micp"],
      risks: [],
      statements: [],
    })
    expect(conflicts.some((x) => x.kind === "domain-blindspot" && x.severity === "hard")).toBe(true)
  })

  test("does not flag non-urea pathway + zero ammonium emission", () => {
    const conflicts = detectAllConflicts({
      metrics: [],
      constraints: { pathway: "denitrification", ammonium_emission: "zero NH4 emission" },
      domain_tags: ["micp"],
      risks: [],
      statements: [],
    })
    expect(conflicts.some((x) => x.kind === "domain-blindspot")).toBe(false)
  })

  test("detects constraint pairs with maximize/minimize opposites", () => {
    const conflicts = detectAllConflicts({
      metrics: [],
      constraints: { a: "maximize X", b: "minimize X" },
      domain_tags: [],
      risks: [],
      statements: [],
    })
    expect(conflicts.some((x) => x.kind === "constraint-constraint" && x.severity === "soft")).toBe(true)
  })
})

// ---------------------------------------------------------------------------
// missing.ts
// ---------------------------------------------------------------------------

describe("missing-field detection", () => {
  test("vague request yields blocking gaps", () => {
    const missing = detectMissingFields(inputFor("提高MICP效果"), undefined)
    const blocking = missing.filter((m) => m.blocking)
    expect(blocking.length).toBeGreaterThanOrEqual(8)
    const names = blocking.map((m) => m.field)
    for (const f of ["contract.objectives", "contract.metrics[].target", "contract.stop_conditions", "micp.pathway", "micp.performance_metric"]) {
      expect(names).toContain(f)
    }
  })

  test("each missing field explains why and how to obtain", () => {
    const missing = detectMissingFields(inputFor("vague"), undefined)
    for (const m of missing) {
      expect(m.why_critical.length).toBeGreaterThan(0)
      expect(m.how_to_obtain.length).toBeGreaterThan(0)
      expect(typeof m.blocking).toBe("boolean")
    }
  })

  test("high-risk request without approval gate reports human_approval_state gap", () => {
    const missing = detectMissingFields(inputFor("field pilot of MICP", { risk_level: "high" }), undefined)
    const gap = missing.find((m) => m.field === "human_approval_state")
    expect(gap).toBeDefined()
    expect(gap!.blocking).toBe(true)
  })

  test("complete contract reduces blocking gaps", () => {
    const c = baseContract({
      spatial_scale: "lab column",
      temporal_scale: "28 days",
      stakeholders: ["PI", "site engineer"],
      domain_tags: [], // avoid MICP-specific checks in this generic test
    })
    const missing = detectMissingFields(inputFor("full"), c)
    expect(missing.filter((m) => m.blocking)).toHaveLength(0)
  })

  test("draft contract without NH4 risk under ureolysis gets an MICP-specific gap", () => {
    const c = baseContract({ domain_tags: ["micp", "ureolysis"] })
    const missing = detectMissingFields(inputFor("micp ureolysis"), c)
    expect(missing.some((m) => m.field === "micp.nitrogen_balance")).toBe(true)
  })
})

// ---------------------------------------------------------------------------
// diff.ts
// ---------------------------------------------------------------------------

describe("contract diff / goal drift", () => {
  test("identical contracts produce no drift alerts", () => {
    const a = baseContract()
    const d = diffContracts(a, { ...a })
    expect(d.drift_alerts).toHaveLength(0)
    expect(d.version_bump).toBe("none")
  })

  test("primary objective switch triggers critical drift", () => {
    const before = baseContract()
    const after = baseContract({
      primary_objective_id: "O2",
      secondary_objective_ids: [],
    })
    const d = diffContracts(before, after)
    expect(d.drift_alerts.some((x) => x.kind === "primary-objective-changed" && x.severity === "critical")).toBe(true)
  })

  test("removing a success criterion triggers critical drift", () => {
    const before = baseContract()
    const after = baseContract({ success_criteria: [] })
    const d = diffContracts(before, after)
    expect(d.drift_alerts.some((x) => x.kind === "success-criteria-weakened")).toBe(true)
  })

  test("removing an approval gate triggers critical drift", () => {
    const before = baseContract({ human_approval_gates: ["bio-safety sign-off"] })
    const after = baseContract()
    const d = diffContracts(before, after)
    expect(d.drift_alerts.some((x) => x.kind === "approval-gate-removed")).toBe(true)
  })

  test("changing task_id is flagged as a new mission, not a revision", () => {
    const before = baseContract()
    const after = baseContract({ task_id: "t-999" })
    const d = diffContracts(before, after)
    expect(d.same_task).toBe(false)
    expect(d.drift_alerts.some((x) => x.kind === "task-id-changed")).toBe(true)
  })
})

// ---------------------------------------------------------------------------
// errors.ts
// ---------------------------------------------------------------------------

describe("error code taxonomy", () => {
  test("all ten codes are registered and unique", () => {
    expect(ERROR_CODES).toHaveLength(10)
    expect(new Set(ERROR_CODES).size).toBe(10)
  })

  test("MissionLockError serializes machine-readably", () => {
    const e = new MissionLockError("OML-E1003", "unit mismatch", { metric: "k" })
    expect(e.code).toBe("OML-E1003")
    expect(e.retryable).toBe(false)
    const json = e.toJSON()
    expect(json).toMatchObject({ code: "OML-E1003", retryable: false })
    expect(typeof json.message).toBe("string")
  })

  test("OML-E1004 (tool unavailable) is retryable; OML-E1001 is not", () => {
    expect(new MissionLockError("OML-E1004", "x").retryable).toBe(true)
    expect(new MissionLockError("OML-E1007", "x").retryable).toBe(true)
    expect(new MissionLockError("OML-E1001", "x").retryable).toBe(false)
  })
})
