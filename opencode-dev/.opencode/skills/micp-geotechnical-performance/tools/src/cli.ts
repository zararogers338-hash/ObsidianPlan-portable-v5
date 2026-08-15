#!/usr/bin/env bun
// cli.ts — top-level CLI for the micp-geotechnical-performance tool suite.
//
// Subcommands (all offline-capable, deterministic):
//   parse --input <samples.json>            parse+validate raw samples (stdin default)
//   metrics --input <samples.json>          extract stress-strain indicators
//   stats --input <samples.json>            sample statistics + spatial uniformity
//   durability --input <samples.json>       durability cycle decay fitting
//   effect --input <effect.json>            effect size + safety margin
//   evaluate [--input <envelope.json>]      full pipeline: schema -> tools -> self-check
//   check-self <json-file>                  validate a JSON file against output.schema.json
//
// Exit codes: 0 success, 2 BLOCKED/HUMAN_APPROVAL_REQUIRED, 3 FAILED,
//             4 internal self-check failure.

import { promises as fs } from "node:fs"
import path from "node:path"
import { parseSamples, type NormalizedSample } from "./parse"
import { extractIndicators, checkSpecimenConditions } from "./metrics"
import { sampleStats, spatialUniformity } from "./stats"
import { fitDecay } from "./durability"
import { effectSize, safetyMargin } from "./effect"
import { strengthToKpa } from "./units"
import { makeError, type MgeError } from "./errors"

const HERE = path.resolve(__dirname, "..", "..")

/** Read a JSON input either from --input file or stdin. */
async function readJSON(args: string[]): Promise<unknown> {
  const idx = args.indexOf("--input")
  if (idx >= 0) {
    const file = args[idx + 1]
    if (!file) throw new Error("--input requires a file path")
    return JSON.parse(await fs.readFile(path.resolve(file), "utf8"))
  }
  const text = await new Promise<string>((resolve, reject) => {
    const chunks: Buffer[] = []
    process.stdin.on("data", (c: Buffer) => chunks.push(c))
    process.stdin.on("end", () => resolve(Buffer.concat(chunks).toString("utf8")))
    process.stdin.on("error", reject)
  })
  if (text.trim() === "") return {}
  return JSON.parse(text)
}

function writeJSON(v: unknown): void {
  process.stdout.write(JSON.stringify(v, null, 2) + "\n")
}

async function cmdParse(args: string[]): Promise<number> {
  const raw = await readJSON(args)
  const result = parseSamples((raw as Record<string, unknown>).samples ?? raw)
  const code = result.errors.some((e) => e.code === "MGE-E202") ? 3 : result.errors.length > 0 ? 2 : 0
  writeJSON({ samples: result.samples.map((s) => ({ specimen_id: s.specimen_id, issues: s.issues, usable: s.usable })), errors: result.errors, warnings: result.warnings })
  return code
}

async function cmdMetrics(args: string[]): Promise<number> {
  const raw = await readJSON(args)
  const { samples, errors } = parseSamples((raw as Record<string, unknown>).samples ?? raw)
  const out: Record<string, unknown>[] = []
  for (const s of samples) {
    const entry: Record<string, unknown> = { specimen_id: s.specimen_id, test_type: s.test_type }
    if (s.data_points && s.data_points.length > 0) {
      try {
        const ind = extractIndicators(s.data_points)
        entry.indicators = {
          ucs_kpa: Number(ind.ucs_kpa.toFixed(3)),
          peak_strength_kpa: Number(ind.peak_strength_kpa.toFixed(3)),
          residual_strength_kpa: Number(ind.residual_strength_kpa.toFixed(3)),
          peak_strain_percent: Number((ind.peak_strain_fraction * 100).toFixed(4)),
          e0_kpa: Number(ind.e0_kpa.toFixed(3)),
          e50_kpa: Number(ind.e50_kpa.toFixed(3)),
          brittleness_index: Number(ind.brittleness_index.toFixed(4)),
          n_points: ind.n_points,
        }
      } catch (err) {
        entry.error = err instanceof Error ? { message: err.message } : { message: String(err) }
      }
    } else {
      entry.note = "no data_points; indicators not computed"
    }
    entry.condition_issues = checkSpecimenConditions(s)
    out.push(entry)
  }
  writeJSON({ samples: out, errors })
  return errors.length > 0 ? 2 : 0
}

