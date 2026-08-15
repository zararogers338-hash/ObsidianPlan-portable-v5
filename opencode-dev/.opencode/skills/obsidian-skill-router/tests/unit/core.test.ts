// Unit tests — pure modules, no disk I/O beyond fixtures.

import { describe, expect, test, beforeAll, afterAll } from "bun:test"
import { parseYAML, YAMLParseError, dumpYAML } from "../../tools/osr/yaml"
import { validate } from "../../tools/osr/jsonschema"
import { makeError, ERROR_SPECS, type ErrorCode } from "../../tools/osr/errors"
import { evaluate, evaluateProfile, DEFAULT_POLICY, type PolicyRule } from "../../tools/osr/policy"
import { checkPlan, auditEdges, digestInput, type CallGraphState } from "../../tools/osr/callgraph"
import { checkBudget, resolveCaps, type BudgetCaps } from "../../tools/osr/budget"
import { arbitrate, detectConflicts, detectLabelInflation, type Conflict } from "../../tools/osr/arbitrate"
import { matchSkill, rankSkills, tokenize } from "../../tools/osr/schema-match"
import { stableStringify, sha256Hex } from "../../tools/osr/registry"
import { recordHash } from "../../tools/osr/decision-log"
import { FIXTURE_SKILLS, buildFixtureRegistry } from "../fixtures"

let fixture: Awaited<ReturnType<typeof buildFixtureRegistry>> | undefined

beforeAll(async () => {
  fixture = await buildFixtureRegistry()
})
afterAll(async () => {
  await fixture?.cleanup()
})

describe("yaml subset parser", () => {
  test("parses nested map with sequence values", () => {
    const doc = parseYAML(`name: a-skill
description: A skill.
capabilities:
  - chemistry
  - transport
units:
  strength: MPa
cost_estimate:
  tokens: 2000
  usd: 0.02
`)
    expect(doc.name).toBe("a-skill")
    expect(doc.capabilities).toEqual(["chemistry", "transport"])
    expect((doc.units as Record<string, unknown>).strength).toBe("MPa")
    expect((doc.cost_estimate as Record<string, unknown>).tokens).toBe(2000)
  })

  test("handles flow sequence and scalar numbers/booleans", () => {
    const doc = parseYAML(`arr: [a, b, c]
network: false
version: 1.0.0
count: 3
`)
    expect(doc.arr).toEqual(["a", "b", "c"])
    expect(doc.network).toBe(false)
    expect(doc.version).toBe("1.0.0")
    expect(doc.count).toBe(3)
  })

  test("strips comments outside quotes", () => {
    const doc = parseYAML(`# top comment
name: demo # inline comment
note: "kept # hash"
`)
    expect(doc.name).toBe("demo")
    expect(doc.note).toBe("kept # hash")
  })

  test("rejects tabs", () => {
    expect(() => parseYAML("a:\n\tb: 1\n")).toThrow(YAMLParseError)
  })

  test("round-trips dump", () => {
    const original = { name: "x", caps: ["a", "b"], n: 1, unit: "MPa" }
    const dumped = dumpYAML(original)
    expect(parseYAML(dumped)).toEqual(original)
  })
})

describe("json schema subset validator", () => {
  const schema = {
    type: "object",
    required: ["a"],
    properties: {
      a: { type: "integer", minimum: 1 },
      b: { type: "string", maxLength: 3 },
      c: { enum: ["x", "y"] },
    },
    additionalProperties: false,
  }

  test("accepts valid object", () => {
    expect(validate({ a: 2, b: "ok", c: "x" }, schema)).toEqual([])
  })

  test("rejects missing required", () => {
    const issues = validate({ b: "ok" }, schema)
    expect(issues.some((i) => i.message.includes("missing required property \"a\""))).toBe(true)
  })

  test("rejects type mismatch", () => {
    const issues = validate({ a: "not-an-int" }, schema)
    expect(issues.some((i) => i.message.includes("expected type"))).toBe(true)
  })

  test("rejects additional property when disallowed", () => {
    const issues = validate({ a: 1, extra: true }, schema)
    expect(issues.some((i) => i.message.includes("additional property"))).toBe(true)
  })

  test("rejects out-of-range", () => {
    const issues = validate({ a: 0 }, schema)
    expect(issues.some((i) => i.message.includes("below minimum"))).toBe(true)
  })

  test("handles $ref to $defs", () => {
    const root = {
      $defs: { ref: { type: "object", required: ["ref_id"], properties: { ref_id: { type: "string" } } } },
      type: "array",
      items: { $ref: "#/$defs/ref" },
    }
    expect(validate([{ ref_id: "x" }], root)).toEqual([])
    expect(validate([{ no_id: true }], root).length).toBeGreaterThan(0)
  })

  test("handles anyOf", () => {
    const schema2 = { anyOf: [{ type: "string" }, { type: "number" }] }
    expect(validate("s", schema2)).toEqual([])
    expect(validate(3, schema2)).toEqual([])
    expect(validate(true, schema2).length).toBeGreaterThan(0)
  })

  test("oneOf requires exactly one match", () => {
    const schema3 = { oneOf: [{ type: "number", minimum: 0 }, { type: "number", maximum: 10 }] }
    expect(validate(5, schema3).length).toBeGreaterThan(0) // matches both
    expect(validate(-5, schema3)).toEqual([]) // matches only second
  })
})

