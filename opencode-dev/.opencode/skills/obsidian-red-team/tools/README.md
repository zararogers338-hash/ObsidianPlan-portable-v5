# obsidian-red-team tools

Pure Python 3.10+ standard library. Offline, deterministic, no hardcoded
paths. Every tool reads ONE JSON envelope on stdin and writes ONE JSON
envelope on stdout; progress goes to stderr.

## Envelope

```json
{"ok": true,  "tool": "citation", "version": "1.0.0", "result": {...}}
{"ok": false, "tool": "cli",      "version": "1.0.0", "error": {...}}
```

Exit codes: `0` success · `2` input/validation · `3` contract/graph ·
`4` internal.

## Tool table

| Tool | Module | Purpose |
|---|---|---|
| `review` | `service.py` | Full adversarial-review pipeline (validate→version→ten dimensions→severity→blocking→counterexamples→fixes→self-check) |
| `validate` | `service.py` | Input-schema validation only |
| `citation` | `citation.py` | Citation verifier: DOI format, fabrication candidates, year, chain |
| `provenance` | `provenance.py` | Evidence source-chain checker: claim→citation→primary source |
| `units` | `units.py` | Unit/dimension checker: quantity-vs-unit, magnitude, false precision |
| `balance` | `balance.py` | Mass/element-balance checker with tolerance |
| `stats` | `stats.py` | Statistical-structure checker: p-only, tiny-effect, selective reporting, assumptions |
| `pseudo` | `pseudo.py` | Pseudo-replication detector (sampling_unit→batch→id→position→time) |
| `modelcheck` | `modelcheck.py` | Model boundary checker: BCs, identifiability, same-data cal/val, scale overflow |
| `escalation` | `escalation.py` | State-escalation checker (SUPPORTED→VALIDATED→PILOT_READY→DEPLOYABLE gates) |
| `permissions` | `permissions.py` | Permission-boundary checker (long-term writes, audited mutation, scope) |
| `counterexamp` | `counterexamp.py` | Counterexample generator + alternative explanations (HYPOTHESIS-tagged) |
| `severity` | `severity.py` | Severity scorer (INFO/MINOR/MAJOR/CRITICAL/BLOCKING) with transparent rules |
| `blocking` | `blocking_rules.py` | Blocking rule engine (BLOCK-1..10, single source of truth) + state recommendation |
| `retest` | `retest.py` | Fix re-test verifier: executable + falsifiable acceptance |
| `check-self` | `check_self.py` | Output self-check against `schemas/output.schema.json` (incl. BLOCKING invariants) |

## Error codes

`ORT-E###`, layout documented in `errors.py` (1xx input · 2xx evidence/units ·
3xx context · 4xx tooling · 5xx approvals/permissions · 6xx downstream ·
7xx self-check · 8xx compatibility · 9xx schema engine).

## Conventions

- `common.py` is the only place that touches stdout/stderr plumbing besides
  `cli.py`; every tool module exposes `main(payload) -> dict`.
- RNG-free and clock-injected: outputs are byte-reproducible for identical
  inputs (M6).
- `blocking_rules.py` is the single source of truth for BLOCKING; any new rule
  must be added there and mirrored in `models.BlockingRuleId`.
