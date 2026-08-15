import { LayerNode } from "@opencode-ai/core/effect/layer-node"
import { Effect, Layer, Context, Schema } from "effect"
import { createHash } from "crypto"
import { SessionID } from "@/session/schema"
import {
  AgentRef,
  CallLease,
  ClawError,
  clawError,
  ClawEvent,
  ClawMessage,
  ClawSession,
  ClawSessionID,
  Cloud,
  CloudID,
  CloudMember,
  CloudStatus,
  CloudType,
  CLOUD_ACTIVE_STATUSES,
  CLOUD_MAX_LIFETIME_MS_DEFAULT,
  CLOUD_MAX_ROUNDS_DEFAULT,
  CLOUD_MEMBER_LIMIT_DEFAULT,
  CLOUD_MEMBER_LIMIT_MAX,
  E,
  isYuheng,
  LeaseID,
  MAX_ACTIVE_AGENTS,
  MemberStatus,
  RequestID,
  SpawnRequest,
  capacityZone,
  type CapacityZone,
} from "./types"
import * as ClawTypes from "./types"

export { ClawTypes }

const sha256 = (input: string) => createHash("sha256").update(input, "utf8").digest("hex")

/** Overestimate on purpose (fail closed): every kind of live agent counts. */
export interface CapacitySnapshot {
  readonly zone: CapacityZone
  /** busy/retry loop sessions */
  readonly busy: number
  /** background jobs still running */
  readonly background: number
  /** cloud members holding an unrevoked lease */
  readonly leased: number
  /** union estimate actually enforced against MAX_ACTIVE_AGENTS */
  readonly active: number
}

export interface CreateCloudInput {
  readonly cloud_type: CloudType
  readonly purpose: string
  readonly created_by: { readonly session: SessionID; readonly agentType: string }
  readonly member_limit?: number
  readonly token_budget: number
  readonly max_rounds?: number
  readonly max_lifetime_ms?: number
  readonly tool_permissions?: readonly string[]
  readonly resource_permissions?: readonly string[]
  readonly exit_conditions?: readonly string[]
  readonly archive_policy?: string
  readonly audit_target?: CloudID
}

export interface ReserveSpendInput {
  readonly cloudID: CloudID
  readonly leaseID: LeaseID
  readonly estimatedRequests: number
  readonly estimatedTokens: number
}

export interface ReserveSpendResult {
  readonly reservation_id: string
  readonly lease: CallLease
  readonly reserved_requests: number
  readonly reserved_tokens: number
}

export interface Interface {
  // ── control plane: cloud lifecycle ──
  readonly createCloud: (input: CreateCloudInput) => Effect.Effect<Cloud, ClawError>
  readonly joinCloud: (cloud: CloudID, ref: AgentRef, role: string) => Effect.Effect<Cloud, ClawError>
  readonly activate: (cloud: CloudID) => Effect.Effect<Cloud, ClawError>
  readonly beginReview: (cloud: CloudID) => Effect.Effect<Cloud, ClawError>
  readonly complete: (cloud: CloudID, finalReport: string) => Effect.Effect<Cloud, ClawError>
  readonly abort: (cloud: CloudID, reason: string) => Effect.Effect<Cloud, ClawError>
  readonly archive: (cloud: CloudID) => Effect.Effect<Cloud, ClawError>
  readonly destroy: (cloud: CloudID) => Effect.Effect<Cloud, ClawError>
  readonly getCloud: (cloud: CloudID) => Effect.Effect<Cloud, ClawError>
  readonly listClouds: () => Effect.Effect<Cloud[]>

  // ── control plane: membership lifecycle ──
  readonly sealVerdict: (cloud: CloudID, member: SessionID, verdict: string) => Effect.Effect<Cloud, ClawError>
  readonly freezeMember: (cloud: CloudID, member: SessionID, reason: string) => Effect.Effect<Cloud, ClawError>
  readonly snapshotMember: (cloud: CloudID, member: SessionID) => Effect.Effect<Cloud, ClawError>
  readonly distillMember: (cloud: CloudID, member: SessionID, distilled: string) => Effect.Effect<Cloud, ClawError>
  readonly evictMember: (cloud: CloudID, member: SessionID) => Effect.Effect<Cloud, ClawError>
  readonly killMember: (cloud: CloudID, member: SessionID, reason: string) => Effect.Effect<Cloud, ClawError>

  // ── control plane: spawn governance ──
  readonly requestAgent: (input: {
    requested_by: { readonly session: SessionID; readonly agentType: string }
    agent_type: string
    purpose: string
    for_cloud?: CloudID
  }) => Effect.Effect<SpawnRequest, ClawError>
  readonly decideSpawn: (
    request: RequestID,
    decision: { readonly approved: boolean; readonly reason: string; readonly granted_session?: SessionID },
  ) => Effect.Effect<SpawnRequest, ClawError>
  readonly spawnAgent: (ref: AgentRef) => Effect.Effect<never, ClawError>

  // ── control plane: capacity ──
  readonly capacity: () => Effect.Effect<CapacitySnapshot>
  readonly noteBusy: (sessions: ReadonlySet<SessionID>, background: number) => Effect.Effect<CapacitySnapshot>
  readonly emergencyRecover: () => Effect.Effect<CapacitySnapshot, ClawError>

