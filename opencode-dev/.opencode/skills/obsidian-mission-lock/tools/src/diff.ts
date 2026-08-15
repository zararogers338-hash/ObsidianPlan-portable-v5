/**
 * Contract version differ.
 *
 * Compares two mission contracts and reports semantic changes, with
 * special attention to GOAL DRIFT / objective substitution: if the
 * primary objective or success criteria change without the task_id
 * changing, that is flagged as a drift alert, not a routine edit.
 *
 * Output is machine-readable so the controller can enforce approval
 * gates on contract mutation.
 */

import type { MissionContract, Metric } from "./types"
import { requiredBump } from "./validate"

export type ChangeKind = "added" | "removed" | "modified"

export interface FieldChange {
  path: string
  kind: ChangeKind
  before?: unknown
  after?: unknown
}

export interface DriftAlert {
  severity: "critical" | "warning"
  kind:
    | "primary-objective-changed"
    | "success-criteria-weakened"
    | "failure-threshold-loosened"
    | "exclusion-removed"
    | "metric-target-raised"
    | "metric-target-lowered"
    | "approval-gate-removed"
    | "task-id-changed"
  message: string
}

export interface ContractDiff {
  same_task: boolean
  version_bump: "major" | "minor" | "patch" | "none" | "invalid"
  changes: FieldChange[]
  drift_alerts: DriftAlert[]
  summary: string
}

function metricByName(list: Metric[]): Map<string, Metric> {
  return new Map(list.map((m) => [m.name, m]))
}

function diffStringSet(before: string[], after: string[], path: string, changes: FieldChange[]): void {
  const b = new Set(before)
  const a = new Set(after)
  for (const x of a) if (!b.has(x)) changes.push({ path, kind: "added", after: x })
  for (const x of b) if (!a.has(x)) changes.push({ path, kind: "removed", before: x })
}

function objectiveText(c: MissionContract, id: string): string | undefined {
  return c.objectives.find((o) => o.id === id)?.statement
}

/** Loose comparison: did a numeric target move, and in which direction? */
function targetDirection(before?: { value: number; unit: string }, after?: { value: number; unit: string }): "raised" | "lowered" | "same" | "incomparable" {
  if (!before || !after) return "incomparable"
  if (before.unit !== after.unit) return "incomparable" // unit change is a change, but direction needs conversion; keep conservative
  if (after.value > before.value) return "raised"
  if (after.value < before.value) return "lowered"
  return "same"
}

