import { describe, expect } from "bun:test"
import { Cause, Effect, Exit, Layer } from "effect"
import { ConfigV1 } from "@opencode-ai/core/v1/config/config"
import { SessionID } from "../../src/session/schema"
import { Session } from "../../src/session/session"
import { SessionPrompt } from "../../src/session/prompt"
import { node as ClawManagerNode, Service as ClawManager } from "../../src/claw/manager"
import {
  ClawError,
  CloudID,
  E,
  YUHENG_AGENT_NAME,
  capacityZone,
} from "../../src/claw/types"
import { assertAuditIndependence } from "../../src/claw/audit"
import { TestInstance } from "../fixture/fixture"
import { testEffect } from "../lib/effect"
import { reply, TestLLMServer } from "../lib/llm-server"
import { LayerNode } from "@opencode-ai/core/effect/layer-node"
import { FSUtil } from "@opencode-ai/core/fs-util"
import { EventV2Bridge } from "@/event-v2-bridge"
import { SessionProjector } from "@opencode-ai/core/session/projector"
import { MessageV2 } from "../../src/session/message-v2"
import path from "path"

/**
 * Full end-to-end integration: 4 REAL independent agent sessions, each driven
 * through the actual session loop against a scripted fake LLM server, composed
 * into one Audit Cloud by the control plane, then dissolved.
 *
 * This is the acceptance gate for the Claw/Cloud MVP: real sessions, real
 * isolation, real dissolution — no prompt role-playing of agent independence.
 */

const testLLMServerNode = LayerNode.make({ service: TestLLMServer, layer: TestLLMServer.layer, deps: [] })

const it = testEffect(
  LayerNode.compile(
    LayerNode.group([
      SessionPrompt.node,
      Session.node,
      SessionProjector.node,
      MessageV2.node,
      FSUtil.node,
      EventV2Bridge.node,
      ClawManagerNode,
      testLLMServerNode,
    ]),
    [],
  ),
)

const ref = (n: number | string, agentType = "micp-data-analyst") => ({
  id: SessionID.make(`ses_int_${n}`),
  agentType,
})

const CONTROL = { session: SessionID.make("ses_int_control"), agentType: "build" }

const writeConfig = Effect.fn("int.writeConfig")(function* (dir: string, config: Partial<ConfigV1.Info>) {
  const fs = yield* FSUtil.Service
  yield* fs.writeWithDirs(path.join(dir, "opencode.json"), JSON.stringify({ $schema: "https://opencode.ai/config.json", ...config }))
})

function providerCfg(url: string): Partial<ConfigV1.Info> {
  const auditor = (name: string, description: string) => ({
    [name]: {
      mode: "subagent" as const,
      description,
      hidden: true,
      prompt: `You are ${name}, an independent audit member of an Obsidian audit cloud. Answer in one short verdict line.`,
    },
  })
  return {
    enabled_providers: ["test"],
    agent: {
      ...auditor("micp-data-analyst", "independent statistics auditor"),
      ...auditor("micp-evidence-extractor", "independent evidence auditor"),
      ...auditor("micp-biology-reasoner", "independent biology auditor"),
      ...auditor("micp-ureolysis-chemistry", "independent chemistry auditor"),
    },
    provider: {
      test: {
        name: "Test",
        id: "test",
        env: [],
        npm: "@ai-sdk/openai-compatible",
        models: {
          "test-model": {
            id: "test-model",
            name: "Test Model",
            attachment: false,
            reasoning: false,
            temperature: false,
            tool_call: true,
            release_date: "2025-01-01",
            limit: { context: 100000, output: 10000 },
            cost: { input: 0, output: 0 },
            options: {},
          },
        },
        options: { apiKey: "test-key", baseURL: url },
      },
    },
  }
}

