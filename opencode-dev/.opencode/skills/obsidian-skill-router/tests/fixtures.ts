// Test fixtures: build an on-disk fake skill registry in a temp directory so
// the real indexer (registry.ts) exercises genuine SKILL.md parsing.

import { promises as fs } from "node:fs"
import os from "node:os"
import path from "node:path"
import { indexRegistry, type RegistrySnapshot } from "../tools/osr/registry"

export interface FixtureSkill {
  name: string
  description: string
  manifest?: Record<string, unknown>
  body?: string
}

export interface FixtureRegistry {
  root: string
  snapshot: RegistrySnapshot
  cleanup: () => Promise<void>
}

export const FIXTURE_SKILLS: FixtureSkill[] = [
  {
    name: "micp-ureolysis-chemistry",
    description: "尿素水解化学与铵态氮质量守恒分析。Use when task involves urea hydrolysis, ammonium, or calcite precipitation chemistry.",
    manifest: {
      version: "1.0.0",
      capabilities: ["chemistry", "mass_balance", "biosafety_ammonia"],
      inputs_required: ["task_id", "request", "evidence_refs"],
      outputs: ["stoichiometry", "ammonium_balance"],
      units: { ammonia_conc: "mol/L" },
      domain_keywords: ["尿素水解", "urea", "水解", "铵", "氨", "ammonium", "calcite", "方解石", "沉淀", "化学"],
      network: false,
      writes: [],
      cost_estimate: { tokens: 8000, usd: 0.08 },
    },
  },
  {
    name: "micp-mineral-phase-interpreter",
    description: "方解石/球霰石等矿物相解释。Use when task involves mineral phase or calcite form.",
    manifest: {
      version: "1.0.0",
      capabilities: ["mineral_phase"],
      inputs_required: ["task_id", "request"],
      units: { calcite_mass: "g" },
      domain_keywords: ["矿相", "矿物", "calcite", "方解石", "vaterite", "球霰石", "aragonite"],
      network: false,
      writes: [],
      cost_estimate: { tokens: 6000, usd: 0.06 },
    },
  },
  {
    name: "micp-porous-media-transport",
    description: "多孔介质渗流与溶质输运分析。Use when task involves porous media, advection, diffusion or hydraulic gradient.",
    manifest: {
      version: "1.0.0",
      capabilities: ["transport"],
      inputs_required: ["task_id", "request", "data_refs"],
      units: { permeability: "m2" },
      domain_keywords: ["渗流", "多孔介质", "porous", "渗透", "扩散", "diffusion", "advection", "渗透系数"],
      network: false,
      writes: [],
      cost_estimate: { tokens: 10000, usd: 0.1 },
    },
  },
  {
    name: "micp-geotechnical-performance",
    description: "MICP 处理土体的岩土工程性能评估。Use when task involves geotechnical strength, modulus or bearing capacity.",
    manifest: {
      version: "1.0.0",
      capabilities: ["geotechnical"],
      inputs_required: ["task_id", "request", "data_refs"],
      units: { strength: "MPa" },
      domain_keywords: ["岩土", "geotech", "强度", "strength", "模量", "承载", "固结", "性能"],
      network: false,
      writes: [],
      cost_estimate: { tokens: 9000, usd: 0.09 },
    },
  },
  {
    name: "obsidian-red-team",
    description: "红队对抗审查。Use ONLY for adversarial review of high-risk claims and plans.",
    manifest: {
      version: "1.0.0",
      capabilities: ["red_team"],
      risk_tier: "high",
      network: false,
      writes: [],
      cost_estimate: { tokens: 3000, usd: 0.03 },
    },
  },
  {
    name: "obsidian-decision-gate",
    description: "决策门:风险放行与人工批准记录。Use ONLY for gate-keeping high-risk decisions.",
    manifest: {
      version: "1.0.0",
      capabilities: ["decision_gate"],
      network: false,
      writes: ["state/gates/**"],
      cost_estimate: { tokens: 2000, usd: 0.02 },
    },
  },
  {
    name: "obsidian-data-analyst",
    description: "数据分析与统计拟合。Use when task involves regression, statistics or time series.",
    manifest: {
      version: "1.0.0",
      capabilities: ["data_analysis"],
      inputs_required: ["task_id", "request", "data_refs"],
      network: false,
      writes: [],
      cost_estimate: { tokens: 15000, usd: 0.12 },
    },
  },
  {
    name: "obsidian-evidence-synthesizer",
    description: "证据综合与综述合成。Use when task involves synthesizing multiple evidence sources.",
    manifest: {
      version: "1.0.0",
      capabilities: ["synthesis"],
      network: false,
      writes: [],
    },
  },
  {
    name: "obsidian-literature-scout",
    description: "文献检索与筛选。Use when task involves literature search or paper scout.",
    manifest: {
      version: "1.0.0",
      capabilities: ["literature"],
      inputs_required: ["task_id", "request"],
      network: true,
      writes: [],
    },
  },
  {
    name: "obsidian-experiment-designer",
    description: "实验方案设计。Use when task involves experiment or trial design.",
    manifest: {
      version: "1.0.0",
      capabilities: ["experiment", "scaleup"],
      network: false,
      writes: [],
    },
  },
  {
    name: "micp-biosafety-environment-auditor",
    description: "生物安全与环境影响审计。Use when task involves biosafety, environmental impact or ammonia emissions.",
    manifest: {
      version: "1.0.0",
      capabilities: ["biosafety"],
      inputs_required: ["task_id", "request"],
      network: false,
      writes: [],
    },
  },
  {
    name: "obsidian-evidence-extractor",
    description: "证据提取与核验。Use when task involves extracting or verifying evidence from sources.",
    manifest: {
      version: "1.0.0",
      capabilities: ["evidence"],
      inputs_required: ["task_id", "request", "evidence_refs"],
      network: false,
      writes: [],
      cost_estimate: { tokens: 5000, usd: 0.05 },
    },
  },
]

