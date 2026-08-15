import { describe, expect, test } from "bun:test"
import { Cause, Effect, Exit, Layer } from "effect"
import { SessionID } from "../../src/session/schema"
import { layer as ClawManagerLayer, Service as ClawManager } from "../../src/claw/manager"
import {
  AgentRef,
  ClawError,
  CloudID,
  CLOUD_MEMBER_LIMIT_DEFAULT,
  E,
  LeaseID,
  MAX_ACTIVE_AGENTS,
  YUHENG_AGENT_NAME,
  capacityZone,
} from "../../src/claw/types"

const live = Layer.fresh(ClawManagerLayer)

function run<A>(effect: Effect.Effect<A, ClawError, ClawManager>): Promise<A> {
  return Effect.runPromise(Effect.provide(effect, live))
}

function runExit<A>(effect: Effect.Effect<A, ClawError, ClawManager>): Promise<Exit.Exit<A, ClawError>> {
  return Effect.runPromise(Effect.provide(effect, Layer.fresh(live)).pipe(Effect.exit))
}

const ref = (n: number | string, agentType = "micp-data-analyst"): AgentRef => ({
  id: SessionID.make(`ses_test_${n}`),
  agentType,
})

const yuheng: AgentRef = { id: SessionID.make("ses_yuheng_0"), agentType: YUHENG_AGENT_NAME }

const CONTROL = { session: SessionID.make("ses_control_plane"), agentType: "build" }

const expectCode = async <A>(
  effect: Effect.Effect<A, ClawError, ClawManager>,
  code: string,
): Promise<ClawError> => {
  const exit = await runExit(effect)
  expect(Exit.isFailure(exit)).toBe(true)
  if (!Exit.isFailure(exit)) throw new Error(`expected failure ${code}, got success`)
  const err = Cause.squash(exit.cause)
  expect(err).toBeInstanceOf(ClawError)
  expect((err as ClawError).code).toBe(code)
  return err as ClawError
}

const buildAuditCloud = (members: readonly AgentRef[]) =>
  Effect.gen(function* () {
    const svc = yield* ClawManager
    const cloud = yield* svc.createCloud({
      cloud_type: "audit",
      purpose: "TEST: audit MICP evidence cards",
      created_by: CONTROL,
      token_budget: 100_000,
    })
    for (const [i, m] of members.entries()) {
      yield* svc.joinCloud(cloud.cloud_id, m, `auditor-${i + 1}`)
    }
    return yield* svc.getCloud(cloud.cloud_id)
  })

describe("claw capacity zones", () => {
  test("zone boundaries match the 75-agent governance red line", () => {
    expect(capacityZone(0)).toBe("NORMAL")
    expect(capacityZone(60)).toBe("NORMAL")
    expect(capacityZone(61)).toBe("RESTRICTED")
    expect(capacityZone(68)).toBe("RESTRICTED")
    expect(capacityZone(69)).toBe("LOCKDOWN")
    expect(capacityZone(74)).toBe("LOCKDOWN")
    expect(capacityZone(75)).toBe("HARD_STOP")
    expect(capacityZone(76)).toBe("EMERGENCY_RECOVERY")
    expect(MAX_ACTIVE_AGENTS).toBe(75)
    expect(CLOUD_MEMBER_LIMIT_DEFAULT).toBe(4)
  })
})

