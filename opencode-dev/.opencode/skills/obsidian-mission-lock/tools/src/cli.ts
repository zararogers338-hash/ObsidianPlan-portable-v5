#!/usr/bin/env bun
/**
 * obsidian-mission-lock CLI — machine entrypoint for the Obsidian controller.
 *
 * Reads a SkillInput JSON envelope from stdin (or --input file), runs the
 * deterministic part of the mission-lock pipeline, and writes a SkillOutput
 * JSON envelope to stdout. Exit codes:
 *   0 — status SUCCESS / PARTIAL
 *   2 — status BLOCKED (missing critical input, unresolved hard conflict, approval gate)
 *   3 — status FAILED (input unreadable / corrupted / schema-broken)
 *
 * The LLM layer (SKILL.md) performs semantic decomposition and judgement;
 * this CLI performs everything that is programmatically checkable. The two
 * compose: the skill calls this CLI to validate/lock its drafted contract.
 *
 * Subcommands:
 *   lock      — full pipeline: validate input, check units, detect conflicts
 *               & missing fields, validate contract (if provided), emit output
 *   validate  — validate a contract JSON against the contract schema only
 *   diff      — diff two contract JSON files (goal-drift detection)
 *   units     — unit/scale check on a contract JSON
 *
 * All modes are offline and deterministic. No network, no LLM calls.
 */

import { detectAllConflicts } from "./conflicts"
import { diffContracts } from "./diff"
import { MissionLockError, type ErrorCode } from "./errors"
import { detectMissingFields } from "./missing"
import type { MissionContract, SkillInput, SkillOutput, Status } from "./types"
import { checkContractUnits } from "./units"
import { isVersionCompatible, validateContract } from "./validate"

const SKILL_NAME = "obsidian-mission-lock"
const SKILL_VERSION = "1.0.0"
const CONTRACT_VERSION = "1.0.0"
/** Registered cross-major migrations ("from->to"). Empty at 1.x. */
const MIGRATIONS: string[] = []

interface ToolCall {
  tool: string
  ok: boolean
  note?: string
}

function makeOutput(partial: Partial<SkillOutput> & { status: Status; summary: string }): SkillOutput {
  return {
    findings: [],
    assumptions: [],
    evidence_used: [],
    uncertainty: { level: "medium", notes: "" },
    risks: [],
    artifacts: [],
    requested_next_skills: [],
    validation: { schema_passed: false, self_check_passed: false, tool_calls: [] },
    provenance: {
      skill: SKILL_NAME,
      skill_version: SKILL_VERSION,
      contract_version: CONTRACT_VERSION,
      timestamp: new Date().toISOString(),
      tools_used: [],
    },
    errors: [],
    ...partial,
  }
}

function errJSON(e: unknown): { code: string; message: string; retryable: boolean; details?: Record<string, unknown> } {
  if (e instanceof MissionLockError) return e.toJSON()
  return { code: "OML-E1009", message: e instanceof Error ? e.message : String(e), retryable: false }
}

async function readStdin(): Promise<string> {
  const chunks: Buffer[] = []
  for await (const chunk of process.stdin) chunks.push(chunk as Buffer)
  return Buffer.concat(chunks).toString("utf8")
}

async function readJsonSource(flagValue: string | undefined): Promise<unknown> {
  const raw = flagValue !== undefined ? await Bun.file(flagValue).text() : await readStdin()
  if (!raw.trim()) {
    throw new MissionLockError("OML-E1009", "empty input: expected a JSON envelope on stdin or via --input <file>")
  }
  try {
    return JSON.parse(raw)
  } catch (e) {
    throw new MissionLockError("OML-E1009", `input is not valid JSON: ${e instanceof Error ? e.message : String(e)}`)
  }
}

function parseArgs(argv: string[]): { cmd: string; flags: Record<string, string> } {
  const [cmd = "lock", ...rest] = argv
  const flags: Record<string, string> = {}
  for (let i = 0; i < rest.length; i += 2) {
    const key = rest[i].replace(/^--/, "")
    flags[key] = rest[i + 1]
  }
  return { cmd, flags }
}

function validateInputEnvelope(raw: unknown): SkillInput {
  if (typeof raw !== "object" || raw === null) {
    throw new MissionLockError("OML-E1001", "input envelope must be a JSON object")
  }
  const r = raw as Record<string, unknown>
  const problems: string[] = []
  if (typeof r.task_id !== "string" || !r.task_id) problems.push("task_id: required non-empty string")
  if (typeof r.project_id !== "string" || !r.project_id) problems.push("project_id: required non-empty string")
  if (typeof r.request !== "string" || !r.request.trim()) problems.push("request: required non-empty string")
  if (typeof r.skill_version !== "string" || !r.skill_version) problems.push("skill_version: required")
  if (typeof r.timestamp !== "string" || Number.isNaN(Date.parse(r.timestamp))) {
    problems.push("timestamp: required ISO-8601 string")
  }
  if (problems.length > 0) {
    throw new MissionLockError("OML-E1001", "input envelope failed validation", { problems })
  }
  return raw as SkillInput
}