async function cmdStats(args: string[]): Promise<number> {
  const raw = await readJSON(args)
  const { samples, errors } = parseSamples((raw as Record<string, unknown>).samples ?? raw)

  // Use the first group with curve data for a strength summary; collect per-group values.
  const strengths: Record<string, { id: string; value: number }[]> = {}
  for (const s of samples) {
    const group = s.group ?? "all"
    let valueKpa: number | undefined
    if (s.data_points && s.data_points.length > 0) {
      try {
        const ind = extractIndicators(s.data_points, { error: undefined as never })
        valueKpa = ind.ucs_kpa
      } catch {
        valueKpa = undefined
      }
    }
    if (valueKpa !== undefined) {
      ;(strengths[group] ??= []).push({ id: s.specimen_id, value: valueKpa })
    }
  }

  const perGroup = Object.fromEntries(
    Object.entries(strengths).map(([g, pairs]) => {
      const st = sampleStats(pairs)
      return [
        g,
        {
          n: st.n,
          mean_kpa: st.mean,
          median_kpa: st.median,
          stddev_kpa: st.stddev,
          cv: st.cv,
          ci95_kpa: st.ci95,
          outliers: st.outliers,
          reliability: st.reliability,
        },
      ]
    }),
  )

  // Spatial uniformity: first sample that has layer data.
  const layerSample = samples.find((s) => s.layer_data_norm && s.layer_data_norm.length > 0)
  let uniformity: unknown = null
  if (layerSample && layerSample.layer_data_norm) {
    uniformity = spatialUniformity(layerSample.layer_data_norm.map((l) => ({ position: l.position_mm, value: l.value })))
  }

  writeJSON({ groups: perGroup, spatial_uniformity: uniformity, errors, warnings: [] })
  return errors.length > 0 ? 2 : 0
}

async function cmdDurability(args: string[]): Promise<number> {
  const raw = await readJSON(args)
  const { samples, errors } = parseSamples((raw as Record<string, unknown>).samples ?? raw)
  const fits = samples
    .filter((s) => s.durability_cycles_norm && s.durability_cycles_norm.length >= 2)
    .map((s) => {
      const fit = fitDecay(s.durability_cycles_norm!.map((c) => ({ cycle_count: c.cycle_count, strength_kpa: c.strength_kpa })))
      return { specimen_id: s.specimen_id, cycle_type: s.durability_cycles_norm![0]?.cycle_type ?? "other", fit }
    })
  writeJSON({ fits, errors, skipped: samples.filter((s) => !(s.durability_cycles_norm && s.durability_cycles_norm.length >= 2)).map((s) => s.specimen_id) })
  return errors.length > 0 ? 2 : 0
}

async function cmdEffect(args: string[]): Promise<number> {
  const raw = await readJSON(args)
  const input = raw as { a?: number[]; b?: number[]; observed?: number; target?: number; higher_is_better?: boolean; stddev?: number; n?: number; alpha?: number; unit?: string }
  if (!input.a || !input.b) {
    writeJSON({ error: makeError("MGE-E202", "effect requires groups a[] and b[]", { field: "a/b" }) })
    return 3
  }
  const ef = effectSize({ a: input.a, b: input.b, alpha: input.alpha })
  let margin: unknown = null
  if (input.observed !== undefined && input.target !== undefined) {
    margin = safetyMargin({
      observed: input.observed,
      target: input.target,
      higher_is_better: input.higher_is_better ?? true,
      stddev: input.stddev,
      n: input.n,
    })
  }
  writeJSON({ effect: ef, safety_margin: margin, unit: input.unit ?? "kPa" })
  return 0
}

async function cmdCheckSelf(args: string[]): Promise<number> {
  const file = args[0]
  if (!file) {
    process.stderr.write("check-self requires a JSON file path\n")
    return 1
  }
  const schema = JSON.parse(await fs.readFile(path.join(HERE, "schemas", "output.schema.json"), "utf8")) as Record<string, unknown>
  const value = JSON.parse(await fs.readFile(path.resolve(file), "utf8"))
  const { validate } = await import("./jsonschema")
  const issues = validate(value, schema)
  if (issues.length > 0) {
    for (const issue of issues) process.stderr.write(`${issue.path}: ${issue.message}\n`)
    return 1
  }
  process.stdout.write("output schema: OK\n")
  return 0
}

