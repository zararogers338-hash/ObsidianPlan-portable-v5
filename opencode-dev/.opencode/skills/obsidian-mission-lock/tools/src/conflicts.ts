/**
 * Conflict detector.
 *
 * Detects requirement conflicts WITHOUT silently resolving them.
 * Three layers:
 *  1. Declared conflicts — explicit "X vs Y" tension statements in the request
 *     (surfaced by the LLM into contract.objectives/constraints, checked here).
 *  2. Metric-band conflicts — programmatic: maximize/minimize bands that
 *     cannot be jointly satisfied (checked against known antagonistic pairs).
 *  3. Domain rule conflicts — MICP-specific known trade-offs from reviewed
 *     literature (S9–S13), e.g. strength ↑ via dense precipitation vs.
 *     permeability preservation; urea hydrolysis vs. zero ammonium emission.
 *
 * The detector NEVER picks a winner. Every conflict is emitted as a
 * ConflictEntry with resolution: "unresolved" | "human_decision_required".
 */

import type { ConflictEntry, Metric, Quantity } from "./types"
import { sameDimension, toBase } from "./units"

/** Known antagonistic metric-name patterns. Order-insensitive matching on
 *  normalized metric names. Domain sources cited per pair. */
const ANTAGONISTIC_PAIRS: { a: RegExp; b: RegExp; rationale: string; severity: "hard" | "soft" }[] = [
  {
    a: /strength|ucs|compressive|承载|强度/i,
    b: /permeab|conductivity|渗透/i,
    rationale:
      "MICP precipitation that raises strength typically clogs pores and reduces permeability by 1–2 orders of magnitude (S11); 'maximize strength' + 'maintain original permeability' is a hard physical trade-off, not an optimization problem",
    severity: "hard",
  },
  {
    a: /strength|ucs|compressive|强度/i,
    b: /cost|成本|budget/i,
    rationale: "Higher cementation usually needs more treatment cycles / reagent, raising cost; treat as soft unless both are pinned to exact values",
    severity: "soft",
  },
  {
    a: /permeab|渗透/i,
    b: /cost|成本|budget/i,
    rationale: "Permeability control to tight tolerances requires staged injection and monitoring, increasing cost",
    severity: "soft",
  },
  {
    a: /ammonia|ammonium|nh4|氨|铵/i,
    b: /urea|尿素|ureolysis/i,
    rationale:
      "Ureolytic MICP stoichiometrically produces 2 mol NH₄⁺ per mol urea (S10); 'urea pathway' + 'zero ammonium emission' is contradictory unless an explicit capture/removal step is added — non-urea pathways (S13) must not reuse urea-path models",
    severity: "hard",
  },
  {
    a: /fast|rapid|quick|speed|duration|快速|工期|时间/i,
    b: /uniform|homogen|均匀/i,
    rationale: "Faster treatment front propagation reduces spatial uniformity of precipitation",
    severity: "soft",
  },
  {
    a: /maximi[sz]e.*strength|强度.*最大/i,
    b: /minimi[sz]e.*cost|成本.*最低/i,
    rationale: "Joint extrema on antagonistic objectives require an explicit priority or Pareto framing",
    severity: "soft",
  },
]

/** Words that pin a metric to an absolute, non-negotiable value. */
const ABSOLUTE_WORDS = /zero|0\s*(?:%|emission)|original|unchanged|no change|keep.*same|保持.*原|零|不变|不得|must not/i

function metricName(m: Metric): string {
  return m.name
}

/** Detect "maintain at original" semantics: direction maintain, or target
 *  equal to current, or absolute wording in the metric name. */
function isPinned(m: Metric): boolean {
  if (m.direction === "maintain") return true
  if (ABSOLUTE_WORDS.test(m.name)) return true
  if (m.target && m.current && sameDimension(m.target.unit, m.current.unit)) {
    const t = toBase(m.target)
    const c = toBase(m.current)
    if (t !== null && c !== null && Math.abs(t - c) <= 1e-12) return true
  }
  return false
}

function isExtremized(m: Metric): boolean {
  return m.direction === "maximize" || m.direction === "minimize"
}

let counter = 0
function nextId(): string {
  counter += 1
  return `CONF-${String(counter).padStart(3, "0")}`
}