export function diffContracts(before: MissionContract, after: MissionContract): ContractDiff {
  const changes: FieldChange[] = []
  const drift_alerts: DriftAlert[] = []

  const same_task = before.task_id === after.task_id
  if (!same_task) {
    drift_alerts.push({
      severity: "critical",
      kind: "task-id-changed",
      message: `task_id changed (${before.task_id} → ${after.task_id}): this is a NEW mission, not a revision; do not treat as a version bump`,
    })
  }

  const bump = requiredBump(before.contract_version, after.contract_version)

  // --- primary objective substitution = goal drift ---
  if (before.primary_objective_id !== after.primary_objective_id) {
    changes.push({
      path: "$.primary_objective_id",
      kind: "modified",
      before: before.primary_objective_id,
      after: after.primary_objective_id,
    })
    drift_alerts.push({
      severity: "critical",
      kind: "primary-objective-changed",
      message: `Primary objective switched from [${before.primary_objective_id}] "${objectiveText(before, before.primary_objective_id) ?? "?"}" to [${after.primary_objective_id}] "${objectiveText(after, after.primary_objective_id) ?? "?"}" — possible objective substitution; requires human approval`,
    })
  } else {
    const bTxt = objectiveText(before, before.primary_objective_id)
    const aTxt = objectiveText(after, after.primary_objective_id)
    if (bTxt !== undefined && aTxt !== undefined && bTxt !== aTxt) {
      changes.push({ path: `$.objectives[${before.primary_objective_id}].statement`, kind: "modified", before: bTxt, after: aTxt })
      drift_alerts.push({
        severity: "warning",
        kind: "primary-objective-changed",
        message: `Primary objective wording changed in place: "${bTxt}" → "${aTxt}" — verify this is clarification, not quiet re-scoping`,
      })
    }
  }

  // --- success criteria / failure thresholds / exclusions / gates ---
  const bSuccess = new Set(before.success_criteria)
  const aSuccess = new Set(after.success_criteria)
  diffStringSet(before.success_criteria, after.success_criteria, "$.success_criteria", changes)
  for (const removed of before.success_criteria.filter((x) => !aSuccess.has(x))) {
    drift_alerts.push({ severity: "critical", kind: "success-criteria-weakened", message: `Success criterion removed: "${removed}"` })
  }
  const addedSuccess = after.success_criteria.filter((x) => !bSuccess.has(x))
  void addedSuccess

  diffStringSet(before.failure_thresholds, after.failure_thresholds, "$.failure_thresholds", changes)
  const aFail = new Set(after.failure_thresholds)
  for (const removed of before.failure_thresholds.filter((x) => !aFail.has(x))) {
    drift_alerts.push({ severity: "critical", kind: "failure-threshold-loosened", message: `Failure threshold removed: "${removed}" — the mission can now run longer without aborting` })
  }

  diffStringSet(before.explicit_exclusions, after.explicit_exclusions, "$.explicit_exclusions", changes)
  const aExcl = new Set(after.explicit_exclusions)
  for (const removed of before.explicit_exclusions.filter((x) => !aExcl.has(x))) {
    drift_alerts.push({ severity: "critical", kind: "exclusion-removed", message: `Explicit exclusion removed: "${removed}" — scope boundary moved outward` })
  }

  diffStringSet(before.human_approval_gates, after.human_approval_gates, "$.human_approval_gates", changes)
  const aGates = new Set(after.human_approval_gates)
  for (const removed of before.human_approval_gates.filter((x) => !aGates.has(x))) {
    drift_alerts.push({ severity: "critical", kind: "approval-gate-removed", message: `Human approval gate removed: "${removed}"` })
  }

  // --- metrics ---
  const bm = metricByName(before.metrics)
  const am = metricByName(after.metrics)
  for (const [name, b] of bm) {
    const a = am.get(name)
    if (!a) {
      changes.push({ path: `$.metrics[${name}]`, kind: "removed", before: b })
      continue
    }
    const dir = targetDirection(b.target, a.target)
    if (dir === "raised" || dir === "lowered") {
      changes.push({ path: `$.metrics[${name}].target`, kind: "modified", before: b.target, after: a.target })
      const isMaximize = a.direction === "maximize"
      // For a maximize metric, lowering the target weakens the mission; for minimize, raising it does.
      const weakening = (isMaximize && dir === "lowered") || (!isMaximize && a.direction === "minimize" && dir === "raised")
      if (weakening) {
        drift_alerts.push({
          severity: "warning",
          kind: dir === "raised" ? "metric-target-raised" : "metric-target-lowered",
          message: `Metric "${name}" target moved ${dir} (${b.target!.value} → ${a.target!.value} ${a.target!.unit}) in the direction that WEAKENS the mission — verify intent`,
        })
      }
    }
  }
  for (const [name, a] of am) {
    if (!bm.has(name)) changes.push({ path: `$.metrics[${name}]`, kind: "added", after: a })
  }

  // --- secondary objectives & stop conditions (reported, not alerted) ---
  diffStringSet(before.secondary_objective_ids, after.secondary_objective_ids, "$.secondary_objective_ids", changes)
  diffStringSet(before.stop_conditions, after.stop_conditions, "$.stop_conditions", changes)

  const crit = drift_alerts.filter((d) => d.severity === "critical").length
  const warn = drift_alerts.filter((d) => d.severity === "warning").length
  const summary =
    `${changes.length} field change(s), ${crit} critical + ${warn} warning drift alert(s). ` +
    (crit > 0
      ? "CRITICAL alerts present — contract revision must NOT be released without human re-approval."
      : warn > 0
        ? "Warnings present — review recommended before release."
        : "No drift alerts; revision is routine.")

  return { same_task, version_bump: bump, changes, drift_alerts, summary }
}