// Full pipeline: `evaluate` runs parse -> metrics -> stats -> durability ->
// effect -> self-check and emits the machine-readable envelope.
async function cmdEvaluate(args: string[]): Promise<number> {
  const raw = await readJSON(args)
  const envelope = (raw ?? {}) as Record<string, unknown>

  // 1. Input schema validation
  const schema = JSON.parse(await fs.readFile(path.join(HERE, "schemas", "input.schema.json"), "utf8")) as Record<string, unknown>
  const { validate } = await import("./jsonschema")
  const inIssues = validate(envelope, schema)
  if (inIssues.length > 0) {
    const details: Record<string, unknown> = { field_guidance: fieldGuidance() }
    const errors: MgeError[] = [makeError("MGE-E101", `input schema invalid: ${inIssues.length} issue(s)`, details)]
    return emitEnvelope({
      status: "FAILED",
      summary: "input failed schemas/input.schema.json validation",
      errors,
      toolCalls: [],
      checks: [{ name: "input_schema", passed: false, detail: inIssues.map((i) => `${i.path}: ${i.message}`).join("; ") }],
      provenance: { skill_version: String(envelope.skill_version ?? "1.0.0"), controller_version: String(envelope.controller_version ?? "unknown"), data_refs_hash: hashRefs(envelope.data_refs), timestamp: String(envelope.timestamp ?? new Date().toISOString()) },
    })
  }

  const toolCalls: { tool: string; subcommand: string; status: string; detail: string }[] = []
  const checks: { name: string; passed: boolean; detail: string }[] = []
  const errors: MgeError[] = []

  // 2a. Approval gate (MGE-E701): field deployment, live bio-experiments,
  // hazardous-chemical handling, long-term knowledge writes require approval.
  const risk = String(envelope.risk_level ?? "medium")
  const approval = String(envelope.human_approval_state ?? "not_required")
  const isFieldOrHazard = /现场|field|deploy|inject|注入|hazard|危险|chemical|生物实验|live/.test(String(envelope.request ?? ""))
  if (isFieldOrHazard && approval !== "approved") {
    errors.push(makeError("MGE-E701", "field deployment / hazardous / live-bio request requires human approval (human_approval_state=approved)", { field: "human_approval_state" }))
    checks.push({ name: "approval_gate", passed: false, detail: `risk=${risk} approval=${approval}` })
    const out = buildEnvelope({
      status: "HUMAN_APPROVAL_REQUIRED",
      summary: "approval gate not satisfied; no evaluation performed",
      errors,
      toolCalls,
      checks,
      provenance: {
        skill_version: String(envelope.skill_version ?? "1.0.0"),
        controller_version: String(envelope.controller_version ?? "unknown"),
        data_refs_hash: hashRefs(envelope.data_refs),
        timestamp: String(envelope.timestamp ?? new Date().toISOString()),
      },
    })
    writeJSON(out)
    return 2
  }
  checks.push({ name: "approval_gate", passed: true, detail: `risk=${risk} approval=${approval}` })

  // 2. Parse
  const parsed = parseSamples(envelope.samples ?? [])
  toolCalls.push({ tool: "cli.ts", subcommand: "parse", status: parsed.errors.length === 0 ? "ok" : "warn", detail: `${parsed.samples.length} samples` })
  checks.push({ name: "parse", passed: parsed.errors.length === 0, detail: `${parsed.samples.length} samples, ${parsed.errors.length} errors` })
  if (parsed.samples.length === 0) {
    errors.push(makeError("MGE-E202", "no usable samples provided", { field: "samples" }))
    return emitEnvelope({
      status: "BLOCKED",
      summary: "no usable samples; strength/permeability/durability evaluation impossible",
      errors,
      toolCalls,
      checks,
      provenance: { skill_version: "1.0.0", controller_version: "unknown", data_refs_hash: "", timestamp: new Date().toISOString() },
    })
  }

  // Hard parse errors (unit conflicts, corrupted numeric fields) block the
  // evaluation: the numbers cannot be trusted. Non-blocking issues (missing
  // optional fields) are carried as warnings.
  const hardParseErrors = parsed.errors.filter((e) => e.code === "MGE-E203" || e.code === "MGE-E302" || e.code === "MGE-E305")
  if (hardParseErrors.length > 0) {
    errors.push(...hardParseErrors)
    return emitEnvelope({
      status: "BLOCKED",
      summary: `parse errors prevent a trustworthy evaluation (${hardParseErrors.length} hard error(s))`,
      errors,
      toolCalls,
      checks,
      provenance: { skill_version: "1.0.0", controller_version: "unknown", data_refs_hash: "", timestamp: new Date().toISOString() },
    })
  }

  // 3. Per-sample indicators + condition checks
  const samplesOut: Record<string, unknown>[] = []
  const usableWithCurve: NormalizedSample[] = []
  for (const s of parsed.samples) {
    const cond = checkSpecimenConditions(s)
    const entry: Record<string, unknown> = { specimen_id: s.specimen_id, test_type: s.test_type, conditions_checked: cond.length === 0 ? [] : cond, conditions_issues: cond }
    if (s.data_points && s.data_points.length > 0) {
      try {
        const ind = extractIndicators(s.data_points)
        entry.indicators = {
          ucs_kpa: Number(ind.ucs_kpa.toFixed(3)),
          peak_strain_percent: Number((ind.peak_strain_fraction * 100).toFixed(4)),
          e0_kpa: Number(ind.e0_kpa.toFixed(3)),
          e50_kpa: Number(ind.e50_kpa.toFixed(3)),
          brittleness_index: Number(ind.brittleness_index.toFixed(4)),
        }
        usableWithCurve.push(s)
      } catch (err) {
        entry.indicator_error = (err as Error).message
      }
    }
    if (s.permeability_ms !== undefined) entry.permeability_ms = s.permeability_ms
    if (s.caCO3_content !== undefined) entry.caCO3_content = s.caCO3_content
    samplesOut.push(entry)
  }
  toolCalls.push({ tool: "cli.ts", subcommand: "metrics", status: "ok", detail: `${usableWithCurve.length} curves` })
  checks.push({ name: "metrics", passed: usableWithCurve.length > 0 || parsed.samples.every((s) => s.test_type === "permeability"), detail: `${usableWithCurve.length} curves extracted` })

  // 3b. Cross-specimen comparability (acceptance criterion §9): specimens whose
  // size / density / stress path differ enough that a direct strength comparison
  // is misleading must be flagged, not silently compared.
  for (const issue of crossSpecimenIssues(parsed.samples)) {
    const entry = samplesOut.find((s) => s.specimen_id === issue.specimen_id)
    if (entry) {
      entry.conditions_issues = [...((entry.conditions_issues as string[]) ?? []), issue.message]
    }
  }

  // 4. Statistics
  const strengths: Record<string, { id: string; value: number }[]> = {}
  for (const s of usableWithCurve) {
    const ind = extractIndicators(s.data_points!)
    const group = s.group ?? "all"
    ;(strengths[group] ??= []).push({ id: s.specimen_id, value: ind.ucs_kpa })
  }
  const perGroup = Object.fromEntries(
    Object.entries(strengths).map(([g, pairs]) => {
      const st = sampleStats(pairs)
      return [g, { n: st.n, mean_kpa: st.mean, median_kpa: st.median, stddev_kpa: st.stddev, cv: st.cv, ci95_kpa: st.ci95, outliers: st.outliers, reliability: st.reliability }]
    }),
  )
  const layerSample = parsed.samples.find((s) => s.layer_data_norm && s.layer_data_norm.length > 0)
  const uniformity = layerSample && layerSample.layer_data_norm ? spatialUniformity(layerSample.layer_data_norm.map((l) => ({ position: l.position_mm, value: l.value }))) : null
  toolCalls.push({ tool: "cli.ts", subcommand: "stats", status: "ok", detail: `${Object.keys(perGroup).length} groups` })
  checks.push({ name: "stats", passed: true, detail: `${Object.keys(perGroup).length} groups, n=${Object.values(perGroup).reduce((s, g) => s + (g as { n: number }).n, 0)}` })

  // 5. Durability
  const durSamples = parsed.samples.filter((s) => s.durability_cycles_norm && s.durability_cycles_norm.length >= 2)
  const durFits: (ReturnType<typeof fitDecay> & { specimen_id: string; cycle_type: string; max_cycle_observed: number })[] = durSamples.map((s) => {
    const norm = s.durability_cycles_norm!
    const fit = fitDecay(norm.map((c) => ({ cycle_count: c.cycle_count, strength_kpa: c.strength_kpa })))
    const maxCycle = Math.max(...norm.map((c) => c.cycle_count))
    return { ...fit, specimen_id: s.specimen_id, cycle_type: norm[0]?.cycle_type ?? "other", max_cycle_observed: maxCycle }
  })
  if (durFits.length > 0) {
    toolCalls.push({ tool: "cli.ts", subcommand: "durability", status: "ok", detail: `${durFits.length} fits` })
    checks.push({ name: "durability", passed: true, detail: `${durFits.length} cycle fits` })
  }

  // 6. Effect (two-group comparison when groups exist)
  let effect: ReturnType<typeof effectSize> | null = null
  let margin: ReturnType<typeof safetyMargin> | null = null
  const groupKeys = Object.keys(strengths)
  if (groupKeys.length >= 2) {
    const ga = groupKeys[0]!
    const gb = groupKeys[1]!
    const a = strengths[ga]!.map((p) => p.value)
    const b = strengths[gb]!.map((p) => p.value)
    const ef = effectSize({ a, b, alpha: (envelope.constraints as { significance_level?: number } | undefined)?.significance_level ?? 0.05 })
    effect = ef
    const thresholds = (envelope.constraints as { engineering_thresholds?: Record<string, unknown> } | undefined)?.engineering_thresholds
    if (thresholds && typeof thresholds.target === "number") {
      margin = safetyMargin({ observed: ef.mean_a_kpa, target: thresholds.target, higher_is_better: true, stddev: ef.pooled_stddev_kpa, n: ef.n_a })
    }
    toolCalls.push({ tool: "cli.ts", subcommand: "effect", status: "ok", detail: `d=${ef.cohens_d.toFixed(2)} p=${ef.p_value?.toFixed(4) ?? "n/a"}` })
    checks.push({ name: "effect", passed: true, detail: `groups ${groupKeys[0]} vs ${groupKeys[1]}` })
  }

  // 7. Build the schema-shaped envelope once; self-check it; deliver the same object.
  const finalProvenance = {
    skill_version: String(envelope.skill_version ?? "1.0.0"),
    controller_version: String(envelope.controller_version ?? "unknown"),
    data_refs_hash: hashRefs(envelope.data_refs),
    timestamp: String(envelope.timestamp ?? new Date().toISOString()),
  }
  const built = buildEnvelope({
    status: "SUCCESS",
    summary: `evaluated ${parsed.samples.length} samples, ${Object.keys(perGroup).length} groups`,
    errors,
    toolCalls,
    checks,
    perGroup,
    uniformity,
    samplesOut,
    durFits,
    effect,
    margin,
    provenance: finalProvenance,
  })
  const outSchema = JSON.parse(await fs.readFile(path.join(HERE, "schemas", "output.schema.json"), "utf8")) as Record<string, unknown>
  const outIssues = validate(built, outSchema)
  const selfCheckPassed = outIssues.length === 0
  if (!selfCheckPassed) {
    errors.push(makeError("MGE-E801", "output failed schemas/output.schema.json self-check", { issues: outIssues.map((i) => `${i.path}: ${i.message}`) }))
  }
  const validation = built.validation as Record<string, unknown>
  validation.self_check_passed = selfCheckPassed
  validation.output_schema_valid = selfCheckPassed
  validation.checks = [
    ...(validation.checks as unknown[]),
    { name: "output_schema", passed: selfCheckPassed, detail: outIssues.map((i) => `${i.path}: ${i.message}`).join("; ") || "ok" },
  ]
  built.errors = errors
  built.status = selfCheckPassed ? "SUCCESS" : "FAILED"

  writeJSON(built)
  if (built.status === "FAILED") return 3
  if (built.status === "BLOCKED" || built.status === "HUMAN_APPROVAL_REQUIRED") return 2
  return 0
}