export function resetConflictCounter(): void {
  counter = 0
}

/** Detect metric-vs-metric conflicts from the contract's metric set. */
export function detectMetricConflicts(metrics: Metric[]): ConflictEntry[] {
  const conflicts: ConflictEntry[] = []
  for (const pair of ANTAGONISTIC_PAIRS) {
    const as = metrics.filter((m) => pair.a.test(metricName(m)))
    const bs = metrics.filter((m) => pair.b.test(metricName(m)))
    for (const ma of as) {
      for (const mb of bs) {
        // Only a conflict when at least one side is pinned or both are extremized
        const pinned = isPinned(ma) || isPinned(mb)
        const bothExtremes = isExtremized(ma) && isExtremized(mb)
        if (!pinned && !bothExtremes) continue
        conflicts.push({
          id: nextId(),
          between: [ma.name, mb.name],
          kind: "metric-metric",
          description: `${pair.rationale}. [${ma.name}: ${ma.direction}${ma.target ? ` → ${ma.target.value} ${ma.target.unit}` : ""}] vs [${mb.name}: ${mb.direction}${mb.target ? ` → ${mb.target.value} ${mb.target.unit}` : ""}]`,
          severity: pinned && pair.severity === "hard" ? "hard" : pair.severity,
          resolution: pinned && pair.severity === "hard" ? "human_decision_required" : "unresolved",
        })
      }
    }
  }
  return conflicts
}

/** Detect conflicts between free-text constraints (controller/LLM supplies
 *  constraints already extracted; this checks pairwise antagonism). */
export function detectConstraintConflicts(constraints: Record<string, unknown>): ConflictEntry[] {
  const entries = Object.entries(constraints).filter(([, v]) => typeof v === "string" || typeof v === "number")
  const conflicts: ConflictEntry[] = []
  for (const pair of ANTAGONISTIC_PAIRS) {
    const as = entries.filter(([k, v]) => pair.a.test(k) || pair.a.test(String(v)))
    const bs = entries.filter(([k, v]) => pair.b.test(k) || pair.b.test(String(v)))
    for (const [ka, va] of as) {
      for (const [kb, vb] of bs) {
        const absolute = ABSOLUTE_WORDS.test(String(va)) || ABSOLUTE_WORDS.test(String(vb))
        conflicts.push({
          id: nextId(),
          between: [ka, kb],
          kind: "constraint-constraint",
          description: `${pair.rationale}. Constraint "${ka}"="${String(va)}" vs "${kb}"="${String(vb)}"`,
          severity: absolute && pair.severity === "hard" ? "hard" : pair.severity,
          resolution: absolute && pair.severity === "hard" ? "human_decision_required" : "unresolved",
        })
      }
    }
  }

  // Generic extremum conflict: "maximize X" vs "minimize X" on the same object
  const extrema = entries.filter(([, v]) => /maximi[sz]e|minimi[sz]e/i.test(String(v)))
  for (let i = 0; i < extrema.length; i++) {
    for (let j = i + 1; j < extrema.length; j++) {
      const [ka, va] = extrema[i]
      const [kb, vb] = extrema[j]
      const vaStr = String(va)
      const vbStr = String(vb)
      const dirA = /maximi[sz]e/i.test(vaStr) ? "max" : "min"
      const dirB = /maximi[sz]e/i.test(vbStr) ? "max" : "min"
      if (dirA === dirB) continue
      const objA = vaStr.replace(/maximi[sz]e|minimi[sz]e/gi, "").trim().toLowerCase()
      const objB = vbStr.replace(/maximi[sz]e|minimi[sz]e/gi, "").trim().toLowerCase()
      if (objA && objA === objB) {
        conflicts.push({
          id: nextId(),
          between: [ka, kb],
          kind: "constraint-constraint",
          description: `Constraint "${ka}"="${vaStr}" and "${kb}"="${vbStr}" extremize the same object "${objA}" in opposite directions; joint extrema require an explicit priority or Pareto framing`,
          severity: "soft",
          resolution: "unresolved",
        })
      }
    }
  }
  return conflicts
}

/** MICP domain check: urea pathway declared but ammonium absent from
 *  risks/metrics → mass-conservation blind spot (S10). Also covers the
 *  constraint layer: a "urea" constraint alongside a "zero ammonium" or
 *  "zero ammonia" constraint is contradictory unless capture is declared. */
