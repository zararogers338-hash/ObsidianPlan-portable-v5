import { Schema } from "effect"
import { SessionID } from "@/session/schema"

/**
 * Claw / Cloud — experimental governed multi-agent composition for the
 * Obsidian Plan (黑曜石计划).
 *
 * Claw is the controlled connection protocol between agents: membership,
 * message exchange, permission boundaries, shared evidence references,
 * lifecycle, budget boundaries and communication records.
 *
 * Cloud is a bounded composite execution unit: a small set of independent
 * agents temporarily organized through Claw for one task.
 *
 * Hard invariants enforced in this module (not in prompts):
 *
 *   I.   Yuheng (玉衡, obsidian-prompt-amplifier) is a control-plane entity
 *        and can NEVER join a Cloud or a Claw session.
 *   II.  Agents may request agents; only the central control plane spawns.
 *   III. Clouds are finite: member limit, round limit, lifetime, budget.
 *   IV.  Two simultaneously active Clouds never share an agent.
 *   V.   No body may finally audit itself.
 *   VI.  Control plane never becomes a member of the execution plane.
 *   VII. Any exponentially-expanding capability lives under sandbox + caps.
 *   VIII. Active agents never exceed MAX_ACTIVE_AGENTS (75).
 *   IX.  No approved budget, no remote API call.
 *   X.   Terminating an agent never destroys valid artifacts.
 *   XI.  Clouds may be complex; complexity gets no right to self-replicate.
 */

// ─── Identity ────────────────────────────────────────────────────────────────

/** The Yuheng node: control plane. Hardcoded refusal target (invariant I/VI). */
export const YUHENG_AGENT_NAME = "obsidian-prompt-amplifier"

export const CloudID = Schema.String.pipe(Schema.brand("Claw/CloudID"))
export type CloudID = typeof CloudID.Type

export const ClawSessionID = Schema.String.pipe(Schema.brand("Claw/ClawSessionID"))
export type ClawSessionID = typeof ClawSessionID.Type

export const LeaseID = Schema.String.pipe(Schema.brand("Claw/LeaseID"))
export type LeaseID = typeof LeaseID.Type

export const RequestID = Schema.String.pipe(Schema.brand("Claw/RequestID"))
export type RequestID = typeof RequestID.Type

/** A runtime agent entity is identified by the session that embodies it. */
export const AgentRef = Schema.Struct({
  /** Unique runtime instance id (session id). Two refs may share agentType
   *  (e.g. Opus-Agent-017 / Opus-Agent-042) but are distinct instances. */
  id: SessionID,
  /** Static agent definition name from the opencode registry. */
  agentType: Schema.String,
  /** Plane is derived, never supplied: Yuheng is always control plane. */
})
export type AgentRef = typeof AgentRef.Type

export const isYuheng = (ref: Pick<AgentRef, "agentType">) => ref.agentType === YUHENG_AGENT_NAME

// ─── Governance constants (hard caps, not targets) ───────────────────────────

/**
 * Obsidian field governance red line. 75 is NOT a target and NOT a
 * recommended concurrency: it is the absolute ceiling derived from observed
 * loss of reliable control beyond it.
 */
export const MAX_ACTIVE_AGENTS = 75
export const CAPACITY_NORMAL_MAX = 60
export const CAPACITY_RESTRICTED_MAX = 68
export const CAPACITY_LOCKDOWN_MAX = 74

/** First-version Cloud member ceiling. May be widened to 4..6 later; never unbounded. */
export const CLOUD_MEMBER_LIMIT_DEFAULT = 4
export const CLOUD_MEMBER_LIMIT_MAX = 6

export const CLOUD_MAX_ROUNDS_DEFAULT = 8
export const CLOUD_MAX_LIFETIME_MS_DEFAULT = 30 * 60 * 1000

export const CapacityZone = Schema.Literals(["NORMAL", "RESTRICTED", "LOCKDOWN", "HARD_STOP", "EMERGENCY_RECOVERY"])
export type CapacityZone = typeof CapacityZone.Type

