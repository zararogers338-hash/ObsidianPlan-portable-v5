# Changelog — obsidian-red-team

All notable changes to the obsidian-red-team skill package.

Format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/);
versioning follows the project convention (breaking→major, optional add→minor,
implementation fix→patch). Contracts live in `schemas/`.

## [1.0.0] — 2026-08-07

### Added

- **Skill package** (`skills/obsidian-red-team/`): SKILL.md, skill.yaml, manifest.json,
  README.md, prompts/system.md, schemas (input/output/finding), tools/, tests/,
  evals/ (cases.yaml + metrics.py + run_evals.py), examples/, references/sources.md.
- **Ten mandatory attack dimensions** with explicit per-review coverage reporting
  (skipped dimensions must be declared, silence is a MAJOR finding).
- **Severity grading** INFO / MINOR / MAJOR / CRITICAL / BLOCKING with a finding
  contract (`schemas/finding.schema.json`) requiring evidence, why, strongest
  counterexample, required fix, and a verification method for the fix.
- **Blocking rule engine** (`tools/ort/blocking_rules.py`): 10 deterministic
  BLOCKING rules (fabricated citations, ammonia exceedance still deployable,
  open blocker + escalation, mass-balance violation, pseudo-replication carrying
  the key conclusion, unverified regulations with field release, engineering
  blocker + release, state escalation, permission boundary crossing, epistemic
  escalation supporting deployment). Single source of truth for BLOCKING.
- **15 adversarial evaluation cases** (fabricated paper, DOI/title mismatch,
  OD600-as-urease, total-CaCO3-as-effective-bridge, multi-point-as-independent-
  samples, missing control, significant-but-tiny-effect, mass-balance violation,
  same-data calibration+validation, small-column-to-field extrapolation,
  strength-up-permeability-down, ammonia exceedance, unverified regulations,
  open-blocker escalation, out-of-scope long-term-knowledge write).
- **13+ tools**: citation verifier, provenance/evidence-chain checker, unit &
  dimension checker, mass-balance checker, statistical-structure checker,
  pseudo-replication detector, model-boundary checker, escalation checker,
  permission-boundary checker, counterexample generator, severity scorer,
  blocking rule engine, fix-retest verifier (+ validate / review / check-self).
- **System integration**: router capability token `red_team` (already reserved in
  `planner.ts` DOMAIN_MAP and UPSTREAM_HINTS); high/critical risk forces
  `obsidian-red-team → obsidian-decision-gate` chain; state-manager
  `review.request`/`review.complete` already route to this skill; BLOCKING forces
  state upgrade rejection (SUPPORTED→VALIDATED→PILOT_READY→DEPLOYABLE).
- **Bootstrap**: adversarial review of a real repository artifact, then a
  self-review of the review (strongest-counterexample completeness, generic
  advice, wrong blocking, evidence location, executable fixes), fixes applied
  and re-run. Logs under `evals/bootstrap/`.

### Security properties

- Red Team is **read-only** (`tool_permissions: [read]`, `network: false`,
  `writes: audit/**`); it may never mutate the audited conclusion, data, or
  long-term knowledge base.
- BLOCKING findings force `state_recommendation ∈ {REVIEW_FAIL, HOLD}` and a
  non-SUCCESS status; the engine is deterministic and offline.

### Known limitations

- Citation verification is offline and structural: it checks DOI format,
  resolvability pattern, title/DOI consistency, and reference-chain integrity,
  not the full-text contents of a paywalled paper. Network verification is a
  recommended follow-up (`verification_required` flags are emitted).
- Ammonia/regulatory limits are read from a bundled default table
  (`references/sources.md`) and must be overridden by the caller when a specific
  jurisdiction applies; a deployment with no applicable-limit source is flagged.
- Bootstrap artifacts are illustrative reviews of repository material; they are
  not legal or engineering certification.
