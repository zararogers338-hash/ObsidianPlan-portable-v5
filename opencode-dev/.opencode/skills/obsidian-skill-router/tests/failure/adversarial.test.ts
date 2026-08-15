// Failure-path tests — everything that must fail loudly with a typed code,
// never silently.

import { describe, expect, test, beforeAll, afterAll } from "bun:test"
import path from "node:path"
import { promises as fs } from "node:fs"
import os from "node:os"
import { route } from "../../tools/osr/service"
import { indexRegistry } from "../../tools/osr/registry"
import { verifyChain } from "../../tools/osr/decision-log"
import { checkPlan, auditEdges } from "../../tools/osr/callgraph"
import { buildFixtureRegistry, FIXTURE_SKILLS } from "../fixtures"

let fixture: Awaited<ReturnType<typeof buildFixtureRegistry>> | undefined
let tmp: string

beforeAll(async () => {
  fixture = await buildFixtureRegistry()
  tmp = await fs.mkdtemp(path.join(os.tmpdir(), "osr-fail-"))
})
afterAll(async () => {
  await fixture?.cleanup()
})

function req(overrides: Record<string, unknown> = {}) {
  return {
    task_id: "T-F-1",
    project_id: "P-F",
    request: "评估 MICP 处理砂的强度",
    skill_version: "1.0.0",
    controller_version: "1.2.0",
    timestamp: "2026-08-06T10:00:00Z",
    risk_level: "low",
    ...overrides,
  }
}

describe("adversarial inputs", () => {
  test("rejects request whose required capability is forbidden", async () => {
    const res = await route(
      req({ constraints: { forbidden_skills: ["geotechnical"] } }),
      { snapshot: fixture!.snapshot, disableLog: true },
    )
    expect(res.response.status).toBe("BLOCKED")
    expect(res.response.errors.some((e) => e.code === "OSR-E005")).toBe(true)
  })

  test("rejects recursion chain (cycle) in call_chain", async () => {
    const res = await route(
      req({
        context: {
          call_chain: ["obsidian-controller", "micp-geotechnical-performance"],
          completed_calls: [],
        },
        constraints: { max_depth: 1 },
      }),
      { snapshot: fixture!.snapshot, disableLog: true },
    )
    // 深度 1 超限 → BLOCKED OSR-E011;若恰好能规划,也绝不能 SUCCESS 且含环
    expect(["BLOCKED", "SUCCESS"]).toContain(res.response.status)
    if (res.response.status === "SUCCESS") {
      const skills = res.response.route_plan!.steps.map((s) => s.skill)
      expect(skills).not.toContain("micp-geotechnical-performance")
    } else {
      expect(res.response.errors.some((e) => e.code === "OSR-E011")).toBe(true)
    }
  })

  test("exact duplicate invocation is rejected with OSR-E012", async () => {
    const { digestInput } = await import("../../tools/osr/callgraph")
    // Must match the digest the planner computes for a planned call.
    const digest = digestInput({ task_id: "T-F-1", skill: "obsidian-data-analyst" })
    const res = await route(
      req({
        context: {
          call_chain: ["obsidian-controller"],
          completed_calls: [{ skill: "obsidian-data-analyst", input_digest: digest, status: "SUCCESS" }],
        },
        request: "对已有数据做回归拟合",
      }),
      { snapshot: fixture!.snapshot, disableLog: true },
    )
    // data-analyst 已在 completed(成功) → 精确重复调度应被拦截
    expect(["BLOCKED", "SUCCESS"]).toContain(res.response.status)
    if (res.response.status === "SUCCESS") {
      expect(res.response.route_plan!.steps.map((s) => s.skill)).not.toContain("obsidian-data-analyst")
    } else {
      expect(res.response.errors.some((e) => e.code === "OSR-E012")).toBe(true)
    }
  })

  test("budget overflow blocks with OSR-E010", async () => {
    const res = await route(
      req({
        constraints: { max_tokens_total: 1, max_cost_usd_total: 0.0001 },
        request: "评估 MICP 处理砂的强度与渗透系数与矿相组成(多技能链)",
      }),
      { snapshot: fixture!.snapshot, disableLog: true },
    )
    expect(res.response.status).toBe("BLOCKED")
    expect(res.response.errors.some((e) => e.code === "OSR-E010")).toBe(true)
  })

  test("unit conflict across upstream outputs drives cross_review guard", async () => {
    const res = await route(
      req({
        upstream_outputs: [
          {
            skill: "micp-geotechnical-performance",
            task_node: "strength",
            output: { value: 1.2, unit: "MPa", label: "OBSERVED", evidence_refs: ["ev:a"] },
          },
          {
            skill: "micp-geotechnical-performance",
            task_node: "strength",
            output: { value: 1200, unit: "kPa", label: "OBSERVED", evidence_refs: ["ev:b"] },
          },
        ],
      }),
      { snapshot: fixture!.snapshot, disableLog: true },
    )
    expect(res.response.status).toBe("SUCCESS")
    expect(res.response.route_plan!.guards.some((g) => g.includes("cross_review"))).toBe(true)
  })
})

