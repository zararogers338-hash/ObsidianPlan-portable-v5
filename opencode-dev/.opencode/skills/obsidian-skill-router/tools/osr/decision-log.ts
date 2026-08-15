// Decision log: append-only, hash-chained JSONL audit trail for routing
// decisions. Every route decision is one record; each record carries the
// previous record's hash so tampering or truncation is detectable offline.
//
// Layout (relative to skill base dir, overridable for tests):
//   logs/decisions/<project_id>.jsonl

import { promises as fs } from "node:fs"
import path from "node:path"
import { sha256Hex, stableStringify } from "./registry"

export interface DecisionRecord {
  seq: number
  ts: string
  project_id: string
  task_id: string
  decision: "route" | "blocked" | "capability_gap" | "approval_required" | "failed"
  input_digest: string
  summary: string
  reasons: string[]
  budget: { est_tokens: number; est_cost_usd: number }
  planned_skills: string[]
  registry_snapshot_id: string
  router_version: string
  prev_hash: string
  hash?: string
}

const GENESIS = "0".repeat(64)

export function recordHash(rec: Omit<DecisionRecord, "hash">): string {
  return sha256Hex(stableStringify(rec))
}

export class DecisionLog {
  private constructor(
    readonly file: string,
    private seq: number,
    private prevHash: string,
  ) {}

  static async open(dir: string, projectId: string): Promise<DecisionLog> {
    const safe = projectId.replace(/[^a-zA-Z0-9_.-]/g, "_")
    await fs.mkdir(dir, { recursive: true })
    const file = path.join(dir, `${safe}.jsonl`)
    let seq = 0
    let prevHash = GENESIS
    try {
      const raw = await fs.readFile(file, "utf8")
      const lines = raw.split("\n").filter((l) => l.trim() !== "")
      const lastLine = lines[lines.length - 1]
      if (lastLine !== undefined) {
        const last = JSON.parse(lastLine) as DecisionRecord
        seq = last.seq
        prevHash = last.hash ?? prevHash
      }
    } catch {
      // no log yet — start fresh at genesis
    }
    return new DecisionLog(file, seq, prevHash)
  }

  async append(rec: Omit<DecisionRecord, "seq" | "prev_hash" | "hash">): Promise<DecisionRecord> {
    const next: Omit<DecisionRecord, "hash"> = {
      ...rec,
      seq: this.seq + 1,
      prev_hash: this.prevHash,
    }
    const hash = recordHash(next)
    const full: DecisionRecord = { ...next, hash }
    await fs.appendFile(this.file, JSON.stringify(full) + "\n", "utf8")
    this.seq = next.seq
    this.prevHash = hash
    return full
  }
}

export interface ChainVerification {
  ok: boolean
  records: number
  firstBadSeq?: number
  error?: string
}

export async function verifyChain(file: string): Promise<ChainVerification> {
  let raw: string
  try {
    raw = await fs.readFile(file, "utf8")
  } catch (err) {
    return { ok: false, records: 0, error: `log unreadable: ${(err as Error).message}` }
  }
  const lines = raw.split("\n").filter((l) => l.trim() !== "")
  let prev = GENESIS
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i]
    if (line === undefined) continue
    let rec: DecisionRecord
    try {
      rec = JSON.parse(line) as DecisionRecord
    } catch {
      return { ok: false, records: i, firstBadSeq: i + 1, error: "line not valid JSON" }
    }
    if (rec.prev_hash !== prev) {
      return { ok: false, records: i, firstBadSeq: rec.seq, error: "prev_hash mismatch (chain broken)" }
    }
    const { hash, ...rest } = rec
    if (recordHash(rest) !== hash) {
      return { ok: false, records: i, firstBadSeq: rec.seq, error: "record hash mismatch (content tampered)" }
    }
    prev = hash as string
  }
  return { ok: true, records: lines.length }
}