/** Extract a draft contract from the input envelope. The LLM layer passes its
 *  drafted contract back in context.draft_contract for programmatic checking. */
function extractDraftContract(input: SkillInput): MissionContract | undefined {
  const draft = input.context?.draft_contract
  if (draft === undefined || draft === null) return undefined
  return draft as MissionContract
}

function cmdLock(raw: unknown): { output: SkillOutput; exit: number } {
  const tool_calls: ToolCall[] = []
  const tools_used: string[] = []
  let input: SkillInput
  try {
    input = validateInputEnvelope(raw)
    tool_calls.push({ tool: "input-schema-validator", ok: true })
  } catch (e) {
    tool_calls.push({ tool: "input-schema-validator", ok: false, note: e instanceof Error ? e.message : String(e) })
    const output = makeOutput({
      status: "FAILED",
      summary: "Input envelope rejected — not processable.",
      errors: [errJSON(e)],
    })
    output.validation.tool_calls = tool_calls
    output.provenance.tools_used = ["input-schema-validator"]
    return { output, exit: 3 }
  }
  tools_used.push("input-schema-validator")

  // Version compatibility between caller-declared skill_version and this build
  if (!isVersionCompatible(input.skill_version, SKILL_VERSION, MIGRATIONS)) {
    const e = new MissionLockError("OML-E1010", `caller expects skill_version ${input.skill_version}, this build is ${SKILL_VERSION}, no migration registered`)
    const output = makeOutput({ status: "FAILED", summary: e.message, errors: [errJSON(e)] })
    output.validation.tool_calls = tool_calls
    return { output, exit: 3 }
  }

  const draft = extractDraftContract(input)

  // 1. missing-field detection (always runs — even with no draft yet)
  const missing = detectMissingFields(input, draft)
  tools_used.push("missing-field-detector")
  tool_calls.push({ tool: "missing-field-detector", ok: true, note: `${missing.length} gap(s), ${missing.filter((m) => m.blocking).length} blocking` })

  // 2. conflict detection (needs whatever structure exists; works on raw constraints too)
  const constraints = (input.constraints ?? {}) as Record<string, unknown>
  const conflicts = detectAllConflicts({
    metrics: draft?.metrics ?? [],
    constraints,
    domain_tags: draft?.domain_tags ?? [],
    risks: draft?.risks ?? [],
    statements: draft?.statements ?? [],
  })
  tools_used.push("conflict-detector")
  tool_calls.push({ tool: "conflict-detector", ok: true, note: `${conflicts.length} conflict(s), ${conflicts.filter((c) => c.severity === "hard").length} hard` })

  // 3. unit / scale check (only meaningful with a draft)
  let unitIssues: ReturnType<typeof checkContractUnits> = []
  if (draft) {
    unitIssues = checkContractUnits(draft)
    tools_used.push("unit-checker")
    tool_calls.push({ tool: "unit-checker", ok: true, note: `${unitIssues.filter((u) => u.severity === "error").length} error(s), ${unitIssues.filter((u) => u.severity === "warning").length} warning(s)` })
  }

  // 4. contract schema validation (only with a draft)
  let schema_ok = false
  let schemaIssues: { path: string; message: string }[] = []
  if (draft) {
    const v = validateContract(draft)
    schema_ok = v.ok
    schemaIssues = v.issues
    tools_used.push("contract-validator")
    tool_calls.push({ tool: "contract-validator", ok: v.ok, note: v.ok ? "contract valid" : `${v.issues.length} issue(s)` })
  }

  // 5. approval gate
  const needsApproval = input.risk_level === "high" || input.risk_level === "critical"
  const approvalMissing = needsApproval && input.human_approval_state !== "approved"

  // --- decide status ---
  const blockingMissing = missing.filter((m) => m.blocking)
  const hardConflicts = conflicts.filter((c) => c.severity === "hard")
  const unitErrors = unitIssues.filter((u) => u.severity === "error")

  let status: Status
  let summary: string
  const errors: SkillOutput["errors"] = []

  if (approvalMissing) {
    status = "HUMAN_APPROVAL_REQUIRED"
    summary = `Risk level ${input.risk_level} requires human approval before the contract can be locked; human_approval_state="${input.human_approval_state ?? "unset"}".`
    errors.push(errJSON(new MissionLockError("OML-E1007", summary)))
  } else if (draft && !schema_ok) {
    status = "FAILED"
    summary = `Draft contract failed schema validation with ${schemaIssues.length} issue(s).`
    errors.push(errJSON(new MissionLockError("OML-E1001", summary, { issues: schemaIssues })))
  } else if (unitErrors.length > 0) {
    status = "BLOCKED"
    summary = `${unitErrors.length} unit/scale error(s) must be fixed before lock: ${unitErrors[0].message}`
    errors.push(errJSON(new MissionLockError("OML-E1003", summary, { issues: unitErrors })))
  } else if (hardConflicts.length > 0) {
    status = "BLOCKED"
    summary = `${hardConflicts.length} hard conflict(s) detected — no silent resolution permitted. Human decision required on: ${hardConflicts.map((c) => c.between.join(" vs ")).join("; ")}.`
  } else if (blockingMissing.length > 0) {
    status = "BLOCKED"
    summary = `${blockingMissing.length} blocking input(s) missing: ${blockingMissing.map((m) => m.field).join(", ")}.`
  } else if (draft) {
    status = missing.length > 0 || conflicts.length > 0 ? "PARTIAL" : "SUCCESS"
    summary =
      status === "SUCCESS"
        ? `Contract "${draft.title}" passed all programmatic checks and is ready for lock.`
        : `Contract structurally valid; ${missing.length} non-blocking gap(s) and ${conflicts.length} soft conflict(s) recorded.`
  } else {
    // No draft yet: report what the LLM layer must supply
    status = missing.some((m) => m.blocking) ? "BLOCKED" : "PARTIAL"
    summary = `No draft contract supplied (context.draft_contract). Programmatic pre-check: ${missing.length} gap(s), ${conflicts.length} conflict(s). Supply a draft for full validation.`
  }

  const self_check_passed = schema_ok || !draft

  const output = makeOutput({
    status,
    summary,
    contract: draft,
    conflict_matrix: conflicts.length > 0 ? conflicts : undefined,
    missing_inputs: missing.length > 0 ? missing : undefined,
    errors,
  })
  output.validation = {
    schema_passed: schema_ok,
    self_check_passed,
    tool_calls,
  }
  output.provenance.tools_used = tools_used
  output.evidence_used = (input.evidence_refs ?? []).slice()
  if (unitIssues.length > 0) {
    output.findings.push(
      ...unitIssues.map((u) => ({
        text: `[${u.severity}] ${u.where}: ${u.message}`,
        label: "CALCULATED" as const,
        source: "unit-checker",
      })),
    )
  }
  return { output, exit: status === "SUCCESS" || status === "PARTIAL" ? 0 : status === "FAILED" ? 3 : 2 }
}

