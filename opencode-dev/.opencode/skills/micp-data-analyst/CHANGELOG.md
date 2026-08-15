# Changelog — micp-data-analyst

Version policy: semantic versioning on the **contracts** — schemas, error-code
table, tool exit codes (see `skill.yaml` `version_policy`).

## [1.0.0] — 2026-08-06

Initial shipping release.

### Added
- **Skill package** under `skills/micp-data-analyst/`:
  - `SKILL.md` with OpenCode frontmatter (`name`, `description`), triggers
    (7 positive, 4 negative, 4 boundary), workflow, tool table, stop rules,
    error-code table, version policy, performance indicators.
  - `skill.yaml` machine-readable manifest: version, compatibility
    (OpenCode ≥ 0.1.0, Python ≥ 3.10, offline), permissions (network:false,
    fs_write:audit only), entry points, capabilities, units, stop conditions,
    version policy.
  - `prompts/system.md`: minimal system prompt (identity, workflow, boundaries,
    epistemic discipline, stop rules, error-code table, MICP guardrails,
    trigger/boundary examples).
  - `schemas/input.schema.json`, `schemas/output.schema.json` (both draft
    2020-12, within the supported validator subset).
- **Tools** (`tools/micp/`, stdlib-only, offline, deterministic, envelope
  contract `{ok, tool, version, result|error}`, exit 0/2/3/4):
  - `_common.py` — envelope, numeric/type guards, non-finite rejection.
  - `_jsonschema.py` — JSON Schema 2020-12 subset validator (audited).
  - `_numerics.py` — norm/t/F/chi-square via Acklam + A&S + NR, verified against
    known quantiles.
  - `errors.py` — MDA-E### error taxonomy (single source of truth).
  - `qc.py` — schema/unit/missing/range/time/batch/independence checks +
    pseudo-replication detection (unit resolution: column `sampling_unit` >
    `batch` > `id`).
  - `stats.py` — descriptive, t CI, normality screen (n<8 no-power), outlier
    policies, Hedges' g, power, OLS, one-way ANOVA, spatial uniformity,
    reproducibility hash.
  - `service.py` — full pipeline (validate → version gate → preconditions →
    qc → stats → findings with epistemic tags → self-check → unified envelope).
  - `cli.py` — stdin/stdout entry for `service | qc | stats | validate`.
- **Tests** (`tests/`): unit (stats/qc/service), integration (full pipeline),
  failure (malformed/conflicting/adversarial), regression (determinism),
  schema-subset guard. Offline; run with `python -m pytest tests/`.
- **Evals** (`evals/`): `cases.yaml` (10 cases: positive/conflict/adversarial/
  boundary/missing) and offline `run_evals.py` measuring the seven minimum
  performance indicators from `skill.yaml`.
- **Examples** (`examples/`): three runnable end-to-end invocations
  (01 clean+infer, 02 pseudo-replication sensitivity, 03 blocked-input).
- **Docs**: `references/sources.md` (sources, access dates, usage, key
  limitations), `tools/README.md` (tool contracts), this changelog.

### Compatibility
- Input/output schemas at contract version 1.0.0; `provenance.skill_version`
  must be `1.0.0`. `MDA-E801` guards older/newer artifacts.
- Error-code taxonomy at MDA-E1xx..E9xx; stable — never renumber, only append.

### Known limitations (not fixed in this release)
- Normality screening is approximate for n in [8, 30) and refuses to certify at
  n < 8 (see references S9). Confirm with model diagnostics for critical
  decisions.
- Mixed-effects, response-surface, multi-objective, and full time-series models
  are routed to `obsidian-modeling-optimizer` via `NEED_ADDITIONAL_SKILL`, not
  implemented in this skill.
- Visualization assets are declared in the output contract; PNG/HTML renderers
  are stubbed to be provided by a companion rendering skill in a later release.
- Power estimates use a normal approximation to the noncentral t (planning
  grade); simulate for critical decisions.

### Migration
- No prior versions exist; nothing to migrate. Future breaking changes will be
  documented here.