export function detectDomainBlindSpots(contract: {
  domain_tags: string[]
  metrics: Metric[]
  risks: { text: string }[]
  statements: { text: string }[]
  constraints?: Record<string, unknown>
}): ConflictEntry[] {
  const conflicts: ConflictEntry[] = []
  const allText = [
    ...contract.metrics.map((m) => m.name),
    ...contract.risks.map((r) => r.text),
    ...contract.statements.map((s) => s.text),
    ...contract.domain_tags,
  ].join(" ")

  const mentionsUrea = /urea|尿素|ureolysis|水解/i.test(allText)
  const mentionsNonUrea = /denitrification|反硝化|eps|non-urea|非尿素/i.test(allText)
  const tracksAmmonium = /ammonia|ammonium|nh4|氨|铵|nitrogen|氮/i.test(allText)

  // Constraint-layer conflict: urea pathway + absolute-zero ammonium emission
  const constraintEntries = Object.entries(contract.constraints ?? {})
  const ureaConstraint = constraintEntries.find(([k, v]) => /urea|尿素|ureolysis|pathway/i.test(k) && /urea|尿素/i.test(String(v)))
  const zeroAmmoniumConstraint = constraintEntries.find(
    ([k, v]) =>
      /ammonia|ammonium|nh4|氨|铵|emission|discharge/i.test(k) && ABSOLUTE_WORDS.test(String(v)),
  )
  if (ureaConstraint && zeroAmmoniumConstraint) {
    conflicts.push({
      id: nextId(),
      between: [zeroAmmoniumConstraint[0], ureaConstraint[0]],
      kind: "domain-blindspot",
      description:
        `Ureolytic MICP stoichiometrically produces 2 mol NH₄⁺ per mol urea (S10); constraint "${ureaConstraint[0]}"="${String(ureaConstraint[1])}" combined with "${zeroAmmoniumConstraint[0]}"="${String(zeroAmmoniumConstraint[1])}" is contradictory unless an explicit NH₄⁺ capture/removal step is added — non-urea pathways (S13) must not reuse urea-path models.`,
      severity: "hard",
      resolution: "human_decision_required",
    })
  }

  if (mentionsUrea && !mentionsNonUrea && !tracksAmmonium) {
    conflicts.push({
      id: nextId(),
      between: ["urea pathway", "ammonium mass balance"],
      kind: "goal-contradiction",
      description:
        "Urea-hydrolysis MICP declared, but no ammonium (NH₄⁺) tracking, risk, or mitigation appears anywhere in the contract. Ureolysis produces 2 mol NH₄⁺ per mol urea (S10); omitting it breaks nitrogen mass conservation and hides an environmental-impact dimension.",
      severity: "hard",
      resolution: "unresolved",
    })
  }
  if (mentionsUrea && mentionsNonUrea) {
    conflicts.push({
      id: nextId(),
      between: ["urea pathway", "non-urea pathway"],
      kind: "goal-contradiction",
      description:
        "Contract mixes urea-pathway and non-urea-pathway language. Kinetic models, stoichiometry, and risk profiles differ (S13); the contract must declare ONE primary pathway or explicitly scope a comparison study.",
      severity: "soft",
      resolution: "unresolved",
    })
  }
  return conflicts
}

/** Merge + dedupe (by between-pair) all conflict layers. */
export function detectAllConflicts(input: {
  metrics: Metric[]
  constraints?: Record<string, unknown>
  domain_tags: string[]
  risks: { text: string }[]
  statements: { text: string }[]
}): ConflictEntry[] {
  resetConflictCounter()
  const all = [
    ...detectMetricConflicts(input.metrics),
    ...(input.constraints ? detectConstraintConflicts(input.constraints) : []),
    ...detectDomainBlindSpots({
      metrics: input.metrics,
      domain_tags: input.domain_tags,
      risks: input.risks,
      statements: input.statements,
      constraints: input.constraints,
    }),
  ]
  const seen = new Set<string>()
  return all.filter((c) => {
    const key = [...c.between].sort().join("|") + ":" + c.kind
    if (seen.has(key)) return false
    seen.add(key)
    return true
  })
}
