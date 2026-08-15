# Eval metrics — micp-reproducibility-versioning

The seven minimum performance indicators (M1–M7) implemented in
`evals/run_evals.py`, driven by `evals/cases.yaml`.

## Measurement

| # | Indicator | Measurement | Hard threshold |
|---|---|---|---|
| M1 | structured_output_pass_rate | every SUCCESS/PARTIAL case output validates against `schemas/output.schema.json` (project's own draft-2020-12 subset validator) | ≥ 0.95 |
| M2 | tool_invocation_rate | each case is executed by invoking the real `cli.py` subcommand over stdin — never narrated | = 1.0 (invariant) |
| M3 | evidence_traceability_rate | every `evidence_used.ref_id` in outputs exists in the input `evidence_refs`/`data_refs` | ≥ 0.9 |
| M4 | missing_input_detection_rate | `missing`/`without` cases must yield `BLOCKED` with per-field `missing_inputs` (field → why → how) | = 1.0 |
| M5 | adversarial_interception_rate | adversarial cases (writable raw, path escape, fabricated version, pollution) must be intercepted or surfaced, never silently pass | = 1.0 |
| M6 | repeat_run_consistency | first case run twice through the real CLI; byte-identical JSON envelope required | = 1.0 (deterministic tools) |
| M7 | mean_failure_recovery_time | wall time per case (stdin → result); reported as mean over all cases | ≤ 1 round (baseline) |

## Cases (12)

1. positive/manifest-generation — data manifest with layer classification.
2. positive/environment-collection — OS/runtime/tools/locks/git-or-fingerprint.
3. positive/dependency-lock — passive lock export, never executes a package manager.
4. positive/seed-management — deterministic seed + PCG preview.
5. positive/reproduce-roundtrip — full manifest→lock→record→run→persist→rerun loop.
6. positive/diff-identical — two identical runs diff as identical.
7. boundary/missing-commands — reproduce without commands → BLOCKED.
8. boundary/missing-baseline — diff without baseline → BLOCKED.
9. adversarial/writable-raw — raw write protection breach → MRV-E501.
10. adversarial/path-escape — `../escape` target → clean MRV-E302 envelope.
11. adversarial/fabricated-version — skill_version 2.0.0 → MRV-E801.
12. adversarial/pollution-after-overwrite — manual overwrite → pollution_detected.

## Determinism & offline discipline

- All cases run against fresh temp sandboxes (no shared state, no network).
- Placeholders (`SANDBOX_ROOT`, `EVAL_SUMMARY_CMD`, …) are substituted by the
  runner; the real `cli.py` subcommands execute the work.
- The only RNG in the toolset is seed-driven (PCG32/splitmix64); timestamps are
  taken from the input `timestamp` field, so reruns are byte-identical.
