// Integration tests — full pipeline (service → planner → output envelope),
// real fixture registry, real decision-log writes, real schema validation.

import { describe, expect, test, beforeAll, afterAll } from "bun:test"
import path from "node:path"
import { promises as fs } from "node:fs"
import os from "node:os"
import { route, validateOutput } from "../../tools/osr/service"
import { indexRegistry } from "../../tools/osr/registry"
import { verifyChain } from "../../tools/osr/decision-log"
import { buildFixtureRegistry, FIXTURE_SKILLS } from "../fixtures"
import type { RouteResponse } from "../../tools/osr/types"

let fixture: Awaited<ReturnType<typeof buildFixtureRegistry>> | undefined
let logDir: string
let artifactDir: string

beforeAll(async () => {
  fixture = await buildFixtureRegistry()
  const base = await fs.mkdtemp(path.join(os.tmpdir(), "osr-it-"))
  logDir = path.join(base, "logs", "decisions")
  artifactDir = path.join(base, "state", "plans")
})
afterAll(async () => {
  await fixture?.cleanup()
})

function validRequest(overrides: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    task_id: "TASK-IT-1",
    project_id: "PRJ-IT",
    request: "评估 MICP 处理砂的强度与渗透系数变化",
    skill_version: "1.0.0",
    controller_version: "1.2.0",
    timestamp: "2026-08-06T10:00:00Z",
    risk_level: "medium",
    ...overrides,
  }
}

describe("service route — success path", () => {
  test("routes a multi-domain task to combined specialist plan", async () => {
    const res = await route(validRequest(), {
      snapshot: fixture!.snapshot,
      logDir,
      artifactDir,
      disableLog: false,
    })
    const r = res.response
    expect(r.status).toBe("SUCCESS")
    expect(r.route_plan).toBeDefined()
    expect(r.route_plan!.steps.length).toBeGreaterThan(0)
    // 跨领域组合:至少覆盖 geotechnical + transport + chemistry 之一
    const skills = r.route_plan!.steps.map((s) => s.skill)
    expect(skills.some((s) => s.includes("geotechnical"))).toBe(true)
    // 每步都有理由与预算
    for (const step of r.route_plan!.steps) {
      expect(step.reason.length).toBeGreaterThan(0)
      expect(step.budget.est_tokens).toBeGreaterThan(0)
      expect(step.expected_artifacts.length).toBeGreaterThan(0)
    }
    // 自检通过
    expect(r.validation.self_check_passed).toBe(true)
    expect(validateOutput(r).valid).toBe(true)
  })

  test("evidence_refs and data_refs appear in evidence_used", async () => {
    const res = await route(
      validRequest({
        evidence_refs: [{ ref_id: "ev:1", uri: "file:///ev.json" }],
        data_refs: [{ ref_id: "data:1" }],
      }),
      { snapshot: fixture!.snapshot, logDir, artifactDir },
    )
    const ids = res.response.evidence_used.map((e) => e.ref_id)
    expect(ids).toContain("ev:1")
    expect(ids).toContain("data:1")
  })

  test("writes a verifiable decision log record", async () => {
    const res = await route(validRequest({ task_id: "TASK-LOG-1" }), {
      snapshot: fixture!.snapshot,
      logDir,
      artifactDir,
    })
    expect(res.logEntry).toBeDefined()
    expect(res.logEntry!.seq).toBeGreaterThanOrEqual(1)
    expect(res.logEntry!.hash).toMatch(/^[0-9a-f]{64}$/)
    // re-open and verify chain
    const logFile = path.join(logDir, "PRJ-IT.jsonl")
    const chain = await verifyChain(logFile)
    expect(chain.ok).toBe(true)
    expect(chain.records).toBeGreaterThanOrEqual(1)
  })

  test("writes plan artifact to state/plans", async () => {
    const res = await route(validRequest({ task_id: "TASK-ART-1" }), {
      snapshot: fixture!.snapshot,
      logDir,
      artifactDir,
    })
    expect(res.artifactPath).toBeDefined()
    const content = JSON.parse(await fs.readFile(res.artifactPath!, "utf8"))
    expect(content.steps.length).toBeGreaterThan(0)
  })

  test("plan is deterministic for identical input", async () => {
    const a = await route(validRequest({ task_id: "TASK-DET-1" }), {
      snapshot: fixture!.snapshot,
      logDir,
      artifactDir,
      now: () => new Date("2026-08-06T00:00:00Z"),
    })
    const b = await route(validRequest({ task_id: "TASK-DET-1" }), {
      snapshot: fixture!.snapshot,
      logDir,
      artifactDir,
      now: () => new Date("2026-08-06T00:00:00Z"),
    })
    expect(a.response.route_plan!.steps).toEqual(b.response.route_plan!.steps)
    expect(a.response.route_plan!.total_budget).toEqual(b.response.route_plan!.total_budget)
  })
})