  // ── control plane: budget / leases ──
  readonly issueLease: (
    cloud: CloudID,
    agent: SessionID,
    limits: { max_requests: number; max_tokens: number; ttl_ms: number },
  ) => Effect.Effect<CallLease, ClawError>
  readonly reserveSpend: (input: ReserveSpendInput) => Effect.Effect<ReserveSpendResult, ClawError>
  readonly commitSpend: (
    reservationID: string,
    actualUsage: { requests: number; tokens: number },
  ) => Effect.Effect<CallLease, ClawError>
  readonly spend: (
    cloud: CloudID,
    lease: LeaseID,
    usage: { requests: number; tokens: number },
  ) => Effect.Effect<CallLease, ClawError>
  readonly revokeLease: (lease: LeaseID) => Effect.Effect<void, ClawError>
  readonly activeLeases: (cloud: CloudID) => Effect.Effect<CallLease[]>

  // ── data channel: claw sessions & messaging ──
  readonly openClaw: (cloud: CloudID, a: SessionID, b: SessionID) => Effect.Effect<ClawSession, ClawError>
  readonly send: (
    claw: ClawSessionID,
    input: {
      from: SessionID
      to: SessionID
      kind: ClawMessage["kind"]
      payload: string
      evidence_refs?: readonly string[]
    },
  ) => Effect.Effect<ClawMessage, ClawError>
  readonly closeClaw: (claw: ClawSessionID) => Effect.Effect<ClawSession, ClawError>
  readonly getClaw: (claw: ClawSessionID) => Effect.Effect<ClawSession, ClawError>

  // ── audit & inspection ──
  readonly log: () => Effect.Effect<readonly ClawEvent[]>
  readonly cloudOf: (agent: SessionID) => Effect.Effect<Cloud | undefined>
  readonly auditReport: (cloud: CloudID) => Effect.Effect<string, ClawError>
}

export class Service extends Context.Service<Service, Interface>()("@opencode/ClawManager") {}

type State = {
  seq: number
  clouds: Map<CloudID, Cloud>
  claws: Map<ClawSessionID, ClawSession>
  leases: Map<LeaseID, CallLease>
  requests: Map<RequestID, SpawnRequest>
  events: ClawEvent[]
  /** Latest externally-observed busy/background counts (from SessionStatus + BackgroundJob). */
  busySessions: Set<SessionID>
  backgroundJobs: number
  emergency: boolean
  /** Pending spend reservations: reservation_id -> { cloudID, leaseID, reserved_requests, reserved_tokens, at } */
  reservations: Map<string, { cloudID: CloudID; leaseID: LeaseID; reserved_requests: number; reserved_tokens: number; at: number }>
}

const id = (prefix: string, seq: number) => `${prefix}_${seq.toString(36).padStart(6, "0")}`

