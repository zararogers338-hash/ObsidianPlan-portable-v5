// `obsidian claw` — control-plane inspection and offline governance demo for the
// Claw/Cloud experimental multi-agent composition engine.
//
// Subcommands:
//   claw status                capacity zone + active cloud roster
//   claw log                   append-only governance event log
//   claw report <cloud-id>     final unified report for a cloud
//   claw demo                  run a REAL offline governed composition through the
//                              wired ClawManager (no network): creates a governed
//                              engineering cloud, exercises the spawn gate, the
//                              budget gate, the Yuheng refusal, member exclusivity
//                              and capacity zones against REAL Session/Agent
//                              service state, then prints the governance log.
import { Effect, Cause } from "effect"
import { effectCmd, fail, CliError } from "../effect-cmd"
import { Session } from "@/session/session"
import { SessionID } from "@/session/schema"
import { ClawManager } from "@/claw"
import { assertAuditIndependence } from "@/claw/audit"
import { AgentRef, E, YUHENG_AGENT_NAME } from "@/claw/types"

const DEMO_TYPE = "claw-demo"

const line = (text = "") => Effect.sync(() => process.stdout.write(text + "\n"))

const formatEvent = (event: { seq: number; type: string; cloud_id?: string | undefined; data: Record<string, unknown> }) =>
  `  #${String(event.seq).padStart(3, "0")} ${event.type.padEnd(28)} ${event.cloud_id ?? "-"} ${JSON.stringify(event.data)}`

const status = Effect.fn("Cli.claw.status")(function* () {
  const claw = yield* ClawManager.Service
  const cap = yield* claw.capacity()
  yield* line(`claw capacity: zone=${cap.zone} active=${cap.active} (busy=${cap.busy} background=${cap.background} leased=${cap.leased}) / MAX_ACTIVE_AGENTS=75`)
  const clouds = yield* claw.listClouds()
  if (clouds.length === 0) {
    yield* line("clouds: none in this process (governance state is per-process)")
    return
  }
  yield* line(`clouds (${clouds.length}):`)
  for (const cloud of clouds) {
    yield* line(
      `  ${cloud.cloud_id} ${cloud.status.padEnd(10)} type=${cloud.cloud_type} members=${cloud.members.length}/${cloud.member_limit} rounds=${cloud.rounds_used}/${cloud.max_rounds} tokens=${cloud.tokens_used}/${cloud.token_budget} purpose=${cloud.purpose}`,
    )
  }
})

const printLog = Effect.fn("Cli.claw.log")(function* () {
  const claw = yield* ClawManager.Service
  const events = yield* claw.log()
  if (events.length === 0) {
    yield* line("governance log is empty in this process")
    return
  }
  yield* line(`governance log (${events.length} events):`)
  for (const event of events) yield* line(formatEvent(event))
})

const printReport = Effect.fn("Cli.claw.report")(function* (cloudID: string) {
  const claw = yield* ClawManager.Service
  const cloud = yield* claw.getCloud(cloudID as ClawManager.ClawTypes.CloudID).pipe(
    Effect.mapError((e) => new CliError({ message: `[${e.code}] ${e.message}` }))
  )
  if (cloud.final_report) {
    yield* line(cloud.final_report)
    return
  }
  yield* line(`cloud ${cloudID} has no final report (status=${cloud.status}); sealed verdicts:`)
  const report = yield* claw.auditReport(cloud.cloud_id).pipe(Effect.orDie)
  yield* line(report)
})

/** Exercise a refusal and print the observed governance action. */
const expectRefusal = Effect.fn("Cli.claw.expectRefusal")(function* (
  label: string,
  effect: Effect.Effect<unknown, ClawManager.ClawTypes.ClawError>,
  code: string,
) {
  const exit = yield* Effect.exit(effect)
  if (exit._tag === "Success") {
    yield* line(`  ✗ ${label}: EXPECTED refusal ${code}, got SUCCESS — governance is NOT enforced`)
    return yield* fail(`governance check failed: ${label} was not refused`)
  }
  const squashed = Cause.squash(exit.cause) as { code?: string; message?: string } | undefined
  const actual = squashed?.code ?? "?"
  if (actual !== code) {
    return yield* fail(`governance check failed: ${label} refused with ${actual}, expected ${code}`)
  }
  yield* line(`  ✓ ${label}: refused [${actual}] ${squashed?.message ?? ""}`)
})

