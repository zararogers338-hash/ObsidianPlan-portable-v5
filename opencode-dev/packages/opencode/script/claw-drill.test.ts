// claw-drill.test.ts — REAL offline 12-agent governance drill through the wired
// ClawManager, using the repository's own test harness (testEffect) exactly as
// test/claw/integration.test.ts does. Every governance action (createCloud,
// request/decideSpawn, joinCloud, issueLease/spend, activate, sealVerdict,
// openClaw/send, beginReview, complete, archive, destroy, noteBusy, capacity,
// log) is executed against the real service; every emitted event and rejection
// is printed verbatim. Fully offline; no remote LLM. Member verdict texts are
// authored below; governance itself always goes through ClawManager.
import { describe, expect } from "bun:test"
import { Effect } from "effect"
import { LayerNode } from "@opencode-ai/core/effect/layer-node"
import { node as ClawManagerNode, Service as ClawManager } from "../src/claw/manager"
import { SessionID } from "../src/session/schema"
import { YUHENG_AGENT_NAME } from "../src/claw/types"
import { testEffect } from "../test/lib/effect"

const it = testEffect(LayerNode.compile(LayerNode.group([ClawManagerNode]), []))

type ActionResult =
  | { kind: "ok"; value: unknown }
  | { kind: "rejected"; code: string; message: string }

const capture = <A, E>(eff: Effect.Effect<A, E>): Effect.Effect<ActionResult, never, never> =>
  eff.pipe(
    Effect.match({
      onFailure: (err): ActionResult => ({
        kind: "rejected",
        code: (err as { code?: string }).code ?? "?",
        message: (err as { message?: string }).message ?? String(err),
      }),
      onSuccess: (value): ActionResult => ({ kind: "ok", value }),
    }),
  )

const out = (s: string) => process.stdout.write(s + "\n")
const sid = (n: string) => SessionID.make(`ses_drill_${n}`)
const idShort = (s: string) => s.replace(/^ses_drill_[AB]_/, "")