describe("TEST 1 — basic cloud lifecycle (create/collaborate/dissolve)", () => {
  test("4 agents form an audit cloud, exchange sealed verdicts, dissolve cleanly", async () => {
    const result = await run(
      Effect.gen(function* () {
        const svc = yield* ClawManager
        const members = [ref(1), ref(2), ref(3), ref(4)]
        let cloud = yield* buildAuditCloud(members)
        expect(cloud.members.length).toBe(4)
        expect(cloud.status).toBe("FORMING")

        cloud = yield* svc.activate(cloud.cloud_id)
        expect(cloud.status).toBe("ACTIVE")

        // leases: budget is issued, never created by members
        const leases = []
        for (const m of members) {
          leases.push(yield* svc.issueLease(cloud.cloud_id, m.id, { max_requests: 4, max_tokens: 20_000, ttl_ms: 60_000 }))
        }
        for (const lease of leases) {
          yield* svc.spend(cloud.cloud_id, lease.lease_id, { requests: 1, tokens: 1000 })
        }

        // round 1: independent verdicts, sealed before any exchange
        for (const [i, m] of members.entries()) {
          yield* svc.sealVerdict(cloud.cloud_id, m.id, `verdict-${i + 1}: finding with evidence ref ev://${i + 1}`)
        }

        // round 2: pairwise claw exchange (data channel only)
        const clawAB = yield* svc.openClaw(cloud.cloud_id, members[0].id, members[1].id)
        const msg = yield* svc.send(clawAB.claw_session_id, {
          from: members[0].id,
          to: members[1].id,
          kind: "report",
          payload: "sealed report A->B",
          evidence_refs: ["ev://1"],
        })
        expect(msg.signature).toMatch(/^[0-9a-f]{64}$/)
        yield* svc.send(clawAB.claw_session_id, {
          from: members[1].id,
          to: members[0].id,
          kind: "challenge",
          payload: "conflict check B->A",
        })

        cloud = yield* svc.beginReview(cloud.cloud_id)
        expect(cloud.status).toBe("REVIEWING")

        const report = yield* svc.auditReport(cloud.cloud_id)
        expect(report).toContain("verdict-1")
        expect(report).toContain("verdict-4")

        const done = yield* svc.complete(cloud.cloud_id, report)
        expect(done.status).toBe("COMPLETED")

        // PASS conditions: all released, cloud closed, logs exist, result exists
        expect(done.members.every((m) => m.releasedAt !== undefined)).toBe(true)
        expect(done.members.every((m) => m.status === "RELEASED")).toBe(true)
        expect((yield* svc.activeLeases(cloud.cloud_id)).length).toBe(0)
        expect(done.final_report).toBe(report)
        const events = yield* svc.log()
        expect(events.some((e) => e.type === "cloud.completed")).toBe(true)
        expect(events.some((e) => e.type === "cloud.member.verdict_sealed")).toBe(true)
        expect(events.some((e) => e.type === "lease.revoked" || e.type === "cloud.completed")).toBe(true)

        const archived = yield* svc.archive(cloud.cloud_id)
        expect(archived.status).toBe("ARCHIVED")
        const destroyed = yield* svc.destroy(cloud.cloud_id)
        expect(destroyed.status).toBe("DESTROYED")
        // artifacts survive destruction
        expect(destroyed.final_report).toBe(report)
        const after = yield* svc.getCloud(cloud.cloud_id)
        expect(after.final_report).toBe(report)
        return done
      }),
    )
    expect(result.status).toBe("COMPLETED")
  })
})

describe("TEST 2 — cloud membership mutual exclusion", () => {
  test("agent in active cloud A cannot join cloud B", async () => {
    await run(
      Effect.gen(function* () {
        const svc = yield* ClawManager
        const a = yield* buildAuditCloud([ref(1), ref(2)])
        yield* svc.activate(a.cloud_id)
        const b = yield* svc.createCloud({ cloud_type: "research", purpose: "TEST: B", created_by: CONTROL, token_budget: 10_000 })
        const exit = yield* svc.joinCloud(b.cloud_id, ref(1), "infiltrator").pipe(Effect.exit)
        expect(Exit.isFailure(exit)).toBe(true)
        if (Exit.isFailure(exit)) {
          expect((Cause.squash(exit.cause) as ClawError).code).toBe(E.AGENT_ALREADY_IN_ACTIVE_CLOUD)
        }
      }),
    )
  })

  test("agent may join a new cloud only after release + cleanup completed", async () => {
    await run(
      Effect.gen(function* () {
        const svc = yield* ClawManager
        const a = yield* buildAuditCloud([ref(1)])
        yield* svc.activate(a.cloud_id)
        yield* svc.complete(a.cloud_id, "done")
        const b = yield* svc.createCloud({ cloud_type: "research", purpose: "TEST: B2", created_by: CONTROL, token_budget: 10_000 })
        const joined = yield* svc.joinCloud(b.cloud_id, ref(1), "researcher")
        expect(joined.members.length).toBe(1)
      }),
    )
  })
})

describe("TEST 3 — agents can never spawn agents", () => {
  test("spawn_agent() is unconditionally refused", async () => {
    const err = await expectCode(
      Effect.flatMap(ClawManager, (svc) => svc.spawnAgent(ref(99))),
      E.SPAWN_NOT_PERMITTED,
    )
    expect(err.message).toContain("requestAgent")
  })
})