/** Map each required field to why it matters and how to obtain it. */
function fieldGuidance(): Record<string, string> {
  return {
    task_id: "audit anchor and reproducibility | Task Decomposer assigns it",
    project_id: "selects provenance file | project registry",
    request: "primary signal for what to evaluate | Mission Lock contract",
    skill_version: "version compatibility gate | this skill frontmatter",
    controller_version: "permission model gate | controller constant",
    timestamp: "audit and reproducibility | controller injects at call time",
    samples: "numeric evaluation input | test records / data_refs data files",
    "samples[].data_points": "stress-strain curve for strength indicators | test machine output",
    "samples[].permeability": "permeability evaluation | permeability test record",
  }
}

function hashRefs(refs: unknown): string {
  if (!Array.isArray(refs)) return ""
  return refs.map((r) => (r as { ref_id?: string }).ref_id ?? "").filter((x) => x).join(",")
}

interface EnvelopeParts {
  status: "SUCCESS" | "PARTIAL" | "BLOCKED" | "FAILED" | "NEED_ADDITIONAL_SKILL" | "HUMAN_APPROVAL_REQUIRED"
  summary: string
  errors: MgeError[]
  toolCalls: { tool: string; subcommand: string; status: string; detail: string }[]
  checks: { name: string; passed: boolean; detail: string }[]
  perGroup?: Record<string, unknown>
  uniformity?: unknown
  samplesOut?: Record<string, unknown>[]
  durFits?: (ReturnType<typeof fitDecay> & { specimen_id: string; cycle_type: string; max_cycle_observed: number })[]
  effect?: ReturnType<typeof effectSize> | null
  margin?: ReturnType<typeof safetyMargin> | null
  provenance: Record<string, unknown>
}