export const capacityZone = (active: number): CapacityZone => {
  if (active > MAX_ACTIVE_AGENTS) return "EMERGENCY_RECOVERY"
  if (active === MAX_ACTIVE_AGENTS) return "HARD_STOP"
  if (active >= CAPACITY_RESTRICTED_MAX + 1) return "LOCKDOWN" // 69..74
  if (active > CAPACITY_NORMAL_MAX) return "RESTRICTED" // 61..68
  return "NORMAL"
}

// ─── Cloud ───────────────────────────────────────────────────────────────────

export const CloudType = Schema.Literals([
  "audit",
  "engineering",
  "research",
  "evidence",
  "release",
  "red_team",
])
export type CloudType = typeof CloudType.Type

export const CloudStatus = Schema.Literals([
  "CREATE",
  "FORMING",
  "ACTIVE",
  "REVIEWING",
  "COMPLETED",
  "FAILED",
  "ABORTED",
  "ARCHIVED",
  "DESTROYED",
])
export type CloudStatus = typeof CloudStatus.Type

/** Statuses in which a Cloud holds its members exclusively (invariant IV). */
export const CLOUD_ACTIVE_STATUSES: ReadonlySet<CloudStatus> = new Set(["FORMING", "ACTIVE", "REVIEWING"])

export const MemberStatus = Schema.Literals([
  "JOINING",
  "ACTIVE",
  "FROZEN",
  "SNAPSHOTTING",
  "DISTILLING",
  "EVICTING",
  "RELEASED",
  "KILLED",
])
export type MemberStatus = typeof MemberStatus.Type

export const CloudMember = Schema.Struct({
  ref: AgentRef,
  role: Schema.String,
  status: MemberStatus,
  joinedAt: Schema.Number,
  /** Set when this member has finished permission cleanup and may re-join elsewhere. */
  releasedAt: Schema.optional(Schema.Number),
  /** Sealed first-round independent verdict (Audit Cloud). Immutable once written. */
  sealedVerdict: Schema.optional(Schema.String),
})
export type CloudMember = typeof CloudMember.Type

export const CallLease = Schema.Struct({
  lease_id: LeaseID,
  cloud_id: CloudID,
  agent_id: SessionID,
  max_requests: Schema.Number,
  max_tokens: Schema.Number,
  used_requests: Schema.Number,
  used_tokens: Schema.Number,
  expires_at: Schema.Number,
  transferable: Schema.Literal(false),
  may_spawn: Schema.Literal(false),
  revoked_at: Schema.optional(Schema.Number),
})
export type CallLease = typeof CallLease.Type

export const Cloud = Schema.Struct({
  cloud_id: CloudID,
  cloud_type: CloudType,
  purpose: Schema.String,
  members: Schema.Array(CloudMember),
  member_limit: Schema.Number,
  token_budget: Schema.Number,
  tokens_used: Schema.Number,
  max_rounds: Schema.Number,
  rounds_used: Schema.Number,
  max_lifetime_ms: Schema.Number,
  tool_permissions: Schema.Array(Schema.String),
  resource_permissions: Schema.Array(Schema.String),
  created_at: Schema.Number,
  expires_at: Schema.Number,
  status: CloudStatus,
  exit_conditions: Schema.Array(Schema.String),
  archive_policy: Schema.String,
  /** Audit Cloud: the cloud this one audits. Conflict-of-interest checks use it (invariant V). */
  audit_target: Schema.optional(CloudID),
  /** Final unified report; preserved through ARCHIVED/DESTROYED (invariant X). */
  final_report: Schema.optional(Schema.String),
})
export type Cloud = typeof Cloud.Type

// ─── Claw session (data channel only) ────────────────────────────────────────

export const ClawMessageKind = Schema.Literals([
  "report",
  "evidence_pack",
  "state_summary",
  "challenge",
  "verdict",
])
export type ClawMessageKind = typeof ClawMessageKind.Type

export const ClawMessage = Schema.Struct({
  id: Schema.String,
  claw_session_id: ClawSessionID,
  from: SessionID,
  to: SessionID,
  kind: ClawMessageKind,
  /** Content hash of the payload, acting as the message signature. */
  signature: Schema.String,
  payload: Schema.String,
  /** References to shared evidence (read-only resources), never live context. */
  evidence_refs: Schema.Array(Schema.String),
  round: Schema.Number,
  at: Schema.Number,
})
export type ClawMessage = typeof ClawMessage.Type