describe("TEST 4 — request_agent enters the central scheduling flow", () => {
  test("request is recorded and decided by the control plane only", async () => {
    await run(
      Effect.gen(function* () {
        const svc = yield* ClawManager
        const req = yield* svc.requestAgent({
          requested_by: { session: ref(1).id, agentType: "micp-data-analyst" },
          agent_type: "micp-instrumentation-qc",
          purpose: "need a statistics audit agent",
        })
        expect(req.decision).toBeUndefined()
        const events = yield* svc.log()
        expect(events.some((e) => e.type === "spawn.requested")).toBe(true)

        const denied = yield* svc.decideSpawn(req.request_id, { approved: false, reason: "capacity" })
        expect(denied.decision?.approved).toBe(false)

        const req2 = yield* svc.requestAgent({
          requested_by: { session: ref(1).id, agentType: "micp-data-analyst" },
          agent_type: "micp-instrumentation-qc",
          purpose: "retry with justification",
        })
        const granted = yield* svc.decideSpawn(req2.request_id, {
          approved: true,
          reason: "within budget",
          granted_session: SessionID.make("ses_granted_1"),
        })
        expect(granted.decision?.approved).toBe(true)
        // double decision is refused
        const again = yield* svc
          .decideSpawn(req2.request_id, { approved: true, reason: "dup", granted_session: SessionID.make("ses_x") })
          .pipe(Effect.exit)
        expect(Exit.isFailure(again)).toBe(true)
      }),
    )
  })
})

describe("TEST 5 — cloud member hard limit", () => {
  test("5th member is refused at the default limit of 4", async () => {
    await run(
      Effect.gen(function* () {
        const svc = yield* ClawManager
        const cloud = yield* buildAuditCloud([ref(1), ref(2), ref(3), ref(4)])
        const exit = yield* svc.joinCloud(cloud.cloud_id, ref(5), "overflow").pipe(Effect.exit)
        expect(Exit.isFailure(exit)).toBe(true)
        if (Exit.isFailure(exit)) {
          expect((Cause.squash(exit.cause) as ClawError).code).toBe(E.CLOUD_MEMBER_LIMIT_REACHED)
        }
      }),
    )
  })

  test("member_limit above the configurable max 6 is refused at creation", async () => {
    await expectCode(
      Effect.flatMap(ClawManager, (svc) =>
        svc.createCloud({ cloud_type: "audit", purpose: "TEST: huge", created_by: CONTROL, token_budget: 1000, member_limit: 7 }),
      ),
      E.INVALID_STATE_TRANSITION,
    )
  })
})

describe("TEST 6 — Yuheng can never join a cloud", () => {
  test("joinCloud with the Yuheng agent type is refused", async () => {
    await run(
      Effect.gen(function* () {
        const svc = yield* ClawManager
        const cloud = yield* svc.createCloud({ cloud_type: "audit", purpose: "TEST: yuheng", created_by: CONTROL, token_budget: 10_000 })
        const exit = yield* svc.joinCloud(cloud.cloud_id, yuheng, "controller").pipe(Effect.exit)
        expect(Exit.isFailure(exit)).toBe(true)
        if (Exit.isFailure(exit)) {
          expect((Cause.squash(exit.cause) as ClawError).code).toBe(E.CONTROL_PLANE_ENTITY_CANNOT_JOIN_CLOUD)
        }
      }),
    )
  })
})

describe("TEST 7 — Yuheng can never be bound to a claw session", () => {
  test("openClaw refuses any party registered under the Yuheng agent type", async () => {
    await run(
      Effect.gen(function* () {
        const svc = yield* ClawManager
        // Yuheng is refused at join time, so an active cloud can never contain
        // it; the claw gate is the second, independent line of defense.
        const cloud = yield* buildAuditCloud([ref(1), ref(2)])
        const forged = yield* svc.openClaw(cloud.cloud_id, ref(1).id, yuheng.id).pipe(Effect.exit)
        expect(Exit.isFailure(forged)).toBe(true)
        if (Exit.isFailure(forged)) {
          const code = (Cause.squash(forged.cause) as ClawError).code
          expect(code === E.MEMBER_NOT_FOUND || code === E.CONTROL_PLANE_ENTITY_CANNOT_BIND_CLAW).toBe(true)
        }
      }),
    )
  })
})