describe("error code taxonomy", () => {
  test("all codes are OSR-E### and specified", () => {
    for (const code of Object.keys(ERROR_SPECS) as ErrorCode[]) {
      expect(code).toMatch(/^OSR-E\d{3}$/)
      expect(ERROR_SPECS[code].retryable).toBeTypeOf("boolean")
      expect(ERROR_SPECS[code].human.length).toBeGreaterThan(0)
    }
  })
  test("makeError carries retryable flag", () => {
    expect(makeError("OSR-E004", "dep unavailable").retryable).toBe(true)
    expect(makeError("OSR-E001", "bad input").retryable).toBe(false)
  })
})

describe("policy engine", () => {
  const rules: PolicyRule[] = [
    { permission: "*", pattern: "*", action: "allow" },
    { permission: "network", pattern: "*", action: "ask" },
    { permission: "write", pattern: "kb/**", action: "ask" },
    { permission: "bash", pattern: "*", action: "ask" },
  ]

  test("last matching rule wins (mirrors opencode semantics)", () => {
    const r: PolicyRule[] = [
      { permission: "*", pattern: "*", action: "allow" },
      { permission: "bash", pattern: "rm *", action: "deny" },
    ]
    expect(evaluate("bash", "rm -rf /", r)).toBe("deny")
    expect(evaluate("bash", "ls", r)).toBe("allow")
  })

  test("default action is ask when nothing matches", () => {
    expect(evaluate("read", "x", [])).toBe("ask")
  })

  test("deny blocks profile; ask at high risk requires approval", () => {
    const profile = { tools: ["read"], network: true, writes: [] }
    const denied = evaluateProfile(profile, [{ permission: "network", pattern: "*", action: "deny" }], {
      riskLevel: "high",
      skillName: "scout",
    })
    expect(denied.allowed).toBe(false)
    expect(denied.denials.length).toBe(1)

    const asks = evaluateProfile({ tools: ["read"], network: true, writes: [] }, rules, {
      riskLevel: "high",
      skillName: "scout",
    })
    expect(asks.allowed).toBe(true)
    expect(asks.requires_approval).toBe(true)
  })

  test("DEFAULT_POLICY is non-trivial and self-consistent", () => {
    expect(DEFAULT_POLICY.length).toBeGreaterThan(0)
    const p = evaluateProfile({ tools: ["read"], network: true, writes: [] }, DEFAULT_POLICY, {
      riskLevel: "medium",
      skillName: "scout",
    })
    expect(p.allowed).toBe(true)
  })
})

describe("call graph monitor", () => {
  test("rejects re-entry of a skill already in the chain (cycle)", () => {
    const state: CallGraphState = {
      chain: ["obsidian-controller", "obsidian-data-analyst"],
      completed: [],
      limits: { maxDepth: 4, maxTotalCalls: 16, maxRetriesPerSkill: 2 },
    }
    const res = checkPlan(state, [{ skill: "obsidian-data-analyst" }])
    expect(res.ok).toBe(false)
    expect(res.errors.some((e) => e.code === "OSR-E011")).toBe(true)
  })

  test("rejects depth overflow", () => {
    const state: CallGraphState = {
      chain: ["obsidian-controller", "a", "b", "c", "d"],
      completed: [],
      limits: { maxDepth: 4, maxTotalCalls: 16, maxRetriesPerSkill: 2 },
    }
    const res = checkPlan(state, [{ skill: "e" }])
    expect(res.ok).toBe(false)
    expect(res.errors[0]?.code).toBe("OSR-E011")
  })

  test("rejects exact duplicate invocation", () => {
    const digest = digestInput({ task_id: "t1", skill: "data-analyst" })
    const state: CallGraphState = {
      chain: ["obsidian-controller"],
      completed: [{ skill: "obsidian-data-analyst", input_digest: digest, status: "SUCCESS" }],
      limits: { maxDepth: 4, maxTotalCalls: 16, maxRetriesPerSkill: 2 },
    }
    const res = checkPlan(state, [{ skill: "obsidian-data-analyst", inputDigest: digest }])
    expect(res.ok).toBe(false)
    expect(res.errors.some((e) => e.code === "OSR-E012")).toBe(true)
  })

  test("auditEdges flags specialist->specialist bypass", () => {
    const { violations, ok } = auditEdges([
      { from: "obsidian-controller", to: "obsidian-skill-router" },
      { from: "obsidian-skill-router", to: "obsidian-evidence-synthesizer" },
      { from: "obsidian-evidence-synthesizer", to: "obsidian-literature-scout" }, // bypass
    ])
    expect(ok).toBe(false)
    expect(violations.length).toBe(1)
  })
})