function v(value: number, unit = "kPa"): { value: number; unit: string } {
  return { value: Number.isFinite(value) ? Number(value.toFixed(4)) : 0, unit }
}

function buildEnvelope(p: EnvelopeParts): Record<string, unknown> {
  const out: Record<string, unknown> = {
    status: p.status,
    summary: p.summary,
    findings: [],
    assumptions: [],
    evidence_used: [],
    uncertainty: [],
    risks: [],
    artifacts: [],
    requested_next_skills: [],
    validation: { self_check_passed: p.checks.every((c) => c.passed), output_schema_valid: true, tool_calls: p.toolCalls, checks: p.checks },
    provenance: p.provenance,
    errors: p.errors,
  }

  // performance: samples (schema-shaped) + spatial uniformity
  const performance: Record<string, unknown> = {}
  if (p.samplesOut) {
    performance.samples = (p.samplesOut as Record<string, unknown>[]).map((s) => {
      const entry: Record<string, unknown> = { specimen_id: s.specimen_id, test_type: s.test_type }
      const ind = s.indicators as Record<string, number> | undefined
      if (ind) {
        entry.ucs = v(ind.ucs_kpa!)
        entry.peak_strength = v(ind.peak_strength_kpa ?? ind.ucs_kpa!)
        entry.residual_strength = v(ind.residual_strength_kpa ?? ind.ucs_kpa!)
        entry.peak_strain = { value: Number(ind.peak_strain_percent!.toFixed(4)), unit: "%" }
        if (Number.isFinite(ind.e0_kpa!)) entry.initial_modulus_e0 = v(ind.e0_kpa!)
        if (Number.isFinite(ind.e50_kpa!)) entry.secant_modulus_e50 = v(ind.e50_kpa!)
        entry.brittleness_index = { value: Number(ind.brittleness_index!.toFixed(4)), unit: "-" }
      }
      if (s.permeability_ms !== undefined) entry.permeability = { value: Number((s.permeability_ms as number).toFixed(9)), unit: "m/s" }
      if (s.caCO3_content !== undefined) entry.caCO3_content = { value: s.caCO3_content as number, unit: "mass_percent" }
      entry.conditions_checked = s.conditions_checked ?? []
      entry.conditions_issues = s.conditions_issues ?? []
      return entry
    })
  }
  if (p.uniformity) {
    const u = p.uniformity as { segments?: number; segment_cv?: number; trend?: string; note?: string }
    const su: Record<string, unknown> = { segments: u.segments, trend: u.trend, note: u.note }
    if (Number.isFinite(u.segment_cv)) su.segment_cv = { value: Number((u.segment_cv as number).toFixed(4)), unit: "-" }
    performance.spatial_uniformity = su
  }
  if (Object.keys(performance).length > 0) out.performance = performance

  // statistical: group stats + effect size
  const statistical: Record<string, unknown> = {}
  if (p.perGroup) {
    statistical.groups = Object.keys(p.perGroup)
    statistical.group_means = p.perGroup
  }
  if (p.effect) {
    statistical.improvement_percent = v(Number.isFinite(p.effect.improvement_percent) ? p.effect.improvement_percent : NaN, "%")
    // Cohen's d is only meaningful when a pooled SD exists (each group n≥2).
    // When it is not calculable we OMIT it rather than fabricate 0/negligible.
    if (Number.isFinite(p.effect.cohens_d)) {
      statistical.cohens_d = { value: Number(p.effect.cohens_d.toFixed(4)), interpretation: p.effect.cohens_d_interpretation }
    }
    statistical.statistically_significant = p.effect.statistically_significant
    statistical.significance_level = p.effect.alpha ?? 0.05
    statistical.p_value = Number.isFinite(p.effect.p_value as number) ? p.effect.p_value : null
    if (p.effect.confidence_interval_kpa) {
      statistical.confidence_interval = { lower: Number(p.effect.confidence_interval_kpa.lower.toFixed(3)), upper: Number(p.effect.confidence_interval_kpa.upper.toFixed(3)), unit: "kPa" }
    }
  }
  if (Object.keys(statistical).length > 0) out.statistical = statistical

  // durability
  if (p.durFits && p.durFits.length > 0) {
    out.durability = {
      specimens: p.durFits.map((f) => {
        const rec: Record<string, unknown> = {
          specimen_id: f.specimen_id,
          cycle_type: f.cycle_type,
          cycle_count: f.max_cycle_observed,
          initial_strength: Number(f.initial_strength_kpa.toFixed(3)),
          final_strength: Number(f.final_strength_kpa.toFixed(3)),
          residual_ratio: Number(f.residual_ratio.toFixed(4)),
          decay_per_cycle: Number.isFinite(f.decay_per_cycle) ? Number(f.decay_per_cycle.toFixed(6)) : null,
          model: f.model,
          r_squared: Number.isFinite(f.r_squared) ? Number(f.r_squared.toFixed(4)) : null,
        }
        if (f.half_life_cycles !== null) rec.half_life_cycles = Number(f.half_life_cycles.toFixed(2))
        if (f.projected_cycles_to_threshold !== null) rec.projected_cycles_to_threshold = Number(f.projected_cycles_to_threshold.toFixed(2))
        rec.note = f.note
        return rec
      }),
    }
  }

  // engineering judgment
  const judgments: string[] = []
  if (p.margin) {
    judgments.push(
      `safety margin ratio ${p.margin.ratio.toFixed(2)} (${p.margin.margin_percent.toFixed(0)}%), ${p.margin.adequate ? "adequate" : "inadequate"}`,
    )
  }
  // Strength–permeability tradeoff: when the same evaluation carries both a
  // treated strength and a treated permeability, surface the orders-of-magnitude
  // reduction so the decision (fit-for-use) is explicit, not implicit.
  const permTradeoff = strengthPermeabilityTradeoff(p.samplesOut ?? [])
  if (permTradeoff) judgments.push(permTradeoff)
  if (judgments.length > 0) {
    out.engineering_judgment = {
      judgment: judgments.join(" | "),
      basis: p.margin ? p.margin.note : "derived from sample permeability/strength pairing",
      ...(p.margin ? { safety_margin: { ratio: Number(p.margin.ratio.toFixed(4)) } } : {}),
    }
  }
  return out
}