describe("TEST 8 — the 75-agent global red line", () => {
  test("at 75 active agents any new cloud/member/agent is refused", async () => {
    await run(
      Effect.gen(function* () {
        const svc = yield* ClawManager
        const busy = new Set(Array.from({ length: MAX_ACTIVE_AGENTS }, (_, i) => SessionID.make(`ses_busy_${i}`)))
        const cap = yield* svc.noteBusy(busy, 0)
        expect(cap.zone).toBe("HARD_STOP")
        expect(cap.active).toBe(75)

        yield* expectCodeInEffect(
          svc.createCloud({ cloud_type: "audit", purpose: "TEST: over capacity", created_by: CONTROL, token_budget: 1000 }),
          E.CAPACITY_HARD_STOP,
        )
      }),
    )
  })

  test("lockdown (69-74) blocks new clouds and members but allows plain agent approval", async () => {
    await run(
      Effect.gen(function* () {
        const svc = yield* ClawManager
        const busy = new Set(Array.from({ length: 70 }, (_, i) => SessionID.make(`ses_busy_${i}`)))
        const cap = yield* svc.noteBusy(busy, 0)
        expect(cap.zone).toBe("LOCKDOWN")
        yield* expectCodeInEffect(
          svc.createCloud({ cloud_type: "research", purpose: "TEST: lockdown", created_by: CONTROL, token_budget: 1000 }),
          E.CAPACITY_LOCKDOWN,
        )
        const req = yield* svc.requestAgent({
          requested_by: { session: ref(1).id, agentType: "micp-data-analyst" },
          agent_type: "micp-evidence-extractor",
          purpose: "essential only",
        })
        const granted = yield* svc.decideSpawn(req.request_id, {
          approved: true,
          reason: "essential",
          granted_session: SessionID.make("ses_essential_1"),
        })
        expect(granted.decision?.approved).toBe(true)
      }),
    )
  })

  test("beyond 75 triggers EMERGENCY_RECOVERY and forced teardown", async () => {
    await run(
      Effect.gen(function* () {
        const svc = yield* ClawManager
        const cloud = yield* buildAuditCloud([ref(1), ref(2)])
        yield* svc.activate(cloud.cloud_id)
        const busy = new Set(Array.from({ length: 76 }, (_, i) => SessionID.make(`ses_over_${i}`)))
        yield* svc.noteBusy(busy, 0)
        const exit = yield* svc
          .createCloud({ cloud_type: "audit", purpose: "TEST: emergency", created_by: CONTROL, token_budget: 1000 })
          .pipe(Effect.exit)
        expect(Exit.isFailure(exit)).toBe(true)
        if (Exit.isFailure(exit)) {
          expect((Cause.squash(exit.cause) as ClawError).code).toBe(E.CAPACITY_EMERGENCY)
        }
        const after = yield* svc.emergencyRecover()
        expect(after.zone).toBe("EMERGENCY_RECOVERY")
        const torn = yield* svc.getCloud(cloud.cloud_id)
        expect(torn.status).toBe("ABORTED")
      }),
    )
  })
})

const expectCodeInEffect = <A>(effect: Effect.Effect<A, ClawError, ClawManager>, code: string) =>
  Effect.gen(function* () {
    const exit = yield* effect.pipe(Effect.exit)
    expect(Exit.isFailure(exit)).toBe(true)
    if (Exit.isFailure(exit)) {
      expect((Cause.squash(exit.cause) as ClawError).code).toBe(code)
    }
  })

describe("TEST 9 — self-audit prohibition", () => {
  test("a member of cloud A cannot join an audit cloud targeting A", async () => {
    await run(
      Effect.gen(function* () {
        const svc = yield* ClawManager
        const target = yield* svc.createCloud({
          cloud_type: "research",
          purpose: "TEST: target cloud",
          created_by: CONTROL,
          token_budget: 10_000,
        })
        yield* svc.joinCloud(target.cloud_id, ref(1), "researcher")
        const completed = yield* svc.activate(target.cloud_id)
        yield* svc.complete(completed.cloud_id, "research output")
        // target is now COMPLETED: its membership record persists for COI checks
        const audit = yield* svc.createCloud({
          cloud_type: "audit",
          purpose: "TEST: audit the research cloud",
          created_by: CONTROL,
          token_budget: 10_000,
          audit_target: target.cloud_id,
        })
        const exit = yield* svc.joinCloud(audit.cloud_id, ref(1), "auditor").pipe(Effect.exit)
        expect(Exit.isFailure(exit)).toBe(true)
        if (Exit.isFailure(exit)) {
          expect((Cause.squash(exit.cause) as ClawError).code).toBe(E.SELF_AUDIT_FORBIDDEN)
        }
        // an independent agent CAN join the audit cloud
        yield* svc.joinCloud(audit.cloud_id, ref(2), "auditor")
        const joined = yield* svc.getCloud(audit.cloud_id)
        expect(joined.members.length).toBe(1)
      }),
    )
  })
})