async function main(): Promise<void> {
  const { cmd, flags } = parseArgs(process.argv.slice(2))

  try {
    if (cmd === "lock") {
      const raw = await readJsonSource(flags.input)
      const { output, exit } = cmdLock(raw)
      process.stdout.write(JSON.stringify(output, null, 2) + "\n")
      process.exit(exit)
    }
    if (cmd === "validate") {
      const raw = await readJsonSource(flags.input)
      const v = validateContract(raw)
      const unitIssues = v.ok ? checkContractUnits(raw as MissionContract) : []
      process.stdout.write(
        JSON.stringify(
          {
            ok: v.ok,
            schema_issues: v.issues,
            unit_issues: unitIssues,
            provenance: { skill: SKILL_NAME, skill_version: SKILL_VERSION, contract_version: CONTRACT_VERSION },
          },
          null,
          2,
        ) + "\n",
      )
      process.exit(v.ok && unitIssues.every((u) => u.severity !== "error") ? 0 : 3)
    }

    if (cmd === "diff") {
      if (!flags.before || !flags.after) {
        throw new MissionLockError("OML-E1001", "diff requires --before <file> and --after <file>")
      }
      const before = JSON.parse(await Bun.file(flags.before).text()) as MissionContract
      const after = JSON.parse(await Bun.file(flags.after).text()) as MissionContract
      const d = diffContracts(before, after)
      process.stdout.write(JSON.stringify(d, null, 2) + "\n")
      process.exit(d.drift_alerts.some((a) => a.severity === "critical") ? 2 : 0)
    }

    if (cmd === "units") {
      const raw = (await readJsonSource(flags.input)) as MissionContract
      const issues = checkContractUnits(raw)
      process.stdout.write(JSON.stringify({ issues }, null, 2) + "\n")
      process.exit(issues.some((i) => i.severity === "error") ? 3 : 0)
    }

    throw new MissionLockError("OML-E1001", `unknown subcommand "${cmd}"; expected lock|validate|diff|units`)
  } catch (e) {
    const output = makeOutput({
      status: "FAILED",
      summary: e instanceof Error ? e.message : String(e),
      errors: [errJSON(e)],
    })
    process.stdout.write(JSON.stringify(output, null, 2) + "\n")
    process.exit(3)
  }
}

export { cmdLock }

if (import.meta.main) {
  await main()
}