/** Cross-specimen comparability warnings: size / density / stress-path gaps
 * that make a direct strength comparison misleading. One issue per offending
 * specimen. Deterministic. */
function crossSpecimenIssues(samples: NormalizedSample[]): { specimen_id: string; message: string }[] {
  const issues: { specimen_id: string; message: string }[] = []
  const curve = samples.filter((s) => s.data_points && s.data_points.length > 0)
  if (curve.length < 2) return issues

  // Diameter spread: if any two specimens differ by >25% in diameter, the
  // smaller one is flagged (end-effect and representativeness differences).
  const dims = curve
    .map((s) => ({ id: s.specimen_id, d: s.dimensions_mm?.diameter }))
    .filter((x): x is { id: string; d: number } => typeof x.d === "number")
  if (dims.length >= 2) {
    const maxD = Math.max(...dims.map((x) => x.d))
    for (const x of dims) {
      if (maxD / x.d > 1.25) {
        issues.push({ specimen_id: x.id, message: `${x.id}: diameter ${x.d} mm vs largest ${maxD} mm (>25% spread) — direct UCS comparison may be misleading (size effect)` })
      }
    }
  }

  // Loading rate spread: order-of-magnitude differences affect rate-dependent strength.
  const rates = curve
    .map((s) => ({ id: s.specimen_id, r: s.loading_rate, u: s.loading_rate_unit ?? "mm/min" }))
    .filter((x): x is { id: string; r: number; u: string } => typeof x.r === "number" && x.u === "mm/min")
  if (rates.length >= 2) {
    const maxR = Math.max(...rates.map((x) => x.r))
    const minR = Math.min(...rates.map((x) => x.r))
    if (maxR / minR > 10) {
      for (const x of rates) {
        issues.push({ specimen_id: x.id, message: `${x.id}: loading rate ${x.r} mm/min spans >10x across specimens — rate-dependent strength comparison may be misleading` })
      }
    }
  }

  // Density spread: >5% difference in dry density changes initial state.
  const dens = curve
    .map((s) => ({ id: s.specimen_id, g: s.density_gcm3 }))
    .filter((x): x is { id: string; g: number } => typeof x.g === "number")
  if (dens.length >= 2) {
    const maxG = Math.max(...dens.map((x) => x.g))
    const minG = Math.min(...dens.map((x) => x.g))
    if (maxG / minG > 1.05) {
      for (const x of dens) {
        issues.push({ specimen_id: x.id, message: `${x.id}: dry density differs >5% from the other specimen(s) — strength comparison may be density-confounded` })
      }
    }
  }

  return issues
}

