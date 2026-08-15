# Changelog — obsidian-task-decomposer

Version policy: semantic versioning on the **contracts** — schemas, error-code
table, tool exit codes (see `skill.yaml` `version_policy`).

## [1.0.0] — 2026-08-06

Initial shipping release.

### Added
- **Skill package** under `.opencode/skills/obsidian-task-decomposer/`:
  - `SKILL.md` with OpenCode frontmatter (`name`, `description`), triggers
    (6 positive, 4 negative, 4 boundary), workflow, tool table, stop rules.
  - `skill.yaml` machine-readable manifest: version, compatibility
    (OpenCode ≥ 0.1.0, Python ≥ 3.10, offline), permissions (network:false,
    fs_write:false, ltm_write:false), entry points, schema paths, version
    policy, minimum performance indicators.
  - `prompts/system.md`: minimal system prompt (identity, workflow,
    boundaries, epistemic discipline, stop rules, error-code table, MICP
    guardrails, trigger/boundary examples).
  - `schemas/input.schema.json`, `schemas/output.schema.json`,
    `schemas/task-node.schema.json` (all draft 2020-12, within the supported
    validator subset).
- **Tools** (`tools/`, stdlib-only, offline, deterministic, envelope contract):
  - `validate.py` — schema validation via local `_jsonschema.py`.
  - `dag_check.py` — Kahn topo sort, cycle evidence, unknown deps, levels.
  - `granularity_scorer.py` — per-node verdicts (TOO_FINE/OK/TOO_COARSE/
    UNDER_SPECIFIED) with issues and suggestions.
  - `budget_estimator.py` — reference-class effort/cost (planning-fallacy
    guard; method cited in references/sources.md S5).
  - `critical_path.py` — CPM forward/backward pass, slack, parallelism
    (method S6).
  - `replan_diff.py` — local replan; preserves confirmed facts and completed
    work, flags stale completed nodes, validates merged graph.
  - `self_audit.py` — acceptance gates G1–G6.
- **Tests** (`tests/`): unit, integration, failure, regression, and
  `test_schema_subset.py` (proves our schemas stay inside the supported
  validator subset).
- **Evals** (`evals/`): `cases.yaml` (≥8 cases incl. adversarial/conflict/
  boundary/malformed) and offline `run_evals.py` measuring the seven minimum
  performance indicators from `skill.yaml`.
- **Examples** (`examples/`): three runnable end-to-end invocations
  (01 basic MICP DAG, 02 replan-after-failure, 03 blocked-input).
- **Docs**: `references/sources.md` (sources, access dates, usage, key
  limitations), `tools/README.md` (tool contracts), this changelog.

### Compatibility
- Input/output/task-node schemas at version 1.0.0; `provenance.skill_version`
  must be `1.0.0`. `E_VERSION_MISMATCH` guards older/newer artifacts.

### Known limitations (not fixed in this release)
- Reference-class budgets and slack are `CALCULATED` estimates, not promises
  (sources S5/S6).
- `self_audit` proves mechanical gates, not research-quality — adversarial
  content review belongs to `obsidian-red-team`.
- File-list enumeration by OpenCode's `skill` tool is sampled; the skill
  references all needed files by relative path instead of relying on
  enumeration.

### Migration
- No prior versions exist; nothing to migrate. Future breaking changes will be
  documented here.