describe("TEST 10 — teardown leaves no residue but keeps artifacts", () => {
  test("after dissolve: no members/leases/claws active; report/evidence/log remain", async () => {
    await run(
      Effect.gen(function* () {
        const svc = yield* ClawManager
        const members = [ref(1), ref(2), ref(3), ref(4)]
        const cloud = yield* buildAuditCloud(members)
        yield* svc.activate(cloud.cloud_id)
        const lease = yield* svc.issueLease(cloud.cloud_id, members[0].id, { max_requests: 2, max_tokens: 5000, ttl_ms: 60_000 })
        yield* svc.spend(cloud.cloud_id, lease.lease_id, { requests: 1, tokens: 500 })
        yield* svc.sealVerdict(cloud.cloud_id, members[0].id, "critical finding, evidence ev://x")
        const claw = yield* svc.openClaw(cloud.cloud_id, members[0].id, members[1].id)
        yield* svc.send(claw.claw_session_id, { from: members[0].id, to: members[1].id, kind: "evidence_pack", payload: "evidence bundle" })

        const done = yield* svc.complete(cloud.cloud_id, "final report body")
        expect(done.members.every((m) => m.releasedAt !== undefined)).toBe(true)
        expect((yield* svc.activeLeases(cloud.cloud_id)).length).toBe(0)

        // claw sessions are closed: further sends refuse
        const sendExit = yield* svc
          .send(claw.claw_session_id, { from: members[0].id, to: members[1].id, kind: "report", payload: "late" })
          .pipe(Effect.exit)
        expect(Exit.isFailure(sendExit)).toBe(true)

        // artifacts preserved
        const after = yield* svc.getCloud(cloud.cloud_id)
        expect(after.final_report).toBe("final report body")
        expect(after.members[0].sealedVerdict).toContain("critical finding")
        const events = yield* svc.log()
        expect(events.filter((e) => e.cloud_id === cloud.cloud_id).length).toBeGreaterThan(5)
        const closed = yield* svc.getClaw(claw.claw_session_id)
        expect(closed.closed_at).toBeDefined()
        expect(closed.messages.length).toBe(1)
      }),
    )
  })
})