describe("service route — risk gating", () => {
  test("high risk chains red-team and decision-gate when present", async () => {
    const res = await route(validRequest({ risk_level: "high", human_approval_state: "approved" }), {
      snapshot: fixture!.snapshot,
      logDir,
      artifactDir,
    })
    const r = res.response
    expect(r.status).toBe("SUCCESS")
    const skills = r.route_plan!.steps.map((s) => s.skill)
    expect(skills).toContain("obsidian-red-team")
    expect(skills).toContain("obsidian-decision-gate")
    expect(r.route_plan!.guards.some((g) => g.includes("风险"))).toBe(true)
  })

  test("high risk with pending approval returns HUMAN_APPROVAL_REQUIRED", async () => {
    const res = await route(validRequest({ risk_level: "high", human_approval_state: "pending" }), {
      snapshot: fixture!.snapshot,
      logDir,
      artifactDir,
    })
    expect(res.response.status).toBe("HUMAN_APPROVAL_REQUIRED")
    expect(res.response.errors.some((e) => e.code === "OSR-E007")).toBe(true)
  })

  test("critical risk blocked when audit skills missing", async () => {
    const mini = await buildFixtureRegistry({ skills: FIXTURE_SKILLS.filter((s) => !s.name.includes("red-team") && !s.name.includes("decision-gate")) })
    try {
      const res = await route(validRequest({ risk_level: "critical", human_approval_state: "approved" }), {
        snapshot: mini.snapshot,
        disableLog: true,
      })
      expect(res.response.status).toBe("BLOCKED")
      expect(res.response.errors.some((e) => e.code === "OSR-E006")).toBe(true)
    } finally {
      await mini.cleanup()
    }
  })
})

describe("service route — input validation", () => {
  test("missing required fields return FAILED with per-field guidance", async () => {
    const res = await route({ request: "没有 task_id 也没有 project_id" }, { snapshot: fixture!.snapshot, disableLog: true })
    expect(res.response.status).toBe("FAILED")
    expect(res.response.errors.some((e) => e.code === "OSR-E001")).toBe(true)
    const details = res.response.errors[0]?.details as Record<string, unknown>
    expect(details?.missing_fields).toContain("task_id")
    const guidance = (details?.field_guidance as Record<string, string>) ?? {}
    expect(guidance.task_id).toBeDefined()
    expect((guidance.task_id as string | undefined)?.length ?? 0).toBeGreaterThan(10)
    // 自检仍通过(坏输入也要产出合法信封)
    expect(res.response.validation.self_check_passed).toBe(true)
    expect(validateOutput(res.response).valid).toBe(true)
  })

  test("invalid version format returns FAILED", async () => {
    const res = await route(validRequest({ skill_version: "abc" }), { snapshot: fixture!.snapshot, disableLog: true })
    expect(res.response.status).toBe("FAILED")
    expect(res.response.errors.some((e) => e.code === "OSR-E001")).toBe(true)
  })

  test("non-object input returns FAILED", async () => {
    const res = await route("just a string", { snapshot: fixture!.snapshot, disableLog: true })
    expect(res.response.status).toBe("FAILED")
  })
})

describe("service route — capability gap", () => {
  test("uncovered capability returns NEED_ADDITIONAL_SKILL with spec", async () => {
    const mini = await buildFixtureRegistry({ skills: FIXTURE_SKILLS.filter((s) => s.name !== "micp-geotechnical-performance") })
    try {
      const res = await route(
        validRequest({ request: "评估 MICP 处理砂的岩土承载强度", risk_level: "low" }),
        { snapshot: mini.snapshot, disableLog: true },
      )
      expect(res.response.status).toBe("NEED_ADDITIONAL_SKILL")
      expect(res.response.capability_gap_spec).toBeDefined()
      expect(res.response.capability_gap_spec!.suggested_name).toContain("geotechnical")
      expect(res.response.requested_next_skills.length).toBeGreaterThan(0)
    } finally {
      await mini.cleanup()
    }
  })
})

describe("registry indexer — real disk", () => {
  test("indexes the actual skill directory tree", async () => {
    // bun 测试运行时 cwd 为 skill 包根目录(bun test 在包目录运行)
    const { snapshot } = await indexRegistry([path.resolve(process.cwd())])
    const ours = snapshot.entries.find((e) => e.name === "obsidian-skill-router")
    expect(ours).toBeDefined()
    expect(ours!.usable).toBe(true)
    expect(ours!.description.length).toBeGreaterThan(0)
    expect(snapshot.snapshot_id).toMatch(/^reg_/)
  })

  test("deterministic fingerprint for identical roots", async () => {
    const a = await indexRegistry([path.resolve(__dirname, "..")])
    const b = await indexRegistry([path.resolve(__dirname, "..")])
    expect(a.snapshot.snapshot_id).toBe(b.snapshot.snapshot_id)
  })
})
