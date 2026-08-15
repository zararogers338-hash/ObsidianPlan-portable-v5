import { Effect, Schema } from "effect"
import * as Tool from "./tool"
import { ClawManager } from "@/claw"
import { SessionID } from "../session/schema"
import { AgentRef, CloudType, YUHENG_AGENT_NAME } from "@/claw/types"

/**
 * claw — the LLM-facing control-plane tool for Claw/Cloud governed multi-agent
 * composition.
 *
 * This is the tool that lets a plane actually RUN clouds: create clouds, drive
 * the request→approve→join spawn ritual, issue/spend leases, seal verdicts,
 * open claw data channels, review/complete/archive/destroy, and read the
 * governance log. Hard invariants (Yuheng ban, spawn gate, member exclusivity,
 * budget gate, capacity red line, self-audit ban) are enforced inside
 * ClawManager — never in this description.
 *
 * Authorization (invariant II / VI): control-plane ops (spawn decisions, lease
 * issue, member lifecycle) require the CONTROL_PLANE_OPS allowlist or Yuheng.
 * Data-plane ops (seal/send/report/log) are open to any agent. Yuheng can NEVER
 * be made a cloud member — that refusal lives in ClawManager.joinCloud.
 */

const CONTROL_PLANE_OPS: ReadonlySet<string> = new Set([
  "create",
  "decide_spawn",
  "issue_lease",
  "activate",
  "begin_review",
  "complete",
  "abort",
  "archive",
  "destroy",
])

const CONTROL_PLANE_ACTORS: ReadonlySet<string> = new Set([
  YUHENG_AGENT_NAME, // obsidian-prompt-amplifier
  "build",
  "general",
])

export const Parameters = Schema.Struct({
  op: Schema.Literals([
    "capacity",
    "note_busy",
    "create",
    "request_agent",
    "decide_spawn",
    "join",
    "issue_lease",
    "spend",
    "activate",
    "seal_verdict",
    "open_claw",
    "send",
    "begin_review",
    "complete",
    "abort",
    "archive",
    "destroy",
    "report",
    "log",
    "list",
  ]).annotate({ description: "governance operation to perform" }),

  // cloud / actor identity
  cloud_id: Schema.optional(Schema.String).annotate({ description: "target cloud id" }),
  cloud_type: Schema.optional(CloudType).annotate({ description: "type for op=create" }),
  purpose: Schema.optional(Schema.String).annotate({ description: "cloud purpose / spawn purpose / abort reason" }),
  audit_target: Schema.optional(Schema.String).annotate({ description: "op=create: cloud id this cloud audits" }),

  // spawn ritual
  agent_type: Schema.optional(Schema.String).annotate({ description: "agent type to request/join" }),
  request_id: Schema.optional(Schema.String).annotate({ description: "spawn request id for op=decide_spawn" }),
  approved: Schema.optional(Schema.Boolean).annotate({ description: "op=decide_spawn decision" }),
  reason: Schema.optional(Schema.String).annotate({ description: "decision/abort/freeze reason" }),
  granted_session: Schema.optional(Schema.String).annotate({ description: "op=decide_spawn approved session id" }),

  // membership
  role: Schema.optional(Schema.String).annotate({ description: "member role for op=join" }),
  member_session: Schema.optional(Schema.String).annotate({
    description: "session id of the member (defaults to this session for data-plane ops)",
  }),

  // governance limits
  member_limit: Schema.optional(Schema.Number),
  token_budget: Schema.optional(Schema.Number),
  max_rounds: Schema.optional(Schema.Number),
  max_lifetime_ms: Schema.optional(Schema.Number),

  // lease
  lease_id: Schema.optional(Schema.String),
  max_requests: Schema.optional(Schema.Number),
  max_tokens: Schema.optional(Schema.Number),
  ttl_ms: Schema.optional(Schema.Number),
  requests: Schema.optional(Schema.Number).annotate({ description: "op=spend usage" }),
  tokens: Schema.optional(Schema.Number).annotate({ description: "op=spend usage" }),

  // data channel
  claw_session_id: Schema.optional(Schema.String),
  to_session: Schema.optional(Schema.String).annotate({ description: "op=open_claw other party / op=send recipient" }),
  kind: Schema.optional(Schema.Literals(["report", "evidence_pack", "state_summary", "challenge", "verdict"])),
  payload: Schema.optional(Schema.String),
  verdict: Schema.optional(Schema.String).annotate({ description: "op=seal_verdict text" }),
  evidence_refs: Schema.optional(Schema.Array(Schema.String)),

  // capacity sampling
  busy_sessions: Schema.optional(Schema.Array(Schema.String)).annotate({ description: "op=note_busy session ids" }),
  background: Schema.optional(Schema.Number).annotate({ description: "op=note_busy background job count" }),

  limit: Schema.optional(Schema.Number).annotate({ description: "op=log max events (newest last)" }),
})

type Metadata = {
  op: string
  ok: boolean
  code?: string
}

const ok = (op: string, data: unknown): { title: string; output: string; metadata: Metadata } => ({
  title: `claw ${op}`,
  output: typeof data === "string" ? data : JSON.stringify(data, null, 2),
  metadata: { op, ok: true },
})