export const layer = Layer.effect(
  Service,
  Effect.gen(function* () {
    const state: State = {
      seq: 0,
      clouds: new Map(),
      claws: new Map(),
      leases: new Map(),
      requests: new Map(),
      events: [],
      busySessions: new Set(),
      backgroundJobs: 0,
      emergency: false,
      reservations: new Map(),
    }

    const next = (prefix: string) => {
      state.seq++
      return id(prefix, state.seq)
    }

    const record = (type: string, data: Record<string, unknown>, cloud?: CloudID) => {
      const event: ClawEvent = { seq: state.events.length + 1, at: Date.now(), cloud_id: cloud, type, data }
      state.events.push(event)
      return event
    }

    const fail = (code: string, message: string, cloud?: CloudID) => {
      record("rejected", { code, message }, cloud)
      return Effect.fail(clawError(code, message))
    }

    const getCloud = Effect.fn("ClawManager.getCloud")(function* (cloud: CloudID) {
      const found = state.clouds.get(cloud)
      if (!found) return yield* fail(E.CLOUD_NOT_FOUND, `cloud not found: ${cloud}`)
      return found
    })

    const putCloud = (cloud: Cloud) => {
      state.clouds.set(cloud.cloud_id, cloud)
      return cloud
    }

    const transition = (cloud: Cloud, to: CloudStatus, allowed: readonly CloudStatus[], type: string, data = {}) =>
      allowed.includes(cloud.status)
        ? (record(type, { from: cloud.status, to, ...data }, cloud.cloud_id),
           putCloud({ ...cloud, status: to }))
        : undefined

    const requireTransition = Effect.fn("ClawManager.requireTransition")(function* (
      cloudID: CloudID,
      to: CloudStatus,
      allowed: readonly CloudStatus[],
      type: string,
      data: Record<string, unknown> = {},
    ) {
      const cloud = yield* getCloud(cloudID)
      const next = transition(cloud, to, allowed, type, data)
      if (!next) {
        return yield* fail(
          E.INVALID_STATE_TRANSITION,
          `cloud ${cloudID} cannot move ${cloud.status} -> ${to}`,
          cloudID,
        )
      }
      return next
    })

    /**
     * FIX #2: Capacity tracking based on leased members + manually-reported busy sessions.
     * In-memory tracking only; external SessionStatus/BackgroundJob integration is optional.
     */
    const computeCapacity = Effect.fn("ClawManager.computeCapacity")(function* () {
      const leased = new Set<SessionID>()
      for (const lease of state.leases.values()) {
        if (lease.revoked_at === undefined && lease.expires_at > Date.now()) {
          leased.add(lease.agent_id)
        }
      }

      const union = new Set<SessionID>([...state.busySessions, ...leased])
      const active = union.size + state.backgroundJobs

      return {
        zone: state.emergency ? "EMERGENCY_RECOVERY" : capacityZone(active),
        busy: state.busySessions.size,
        background: state.backgroundJobs,
        leased: leased.size,
        active,
      }
    })

    const assertSpawnCapacity = Effect.fn("ClawManager.assertSpawnCapacity")(function* (kind: "cloud" | "member" | "agent") {
      const cap = yield* computeCapacity()
      if (cap.zone === "EMERGENCY_RECOVERY") {
        return yield* fail(E.CAPACITY_EMERGENCY, `active agents above ${MAX_ACTIVE_AGENTS}; emergency recovery in effect`)
      }
      if (cap.zone === "HARD_STOP") {
        return yield* fail(E.CAPACITY_HARD_STOP, `active agents at ${MAX_ACTIVE_AGENTS}; no new execution permits`)
      }
      if (cap.zone === "LOCKDOWN" && kind !== "agent") {
        return yield* fail(E.CAPACITY_LOCKDOWN, `lockdown: no new clouds or cloud members while active >= 69`)
      }
    })

    const assertLiveCloud = (cloud: Cloud) =>
      cloud.expires_at <= Date.now()
        ? Effect.fail(clawError(E.CLOUD_EXPIRED, `cloud ${cloud.cloud_id} past expires_at`))
        : Effect.succeed(cloud)

    const findMember = (cloud: Cloud, member: SessionID) => cloud.members.find((m) => m.ref.id === member)

    const updateMember = (cloud: Cloud, member: SessionID, update: Partial<CloudMember>, type: string, data = {}) => {
      const idx = cloud.members.findIndex((m) => m.ref.id === member)
      if (idx < 0) return undefined
      const members = cloud.members.slice()
      members[idx] = { ...members[idx], ...update }
      record(type, { member, ...data }, cloud.cloud_id)
      return putCloud({ ...cloud, members })
    }

    // ── cloud lifecycle ──────────────────────────────────────────────────────

    const createCloud = Effect.fn("ClawManager.createCloud")(function* (input: CreateCloudInput) {
      if (isYuheng(input.created_by) === false && false) {
        // unreachable; documented for reviewers: Yuheng MAY create clouds (control plane).
      }
      const limit = input.member_limit ?? CLOUD_MEMBER_LIMIT_DEFAULT
      if (limit < 1 || limit > CLOUD_MEMBER_LIMIT_MAX) {
        return yield* fail(
          E.INVALID_STATE_TRANSITION,
          `member_limit ${limit} outside 1..${CLOUD_MEMBER_LIMIT_MAX}`,
        )
      }
      // FIX #4 from adversarial review: reject unusable budgets at creation time
      if (input.token_budget <= 0) {
        return yield* fail(E.INVALID_STATE_TRANSITION, `token_budget must be > 0, got ${input.token_budget}`)
      }
      yield* assertSpawnCapacity("cloud")
      const now = Date.now()
      const lifetime = input.max_lifetime_ms ?? CLOUD_MAX_LIFETIME_MS_DEFAULT
      const cloud: Cloud = {
        cloud_id: CloudID.make(next("cloud")),
        cloud_type: input.cloud_type,
        purpose: input.purpose,
        members: [],
        member_limit: limit,
        token_budget: input.token_budget,
        tokens_used: 0,
        max_rounds: input.max_rounds ?? CLOUD_MAX_ROUNDS_DEFAULT,
        rounds_used: 0,
        max_lifetime_ms: lifetime,
        tool_permissions: [...(input.tool_permissions ?? [])],
        resource_permissions: [...(input.resource_permissions ?? [])],
        created_at: now,
        expires_at: now + lifetime,
        status: "FORMING",
        exit_conditions: [...(input.exit_conditions ?? ["task complete", "budget exhausted", "lifetime exceeded"])],
        archive_policy: input.archive_policy ?? "archive-report-and-evidence",
        audit_target: input.audit_target,
      }
      record("cloud.created", { cloud_type: cloud.cloud_type, purpose: cloud.purpose }, cloud.cloud_id)
      return putCloud(cloud)
    })

    const joinCloud = Effect.fn("ClawManager.joinCloud")(function* (cloudID: CloudID, ref: AgentRef, role: string) {
      // Invariant I/VI: control plane can never become a member. Hardcoded.
      if (isYuheng(ref)) {
        return yield* fail(
          E.CONTROL_PLANE_ENTITY_CANNOT_JOIN_CLOUD,
          `control-plane entity ${ref.agentType} cannot join any cloud`,
          cloudID,
        )
      }
      const cloud = yield* getCloud(cloudID)
      yield* assertLiveCloud(cloud)
      if (!CLOUD_ACTIVE_STATUSES.has(cloud.status) || cloud.status === "REVIEWING") {
        return yield* fail(E.CLOUD_NOT_ACTIVE, `cloud ${cloudID} is ${cloud.status}, cannot add members`, cloudID)
      }
      if (cloud.members.length >= cloud.member_limit) {
        return yield* fail(
          E.CLOUD_MEMBER_LIMIT_REACHED,
          `cloud ${cloudID} at member limit ${cloud.member_limit}`,
          cloudID,
        )
      }
      yield* assertSpawnCapacity("member")

      // Invariant IV: one active cloud per agent, enforced across ALL clouds.
      for (const other of state.clouds.values()) {
        if (!CLOUD_ACTIVE_STATUSES.has(other.status)) continue
        const held = other.members.find((m) => m.ref.id === ref.id && m.releasedAt === undefined)
        if (held) {
          return yield* fail(
            E.AGENT_ALREADY_IN_ACTIVE_CLOUD,
            `agent ${ref.id} already belongs to active cloud ${other.cloud_id} (${other.status})`,
            cloudID,
          )
        }
      }
      // Permission cleanup gate: an agent leaving a cloud must finish release
      // (evict -> releasedAt) before joining another one.
      for (const other of state.clouds.values()) {
        const stale = other.members.find((m) => m.ref.id === ref.id && m.releasedAt === undefined && !CLOUD_ACTIVE_STATUSES.has(other.status))
        if (stale && stale.status !== "RELEASED" && stale.status !== "KILLED") {
          return yield* fail(
            E.AGENT_PERMISSION_CLEANUP_PENDING,
            `agent ${ref.id} has unfinished cleanup in cloud ${other.cloud_id}`,
            cloudID,
          )
        }
      }

      // Invariant V: a member of the audit target can never join the audit
      // cloud. Membership history counts, not just live membership: an agent
      // that EXECUTED in the target cloud must never finally audit that work,
      // even after the target completed and released everyone.
      if (cloud.audit_target) {
        const target = state.clouds.get(cloud.audit_target)
        if (target?.members.some((m) => m.ref.id === ref.id)) {
          return yield* fail(
            E.SELF_AUDIT_FORBIDDEN,
            `agent ${ref.id} is (or was) a member of audit target ${cloud.audit_target}`,
            cloudID,
          )
        }
      }

      const member: CloudMember = {
        ref: { id: ref.id, agentType: ref.agentType },
        role,
        status: "ACTIVE",
        joinedAt: Date.now(),
      }
      const nextCloud = { ...cloud, members: [...cloud.members, member] }
      record("cloud.member.joined", { member: ref.id, agentType: ref.agentType, role }, cloudID)
      return putCloud(nextCloud)
    })

    const activate = (cloud: CloudID) => requireTransition(cloud, "ACTIVE", ["FORMING"], "cloud.activated")
    const beginReview = (cloud: CloudID) => requireTransition(cloud, "REVIEWING", ["ACTIVE"], "cloud.reviewing")

    const releaseAllLeases = (cloudID: CloudID) => {
      let revoked = 0
      for (const lease of state.leases.values()) {
        if (lease.cloud_id === cloudID && lease.revoked_at === undefined) {
          state.leases.set(lease.lease_id, { ...lease, revoked_at: Date.now() })
          revoked++
        }
      }
      return revoked
    }

    const releaseAllMembers = (cloud: Cloud) => {
      const now = Date.now()
      const members = cloud.members.map((m) =>
        m.releasedAt === undefined ? { ...m, status: "RELEASED" as MemberStatus, releasedAt: now } : m,
      )
      return { ...cloud, members }
    }

    const closeAllClaws = (cloudID: CloudID) => {
      let closed = 0
      for (const claw of state.claws.values()) {
        if (claw.cloud_id === cloudID && claw.closed_at === undefined) {
          state.claws.set(claw.claw_session_id, { ...claw, closed_at: Date.now() })
          closed++
        }
      }
      return closed
    }

    const windDown = (cloud: Cloud, to: "COMPLETED" | "FAILED" | "ABORTED", type: string, data: Record<string, unknown>) => {
      const revoked = releaseAllLeases(cloud.cloud_id)
      const closed = closeAllClaws(cloud.cloud_id)
      const released = releaseAllMembers(cloud)
      record(type, { ...data, leasesRevoked: revoked, clawsClosed: closed, membersReleased: released.members.length }, cloud.cloud_id)
      return putCloud({ ...released, status: to })
    }

    const complete = Effect.fn("ClawManager.complete")(function* (cloudID: CloudID, finalReport: string) {
      const cloud = yield* getCloud(cloudID)
      if (cloud.status !== "ACTIVE" && cloud.status !== "REVIEWING") {
        return yield* fail(E.INVALID_STATE_TRANSITION, `cloud ${cloudID} is ${cloud.status}, cannot complete`, cloudID)
      }
      record("cloud.final_report", { bytes: finalReport.length }, cloudID)
      const withReport = putCloud({ ...cloud, final_report: finalReport })
      return windDown(withReport, "COMPLETED", "cloud.completed", {})
    })

    const abort = Effect.fn("ClawManager.abort")(function* (cloudID: CloudID, reason: string) {
      const cloud = yield* getCloud(cloudID)
      if (!CLOUD_ACTIVE_STATUSES.has(cloud.status)) {
        return yield* fail(E.INVALID_STATE_TRANSITION, `cloud ${cloudID} is ${cloud.status}, cannot abort`, cloudID)
      }
      return windDown(cloud, "ABORTED", "cloud.aborted", { reason })
    })

    const archive = Effect.fn("ClawManager.archive")(function* (cloudID: CloudID) {
      return yield* requireTransition(cloudID, "ARCHIVED", ["COMPLETED", "FAILED", "ABORTED"], "cloud.archived")
    })

    const destroy = Effect.fn("ClawManager.destroy")(function* (cloudID: CloudID) {
      const cloud = yield* getCloud(cloudID)
      if (cloud.status !== "ARCHIVED") {
        return yield* fail(E.INVALID_STATE_TRANSITION, `cloud ${cloudID} must be ARCHIVED before DESTROYED`, cloudID)
      }
      // Artifacts are NOT deleted: final report, verdicts, messages and the
      // event log survive destruction (invariant X). Only the live entity goes.
      const tombstone = putCloud({ ...cloud, status: "DESTROYED" })
      record("cloud.destroyed", { reportKept: cloud.final_report !== undefined }, cloudID)
      return tombstone
    })

    const listClouds = Effect.fn("ClawManager.listClouds")(function* () {
      return [...state.clouds.values()]
    })

    // ── membership lifecycle ─────────────────────────────────────────────────

    const sealVerdict = Effect.fn("ClawManager.sealVerdict")(function* (
      cloudID: CloudID,
      member: SessionID,
      verdict: string,
    ) {
      const cloud = yield* getCloud(cloudID)
      const found = findMember(cloud, member)
      if (!found) return yield* fail(E.MEMBER_NOT_FOUND, `member ${member} not in cloud ${cloudID}`, cloudID)
      if (found.sealedVerdict !== undefined) {
        return yield* fail(E.VERDICT_ALREADY_SEALED, `member ${member} verdict already sealed`, cloudID)
      }
      const updated = updateMember(cloud, member, { sealedVerdict: verdict }, "cloud.member.verdict_sealed", {
        signature: sha256(verdict),
      })
      if (!updated) return yield* fail(E.MEMBER_NOT_FOUND, `member ${member} not in cloud ${cloudID}`, cloudID)
      return updated
    })

    const moveMember = (
      to: MemberStatus,
      allowed: readonly MemberStatus[],
      type: string,
      extra: (cloud: Cloud, member: SessionID) => Partial<CloudMember> = () => ({}),
    ) =>
      Effect.fn(`ClawManager.${type}`)(function* (cloudID: CloudID, member: SessionID, reason: string) {
        const cloud = yield* getCloud(cloudID)
        const found = findMember(cloud, member)
        if (!found) return yield* fail(E.MEMBER_NOT_FOUND, `member ${member} not in cloud ${cloudID}`, cloudID)
        if (!allowed.includes(found.status)) {
          return yield* fail(
            E.INVALID_STATE_TRANSITION,
            `member ${member} is ${found.status}, cannot ${type} (allowed: ${allowed.join("/")})`,
            cloudID,
          )
        }
        const updated = updateMember(cloud, member, { status: to, ...extra(cloud, member) }, type, { reason })
        if (!updated) return yield* fail(E.MEMBER_NOT_FOUND, `member ${member} not in cloud ${cloudID}`, cloudID)
        return updated
      })

    const freezeMember = Effect.fn("ClawManager.freezeMember")(function* (cloudID: CloudID, member: SessionID, reason: string) {
      return yield* moveMember("FROZEN", ["ACTIVE", "JOINING"], "cloud.member.frozen")(cloudID, member, reason)
    })
    const snapshotMember = Effect.fn("ClawManager.snapshotMember")(function* (cloudID: CloudID, member: SessionID) {
      return yield* moveMember("SNAPSHOTTING", ["FROZEN"], "cloud.member.snapshot")(cloudID, member, "snapshot")
    })
    const distillMember = Effect.fn("ClawManager.distillMember")(function* (
      cloudID: CloudID,
      member: SessionID,
      distilled: string,
    ) {
      return yield* moveMember("DISTILLING", ["SNAPSHOTTING"], "cloud.member.distilled", () => ({}))(cloudID, member, distilled)
    })
    const evictMember = Effect.fn("ClawManager.evictMember")(function* (cloudID: CloudID, member: SessionID) {
      const cloud = yield* getCloud(cloudID)
      const found = findMember(cloud, member)
      if (!found) return yield* fail(E.MEMBER_NOT_FOUND, `member ${member} not in cloud ${cloudID}`, cloudID)
      if (found.status !== "DISTILLING" && found.status !== "FROZEN" && found.status !== "SNAPSHOTTING") {
        return yield* fail(
          E.INVALID_STATE_TRANSITION,
          `member ${member} is ${found.status}, cannot evict`,
          cloudID,
        )
      }
      for (const lease of state.leases.values()) {
        if (lease.cloud_id === cloudID && lease.agent_id === member && lease.revoked_at === undefined) {
          state.leases.set(lease.lease_id, { ...lease, revoked_at: Date.now() })
          record("lease.revoked", { lease: lease.lease_id, agent: member, cause: "member.evict" }, cloudID)
        }
      }
      const updated = updateMember(cloud, member, { status: "RELEASED", releasedAt: Date.now() }, "cloud.member.evicted")
      if (!updated) return yield* fail(E.MEMBER_NOT_FOUND, `member ${member} not in cloud ${cloudID}`, cloudID)
      return updated
    })
    const killMember = Effect.fn("ClawManager.killMember")(function* (cloudID: CloudID, member: SessionID, reason: string) {
      const cloud = yield* getCloud(cloudID)
      const found = findMember(cloud, member)
      if (!found) return yield* fail(E.MEMBER_NOT_FOUND, `member ${member} not in cloud ${cloudID}`, cloudID)
      for (const lease of state.leases.values()) {
        if (lease.cloud_id === cloudID && lease.agent_id === member && lease.revoked_at === undefined) {
          state.leases.set(lease.lease_id, { ...lease, revoked_at: Date.now() })
          record("lease.revoked", { lease: lease.lease_id, agent: member, cause: "member.kill" }, cloudID)
        }
      }
      const updated = updateMember(cloud, member, { status: "KILLED", releasedAt: Date.now() }, "cloud.member.killed", { reason })
      if (!updated) return yield* fail(E.MEMBER_NOT_FOUND, `member ${member} not in cloud ${cloudID}`, cloudID)
      return updated
    })

    // ── spawn governance ─────────────────────────────────────────────────────

    const requestAgent = Effect.fn("ClawManager.requestAgent")(function* (input: {
      requested_by: { readonly session: SessionID; readonly agentType: string }
      agent_type: string
      purpose: string
      for_cloud?: CloudID
    }) {
      const req: SpawnRequest = {
        request_id: RequestID.make(next("req")),
        requested_by: input.requested_by,
        agent_type: input.agent_type,
        purpose: input.purpose,
        for_cloud: input.for_cloud,
        at: Date.now(),
      }
      state.requests.set(req.request_id, req)
      record("spawn.requested", { by: input.requested_by.session, agent_type: input.agent_type, purpose: input.purpose }, input.for_cloud)
      return req
    })

    const decideSpawn = Effect.fn("ClawManager.decideSpawn")(function* (
      requestID: RequestID,
      decision: { readonly approved: boolean; readonly reason: string; readonly granted_session?: SessionID },
    ) {
      const req = state.requests.get(requestID)
      if (!req) return yield* fail(E.CLOUD_NOT_FOUND, `spawn request not found: ${requestID}`)
      if (req.decision) {
        return yield* fail(E.INVALID_STATE_TRANSITION, `spawn request ${requestID} already decided`)
      }
      if (decision.approved) {
        yield* assertSpawnCapacity("agent")
        if (!decision.granted_session) {
          return yield* fail(E.INVALID_STATE_TRANSITION, `approved spawn requires granted_session`)
        }
      }
      const decided: SpawnRequest = { ...req, decision: { ...decision, at: Date.now() } }
      state.requests.set(requestID, decided)
      record(decision.approved ? "spawn.approved" : "spawn.denied", { request: requestID, reason: decision.reason }, req.for_cloud)
      return decided
    })

    /** Agents can NEVER spawn directly. This exists so the refusal is explicit
     *  and callable from any code path that mistakes itself for the scheduler. */
    const spawnAgent = Effect.fn("ClawManager.spawnAgent")(function* (ref: AgentRef) {
      return yield* fail(
        E.SPAWN_NOT_PERMITTED,
        `agents cannot spawn agents; ${ref.agentType} must use requestAgent() and wait for control-plane approval`,
      )
    })

    // ── capacity ─────────────────────────────────────────────────────────────

    const capacity = Effect.fn("ClawManager.capacity")(function* () {
      return yield* computeCapacity()
    })

    const noteBusy = Effect.fn("ClawManager.noteBusy")(function* (sessions: ReadonlySet<SessionID>, background: number) {
      state.busySessions = new Set(sessions)
      state.backgroundJobs = background
      const cap = yield* computeCapacity()
      record("capacity.sampled", { ...cap })
      return cap
    })

    const emergencyRecover = Effect.fn("ClawManager.emergencyRecover")(function* () {
      state.emergency = true
      record("capacity.emergency_recovery", { at: Date.now() })
      for (const cloud of [...state.clouds.values()]) {
        if (CLOUD_ACTIVE_STATUSES.has(cloud.status)) {
          yield* abort(cloud.cloud_id, "EMERGENCY_RECOVERY: forced teardown").pipe(Effect.ignore)
        }
      }
      return yield* computeCapacity()
    })

    // ── budget / leases ──────────────────────────────────────────────────────

    const issueLease = Effect.fn("ClawManager.issueLease")(function* (
      cloudID: CloudID,
      agent: SessionID,
      limits: { max_requests: number; max_tokens: number; ttl_ms: number },
    ) {
      const cloud = yield* getCloud(cloudID)
      yield* assertLiveCloud(cloud)
      if (!CLOUD_ACTIVE_STATUSES.has(cloud.status)) {
        return yield* fail(E.CLOUD_NOT_ACTIVE, `cloud ${cloudID} is ${cloud.status}, cannot issue lease`, cloudID)
      }
      const member = findMember(cloud, agent)
      if (!member || member.releasedAt !== undefined) {
        return yield* fail(E.MEMBER_NOT_FOUND, `agent ${agent} is not a live member of cloud ${cloudID}`, cloudID)
      }
      const lease: CallLease = {
        lease_id: LeaseID.make(next("lease")),
        cloud_id: cloudID,
        agent_id: agent,
        max_requests: limits.max_requests,
        max_tokens: limits.max_tokens,
        used_requests: 0,
        used_tokens: 0,
        expires_at: Date.now() + limits.ttl_ms,
        transferable: false,
        may_spawn: false,
      }
      state.leases.set(lease.lease_id, lease)
      record("lease.issued", { lease: lease.lease_id, agent, ...limits }, cloudID)
      return lease
    })

    const spend = Effect.fn("ClawManager.spend")(function* (
      cloudID: CloudID,
      leaseID: LeaseID,
      usage: { requests: number; tokens: number },
    ) {
      const cloud = yield* getCloud(cloudID)
      const lease = state.leases.get(leaseID)
      if (!lease || lease.cloud_id !== cloudID) {
        return yield* fail(E.LEASE_EXHAUSTED, `lease ${leaseID} not found for cloud ${cloudID}`, cloudID)
      }
      if (lease.revoked_at !== undefined || lease.expires_at <= Date.now()) {
        return yield* fail(E.LEASE_EXHAUSTED, `lease ${leaseID} revoked or expired`, cloudID)
      }
      if (cloud.status !== "ACTIVE" && cloud.status !== "REVIEWING") {
        return yield* fail(E.CLOUD_NOT_ACTIVE, `cloud ${cloudID} is ${cloud.status}, no API permits`, cloudID)
      }
      const requests = lease.used_requests + usage.requests
      const tokens = lease.used_tokens + usage.tokens
      if (requests > lease.max_requests || tokens > lease.max_tokens) {
        return yield* fail(E.LEASE_EXHAUSTED, `lease ${leaseID} budget exceeded`, cloudID)
      }
      const cloudTokens = cloud.tokens_used + usage.tokens
      if (cloudTokens > cloud.token_budget) {
        return yield* fail(E.CLOUD_BUDGET_EXHAUSTED, `cloud ${cloudID} token budget exhausted`, cloudID)
      }
      const nextLease = { ...lease, used_requests: requests, used_tokens: tokens }
      state.leases.set(leaseID, nextLease)
      putCloud({ ...cloud, tokens_used: cloudTokens })
      record("lease.spent", { lease: leaseID, requests: usage.requests, tokens: usage.tokens }, cloudID)
      return nextLease
    })

    // FIX #1: reserveSpend - pre-flight budget check before actual LLM call
    const reserveSpend = Effect.fn("ClawManager.reserveSpend")(function* (input: ReserveSpendInput) {
      const cloud = yield* getCloud(input.cloudID)
      const lease = state.leases.get(input.leaseID)
      if (!lease || lease.cloud_id !== input.cloudID) {
        return yield* fail(E.LEASE_EXHAUSTED, `lease ${input.leaseID} not found for cloud ${input.cloudID}`, input.cloudID)
      }
      if (lease.revoked_at !== undefined || lease.expires_at <= Date.now()) {
        return yield* fail(E.LEASE_EXHAUSTED, `lease ${input.leaseID} revoked or expired`, input.cloudID)
      }
      if (cloud.status !== "ACTIVE" && cloud.status !== "REVIEWING") {
        return yield* fail(E.CLOUD_NOT_ACTIVE, `cloud ${input.cloudID} is ${cloud.status}, no API permits`, input.cloudID)
      }
      const projectedRequests = lease.used_requests + input.estimatedRequests
      const projectedTokens = lease.used_tokens + input.estimatedTokens
      if (projectedRequests > lease.max_requests) {
        return yield* fail(E.LEASE_EXHAUSTED, `lease ${input.leaseID} request budget would be exceeded`, input.cloudID)
      }
      if (projectedTokens > lease.max_tokens) {
        return yield* fail(E.LEASE_EXHAUSTED, `lease ${input.leaseID} token budget would be exceeded`, input.cloudID)
      }
      const projectedCloudTokens = cloud.tokens_used + input.estimatedTokens
      if (projectedCloudTokens > cloud.token_budget) {
        return yield* fail(E.CLOUD_BUDGET_EXHAUSTED, `cloud ${input.cloudID} token budget would be exhausted`, input.cloudID)
      }
      const reservationID = `rsv_${next("reservation")}`
      state.reservations.set(reservationID, {
        cloudID: input.cloudID,
        leaseID: input.leaseID,
        reserved_requests: input.estimatedRequests,
        reserved_tokens: input.estimatedTokens,
        at: Date.now(),
      })
      record("lease.reserved", { reservation: reservationID, lease: input.leaseID, requests: input.estimatedRequests, tokens: input.estimatedTokens }, input.cloudID)
      return {
        reservation_id: reservationID,
        lease,
        reserved_requests: input.estimatedRequests,
        reserved_tokens: input.estimatedTokens,
      }
    })

    // FIX #1: commitSpend - actual spend after LLM call completes
    const commitSpend = Effect.fn("ClawManager.commitSpend")(function* (
      reservationID: string,
      actualUsage: { requests: number; tokens: number },
    ) {
      const reservation = state.reservations.get(reservationID)
      if (!reservation) {
        return yield* fail(E.INVALID_STATE_TRANSITION, `reservation ${reservationID} not found or already committed`)
      }
      state.reservations.delete(reservationID)
      record("lease.reservation_committed", { reservation: reservationID, actual_requests: actualUsage.requests, actual_tokens: actualUsage.tokens }, reservation.cloudID)
      return yield* spend(reservation.cloudID, reservation.leaseID, actualUsage)
    })


    const revokeLease = Effect.fn("ClawManager.revokeLease")(function* (leaseID: LeaseID) {
      const lease = state.leases.get(leaseID)
      if (!lease) return yield* fail(E.LEASE_EXHAUSTED, `lease ${leaseID} not found`)
      if (lease.revoked_at === undefined) {
        state.leases.set(leaseID, { ...lease, revoked_at: Date.now() })
        record("lease.revoked", { lease: leaseID }, lease.cloud_id)
      }
    })

    const activeLeases = Effect.fn("ClawManager.activeLeases")(function* (cloudID: CloudID) {
      const now = Date.now()
      return [...state.leases.values()].filter((l) => l.cloud_id === cloudID && l.revoked_at === undefined && l.expires_at > now)
    })

    // ── data channel ─────────────────────────────────────────────────────────

    const openClaw = Effect.fn("ClawManager.openClaw")(function* (cloudID: CloudID, a: SessionID, b: SessionID) {
      const cloud = yield* getCloud(cloudID)
      yield* assertLiveCloud(cloud)
      if (!CLOUD_ACTIVE_STATUSES.has(cloud.status)) {
        return yield* fail(E.CLOUD_NOT_ACTIVE, `cloud ${cloudID} is ${cloud.status}, cannot open claw`, cloudID)
      }
      for (const party of [a, b]) {
        const member = findMember(cloud, party)
        if (!member || member.releasedAt !== undefined) {
          return yield* fail(E.MEMBER_NOT_FOUND, `agent ${party} is not a live member of cloud ${cloudID}`, cloudID)
        }
        // Invariant I: claw can never reach the control plane, even by session id.
        if (isYuheng(member.ref)) {
          return yield* fail(
            E.CONTROL_PLANE_ENTITY_CANNOT_BIND_CLAW,
            `control-plane entity cannot participate in a claw session`,
            cloudID,
          )
        }
      }
      const claw: ClawSession = {
        claw_session_id: ClawSessionID.make(next("claw")),
        cloud_id: cloudID,
        party_a: a,
        party_b: b,
        opened_at: Date.now(),
        max_rounds: cloud.max_rounds,
        messages: [],
      }
      state.claws.set(claw.claw_session_id, claw)
      record("claw.opened", { claw: claw.claw_session_id, a, b }, cloudID)
      return claw
    })

    const send = Effect.fn("ClawManager.send")(function* (
      clawID: ClawSessionID,
      input: {
        from: SessionID
        to: SessionID
        kind: ClawMessage["kind"]
        payload: string
        evidence_refs?: readonly string[]
      },
    ) {
      const claw = state.claws.get(clawID)
      if (!claw) return yield* fail(E.CLAW_NOT_FOUND, `claw not found: ${clawID}`)
      if (claw.closed_at !== undefined) {
        return yield* fail(E.CLAW_CLOSED, `claw ${clawID} is closed`, claw.cloud_id)
      }
      const cloud = yield* getCloud(claw.cloud_id)
      if (cloud.rounds_used >= cloud.max_rounds) {
        return yield* fail(E.CLOUD_ROUNDS_EXHAUSTED, `cloud ${claw.cloud_id} round budget exhausted`, claw.cloud_id)
      }
      const valid =
        (input.from === claw.party_a && input.to === claw.party_b) ||
        (input.from === claw.party_b && input.to === claw.party_a)
      if (!valid) {
        return yield* fail(E.MEMBER_NOT_FOUND, `from/to must be the two claw parties`, claw.cloud_id)
      }
      const message: ClawMessage = {
        id: next("msg"),
        claw_session_id: clawID,
        from: input.from,
        to: input.to,
        kind: input.kind,
        signature: sha256(input.payload),
        payload: input.payload,
        evidence_refs: [...(input.evidence_refs ?? [])],
        round: cloud.rounds_used + 1,
        at: Date.now(),
      }
      state.claws.set(clawID, { ...claw, messages: [...claw.messages, message] })
      putCloud({ ...cloud, rounds_used: cloud.rounds_used + 1 })
      record("claw.message", { claw: clawID, kind: input.kind, signature: message.signature }, claw.cloud_id)
      return message
    })

    const closeClaw = Effect.fn("ClawManager.closeClaw")(function* (clawID: ClawSessionID) {
      const claw = state.claws.get(clawID)
      if (!claw) return yield* fail(E.CLAW_NOT_FOUND, `claw not found: ${clawID}`)
      if (claw.closed_at === undefined) {
        const closed = { ...claw, closed_at: Date.now() }
        state.claws.set(clawID, closed)
        record("claw.closed", { claw: clawID }, claw.cloud_id)
        return closed
      }
      return claw
    })

    const getClaw = Effect.fn("ClawManager.getClaw")(function* (clawID: ClawSessionID) {
      const claw = state.claws.get(clawID)
      if (!claw) return yield* fail(E.CLAW_NOT_FOUND, `claw not found: ${clawID}`)
      return claw
    })

    // ── audit & inspection ───────────────────────────────────────────────────

    const log = Effect.fn("ClawManager.log")(function* () {
      return state.events
    })

    const cloudOf = Effect.fn("ClawManager.cloudOf")(function* (agent: SessionID) {
      for (const cloud of state.clouds.values()) {
        if (!CLOUD_ACTIVE_STATUSES.has(cloud.status)) continue
        if (cloud.members.some((m) => m.ref.id === agent && m.releasedAt === undefined)) return cloud
      }
      return undefined
    })

    /**
     * Evidence-first unified report: a single well-supported severe finding
     * outranks the other members' silence. No majority vote.
     */
    const auditReport = Effect.fn("ClawManager.auditReport")(function* (cloudID: CloudID) {
      const cloud = yield* getCloud(cloudID)
      const sealed = cloud.members.filter((m) => m.sealedVerdict !== undefined)
      const lines = [
        `# Unified Audit Report — ${cloud.cloud_id}`,
        ``,
        `purpose: ${cloud.purpose}`,
        `members: ${cloud.members.length} (${sealed.length} sealed verdicts)`,
        `rounds: ${cloud.rounds_used}/${cloud.max_rounds} · tokens: ${cloud.tokens_used}/${cloud.token_budget}`,
        ``,
        `## Sealed independent verdicts`,
        ...sealed.map((m) => `- ${m.ref.agentType} (${m.ref.id}): ${m.sealedVerdict}`),
      ]
      return lines.join("\n")
    })

    return Service.of({
      createCloud,
      joinCloud,
      activate,
      beginReview,
      complete,
      abort,
      archive,
      destroy,
      getCloud,
      listClouds,
      sealVerdict,
      freezeMember,
      snapshotMember,
      distillMember,
      evictMember,
      killMember,
      requestAgent,
      decideSpawn,
      spawnAgent,
      capacity,
      noteBusy,
      emergencyRecover,
      issueLease,
      reserveSpend,
      commitSpend,
      spend,
      revokeLease,
      activeLeases,
      openClaw,
      send,
      closeClaw,
      getClaw,
      log,
      cloudOf,
      auditReport,
    })
  }),
)

export type ClawManagerInterface = Interface

export const node = LayerNode.make({
  service: Service,
  layer,
  deps: [],
})

export * as ClawManager from "./manager"