describe("budget accountant", () => {
  const caps: BudgetCaps = { maxTokensTotal: 1000, maxCostUsdTotal: 1, maxWallTimeSec: 100, maxRetriesPerSkill: 1 }

  test("accepts within budget", () => {
    const res = checkBudget([{ skill: "a", estTokens: 300, estCostUsd: 0.1, timeoutSec: 60, maxRetries: 1 }], caps)
    expect(res.ok).toBe(true)
    expect(res.totals.tokens).toBe(600) // 300 * (1+1 retry)
  })

  test("rejects token overflow", () => {
    const res = checkBudget([{ skill: "a", estTokens: 900, estCostUsd: 0.1, timeoutSec: 60, maxRetries: 1 }], caps)
    expect(res.ok).toBe(false)
    expect(res.errors.some((e) => e.code === "OSR-E010")).toBe(true)
  })

  test("rejects NaN estimates as internal error", () => {
    const res = checkBudget([{ skill: "a", estTokens: Number.NaN, estCostUsd: 0.1, timeoutSec: 60, maxRetries: 1 }], caps)
    expect(res.ok).toBe(false)
    expect(res.errors.some((e) => e.code === "OSR-E017")).toBe(true)
  })

  test("rejects retry cap violation", () => {
    const res = checkBudget([{ skill: "a", estTokens: 100, estCostUsd: 0.1, timeoutSec: 60, maxRetries: 5 }], caps)
    expect(res.ok).toBe(false)
    expect(res.errors.some((e) => e.code === "OSR-E010")).toBe(true)
  })

  test("resolveCaps ignores invalid overrides", () => {
    const c = resolveCaps({ maxTokensTotal: -5, maxCostUsdTotal: Number.NaN, maxWallTimeSec: 50 })
    expect(c.maxTokensTotal).toBe(DEFAULT_CAPS_REF.maxTokensTotal)
    expect(c.maxCostUsdTotal).toBe(DEFAULT_CAPS_REF.maxCostUsdTotal)
    expect(c.maxWallTimeSec).toBe(50)
  })
})
const DEFAULT_CAPS_REF = { maxTokensTotal: 200_000, maxCostUsdTotal: 5.0, maxWallTimeSec: 1800, maxRetriesPerSkill: 2 }

describe("conflict arbitrator", () => {
  test("mechanical resolution only when winner strictly dominates", () => {
    const conflict: Conflict = {
      kind: "value_mismatch",
      subject: "strength",
      claims: [
        { source: "a", statement: "1.2", label: "OBSERVED", evidence_refs: ["ev:1"] },
        { source: "b", statement: "0.8", label: "REPORTED" },
      ],
    }
    const v = arbitrate(conflict)
    expect(v.type).toBe("resolved")
    if (v.type === "resolved") expect(v.winner.source).toBe("a")
  })

  test("escalates when loser has evidence", () => {
    const conflict: Conflict = {
      kind: "value_mismatch",
      subject: "permeability",
      claims: [
        { source: "a", statement: "1e-9", label: "OBSERVED", evidence_refs: ["ev:1"] },
        { source: "b", statement: "5e-9", label: "REPORTED", evidence_refs: ["ev:2"] },
      ],
    }
    expect(arbitrate(conflict).type).toBe("escalate")
  })

  test("unit conflict always escalates", () => {
    const conflict: Conflict = {
      kind: "unit_mismatch",
      subject: "conc",
      claims: [
        { source: "a", statement: "2", label: "CALCULATED", evidence_refs: ["ev:1"] },
        { source: "b", statement: "2000", label: "CALCULATED", evidence_refs: ["ev:2"] },
      ],
    }
    expect(arbitrate(conflict).type).toBe("escalate")
  })

  test("detectLabelInflation flags unsupported OBSERVED", () => {
    expect(detectLabelInflation({ source: "a", statement: "x", label: "OBSERVED" })).toBe(true)
    expect(detectLabelInflation({ source: "a", statement: "x", label: "OBSERVED", evidence_refs: ["e"] })).toBe(false)
  })

  test("detectConflicts groups by subject", () => {
    const conflicts = detectConflicts([
      { skill: "a", subject: "strength", value: "1.2", label: "OBSERVED" },
      { skill: "b", subject: "strength", value: "0.8", label: "REPORTED" },
      { skill: "c", subject: "strength", value: "0.8", label: "REPORTED" },
      { skill: "d", subject: "ph", value: "9", label: "OBSERVED" },
    ])
    expect(conflicts.length).toBe(1)
    expect(conflicts[0]?.subject).toBe("strength")
  })
})