export async function buildFixtureRegistry(
  extra?: { broken?: string[]; missingManifest?: string[]; skills?: FixtureSkill[] },
): Promise<FixtureRegistry> {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), "osr-fixture-"))
  const skillsRoot = path.join(root, "skills")
  await fs.mkdir(skillsRoot, { recursive: true })
  const all = extra?.skills ?? FIXTURE_SKILLS
  const broken = new Set(extra?.broken ?? [])
  const missingManifest = new Set(extra?.missingManifest ?? [])

  for (const skill of all) {
    const dir = path.join(skillsRoot, skill.name)
    await fs.mkdir(dir, { recursive: true })
    const body = skill.body ?? `# ${skill.name}\n\nInstructions here.\n`
    await fs.writeFile(path.join(dir, "SKILL.md"), `---\nname: ${skill.name}\ndescription: ${skill.description}\n---\n\n${body}`, "utf8")
    if (!missingManifest.has(skill.name)) {
      await fs.writeFile(path.join(dir, "skill.yaml"), yamlOf(skill.manifest ?? {}), "utf8")
    }
  }
  for (const name of broken) {
    // SKILL.md with tab indentation — our YAML parser throws YAMLParseError,
    // so the indexer must skip it with an issue instead of crashing.
    const dir = path.join(skillsRoot, name)
    await fs.mkdir(dir, { recursive: true })
    await fs.writeFile(path.join(dir, "SKILL.md"), "---\nname: " + name + "\n\tbad_indent: 1\n---\n", "utf8")
  }
  const { snapshot } = await indexRegistry([skillsRoot])
  return { root, snapshot, cleanup: () => fs.rm(root, { recursive: true, force: true }) }
}

function yamlOf(o: Record<string, unknown>): string {
  const lines: string[] = []
  for (const [k, v] of Object.entries(o)) {
    if (Array.isArray(v)) {
      if (v.length === 0) {
        lines.push(`${k}: []`)
      } else {
        lines.push(`${k}:`)
        for (const item of v) lines.push(`  - ${String(item)}`)
      }
    } else if (typeof v === "object" && v !== null) {
      lines.push(`${k}:`)
      for (const [k2, v2] of Object.entries(v as Record<string, unknown>)) {
        lines.push(`  ${k2}: ${String(v2)}`)
      }
    } else {
      lines.push(`${k}: ${typeof v === "string" ? v : JSON.stringify(v)}`)
    }
  }
  return lines.join("\n") + "\n"
}