describe("claw 12-agent drill (4 clouds, offline)", () => {
  it.instance(
    "full governed lifecycle with verbatim event seqs",
    () =>
      Effect.gen(function* () {
        const claw = yield* ClawManager
        const control = { session: sid("control"), agentType: "build" }

        // ── PHASE 0 ──────────────────────────────────────────────────────
        out("== PHASE 0: CAPACITY BASELINE ==")
        const cap0 = yield* claw.capacity()
        out(`  capacity.sample zone=${cap0.zone} busy=${cap0.busy} background=${cap0.background} leased=${cap0.leased} active=${cap0.active}`)

        // ── PHASE 1 ──────────────────────────────────────────────────────
        out("== PHASE 1: CLOUD FORMATION (4 clouds x 3 agents) ==")
        const ca = yield* capture(
          claw.createCloud({
            cloud_type: "audit", purpose: "evidence audit of MICP field injection (S. pasteurii, ureolysis)",
            created_by: control, member_limit: 3, token_budget: 80000, max_rounds: 8, max_lifetime_ms: 20 * 60 * 1000,
          }),
        )
        out(`  [A.createCloud] ${ca.kind} ${ca.kind === "ok" ? (ca.value as { cloud_id: string }).cloud_id : ca.code}`)
        const cloudA = (ca as { kind: "ok"; value: { cloud_id: string } }).value.cloud_id

        const cb = yield* capture(
          claw.createCloud({ cloud_type: "engineering", purpose: "engineering scale-up assessment", created_by: control, member_limit: 3, token_budget: 90000 }),
        )
        out(`  [B.createCloud] ${cb.kind} ${cb.kind === "ok" ? (cb.value as { cloud_id: string }).cloud_id : cb.code}`)
        const cloudB = (cb as { kind: "ok"; value: { cloud_id: string } }).value.cloud_id

        const cc = yield* capture(
          claw.createCloud({ cloud_type: "red_team", purpose: "red-team against cloud A sealed verdicts", created_by: control, member_limit: 3, token_budget: 60000, audit_target: cloudA as never }),
        )
        out(`  [C.createCloud] ${cc.kind} ${cc.kind === "ok" ? (cc.value as { cloud_id: string }).cloud_id : cc.code}`)
        const cloudC = (cc as { kind: "ok"; value: { cloud_id: string } }).value.cloud_id

        const cd = yield* capture(
          claw.createCloud({ cloud_type: "release", purpose: "final release ruling over cloud B", created_by: control, member_limit: 3, token_budget: 40000, audit_target: cloudB as never }),
        )
        out(`  [D.createCloud] ${cd.kind} ${cd.kind === "ok" ? (cd.value as { cloud_id: string }).cloud_id : cd.code}`)
        const cloudD = (cd as { kind: "ok"; value: { cloud_id: string } }).value.cloud_id

        const roster: Array<[string, string, string[]]> = [
          [cloudA, "A", ["micp-evidence-extractor", "micp-data-analyst", "micp-biology-reasoner"]],
          [cloudB, "B", ["micp-scaleup-injection-engineer", "micp-modeling-optimizer", "micp-lca-technoeconomic"]],
          [cloudC, "C", ["obsidian-red-team", "micp-mineral-phase-interpreter", "micp-instrumentation-qc"]],
          [cloudD, "D", ["obsidian-decision-gate", "micp-reproducibility-versioning", "micp-biosafety-environment-auditor"]],
        ]
        const idByName = new Map<string, string>()
        const cloudOfMember = new Map<string, string>()
        const agents: Array<{ session: string; agentType: string; cloud: string }> = []

        for (const [cloud, cloudTag, types] of roster) {
          for (const agentType of types) {
            const session = sid(`${cloudTag}_${agentType}`)
            idByName.set(agentType, session)
            cloudOfMember.set(session, cloud)
            const req = yield* capture(claw.requestAgent({ requested_by: control, agent_type: agentType, purpose: `staff ${cloudTag}`, for_cloud: cloud }))
            out(`  [${cloudTag}.${agentType}.request] ${req.kind} ${req.kind === "ok" ? (req.value as { request_id: string }).request_id : req.code}`)
            const dec = yield* capture(claw.decideSpawn((req as { kind: "ok"; value: { request_id: string } }).value.request_id, { approved: true, reason: "control-plane approve", granted_session: session }))
            out(`  [${cloudTag}.${agentType}.decide] ${dec.kind} approved=${dec.kind === "ok" ? (dec.value as { decision: { approved: boolean } }).decision.approved : "-"} granted=${dec.kind === "ok" ? (dec.value as { decision: { granted_session?: string } }).decision.granted_session : "-"}`)
            const j = yield* capture(claw.joinCloud(cloud, { id: session, agentType }, `${cloudTag}-${agentType}`))
            out(`  [${cloudTag}.${agentType}.join] ${j.kind} status=${j.kind === "ok" ? (j.value as { status: string }).status : j.code}`)
            if (j.kind === "ok") agents.push({ session, agentType, cloud })
          }
        }

        out("  -- issueLease per member + activate --")
        const budgetByCloud: Record<string, number> = { [cloudA]: 80000, [cloudB]: 90000, [cloudC]: 60000, [cloudD]: 40000 }
        const leaseByAgent = new Map<string, string>()
        for (const a of agents) {
          const cap = Math.floor(budgetByCloud[a.cloud] / 3)
          const le = yield* capture(claw.issueLease(a.cloud, a.session as never, { max_requests: 20, max_tokens: cap, ttl_ms: 900000 }))
          out(`  [lease.${a.agentType}] ${le.kind} lease=${le.kind === "ok" ? (le.value as { lease_id: string }).lease_id : le.code} max_tokens=${le.kind === "ok" ? (le.value as { max_tokens: number }).max_tokens : "-"}`)
          if (le.kind === "ok") leaseByAgent.set(a.session, (le.value as { lease_id: string }).lease_id)
        }
        for (const cloud of [cloudA, cloudB, cloudC, cloudD]) {
          const ac = yield* capture(claw.activate(cloud))
          out(`  [activate.${cloud}] ${ac.kind} status=${ac.kind === "ok" ? (ac.value as { status: string }).status : ac.code}`)
        }

        // ── PHASE 2 ──────────────────────────────────────────────────────
        out("== PHASE 2: SEALED ROUND-1 VERDICTS + CLAW ==")
        const A3 = roster[0][2].map((t) => idByName.get(t)!)
        const B3 = roster[1][2].map((t) => idByName.get(t)!)
        const r1: Record<string, string> = {
          [A3[0]]: "EVID-CARD ev://NH4-02: effluent NH4+ mass-balance unreconciled (inlet urea-N vs outlet NH4-N exceed cap). CRITICAL. evidence: ev://NH4-02,ev://flow-03. conf:high.",
          [A3[1]]: "STAT: n=4, no independence statement, spatial mean only. NOTE. evidence: ev://stat-01. conf:medium.",
          [A3[2]]: "BIO: urease active at injected OD600, live-cell fraction unreported. OPEN. evidence: ev://bio-01. conf:medium.",
          [B3[0]]: "SCALE: column 3L/h scales linearly; field well array must NOT scale volume linearly; pressure cap unverified. evidence: ev://sc-01. conf:medium.",
          [B3[1]]: "MODEL: reaction-transport reproduces inlet clogging, Da>1. evidence: ev://mo-02. conf:high.",
          [B3[2]]: "LCA: vs cement, urea+ammonia penalty, fair FU. evidence: ev://lca-04. conf:medium.",
        }
        for (const m of [...A3, ...B3]) {
          const s = yield* capture(claw.sealVerdict(cloudOfMember.get(m)! as never, m as never, r1[m]))
          const ok = s.kind === "ok" && (s.value as { members: Array<{ ref: { id: string }; sealedVerdict?: string }> }).members.some((x) => x.ref.id === m && x.sealedVerdict !== undefined)
          out(`  [sealed.${idShort(m)}] ${s.kind} sealed=${ok}`)
        }

        const clawInA = yield* capture(claw.openClaw(cloudA, A3[0] as never, A3[1] as never))
        out(`  [A.openClaw] ${clawInA.kind} claw=${clawInA.kind === "ok" ? (clawInA.value as { claw_session_id: string }).claw_session_id : clawInA.code}`)
        const clawAId = (clawInA as { kind: "ok"; value: { claw_session_id: string } }).value.claw_session_id
        const mA1 = yield* capture(claw.send(clawAId, { from: A3[0], to: A3[1], kind: "report", payload: "A sealed: NH4 mass-balance CRITICAL", evidence_refs: ["ev://NH4-02"] }))
        out(`  [A.report] ${mA1.kind}`)
        const mA2 = yield* capture(claw.send(clawAId, { from: A3[1], to: A3[0], kind: "challenge", payload: "B challenges NH4 reconciliation method", evidence_refs: ["ev://stat-01"] }))
        out(`  [A.challenge] ${mA2.kind}`)

        const clawInB = yield* capture(claw.openClaw(cloudB, B3[0] as never, B3[1] as never))
        out(`  [B.openClaw] ${clawInB.kind}`)
        const clawBId = (clawInB as { kind: "ok"; value: { claw_session_id: string } }).value.claw_session_id
        const mB1 = yield* capture(claw.send(clawBId, { from: B3[0], to: B3[1], kind: "report", payload: "field well-array scaling not linear", evidence_refs: ["ev://sc-01"] }))
        out(`  [B.report] ${mB1.kind}`)
        const mB2 = yield* capture(claw.send(clawBId, { from: B3[1], to: B3[0], kind: "challenge", payload: "inlet clogging vs scale coupling", evidence_refs: ["ev://mo-02"] }))
        out(`  [B.challenge] ${mB2.kind}`)

        const cross = yield* capture(
          claw.openClaw(cloudA, idByName.get("micp-data-analyst")! as never, idByName.get("obsidian-red-team")! as never),
        )
        out(`  [cross-cloud.A<->C.openClaw] ${cross.kind} ${cross.kind === "rejected" ? `${cross.code} | ${cross.message}` : (cross.value as { claw_session_id: string }).claw_session_id}`)
        const Cm = roster[2][2].map((t) => idByName.get(t)!)
        const clawInC = yield* capture(claw.openClaw(cloudC, Cm[0] as never, Cm[1] as never))
        out(`  [C.openClaw] ${clawInC.kind} claw=${clawInC.kind === "ok" ? (clawInC.value as { claw_session_id: string }).claw_session_id : clawInC.code}`)
        const clawCId = (clawInC as { kind: "ok"; value: { claw_session_id: string } }).value.claw_session_id
        const mC1 = yield* capture(claw.send(clawCId, { from: Cm[0], to: Cm[1], kind: "challenge", payload: "red-team challenges A's NH4 reconciliation", evidence_refs: ["ev://NH4-02", "ev://stat-01"] }))
        out(`  [C.challenge] ${mC1.kind}`)

        // ── PHASE 3: WALLS ───────────────────────────────────────────────
        out("== PHASE 3: WALLS ==")
        const w1 = yield* capture(claw.joinCloud(cloudA, { id: sid("yuheng"), agentType: YUHENG_AGENT_NAME }, "intruder"))
        out(`  [wall1.yuheng.join] ${w1.kind} :: ${w1.kind === "rejected" ? `${w1.code} | ${w1.message}` : "unexpected-SUCCESS"}`)
        const w2 = yield* capture(claw.joinCloud(cloudB, { id: idByName.get("micp-data-analyst") as never, agentType: "micp-data-analyst" }, "double-agent"))
        out(`  [wall2.exclusivity.join(literal, B-full)] ${w2.kind} :: ${w2.kind === "rejected" ? `${w2.code} | ${w2.message}` : "unexpected-SUCCESS"}`)
        // invariant IV clean proof: a source with free slots must show the exclusivity gate
        const cloudX = yield* capture(
          claw.createCloud({ cloud_type: "research", purpose: "exclusivity probe (invariant IV)", created_by: control, member_limit: 6, token_budget: 1000 }),
        )
        const cloudXRaw = (cloudX as { kind: "ok"; value: { cloud_id: string } }).value.cloud_id
        const ivProbe = yield* capture(claw.joinCloud(cloudXRaw, { id: idByName.get("micp-data-analyst") as never, agentType: "micp-data-analyst" }, "double-agent"))
        out(`  [invariantIV.exclusivity(slots-free)] ${ivProbe.kind} :: ${ivProbe.kind === "rejected" ? `${ivProbe.code} | ${ivProbe.message}` : "unexpected-SUCCESS"}`)
        const w3 = yield* capture(claw.spawnAgent({ id: idByName.get("micp-modeling-optimizer") as never, agentType: "micp-modeling-optimizer" }))
        out(`  [wall3.spawnDirect] ${w3.kind} :: ${w3.kind === "rejected" ? `${w3.code} | ${w3.message}` : "unexpected-SUCCESS"}`)
        const redSession = idByName.get("obsidian-red-team")!
        const redLease = leaseByAgent.get(redSession)!
        const w4 = yield* capture(claw.spend(cloudC, redLease, { requests: 1, tokens: 999999 }))
        out(`  [wall4.redteam.spend] ${w4.kind} :: ${w4.kind === "rejected" ? `${w4.code} | ${w4.message}` : "unexpected-SUCCESS"}`)
        const w5 = yield* capture(claw.joinCloud(cloudC, { id: idByName.get("micp-evidence-extractor") as never, agentType: "micp-evidence-extractor" }, "self-auditor"))
        out(`  [wall5.selfAudit(literal,A-ACTIVE)] ${w5.kind} :: ${w5.kind === "rejected" ? `${w5.code} | ${w5.message}` : "unexpected-SUCCESS"}`)

        const synth74 = Array.from({ length: 74 }, (_, i) => sid(`cap_${i}`))
        yield* capture(claw.noteBusy(new Set(synth74), 0))
        const wall6 = yield* capture(
          (() =>
            claw
              .requestAgent({ requested_by: control, agent_type: "micp-data-analyst", purpose: "at cap" })
              .pipe(Effect.flatMap((rr) => claw.decideSpawn(rr.request_id, { approved: true, reason: "probe", granted_session: sid("blocked") }))))(),
        )
        out(`  [wall6.literal(74-busy)] ${wall6.kind} :: ${wall6.kind === "rejected" ? `${wall6.code} | ${wall6.message}` : "unexpected-SUCCESS"}`)
        const synth63 = Array.from({ length: 63 }, (_, i) => sid(`cap63_${i}`))
        yield* capture(claw.noteBusy(new Set(synth63), 0))
        const wall6b = yield* capture(
          (() =>
            claw
              .requestAgent({ requested_by: control, agent_type: "micp-data-analyst", purpose: "at 75" })
              .pipe(Effect.flatMap((rr) => claw.decideSpawn(rr.request_id, { approved: true, reason: "probe", granted_session: sid("blocked63") }))))(),
        )
        out(`  [wall6.verified-75(63-busy+12leased)] ${wall6b.kind} :: ${wall6b.kind === "rejected" ? `${wall6b.code} | ${wall6b.message}` : "unexpected-SUCCESS"}`)
        yield* claw.noteBusy(new Set<SessionID>(), 0)
        const capRestored = yield* claw.capacity()
        out(`  capacity restored: zone=${capRestored.zone} busy=${capRestored.busy} background=${capRestored.background} leased=${capRestored.leased} active=${capRestored.active}`)

        out("  -- self-contradiction 1 (budget): follow 乙, reject 甲 --")
        const rNote = yield* capture(
          claw.send(clawBId, {
            from: B3[1], to: B3[0], kind: "verdict",
            payload: "CONTROL_RULING: directive-JIA (raise cloud B budget to 200000) violates IX, refused; per YI cloud B budget stays 90000, tokens_used unchanged.",
          }),
        )
        out(`  [budget-ruling.note] ${rNote.kind}`)
        const bLeaseForIx = leaseByAgent.get(B3[1])!
        const ixProbe = yield* capture(claw.spend(cloudB, bLeaseForIx, { requests: 1, tokens: 90000 }))
        out(`  [selfcontra1.IX.spend(90000 on lease-cap 30000)] ${ixProbe.kind} :: ${ixProbe.kind === "rejected" ? `${ixProbe.code} | ${ixProbe.message}` : "unexpected-SUCCESS"}`)

        out("  -- self-contradiction 2 (lifetime/rounds): keep C finite (III) --")
        const cCloud = yield* capture(claw.getCloud(cloudC))
        if (cCloud.kind === "ok") {
          const c = cCloud.value as { max_rounds: number; expires_at: number; status: string }
          out(`  cloud C record: max_rounds=${c.max_rounds} expires_at=${c.expires_at} status=${c.status} (finite; no API clears these)`)
          const Cnote = roster[2][2].map((t) => idByName.get(t)!)
          const clawCnote = yield* capture(claw.openClaw(cloudC, Cnote[1] as never, Cnote[2] as never))
          const clawCnoteId = (clawCnote as { kind: "ok"; value: { claw_session_id: string } }).value.claw_session_id
          for (let k = 0; k < 9; k++) {
            const rr = yield* capture(claw.send(clawCnoteId, { from: Cnote[1], to: Cnote[2], kind: "report", payload: `round ${k}` }))
            if (k >= 7) out(`  [selfcontra2.round-${k + 1}] ${rr.kind} :: ${rr.kind === "rejected" ? `${rr.code} | ${rr.message}` : ""}`)
          }
          const perma = yield* capture(claw.send(clawCnoteId, { from: Cnote[1], to: Cnote[2], kind: "report", payload: "permanent-residency request refused by governance boundary: finite lifetime + finite rounds (invariant III)" }))
          out(`  [selfcontra2.permanent-residency] ${perma.kind} :: ${perma.kind === "rejected" ? `${perma.code} | ${perma.message}` : "unexpected-SUCCESS"}`)
        }

        const vImm = yield* capture(claw.sealVerdict(cloudA, A3[0], "attempted overwrite"))
        out(`  [probe.verdict.immutable] ${vImm.kind} :: ${vImm.kind === "rejected" ? `${vImm.code} | ${vImm.message}` : "unexpected-SUCCESS"}`)

        // ── PHASE 4 ──────────────────────────────────────────────────────
        out("== PHASE 4: REVIEW / FINAL / COMPLETE / ARCHIVE / DESTROY ==")
        const beginC = yield* capture(claw.beginReview(cloudC))
        out(`  [C.beginReview] ${beginC.kind} status=${beginC.kind === "ok" ? (beginC.value as { status: string }).status : beginC.code}`)
        const beginD = yield* capture(claw.beginReview(cloudD))
        out(`  [D.beginReview] ${beginD.kind} status=${beginD.kind === "ok" ? (beginD.value as { status: string }).status : beginD.code}`)

        const C3 = roster[2][2].map((t) => idByName.get(t)!)
        const D3 = roster[3][2].map((t) => idByName.get(t)!)
        const finC: Record<string, string> = {
          [C3[0]]: "RED-TEAM(FINAL): A's CRITICAL NH4 mass-balance survives challenge; ev://NH4-02 stands. permanent-residency refused (invariant III). severity=BLOCKING until NH4 reconciled.",
          [C3[1]]: "MINERAL: A makes no polymorph claim; NH4 issue is chemical not mineral. Agree with A's NH4 flag.",
          [C3[2]]: "QC: no instrumentation defect in ev://NH4-02; reconciliation method sound. Corroborates A.",
        }
        const finD: Record<string, string> = {
          [D3[0]]: "DECISION-GATE(FINAL): NOT released. Cloud B field scale-up must first reconcile NH4 mass balance + pressure boundary (from cloud A CRITICAL and cloud C BLOCKING). status: SUPPORTED -> needs evidence, NOT PILOT_READY.",
          [D3[1]]: "REPRO(TECH): ev://NH4-02 raw effluent table missing, cannot rebuild -> not VALIDATED.",
          [D3[2]]: "ENV: NH4 N-balance broken => environmental release vetoed; must be corrected before re-review.",
        }
        for (const m of [...C3, ...D3]) {
          const s = yield* capture(claw.sealVerdict(cloudOfMember.get(m)! as never, m as never, finC[m] ?? finD[m]))
          out(`  [finalSeal.${idShort(m)}] ${s.kind}`)
        }

        const reportA = yield* capture(claw.auditReport(cloudA))
        const reportB = yield* capture(claw.auditReport(cloudB))
        const reportC = yield* capture(claw.auditReport(cloudC))
        const reportD = yield* capture(claw.auditReport(cloudD))
        out("  -- unified report A (evidence-first) --")
        out(reportA.kind === "ok" ? (reportA.value as string) : "(report A failed)")
        out("  -- unified report B --")
        out(reportB.kind === "ok" ? (reportB.value as string) : "(report B failed)")
        const unifiedA = reportA.kind === "ok" ? (reportA.value as string) : "(report A unavailable)"
        const unifiedB = reportB.kind === "ok" ? (reportB.value as string) : "(report B unavailable)"
        const unifiedC = reportC.kind === "ok" ? (reportC.value as string) : "(report C unavailable)"
        const unifiedD = reportD.kind === "ok" ? (reportD.value as string) : "(report D unavailable)"

        const doneA = yield* capture(claw.complete(cloudA, unifiedA))
        out(`  [A.complete] ${doneA.kind} status=${doneA.kind === "ok" ? (doneA.value as { status: string }).status : doneA.code} reportPreserved=${doneA.kind === "ok" ? (doneA.value as { final_report?: string })?.final_report !== undefined : false}`)
        const doneB = yield* capture(claw.complete(cloudB, unifiedB))
        out(`  [B.complete] ${doneB.kind} status=${doneB.kind === "ok" ? (doneB.value as { status: string }).status : doneB.code} reportPreserved=${doneB.kind === "ok" ? (doneB.value as { final_report?: string })?.final_report !== undefined : false}`)
        // invariant V clean proof: a FRESH audit cloud over A (slots free), after A completed,
        // still rejects A's executor via membership-history -> SELF_AUDIT_FORBIDDEN
        let v5: ActionResult = { kind: "rejected", code: "?not-run", message: "" }
        {
          const cloudV = yield* capture(
            claw.createCloud({ cloud_type: "audit", purpose: "self-audit probe (invariant V)", created_by: control, member_limit: 6, token_budget: 3000, audit_target: cloudA as never }),
          )
          const cloudVRaw = (cloudV as { kind: "ok"; value: { cloud_id: string } }).value.cloud_id
          v5 = yield* capture(claw.joinCloud(cloudVRaw, { id: idByName.get("micp-evidence-extractor") as never, agentType: "micp-evidence-extractor" }, "self-auditor-final"))
          out(`  [invariantV.selfAudit(after-A-COMPLETED)] ${v5.kind} :: ${v5.kind === "rejected" ? `${v5.code} | ${v5.message}` : "unexpected-SUCCESS"}`)
          yield* capture(claw.archive(cloudVRaw))
          yield* capture(claw.destroy(cloudVRaw))
        }
        const doneC = yield* capture(claw.complete(cloudC, unifiedC))
        out(`  [C.complete] ${doneC.kind} status=${doneC.kind === "ok" ? (doneC.value as { status: string }).status : doneC.code}`)
        const doneD = yield* capture(claw.complete(cloudD, unifiedD))
        out(`  [D.complete] ${doneD.kind} status=${doneD.kind === "ok" ? (doneD.value as { status: string }).status : doneD.code}`)

        for (const c0 of [cloudA, cloudB, cloudC, cloudD]) {
          const ar = yield* capture(claw.archive(c0))
          out(`  [archive.${c0}] ${ar.kind} status=${ar.kind === "ok" ? (ar.value as { status: string }).status : ar.code}`)
        }
        for (const c0 of [cloudA, cloudB]) {
          const d0 = yield* capture(claw.destroy(c0))
          out(`  [destroy.${c0}] ${d0.kind} status=${d0.kind === "ok" ? (d0.value as { status: string }).status : d0.code} reportPreserved=${d0.kind === "ok" ? (d0.value as { final_report?: string })?.final_report !== undefined : false}`)
        }
        const readA = yield* capture(claw.getCloud(cloudA))
        if (readA.kind === "ok") {
          const a = readA.value as { status: string; final_report?: string }
          out(`  verify X: getCloud(A) after destroy -> status=${a.status} reportPreserved=${a.final_report !== undefined}`)
        }

        // ── PHASE 5 ──────────────────────────────────────────────────────
        out("== PHASE 5: FULL CLAW LOG ==")
        const events = (yield* claw.log()) as Array<{ seq: number; type: string; cloud_id?: string; data: Record<string, unknown> }>
        for (const e of events) out(`  #${String(e.seq).padStart(3, "0")} ${e.type.padEnd(30)} ${e.cloud_id ?? "-"} ${JSON.stringify(e.data)}`)
        out(`== EVENTS: ${events.length} ==`)

        // assertions: enforcement must be real. Where the engine's own gate ordering
        // yields a DIFFERENT rejection than the task's "expected", we assert the
        // measured reality and record the discrepancy in the deliverable notes.
        expect(ca.kind).toBe("ok")
        expect(w1.kind === "rejected" ? (w1 as { code: string }).code : "SUCCESS").toBe("CONTROL_PLANE_ENTITY_CANNOT_JOIN_CLOUD")
        expect(w3.kind === "rejected" ? (w3 as { code: string }).code : "SUCCESS").toBe("SPAWN_NOT_PERMITTED")
        expect(w2.kind).toBe("rejected") // measured CLOUD_MEMBER_LIMIT_REACHED (B full), gate ordering
        expect(w5.kind).toBe("rejected") // measured CLOUD_MEMBER_LIMIT_REACHED (C full), gate ordering
        expect(ivProbe.kind === "rejected" ? (ivProbe as { code: string }).code : "SUCCESS").toBe("AGENT_ALREADY_IN_ACTIVE_CLOUD")
        expect(v5.kind === "rejected" ? (v5 as { code: string }).code : "SUCCESS").toBe("SELF_AUDIT_FORBIDDEN")
        expect(events.some((e) => e.type === "cloud.created")).toBe(true)
        expect(events.some((e) => e.type === "cloud.member.verdict_sealed")).toBe(true)
        expect(events.some((e) => e.type === "claw.message")).toBe(true)
        expect(events.some((e) => e.type === "cloud.destroyed")).toBe(true)
      }),
    120_000,
  )
})
