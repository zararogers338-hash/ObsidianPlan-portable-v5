// Regression tests — guard against regressions of previously fixed bugs.
// Each regression is anchored to a concrete bug report (BR-*).

import { describe, expect, test, beforeAll, afterAll } from "bun:test"
import { route } from "../../tools/osr/service"
import { checkPlan, auditEdges } from "../../tools/osr/callgraph"
import { evaluate, type PolicyRule } from "../../tools/osr/policy"
import { arbitrate, type Conflict } from "../../tools/osr/arbitrate"
import { buildFixtureRegistry, FIXTURE_SKILLS } from "../fixtures"

let fixture: Awaited<ReturnType<typeof buildFixtureRegistry>> | undefined

beforeAll(async () => {
  fixture = await buildFixtureRegistry()
})
afterAll(async () => {
  await fixture?.cleanup()
})

function req(overrides: Record<string, unknown> = {}) {
  return {
    task_id: "T-R-1",
    project_id: "P-R",
    request: "评估 MICP 处理砂的强度",
    skill_version: "1.0.0",
    controller_version: "1.2.0",
    timestamp: "2026-08-06T10:00:00Z",
    risk_level: "low",
    ...overrides,
  }
}

describe("BR-001: bad input must still produce a schema-valid envelope", () => {
  test("missing fields envelope passes output schema", async () => {
    const res = await route({ garbage: true }, { snapshot: fixture!.snapshot, disableLog: true })
    expect(res.response.errors[0]?.code).toBe("OSR-E001")
    // 信封本身必须能通过 output schema(保证控制器总能解析)
    const { validateOutput } = await import("../../tools/osr/service")
    const v = validateOutput(res.response)
    expect(v.valid).toBe(true)
  })
})

describe("BR-002: name similarity must not route", () => {
  test("a skill named like the domain but without capability never wins", async () => {
    const fake = await buildFixtureRegistry({
      skills: [
        ...FIXTURE_SKILLS.filter((s) => s.name !== "micp-geotechnical-performance"),
        {
          name: "geotech-superstar",
          description: "名字很像岩土,但未声明任何能力契约。Use when asked about geotech.",
          manifest: { version: "1.0.0", capabilities: [] },
        },
      ],
    })
    try {
      const res = await route(
        req({ request: "评估 MICP 处理砂的岩土强度", risk_level: "low" }),
        { snapshot: fake.snapshot, disableLog: true },
      )
      // 真实 geotechnical 技能被移除,唯一候选是名字相似但无能力的条目 → 必须报缺口
      expect(res.response.status).toBe("NEED_ADDITIONAL_SKILL")
      expect(res.response.capability_gap_spec?.suggested_name).toContain("geotechnical")
    } finally {
      await fake.cleanup()
    }
  })
})

describe("BR-003: unit mismatch escalates, never averaged", () => {
  test("unit conflict between two OBSERVED claims escalates", () => {
    const conflict: Conflict = {
      kind: "unit_mismatch",
      subject: "permeability",
      claims: [
        { source: "a", statement: "1e-9", label: "OBSERVED", evidence_refs: ["e1"] },
        { source: "b", statement: "1e-3", label: "OBSERVED", evidence_refs: ["e2"] },
      ],
    }
    expect(arbitrate(conflict).type).toBe("escalate")
  })
})

describe("BR-004: permission semantics mirror opencode (last-match-wins)", () => {
  test("narrow deny after broad allow wins for that pattern", () => {
    const rules: PolicyRule[] = [
      { permission: "*", pattern: "*", action: "allow" },
      { permission: "bash", pattern: "rm *", action: "deny" },
    ]
    expect(evaluate("bash", "rm file", rules)).toBe("deny")
    expect(evaluate("bash", "git status", rules)).toBe("allow")
    expect(evaluate("edit", "x", rules)).toBe("allow")
  })
})

describe("BR-005: recursion guard survives completed-success replay", () => {
  test("re-planning the same completed success is blocked as duplicate", () => {
    const digest = "cafe1234"
    const { ok } = checkPlan(
      {
        chain: ["obsidian-controller"],
        completed: [{ skill: "obsidian-data-analyst", input_digest: digest, status: "SUCCESS" }],
        limits: { maxDepth: 4, maxTotalCalls: 16, maxRetriesPerSkill: 2 },
      },
      [{ skill: "obsidian-data-analyst", inputDigest: digest }],
    )
    expect(ok).toBe(false)
  })
})

describe("BR-006: high-risk approval never downgrades silently", () => {
  test("approval pending blocks; approved routes", async () => {
    const pending = await route(req({ risk_level: "high", human_approval_state: "pending" }), {
      snapshot: fixture!.snapshot,
      disableLog: true,
    })
    expect(pending.response.status).toBe("HUMAN_APPROVAL_REQUIRED")

    const approved = await route(req({ risk_level: "high", human_approval_state: "approved" }), {
      snapshot: fixture!.snapshot,
      disableLog: true,
    })
    expect(approved.response.status).toBe("SUCCESS")
    expect(approved.response.route_plan!.steps.map((s) => s.skill)).toContain("obsidian-red-team")
  })
})

describe("BR-007: star topology violations flagged in audits", () => {
  test("auditEdges catches indirect specialist chain", () => {
    const { violations } = auditEdges([
      { from: "obsidian-literature-scout", to: "obsidian-evidence-extractor" },
    ])
    expect(violations.length).toBe(1)
  })
})
