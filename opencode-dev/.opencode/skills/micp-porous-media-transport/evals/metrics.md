# Performance metrics — micp-porous-media-transport

Minimum performance indicators (spec §十一) with measurement method and
threshold. All metrics are measured by `evals/run.py` against the **real CLI**
(subprocess), never mocks.

| ID | Metric | Measurement method | Threshold |
|---|---|---|---|
| M1 | Structured-output pass rate | every CLI output validated against `schemas/output.schema.json`; pass_rate = passes / total | ≥ 0.95 |
| M2 | Tool real-call rate | the eval runner only ever invokes `tools/transport.py` (real solver pipeline); invariant by construction | = 1.0 |
| M3 | Citation/data traceability | `evidence_refs` / `data_refs` supplied in input must appear in output `evidence_used` | ≥ 0.9 |
| M4 | Missing-input recognition rate | for each missing required scenario field, BLOCKED with OPM-E102 and the field named in `detail.missing_fields` | = 1.0 |
| M5 | Adversarial interception rate | contract-v2, unknown action, unit conflict, non-finite values — all blocked (no illegal SUCCESS) | = 1.0 |
| M6 | Repeated-run consistency | identical input run twice → identical `mass_balance` block (deterministic solver) | = 1.0 |
| M7 | Mean failure-recovery rounds | number of currently failing eval cases (each needs ≥ 1 fix round) | ≤ 1 |

## Measurement locations

- `evals/run.py` — runs `cases.yaml` through the real CLI, computes M1–M7.
- `evals/metrics.py` — `measure(suite_report)` → per-metric report with `pass`.
- `evals/results/latest.json` — written on every run.

## Interpretation

- M1, M4, M5 guard the contract and safety surface; any drop means the skill
  stops parsing or fabricates.
- M2 is a structural invariant: there is no mock path in the evals.
- M3 requires the caller to pass `evidence_refs`; the service echoes them into
  `evidence_used` (see `service.py` `_envelope`).
- M6 relies on the solver being deterministic (no randomness, no wall-clock in
  the computation; only `timestamp`/`host` provenance differ between runs).
- M7 is a process metric: failing cases must be fixed within one review round.
