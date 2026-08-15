import { Effect, Schema } from "effect"
import { Service as ClawManagerService } from "./manager"
import { AgentRef, ClawError, clawError, Cloud, E, YUHENG_AGENT_NAME } from "./types"

/**
 * Audit Cloud — the first experimental cloud.
 *
 * Four independent agents: independent first-round verdicts are sealed BEFORE
 * any exchange; reports then cross over Claw; conflicts trigger supplementary
 * investigation; the unified report is evidence-first (a single well-evidenced
 * severe finding is never outvoted by silence). Orchestration lives here in
 * the control plane — members never spawn, never self-organize.
 */

export interface AuditMemberVerdict {
  readonly member: AgentRef
  readonly verdict: string
}

export interface AuditFlowResult {
  readonly cloud: Cloud
  readonly report: string
  readonly sealed: readonly AuditMemberVerdict[]
}

/** Compose the unified report from sealed verdicts. Evidence beats votes. */
export function composeAuditReport(input: {
  readonly cloud: Cloud
  readonly managerNote?: string
}): Effect.Effect<string, ClawError, ClawManagerService> {
  return ClawManagerService.use((svc) => svc.auditReport(input.cloud.cloud_id))
}

/** Hard conflict-of-interest check used by the orchestrator before forming. */
export function assertAuditIndependence(cloud: Cloud, target: Cloud): void {
  if (cloud.audit_target !== target.cloud_id) {
    throw clawError(E.CONFLICT_OF_INTEREST, `audit cloud ${cloud.cloud_id} does not declare target ${target.cloud_id}`)
  }
  const overlap = cloud.members.filter((m) => target.members.some((t) => t.ref.id === m.ref.id))
  if (overlap.length > 0) {
    throw clawError(
      E.SELF_AUDIT_FORBIDDEN,
      `audit cloud ${cloud.cloud_id} shares ${overlap.length} member(s) with target ${target.cloud_id}`,
    )
  }
  if (cloud.members.some((m) => m.ref.agentType === YUHENG_AGENT_NAME)) {
    throw clawError(E.CONTROL_PLANE_ENTITY_CANNOT_JOIN_CLOUD, `yuheng cannot be an audit member`)
  }
}

export const SealedVerdict = Schema.Struct({
  member: Schema.String,
  agentType: Schema.String,
  verdict: Schema.String,
})