/** Detect a strength-permeability tradeoff within one evaluation and describe it. */
function strengthPermeabilityTradeoff(samples: Record<string, unknown>[]): string | null {
  const withStrength = samples.find((s) => (s.indicators as { ucs_kpa?: number } | undefined)?.ucs_kpa !== undefined)
  if (!withStrength) return null
  const ucs = (withStrength.indicators as { ucs_kpa?: number }).ucs_kpa!
  const perms = samples
    .map((s) => ({ id: s.specimen_id as string | undefined, p: s.permeability_ms as number | undefined }))
    .filter((x) => x.id !== undefined && typeof x.p === "number" && x.p! > 0) as { id: string; p: number }[]
  if (perms.length < 2) {
    // Single permeability value: report absolute level only.
    const [only] = perms
    if (!only) return null
    return `strength ${ucs.toFixed(0)} kPa with permeability ${only.p.toExponential(1)} m/s; fit-for-use depends on the application's permeability requirement`
  }
  const [maxP] = [...perms].sort((a, b) => b.p - a.p)
  const [minP] = [...perms].sort((a, b) => a.p - b.p)
  if (!maxP || !minP) return null
  const orders = Math.log10(maxP.p / minP.p)
  return `strength ${ucs.toFixed(0)} kPa; permeability spans ${minP.p.toExponential(1)}–${maxP.p.toExponential(1)} m/s (≈${orders.toFixed(1)} order(s) of magnitude between the most and least permeable specimen); fit-for-use depends on the application's permeability requirement (drainage vs. sealing)`
}