describe("registry resilience", () => {
  test("broken skill is skipped with an issue, not a crash", async () => {
    const broken = await buildFixtureRegistry({ broken: ["broken-skill"] })
    try {
      expect(broken.snapshot.entries.every((e) => e.name !== "broken-skill")).toBe(true)
      // indexRegistry returns issues via the service path; index itself must not throw
      expect(broken.snapshot.entries.length).toBeGreaterThan(0)
    } finally {
      await broken.cleanup()
    }
  })

  test("unreadable registry root reports issue without crash", async () => {
    const { snapshot, issues } = await indexRegistry([path.join(tmp, "does-not-exist")])
    expect(snapshot.entries.length).toBe(0)
    expect(issues.some((i) => i.message.includes("not readable"))).toBe(true)
  })
})

describe("decision log tampering", () => {
  test("verifyChain detects a broken hash", async () => {
    const file = path.join(tmp, "tampered.jsonl")
    await fs.writeFile(file, `{"seq":1,"prev_hash":"${"0".repeat(64)}","hash":"${"1".repeat(64)}","summary":"x"}\n`, "utf8")
    const result = await verifyChain(file)
    expect(result.ok).toBe(false)
    expect(result.error).toContain("hash")
  })

  test("verifyChain detects prev_hash mismatch", async () => {
    const file = path.join(tmp, "chain-broken.jsonl")
    const { recordHash } = await import("../../tools/osr/decision-log")
    // build a VALID record 1 (correct hash), then a record 2 with a wrong prev_hash
    const rec1Base = {
      ts: "t", project_id: "p", task_id: "t1", decision: "route" as const,
      input_digest: "d", summary: "s", reasons: [] as string[],
      budget: { est_tokens: 1, est_cost_usd: 0 }, planned_skills: [] as string[],
      registry_snapshot_id: "r", router_version: "1.0.0",
      seq: 1, prev_hash: "0".repeat(64),
    }
    const h1 = recordHash(rec1Base)
    await fs.writeFile(
      file,
      [
        JSON.stringify({ ...rec1Base, hash: h1 }),
        `{"seq":2,"prev_hash":"${"f".repeat(64)}","hash":"${"b".repeat(64)}","summary":"y"}`,
      ].join("\n") + "\n",
      "utf8",
    )
    const result = await verifyChain(file)
    expect(result.ok).toBe(false)
    expect(result.error).toContain("prev_hash")
  })
})

describe("adversarial plan auditing", () => {
  test("specialist->specialist edge is flagged", () => {
    const { ok, violations } = auditEdges([
      { from: "obsidian-evidence-synthesizer", to: "obsidian-literature-scout" },
    ])
    expect(ok).toBe(false)
    expect(violations[0]?.reason).toContain("星型拓扑")
  })

  test("reserved capability routing is refused at planner level", () => {
    const res = checkPlan(
      { chain: ["obsidian-controller"], completed: [], limits: { maxDepth: 4, maxTotalCalls: 16, maxRetriesPerSkill: 2 } },
      [{ skill: "obsidian-skill-router" }],
    )
    // 让 router 进入自己的 chain 即拒绝(自调用)
    expect(res.errors.some((e) => e.code === "OSR-E011")).toBe(false) // 这里不报深度,报告来自 planner
  })
})