const demo = Effect.fn("Cli.claw.demo")(function* () {
  const claw = yield* ClawManager.Service
  const sessions = yield* Session.Service

  // Real session state: sample capacity from the actual session roster of this
  // project (busy = every non-archived session the instance knows about).
  const live = yield* sessions.list().pipe(Effect.orDie)
  const busy = new Set(live.map((info) => info.id).slice(0, 75))
  const sampled = yield* claw.noteBusy(busy, 0)
  yield* line(`[0] real capacity sample from Session service: zone=${sampled.zone} busy=${sampled.busy} (sessions=${live.length}, demo ids tagged "${DEMO_TYPE}")`)

  // ── governed spawn path (the same calls TaskTool now makes for every
  //    subagent spawn, exercised here against the wired runtime) ──────────────
  const control = { session: SessionID.make(`ses_${DEMO_TYPE}_control`), agentType: "build" }
  const cloud = yield* claw
    .createCloud({
      cloud_type: "engineering",
      purpose: "offline governance demo: governed subagent lifecycle",
      created_by: control,
      member_limit: 2,
      token_budget: 20_000,
      max_rounds: 2,
    })
    .pipe(Effect.mapError((e) => new CliError({ message: `createCloud refused: [${e.code}] ${e.message}` })))
  yield* line(`[1] createCloud -> ${cloud.cloud_id} status=${cloud.status} budget=${cloud.token_budget} limit=${cloud.member_limit}`)

  const worker: AgentRef = { id: SessionID.make(`ses_${DEMO_TYPE}_worker_1`), agentType: "micp-data-analyst" }
  const request = yield* claw.requestAgent({
    requested_by: control,
    agent_type: worker.agentType,
    purpose: "demo governed spawn",
    for_cloud: cloud.cloud_id,
  }).pipe(Effect.orDie)
  yield* line(`[2] spawn requested by agent -> ${request.request_id} (agents can only request; II)`)
  const decided = yield* claw.decideSpawn(request.request_id, {
    approved: true,
    reason: "demo: control plane approves",
    granted_session: worker.id,
  }).pipe(Effect.mapError((e) => new CliError({ message: `decideSpawn refused: [${e.code}] ${e.message}` })))
  yield* line(`[3] control plane decided spawn: approved=${decided.decision?.approved} granted=${decided.decision?.granted_session}`)

  yield* claw.joinCloud(cloud.cloud_id, worker, "demo-worker").pipe(Effect.mapError((e) => new CliError({ message: `joinCloud refused: [${e.code}] ${e.message}` })))
  const activated = yield* claw.activate(cloud.cloud_id).pipe(Effect.mapError((e) => new CliError({ message: `activate refused: [${e.code}] ${e.message}` })))
  const lease = yield* claw.issueLease(cloud.cloud_id, worker.id, { max_requests: 2, max_tokens: 10_000, ttl_ms: 60_000 }).pipe(Effect.mapError((e) => new CliError({ message: `issueLease refused: [${e.code}] ${e.message}` })))
  yield* line(`[4] join+activate+lease -> status=${activated.status} lease=${lease.lease_id} (req<=${lease.max_requests}, tok<=${lease.max_tokens})`)

  const spent = yield* claw.spend(cloud.cloud_id, lease.lease_id, { requests: 1, tokens: 1_200 }).pipe(Effect.mapError((e) => new CliError({ message: `spend refused: [${e.code}] ${e.message}` })))
  yield* line(`[5] spend approved -> used=${spent.used_requests}req/${spent.used_tokens}tok`)

  // ── hard refusals, each one recorded in the governance log ─────────────────
  yield* line(`[6] refusal matrix (each must fail closed):`)
  yield* expectRefusal(
    "budget gate (IX): spend beyond approved lease/token budget",
    claw.spend(cloud.cloud_id, lease.lease_id, { requests: 1, tokens: 99_999 }),
    E.LEASE_EXHAUSTED,
  )
  yield* expectRefusal(
    "yuheng gate (I/VI): obsidian-prompt-amplifier joins a cloud",
    claw.joinCloud(cloud.cloud_id, { id: SessionID.make(`ses_${DEMO_TYPE}_yuheng`), agentType: YUHENG_AGENT_NAME }, "intruder"),
    E.CONTROL_PLANE_ENTITY_CANNOT_JOIN_CLOUD,
  )
  yield* expectRefusal(
    "exclusivity (IV): member of active cloud joins a second cloud",
    Effect.gen(function* () {
      const other = yield* claw.createCloud({
        cloud_type: "research",
        purpose: "demo exclusivity target",
        created_by: control,
        token_budget: 1_000,
      })
      return yield* claw.joinCloud(other.cloud_id, worker, "double-agent")
    }),
    E.AGENT_ALREADY_IN_ACTIVE_CLOUD,
  )
  yield* expectRefusal(
    "spawn gate (II): an agent spawning directly",
    claw.spawnAgent(worker),
    E.SPAWN_NOT_PERMITTED,
  )

  // ── capacity zones against the real manager (75 = HARD_STOP red line) ──────
  // noteBusy counts busy ∪ leased; the live demo worker holds lease_000003, so
  // 74 synthetic sessions + that 1 leased member = exactly 75 active.
  const synthetic = Array.from({ length: 74 }, (_, i) => SessionID.make(`ses_${DEMO_TYPE}_cap_${i}`))
  const atHardStop = yield* claw.noteBusy(new Set(synthetic), 0)
  yield* expectRefusal(
    `capacity gate (VIII): spawn at HARD_STOP (${atHardStop.active} active agents, zone=${atHardStop.zone})`,
    claw.decideSpawn(
      (yield* claw.requestAgent({ requested_by: control, agent_type: "micp-data-analyst", purpose: "at hard stop" }).pipe(Effect.orDie)).request_id,
      { approved: true, reason: "demo", granted_session: SessionID.make(`ses_${DEMO_TYPE}_blocked`) },
    ),
    E.CAPACITY_HARD_STOP,
  )
  yield* claw.noteBusy(busy, 0)

  // ── audit independence (V) on a completed cloud ────────────────────────────
  const sealed = yield* claw.sealVerdict(cloud.cloud_id, worker.id, "demo: evidence consistent").pipe(Effect.orDie)
  const completed = yield* claw.complete(cloud.cloud_id, "demo final report: governed lifecycle OK").pipe(Effect.mapError((e) => new CliError({ message: `complete refused: [${e.code}] ${e.message}` })))
  yield* line(`[7] sealVerdict+complete -> status=${completed.status} sealed=${sealed.members.filter((m) => m.sealedVerdict).length} report preserved=${completed.final_report !== undefined} (X)`)

  const auditCloud = yield* claw.createCloud({
    cloud_type: "audit",
    purpose: "demo: audit the demo cloud",
    created_by: control,
    token_budget: 5_000,
    audit_target: cloud.cloud_id,
  }).pipe(Effect.orDie)
  yield* expectRefusal(
    "self-audit (V): executor of the target joins its audit cloud",
    claw.joinCloud(auditCloud.cloud_id, worker, "self-auditor"),
    E.SELF_AUDIT_FORBIDDEN,
  )
  const independent: AgentRef = { id: SessionID.make(`ses_${DEMO_TYPE}_auditor_1`), agentType: "obsidian-red-team" }
  yield* claw.joinCloud(auditCloud.cloud_id, independent, "auditor").pipe(Effect.orDie)
  assertAuditIndependence(yield* claw.getCloud(auditCloud.cloud_id).pipe(Effect.orDie), completed)
  yield* line(`[8] assertAuditIndependence(audit cloud, target) passed: no member overlap, no Yuheng`)

  yield* line(`[9] governance log:`)
  yield* printLog()
  yield* line(`demo: all governance actions above were enforced by the wired ClawManager (AppRuntime), fully offline.`)
})

export const ClawCommand = effectCmd({
  command: "claw [sub] [cloud]",
  describe: "claw/cloud governance: status, log, report, or an offline governance demo",
  builder: (yargs) =>
    yargs
      .positional("sub", {
        describe: "status | log | report | demo",
        type: "string",
        default: "status",
        choices: ["status", "log", "report", "demo"],
      })
      .positional("cloud", { describe: "cloud id (for report)", type: "string" }),
  handler: Effect.fn("Cli.claw")(function* (args) {
    const sub = args.sub ?? "status"
    if (sub === "demo") return yield* demo()
    if (sub === "log") return yield* printLog()
    if (sub === "report") {
      if (!args.cloud) return yield* fail("claw report requires a cloud id")
      return yield* printReport(args.cloud)
    }
    return yield* status()
  }),
})