const runAuditCloudIntegration = Effect.fn("int.auditCloud")(function* (opts: {
  killIndex?: number
  selfAudit?: boolean
  yuhengJoin?: boolean
}) {
  const { directory } = yield* TestInstance
  const llm = yield* TestLLMServer
  yield* writeConfig(directory, providerCfg(llm.url))

  const sessions = yield* Session.Service
  const prompt = yield* SessionPrompt.Service
  const claw = yield* ClawManager

  // ── 1. create 4 real agent sessions, each its own context/permissions/log ──
  const agentTypes = ["micp-data-analyst", "micp-evidence-extractor", "micp-biology-reasoner", "micp-ureolysis-chemistry"]
  const agents = []
  for (const [i, agentType] of agentTypes.entries()) {
    const s = yield* sessions.create({
      title: `audit-member-${i}`,
      agent: agentType,
      permission: [{ permission: "*", pattern: "*", action: "allow" }],
    })
    agents.push({ id: s.id, agentType })
  }

  // ── 2. control plane forms the cloud ──
  let cloud = yield* claw.createCloud({
    cloud_type: "audit",
    purpose: "integration: audit MICP evidence cards",
    created_by: CONTROL,
    token_budget: 100_000,
  })
  for (const [i, a] of agents.entries()) {
    yield* claw.joinCloud(cloud.cloud_id, { id: a.id, agentType: a.agentType }, `auditor-${i + 1}`)
  }
  cloud = yield* claw.activate(cloud.cloud_id)

  // ── 3. optional adversarial joins ──
  if (opts.yuhengJoin) {
    const exit = yield* claw
      .joinCloud(cloud.cloud_id, { id: SessionID.make("ses_int_yh"), agentType: YUHENG_AGENT_NAME }, "controller")
      .pipe(Effect.exit)
    expect(Exit.isFailure(exit)).toBe(true)
  }
  if (opts.selfAudit) {
    // The research target cloud is staffed by a DIFFERENT agent (never a
    // member of the audit cloud) so we can prove the audit cloud may not
    // recruit the executor of the work it audits.
    const target = yield* claw.createCloud({ cloud_type: "research", purpose: "target", created_by: CONTROL, token_budget: 5000 })
    const targetWorker = { id: SessionID.make("ses_int_target_worker"), agentType: "micp-data-analyst" }
    yield* claw.joinCloud(target.cloud_id, targetWorker, "researcher")
    yield* claw.activate(target.cloud_id)
    yield* claw.complete(target.cloud_id, "research done")
    const audit = yield* claw.createCloud({
      cloud_type: "audit",
      purpose: "audit target",
      created_by: CONTROL,
      token_budget: 5000,
      audit_target: target.cloud_id,
    })
    // the executor of the target work may not join its own audit cloud
    const exit = yield* claw.joinCloud(audit.cloud_id, targetWorker, "auditor").pipe(Effect.exit)
    expect(Exit.isFailure(exit)).toBe(true)
  }

  // ── 4. round 1: independent first-pass verdicts, sealed BEFORE exchange ──
  const verdicts = [
    "finding-A: evidence card ev://1 inconsistent units",
    "finding-B: evidence card ev://2 missing control group",
    "finding-C: no blocking issue",
    "finding-D: critical NH4 mass-balance violation, evidence ev://7",
  ]
  for (const [i, a] of agents.entries()) {
    // Each member runs its own session loop against its own scripted reply.
    // No member sees another's verdict before sealing.
    yield* llm.text(verdicts[i])
    const res = yield* prompt.prompt({
      sessionID: a.id,
      agent: a.agentType,
      parts: [{ type: "text", text: `independently audit the assigned evidence cards; output one verdict line` }],
    })
    const text = res.parts.filter((p) => p.type === "text").map((p) => p.text).join("")
    yield* claw.sealVerdict(cloud.cloud_id, a.id, text || verdicts[i])
  }
  cloud = yield* claw.getCloud(cloud.cloud_id)
  expect(cloud.members.every((m) => m.sealedVerdict !== undefined)).toBe(true)

  // ── 5. round 2: claw exchange (data channel) ──
  const ab = yield* claw.openClaw(cloud.cloud_id, agents[0].id, agents[1].id)
  yield* claw.send(ab.claw_session_id, { from: agents[0].id, to: agents[1].id, kind: "report", payload: "A sealed: units issue", evidence_refs: ["ev://1"] })
  yield* claw.send(ab.claw_session_id, { from: agents[1].id, to: agents[0].id, kind: "challenge", payload: "B challenges A scope" })

  // ── 6. conflict check: supplementary investigation only where challenged ──
  yield* llm.text("supplementary: confirmed ev://7 NH4 violation is real")
  const supplemental = yield* prompt.prompt({
    sessionID: agents[3].id,
    agent: agents[3].agentType,
    parts: [{ type: "text", text: "after seeing challenges, verify your critical finding stands; output one line" }],
  })
  const supText = supplemental.parts.filter((p) => p.type === "text").map((p) => p.text).join("")
  expect(supText).toContain("confirmed")

  // ── 7. review + unified report (evidence-first, not majority vote) ──
  cloud = yield* claw.beginReview(cloud.cloud_id)
  const report = yield* claw.auditReport(cloud.cloud_id)
  // single well-evidenced severe finding (member 4) is present regardless of
  // members 1-3 not flagging it
  expect(report).toContain("NH4")

  // ── 8. optional member kill mid-flight ──
  if (opts.killIndex !== undefined) {
    const victim = agents[opts.killIndex]
    yield* claw.freezeMember(cloud.cloud_id, victim.id, "integration kill")
    yield* claw.snapshotMember(cloud.cloud_id, victim.id)
    yield* claw.distillMember(cloud.cloud_id, victim.id, "distilled partial findings")
    yield* claw.evictMember(cloud.cloud_id, victim.id)
    const after = yield* claw.getCloud(cloud.cloud_id)
    const killed = after.members.find((m) => m.ref.id === victim.id)
    expect(killed?.status).toBe("RELEASED")
    expect(killed?.sealedVerdict).toBeDefined()
  }

  // ── 9. dissolve ──
  const done = yield* claw.complete(cloud.cloud_id, report)
  expect(done.status).toBe("COMPLETED")
  expect(done.members.every((m) => m.releasedAt !== undefined)).toBe(true)
  expect((yield* claw.activeLeases(cloud.cloud_id)).length).toBe(0)

  // ── 10. archive + destroy keeps artifacts ──
  yield* claw.archive(cloud.cloud_id)
  const destroyed = yield* claw.destroy(cloud.cloud_id)
  expect(destroyed.final_report).toBe(report)

  // ── 11. audit independence helper confirms no overlap vs target if used ──
  if (opts.selfAudit) {
    // reconstruct: assertAuditIndependence throws on overlap; here we prove the
    // happy path for a CLEAN audit cloud formed from independent agents only
    const target = yield* claw.listClouds()
    const clean = target.find((c) => c.cloud_id !== cloud.cloud_id && c.cloud_type === "research")
    if (clean) {
      const freshAudit = yield* claw.createCloud({
        cloud_type: "audit",
        purpose: "clean audit",
        created_by: CONTROL,
        token_budget: 5000,
        audit_target: clean.cloud_id,
      })
      yield* claw.joinCloud(freshAudit.cloud_id, agents[2], "auditor")
      const loaded = yield* claw.getCloud(freshAudit.cloud_id)
      expect(() => assertAuditIndependence(loaded, clean)).not.toThrow()
    }
  }

  return { done, report, events: yield* claw.log() }
})
describe("integration: 4 independent agents form an Audit Cloud and dissolve", () => {
  it.instance(
    "full lifecycle with real session loops against scripted LLM",
    () =>
      Effect.gen(function* () {
        const { done, report, events } = yield* runAuditCloudIntegration({})
        expect(done.status).toBe("COMPLETED")
        expect(report).toContain("Unified Audit Report")
        expect(events.some((e) => e.type === "cloud.created")).toBe(true)
        expect(events.some((e) => e.type === "cloud.member.verdict_sealed")).toBe(true)
        expect(events.some((e) => e.type === "claw.message")).toBe(true)
        expect(events.some((e) => e.type === "cloud.completed")).toBe(true)
        expect(events.some((e) => e.type === "cloud.destroyed")).toBe(true)
      }),
    60_000,
  )

  it.instance(
    "yuheng and self-audit are refused during formation",
    () =>
      Effect.gen(function* () {
        const { done } = yield* runAuditCloudIntegration({ yuhengJoin: true, selfAudit: true })
        expect(done.status).toBe("COMPLETED")
      }),
    60_000,
  )

  it.instance(
    "cloud survives a member kill and still completes",
    () =>
      Effect.gen(function* () {
        const { done, events } = yield* runAuditCloudIntegration({ killIndex: 1 })
        expect(done.status).toBe("COMPLETED")
        expect(events.some((e) => e.type === "cloud.member.killed" || e.type === "cloud.member.evicted")).toBe(true)
      }),
    60_000,
  )
})