export const ClawSession = Schema.Struct({
  claw_session_id: ClawSessionID,
  cloud_id: CloudID,
  /** Pairwise data-channel link between two member agents. Never to Yuheng. */
  party_a: SessionID,
  party_b: SessionID,
  opened_at: Schema.Number,
  closed_at: Schema.optional(Schema.Number),
  max_rounds: Schema.Number,
  messages: Schema.Array(ClawMessage),
})
export type ClawSession = typeof ClawSession.Type

// ─── Agent requests (control plane intake) ───────────────────────────────────

export const SpawnRequest = Schema.Struct({
  request_id: RequestID,
  requested_by: Schema.Struct({ session: SessionID, agentType: Schema.String }),
  agent_type: Schema.String,
  purpose: Schema.String,
  for_cloud: Schema.optional(CloudID),
  at: Schema.Number,
  decision: Schema.optional(
    Schema.Struct({
      approved: Schema.Boolean,
      reason: Schema.String,
      granted_session: Schema.optional(SessionID),
      at: Schema.Number,
    }),
  ),
})
export type SpawnRequest = typeof SpawnRequest.Type

// ─── Lifecycle events (append-only log, mirrors state-manager pattern) ───────

export const ClawEvent = Schema.Struct({
  seq: Schema.Number,
  at: Schema.Number,
  cloud_id: Schema.optional(CloudID),
  type: Schema.String,
  data: Schema.Record(Schema.String, Schema.Unknown),
})
export type ClawEvent = typeof ClawEvent.Type

// ─── Errors (fail closed; every refusal is explicit) ─────────────────────────

export class ClawError extends Schema.TaggedErrorClass<ClawError>()("ClawError", {
  code: Schema.String,
  message: Schema.String,
}) {}

export const clawError = (code: string, message: string) => new ClawError({ code, message })

export const E = {
  CONTROL_PLANE_ENTITY_CANNOT_JOIN_CLOUD: "CONTROL_PLANE_ENTITY_CANNOT_JOIN_CLOUD",
  CONTROL_PLANE_ENTITY_CANNOT_BIND_CLAW: "CONTROL_PLANE_ENTITY_CANNOT_BIND_CLAW",
  AGENT_ALREADY_IN_ACTIVE_CLOUD: "AGENT_ALREADY_IN_ACTIVE_CLOUD",
  AGENT_PERMISSION_CLEANUP_PENDING: "AGENT_PERMISSION_CLEANUP_PENDING",
  CLOUD_MEMBER_LIMIT_REACHED: "CLOUD_MEMBER_LIMIT_REACHED",
  CLOUD_NOT_FOUND: "CLOUD_NOT_FOUND",
  CLOUD_NOT_ACTIVE: "CLOUD_NOT_ACTIVE",
  CLOUD_BUDGET_EXHAUSTED: "CLOUD_BUDGET_EXHAUSTED",
  CLOUD_ROUNDS_EXHAUSTED: "CLOUD_ROUNDS_EXHAUSTED",
  CLOUD_EXPIRED: "CLOUD_EXPIRED",
  CAPACITY_HARD_STOP: "CAPACITY_HARD_STOP",
  CAPACITY_LOCKDOWN: "CAPACITY_LOCKDOWN",
  CAPACITY_EMERGENCY: "CAPACITY_EMERGENCY",
  SPAWN_NOT_PERMITTED: "SPAWN_NOT_PERMITTED",
  SELF_AUDIT_FORBIDDEN: "SELF_AUDIT_FORBIDDEN",
  CONFLICT_OF_INTEREST: "CONFLICT_OF_INTEREST",
  CLAW_NOT_FOUND: "CLAW_NOT_FOUND",
  CLAW_CLOSED: "CLAW_CLOSED",
  CLAW_ROUND_LIMIT: "CLAW_ROUND_LIMIT",
  LEASE_EXHAUSTED: "LEASE_EXHAUSTED",
  VERDICT_ALREADY_SEALED: "VERDICT_ALREADY_SEALED",
  MEMBER_NOT_FOUND: "MEMBER_NOT_FOUND",
  INVALID_STATE_TRANSITION: "INVALID_STATE_TRANSITION",
} as const
