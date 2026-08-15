// Conflict output arbitrator: detects and classifies disagreements between
// upstream skill outputs, and either resolves them mechanically (epistemic
// label hierarchy + evidence weight) or escalates to cross_review routing.
//
// Hard rule (Panshi constitution): never average away a conflict silently.
// Every resolved conflict keeps the losing statement on record.

import type { EpistemicLabel } from "./types"

export interface ConflictingClaim {
  source: string // skill name
  statement: string
  label: EpistemicLabel
  evidence_refs?: string[]
}

export type ConflictKind = "value_mismatch" | "label_inflation" | "unit_mismatch" | "scope_mismatch"

export interface Conflict {
  kind: ConflictKind
  subject: string
  claims: ConflictingClaim[]
}

export type ArbitrationVerdict =
  | { type: "resolved"; winner: ConflictingClaim; rationale: string; losers: ConflictingClaim[] }
  | { type: "escalate"; reason: string; claims: ConflictingClaim[] }

const LABEL_RANK: Record<EpistemicLabel, number> = {
  OBSERVED: 5,
  CALCULATED: 4,
  REPORTED: 3,
  INFERRED: 2,
  HYPOTHESIS: 1,
  RECOMMENDATION: 0,
}

/** A claim whose label outranks its evidence support is inflated. */
export function detectLabelInflation(claim: ConflictingClaim): boolean {
  const evidenceCount = claim.evidence_refs?.length ?? 0
  if (claim.label === "OBSERVED" && evidenceCount === 0) return true
  if (claim.label === "CALCULATED" && evidenceCount === 0) return true
  return false
}

/**
 * Arbitrate a single conflict. Mechanical resolution is allowed ONLY when the
 * winner is strictly better on label rank AND carries at least one evidence
 * ref while losers carry none. Anything else escalates to human/cross-review —
 * the router must not fabricate agreement.
 */
export function arbitrate(conflict: Conflict): ArbitrationVerdict {
  const { claims } = conflict
  if (claims.length < 2) {
    return { type: "escalate", reason: "fewer than two claims — nothing to arbitrate", claims }
  }

  if (conflict.kind === "unit_mismatch") {
    return {
      type: "escalate",
      reason: "单位冲突不能由 Router 机械仲裁,必须跨审查确认换算关系",
      claims,
    }
  }

  const inflated = claims.filter(detectLabelInflation)
  const candidates = claims.filter((c) => !detectLabelInflation(c))
  if (candidates.length === 0) {
    return { type: "escalate", reason: "所有陈述的标签均缺乏证据支撑(标签膨胀)", claims }
  }

  const ranked = [...candidates].sort((a, b) => LABEL_RANK[b.label] - LABEL_RANK[a.label])
  const top = ranked[0]
  if (!top) return { type: "escalate", reason: "无可仲裁陈述", claims }
  const tied = ranked.filter((c) => LABEL_RANK[c.label] === LABEL_RANK[top.label])
  if (tied.length > 1) {
    return {
      type: "escalate",
      reason: `多个陈述同为最高认识论等级(${top.label})且无进一步机械判据`,
      claims,
    }
  }
  const loserHasEvidence = ranked.slice(1).some((c) => (c.evidence_refs?.length ?? 0) > 0)
  if (loserHasEvidence || (top.evidence_refs?.length ?? 0) === 0) {
    return {
      type: "escalate",
      reason: "高标签陈述与有证据支撑的低标签陈述冲突,需跨审查而非机械取舍",
      claims,
    }
  }

  return {
    type: "resolved",
    winner: top,
    rationale: `${top.source} 的陈述标签(${top.label})高于对手且附证据引用;落选陈述已保留备查${inflated.length > 0 ? `;另有 ${inflated.length} 条标签膨胀被剔除` : ""}`,
    losers: ranked.slice(1).concat(inflated.filter((c) => !ranked.slice(1).includes(c))),
  }
}

/** Group upstream outputs into conflicts by identical subject with differing values. */
export function detectConflicts(
  outputs: { skill: string; subject: string; value: string; label: EpistemicLabel; evidence_refs?: string[]; unit?: string }[],
): Conflict[] {
  const bySubject = new Map<string, typeof outputs>()
  for (const o of outputs) {
    const list = bySubject.get(o.subject) ?? []
    list.push(o)
    bySubject.set(o.subject, list)
  }
  const conflicts: Conflict[] = []
  for (const [subject, group] of bySubject) {
    const values = new Set(group.map((g) => g.value))
    if (values.size <= 1) continue
    const units = new Set(group.map((g) => g.unit).filter((u) => u !== undefined))
    const kind: ConflictKind = units.size > 1 ? "unit_mismatch" : "value_mismatch"
    conflicts.push({
      kind,
      subject,
      claims: group.map((g) => ({ source: g.skill, statement: g.value, label: g.label, evidence_refs: g.evidence_refs })),
    })
  }
  return conflicts
}