export const ClawTool = Tool.define<typeof Parameters, Metadata, never>(
  "claw",
  Effect.gen(function* () {
    const description = [
      "Run Claw/Cloud governed multi-agent composition against the real ClawManager.",
      "Use this to actually form and drive clouds, not to describe them.",
      "Ritual per member: request_agent -> decide_spawn(control plane) -> join -> issue_lease.",
      "Then activate, do work, seal_verdict, optionally open_claw + send between two members,",
      "begin_review, complete, archive, destroy. Control-plane ops require a control-plane actor.",
      "Refusals come back as { ok:false, code } — surface them verbatim, never retry around them.",
    ].join(" ")

    return {
      description,
      parameters: Parameters,
      execute: (params: Schema.Schema.Type<typeof Parameters>, ctx: Tool.Context<Metadata>) =>
        Effect.gen(function* () {
          // Authorization: control-plane ops need a control-plane actor (II/VI).
          if (CONTROL_PLANE_OPS.has(params.op) && !CONTROL_PLANE_ACTORS.has(ctx.agent)) {
            return {
              title: `claw ${params.op} refused`,
              output: JSON.stringify(
                {
                  ok: false,
                  code: "CONTROL_PLANE_REQUIRED",
                  message: `agent '${ctx.agent}' may not run control-plane op '${params.op}'. Only ${[...CONTROL_PLANE_ACTORS].join("/")} may.`,
                },
                null,
                2,
              ),
              metadata: { op: params.op, ok: false, code: "CONTROL_PLANE_REQUIRED" },
            }
          }

          // Resolve the manager from the runtime; refuse closed if unwired.
          const maybe = yield* Effect.serviceOption(ClawManager.Service)
          if (maybe._tag === "None") {
            return {
              title: `claw ${params.op} unavailable`,
              output: JSON.stringify(
                { ok: false, code: "CLAW_UNAVAILABLE", message: "ClawManager is not wired into this runtime." },
                null,
                2,
              ),
              metadata: { op: params.op, ok: false, code: "CLAW_UNAVAILABLE" },
            }
          }
          const claw = maybe.value

          const self = { session: ctx.sessionID, agentType: ctx.agent }
          const memberId = (params.member_session ? SessionID.make(params.member_session) : ctx.sessionID) as SessionID
          const cloudId = (params.cloud_id ?? "") as never
          const memberRef: AgentRef = { id: memberId, agentType: params.agent_type ?? ctx.agent }

          const run = (): Effect.Effect<unknown, ClawManager.ClawTypes.ClawError> => {
            switch (params.op) {
              case "capacity":
                return claw.capacity()
              case "note_busy":
                return claw.noteBusy(
                  new Set((params.busy_sessions ?? []).map((s) => SessionID.make(s))),
                  params.background ?? 0,
                )
              case "create":
                return claw.createCloud({
                  cloud_type: params.cloud_type ?? "engineering",
                  purpose: params.purpose ?? "cloud via claw tool",
                  created_by: self,
                  member_limit: params.member_limit,
                  token_budget: params.token_budget ?? 50_000,
                  max_rounds: params.max_rounds,
                  max_lifetime_ms: params.max_lifetime_ms,
                  audit_target: params.audit_target as never,
                })
              case "request_agent":
                return claw.requestAgent({
                  requested_by: self,
                  agent_type: params.agent_type ?? ctx.agent,
                  purpose: params.purpose ?? "agent requested via claw tool",
                  for_cloud: params.cloud_id ? cloudId : undefined,
                })
              case "decide_spawn":
                return claw.decideSpawn((params.request_id ?? "") as never, {
                  approved: params.approved ?? false,
                  reason: params.reason ?? "decided via claw tool",
                  granted_session: params.granted_session ? SessionID.make(params.granted_session) : undefined,
                })
              case "join":
                return claw.joinCloud(cloudId, memberRef, params.role ?? "member")
              case "issue_lease":
                return claw.issueLease(cloudId, memberId, {
                  max_requests: params.max_requests ?? 30,
                  max_tokens: params.max_tokens ?? 10_000,
                  ttl_ms: params.ttl_ms ?? 900_000,
                })
              case "spend":
                return claw.spend(cloudId, (params.lease_id ?? "") as never, {
                  requests: params.requests ?? 1,
                  tokens: params.tokens ?? 0,
                })
              case "activate":
                return claw.activate(cloudId)
              case "seal_verdict":
                return claw.sealVerdict(cloudId, memberId, params.verdict ?? params.payload ?? "")
              case "open_claw":
                return claw.openClaw(cloudId, memberId, SessionID.make(params.to_session ?? ""))
              case "send":
                return claw.send((params.claw_session_id ?? "") as never, {
                  from: memberId,
                  to: SessionID.make(params.to_session ?? ""),
                  kind: params.kind ?? "report",
                  payload: params.payload ?? "",
                  evidence_refs: params.evidence_refs,
                })
              case "begin_review":
                return claw.beginReview(cloudId)
              case "complete":
                return claw.complete(cloudId, params.payload ?? params.purpose ?? "")
              case "abort":
                return claw.abort(cloudId, params.reason ?? params.purpose ?? "aborted via claw tool")
              case "archive":
                return claw.archive(cloudId)
              case "destroy":
                return claw.destroy(cloudId)
              case "report":
                return claw.auditReport(cloudId)
              case "list":
                return claw.listClouds()
              case "log":
                return Effect.map(claw.log(), (events) => events.slice(-(params.limit ?? events.length)))
              default:
                return Effect.fail(
                  new ClawManager.ClawTypes.ClawError({ code: "UNKNOWN_OP", message: `unknown claw op: ${params.op}` }),
                )
            }
          }

          const result = yield* run().pipe(
            Effect.match({
              onFailure: (e) => ({
                title: `claw ${params.op} refused`,
                output: JSON.stringify(
                  { ok: false, code: (e as { code?: string }).code ?? "CLAW_ERROR", message: (e as { message?: string }).message ?? String(e) },
                  null,
                  2,
                ),
                metadata: { op: params.op, ok: false, code: (e as { code?: string }).code ?? "CLAW_ERROR" },
              }),
              onSuccess: (value) => ok(params.op, value),
            }),
          )

          return result
        }),
    } satisfies Tool.DefWithoutID<typeof Parameters, Metadata>
  }),
)