describe("TEST 11 — killing a member triggers FREEZE→SNAPSHOT→DISTILL→EVICT", () => {
  test("member kill revokes leases, releases slot, cloud policy decides continuation", async () => {
    await run(
      Effect.gen(function* () {
        const svc = yield* ClawManager
        const members = [ref(1), ref(2), ref(3), ref(4)]
        const cloud = yield* buildAuditCloud(members)
        yield* svc.activate(cloud.cloud_id)
        const lease = yield* svc.issueLease(cloud.cloud_id, members[1].id, { max_requests: 4, max_tokens: 5000, ttl_ms: 60_000 })

        // staged teardown of member 2 (controlled kill)
        yield* svc.freezeMember(cloud.cloud_id, members[1].id, "control-plane kill order")
        yield* svc.snapshotMember(cloud.cloud_id, members[1].id)
        yield* svc.distillMember(cloud.cloud_id, members[1].id, "distilled: partial findings of member 2")
        const after = yield* svc.evictMember(cloud.cloud_id, members[1].id)
        const killed = after.members.find((m) => m.ref.id === members[1].id)
        expect(killed?.status).toBe("RELEASED")
        expect(killed?.releasedAt).toBeDefined()

        // lease revoked: no residual live calls
        const spendExit = yield* svc.spend(cloud.cloud_id, lease.lease_id, { requests: 1, tokens: 10 }).pipe(Effect.exit)
        expect(Exit.isFailure(spendExit)).toBe(true)

        // cloud policy: continue with 3 members, then complete
        const done = yield* svc.complete(cloud.cloud_id, "completed with 3/4 members")
        expect(done.status).toBe("COMPLETED")

        // released member may be reassigned to a NEW cloud (no leak, cleanup done)
        const b = yield* svc.createCloud({ cloud_type: "evidence", purpose: "TEST: reassign", created_by: CONTROL, token_budget: 5000 })
        const rejoined = yield* svc.joinCloud(b.cloud_id, members[1], "evidence-clerk")
        expect(rejoined.members.length).toBe(1)
      }),
    )
  })

  test("abrupt kill (no staged teardown) still revokes leases and keeps artifacts", async () => {
    await run(
      Effect.gen(function* () {
        const svc = yield* ClawManager
        const members = [ref(1), ref(2)]
        const cloud = yield* buildAuditCloud(members)
        yield* svc.activate(cloud.cloud_id)
        const lease = yield* svc.issueLease(cloud.cloud_id, members[0].id, { max_requests: 4, max_tokens: 5000, ttl_ms: 60_000 })
        yield* svc.sealVerdict(cloud.cloud_id, members[0].id, "verdict preserved after abrupt kill")

        const after = yield* svc.killMember(cloud.cloud_id, members[0].id, "fiber died")
        const killed = after.members.find((m) => m.ref.id === members[0].id)
        expect(killed?.status).toBe("KILLED")
        expect(killed?.sealedVerdict).toContain("preserved")
        expect((yield* svc.activeLeases(cloud.cloud_id)).length).toBe(0)

        // cloud can still abort or complete; artifacts intact
        const aborted = yield* svc.abort(cloud.cloud_id, "lost half the members")
        expect(aborted.status).toBe("ABORTED")
        const events = yield* svc.log()
        expect(events.some((e) => e.type === "cloud.member.killed")).toBe(true)
      }),
    )
  })

  test("out-of-order teardown stages are refused (no silent skipping)", async () => {
    await run(
      Effect.gen(function* () {
        const svc = yield* ClawManager
        const cloud = yield* buildAuditCloud([ref(1)])
        yield* svc.activate(cloud.cloud_id)
        // cannot distill before snapshot
        const exit = yield* svc.distillMember(cloud.cloud_id, ref(1).id, "early").pipe(Effect.exit)
        expect(Exit.isFailure(exit)).toBe(true)
        if (Exit.isFailure(exit)) {
          expect((Cause.squash(exit.cause) as ClawError).code).toBe(E.INVALID_STATE_TRANSITION)
        }
        // cannot evict an ACTIVE member without freeze first
        const exit2 = yield* svc.evictMember(cloud.cloud_id, ref(1).id).pipe(Effect.exit)
        expect(Exit.isFailure(exit2)).toBe(true)
      }),
    )
  })
})

describe("budget hard gate (invariant IX)", () => {
  test("no approved budget, no spend; lease and cloud budgets both enforced", async () => {
    await run(
      Effect.gen(function* () {
        const svc = yield* ClawManager
        const cloud = yield* buildAuditCloud([ref(1)])
        yield* svc.activate(cloud.cloud_id)
        const lease = yield* svc.issueLease(cloud.cloud_id, ref(1).id, { max_requests: 1, max_tokens: 100, ttl_ms: 60_000 })
        yield* svc.spend(cloud.cloud_id, lease.lease_id, { requests: 1, tokens: 100 })
        // second request exceeds max_requests
        const exit = yield* svc.spend(cloud.cloud_id, lease.lease_id, { requests: 1, tokens: 1 }).pipe(Effect.exit)
        expect(Exit.isFailure(exit)).toBe(true)
        if (Exit.isFailure(exit)) {
          expect((Cause.squash(exit.cause) as ClawError).code).toBe(E.LEASE_EXHAUSTED)
        }
      }),
    )
  })

  test("sealed verdicts are immutable (audit independence of round 1)", async () => {
    await run(
      Effect.gen(function* () {
        const svc = yield* ClawManager
        const cloud = yield* buildAuditCloud([ref(1)])
        yield* svc.sealVerdict(cloud.cloud_id, ref(1).id, "first independent verdict")
        const exit = yield* svc.sealVerdict(cloud.cloud_id, ref(1).id, "rewritten after seeing others").pipe(Effect.exit)
        expect(Exit.isFailure(exit)).toBe(true)
        if (Exit.isFailure(exit)) {
          expect((Cause.squash(exit.cause) as ClawError).code).toBe(E.VERDICT_ALREADY_SEALED)
        }
      }),
    )
  })
})
