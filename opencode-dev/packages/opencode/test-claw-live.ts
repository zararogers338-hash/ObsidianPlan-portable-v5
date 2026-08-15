#!/usr/bin/env bun
/**
 * 在同一个进程内：派生 agent → 查看 Claw 治理日志
 */
import { Effect, Layer } from "effect"
import { layer as ClawManagerLayer, Service as ClawManager } from "./src/claw/manager"
import { SessionID } from "./src/session/schema"

const program = Effect.gen(function* () {
  const claw = yield* ClawManager

  console.log("\n=== Step 1: Check initial Claw status ===")
  const cap1 = yield* claw.capacity()
  console.log(`Initial capacity: zone=${cap1.zone} active=${cap1.active}`)

  console.log("\n=== Step 2: Create a test cloud ===")
  const cloud = yield* claw.createCloud({
    cloud_type: "compute",
    purpose: "test multi-agent spawn",
    created_by: { session: SessionID.make("ses_control"), agentType: "build" },
    member_limit: 5,
    token_budget: 50000,
  })
  console.log(`Cloud created: ${cloud.cloud_id}`)

  console.log("\n=== Step 3: Request spawn permission ===")
  const ref = {
    id: SessionID.make("ses_test_live_1"),
    agentType: "general",
  }

  const req = yield* claw.requestAgent({
    requested_by: { session: SessionID.make("ses_control"), agentType: "build" },
    agent_type: ref.agentType,
    purpose: "test agent spawn",
    for_cloud: cloud.cloud_id,
  })
  console.log(`Spawn request: ${req.request_id}`)

  console.log("\n=== Step 4: Control plane approves ===")
  const decision = yield* claw.decideSpawn(req.request_id, {
    approved: true,
    granted_session: ref.id,
  })
  console.log(`Decision: approved=${decision.approved}`)

  console.log("\n=== Step 5: Agent joins cloud ===")
  const fullRef = { id: ref.id, agentType: ref.agentType }
  yield* claw.joinCloud(cloud.cloud_id, fullRef, "worker")
  console.log(`Agent ${fullRef.id} joined cloud ${cloud.cloud_id}`)

  console.log("\n=== Step 6: Activate cloud ===")
  yield* claw.activate(cloud.cloud_id)
  console.log(`Cloud ${cloud.cloud_id} activated`)

  console.log("\n=== Step 7: Check capacity after spawn ===")
  const cap2 = yield* claw.capacity()
  console.log(`After spawn: zone=${cap2.zone} active=${cap2.active} (busy=${cap2.busy} leased=${cap2.leased})`)

  console.log("\n=== Step 8: Get governance log ===")
  const events = yield* claw.log()
  console.log(`\nGovernance events (${events.length} total):\n`)
  events.forEach((e, i) => {
    console.log(`[${String(i).padStart(3, "0")}] ${e.type} :: ${e.cloud_id ?? "N/A"} | ${e.message}`)
  })

  console.log("\n=== Step 9: Complete cloud ===")
  yield* claw.complete(cloud.cloud_id, { summary: "test completed" })
  console.log(`Cloud ${cloud.cloud_id} completed`)

  console.log("\n=== Final capacity ===")
  const cap3 = yield* claw.capacity()
  console.log(`Final: zone=${cap3.zone} active=${cap3.active}`)
})

const main = program.pipe(
  Effect.provide(Layer.fresh(ClawManagerLayer)),
  Effect.runPromise,
)

main.catch((e) => {
  console.error("Program failed:", e)
  process.exit(1)
})
