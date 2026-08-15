# Metrics — micp-modeling-optimizer evals (M1–M7)

| ID | Metric | Measurement method | Threshold |
|---|---|---|---|
| M1 | Structured-output pass rate | every CLI output validated against `schemas/output.schema.json`; pass_rate = passes / total | ≥ 0.95 |
| M2 | Tool real-call rate | the eval runner only ever invokes `tools/modeling.py` (real solver/optimizer pipeline); invariant by construction | = 1.0 |
| M3 | Citation/data traceability | `evidence_refs` / `data_refs` supplied in input appear in output `evidence_used` | ≥ 0.9 |
| M4 | Missing-input recognition rate | for each missing required field, BLOCKED with MMO-E101/E102 and the field named in `missing_inputs` | = 1.0 |
| M5 | Adversarial interception rate | unknown action, bad contract version, unknown kinetics model, missing spec — all blocked (no illegal SUCCESS) | = 1.0 |
| M6 | Repeated-run consistency | identical input run twice → identical output (deterministic tools; provenance timestamps stripped) | = 1.0 |
| M7 | Mean failure-recovery time | mean wall-clock ms for a malformed-payload recovery (5 runs) | ≤ 2000 ms |

Measurement location: `evals/run_evals.py` (subprocess-driven, real CLI) +
`evals/metrics.py` (threshold computation). Results written to
`evals/results/latest.json`.

## Interpretation

- **M2 is a structural invariant**: there is no mock path in the suite — every
  case drives the real CLI over stdin/stdout.
- **M6 relies on determinism**: all stochastic processes (multi-start guesses,
  Saltelli sampling, MC perturbation, GP init, NSGA-II mutation) are seeded
  from `constraints.random_seed`; only the `provenance` timestamps differ
  between runs and are stripped before comparison.
- **M4** counts a case as detected when the field name appears in the error
  detail or `missing_inputs`.