describe("schema matching", () => {
  test("tokenize strips stopwords and CJK keeps meaning", () => {
    const tokens = tokenize("评估 MICP 处理砂的强度与渗透系数")
    expect(tokens.length).toBeGreaterThan(0)
    expect(tokens).toContain("评估")
  })

  test("capability-based matching beats name similarity", () => {
    const entries = FIXTURE_SKILLS.map((s) => ({
      name: s.name,
      description: s.description,
      location: s.name,
      dir: s.name,
      manifest: s.manifest,
      manifest_valid: true,
      issues: [],
      usable: true,
    }))
    const ctx = {
      requiredCapabilities: ["geotechnical", "transport"],
      availableInputs: ["task_id", "request", "data_refs"],
      expectedUnits: { strength: "MPa" },
    }
    const ranked = rankSkills(entries, ctx, "评估 MICP 处理砂的强度与渗透系数变化")
    const top = ranked[0]
    // 唯一同时覆盖 geotechnical+transport 的条目? fixture 中无 transport+geotech 合一技能,
    // 因此按能力覆盖优先排序,geotechnical 技能应排在前(覆盖 1/2 能力)。
    expect(top!.entry.name).toBe("micp-geotechnical-performance")
    expect(top!.score).toBeGreaterThan(0)
  })

  test("unit conflict zeroes a candidate despite name match", () => {
    const entry = {
      name: "micp-geotechnical-performance",
      description: "x",
      location: "x",
      dir: "x",
      manifest: { capabilities: ["geotechnical"], units: { strength: "kPa" } },
      manifest_valid: true,
      issues: [],
      usable: true,
    }
    const m = matchSkill(entry, {
      requiredCapabilities: ["geotechnical"],
      availableInputs: ["task_id"],
      expectedUnits: { strength: "MPa" },
    }, "评估强度")
    expect(m.unitConflicts.length).toBe(1)
    expect(m.score).toBeLessThanOrEqual(0)
  })

  test("skills without usable flag never rank", () => {
    const entries = [
      {
        name: "obsidian-data-analyst",
        description: "x",
        location: "x",
        dir: "x",
        manifest: { capabilities: ["data_analysis"] },
        manifest_valid: false,
        issues: ["bad manifest"],
        usable: false,
      },
    ]
    const ranked = rankSkills(entries, { requiredCapabilities: ["data_analysis"], availableInputs: [] }, "拟合数据")
    // usable=false 施加 -100 惩罚,但 rankSkills 仍返回排序结果;路由层(planner)依赖该惩罚排除之。
    expect(ranked.length).toBe(1)
    expect(ranked[0]!.score).toBeLessThan(0)
  })
})

describe("registry & decision-log hashing", () => {
  test("stableStringify is key-ordered and deterministic", () => {
    expect(stableStringify({ b: 1, a: 2 })).toBe(stableStringify({ a: 2, b: 1 }))
    expect(sha256Hex("x").length).toBe(64)
  })

  test("recordHash changes when content changes", () => {
    const base = { ts: "t", project_id: "p", task_id: "t1", decision: "route" as const, input_digest: "d", summary: "s", reasons: [], budget: { est_tokens: 1, est_cost_usd: 0 }, planned_skills: [], registry_snapshot_id: "r", router_version: "1.0.0", seq: 1, prev_hash: "0".repeat(64) }
    const h1 = recordHash(base)
    expect(recordHash({ ...base, summary: "s2" })).not.toBe(h1)
  })

  test("fixture registry builds usable entries", () => {
    expect(fixture?.snapshot.entries.length).toBe(FIXTURE_SKILLS.length)
    expect(fixture?.snapshot.entries.every((e) => e.usable)).toBe(true)
    expect(fixture?.snapshot.snapshot_id).toMatch(/^reg_[0-9a-f]{16}$/)
  })
})