async function emitEnvelope(parts: EnvelopeParts): Promise<number> {
  const out = buildEnvelope(parts)
  writeJSON(out)
  const status = out.status as string
  if (status === "FAILED") return 3
  if (status === "BLOCKED" || status === "HUMAN_APPROVAL_REQUIRED") return 2
  return 0
}

async function main(): Promise<number> {
  const [cmd, ...rest] = process.argv.slice(2)
  if (!cmd) {
    process.stderr.write(usage())
    return 1
  }
  try {
    switch (cmd) {
      case "parse":
        return await cmdParse(rest)
      case "metrics":
        return await cmdMetrics(rest)
      case "stats":
        return await cmdStats(rest)
      case "durability":
        return await cmdDurability(rest)
      case "effect":
        return await cmdEffect(rest)
      case "evaluate":
        return await cmdEvaluate(rest)
      case "check-self":
        return await cmdCheckSelf(rest)
      default:
        process.stderr.write(usage())
        return 1
    }
  } catch (err) {
    writeJSON({ error: makeError("MGE-E802", `cli error: ${(err as Error).message}`, {}) })
    return 4
  }
}

function usage(): string {
  return `mge — micp-geotechnical-performance tool suite v1.0.0
  parse [--input <samples.json>]          parse+validate raw samples
  metrics [--input <samples.json>]        extract stress-strain indicators
  stats [--input <samples.json>]          sample statistics + spatial uniformity
  durability [--input <samples.json>]     durability cycle decay fitting
  effect [--input <effect.json>]          effect size + safety margin
  evaluate [--input <envelope.json>]      full pipeline to machine envelope
  check-self <json-file>                  validate JSON against output schema
`
}

main().then((code) => {
  process.exitCode = code
})
