# Changelog — micp-reproducibility-versioning

All notable changes to this skill package. Follows [Keep a Changelog](https://keepachangelog.com/) and
Semantic Versioning: breaking contract changes bump the major version, backward-compatible additions
bump the minor, and non-contract implementation fixes bump the patch.

## [1.0.0] — 2026-08-07

### Added
- **Skill package** at `skills/micp-reproducibility-versioning/`:
  `SKILL.md`, `skill.yaml`, `manifest.json`, `README.md`, `prompts/system.md`,
  `references/sources.md`, `examples/`, `CHANGELOG.md`.
- **Contract schemas** (draft 2020-12): `schemas/input.schema.json`,
  `schemas/output.schema.json`, `schemas/reproduction-manifest.schema.json`,
  `schemas/provenance-event.schema.json`. Envelope follows the unified 12-field
  contract; statuses and epistemic tags per Obsidian Plan conventions.
- **Toolset** `tools/mrv/` (pure stdlib Python ≥ 3.10, offline, deterministic,
  stdin/stdout JSON envelope, exit 0/2/3/4):
  - hashing (SHA-256 file / deterministic directory tree / sorted-members manifests)
  - `manifest` — data-manifest generator with data-layering rules (raw/interim/processed/external)
  - `env` — environment collector (OS, runtime, tools, dependency-lock summaries, git/fingerprint)
  - `lock` — dependency export & lock (pip/pnpm/bun/npm/git detection, resolved lockfile)
  - `seed` — random-seed manager (generate/reuse/require; splitmix64 + PCG, deterministic)
  - `record` — input/output provenance recorder (append-only audit log with hash-chaining)
  - `diff` — result diff comparator (JSON deep compare + hash compare + report)
  - `compat` — version compatibility checker (semver major/minor/patch + compatibility matrix)
  - `migrate` — schema migrator (per-lineage migration chains, transactional)
  - `check-raw` — raw-data write-protection checker
  - `check-pollution` — artifact-pollution detector (guardrail tamper detection)
  - `reproduce` — one-shot reproduction pipeline (manifest → lock → record inputs →
    run commands → record outputs → persist → rerun → compare → diff report)
  - `validate` — input schema validation only
  - `service` — full pipeline orchestrator
- **Error taxonomy** `MRV-E1xx…E9xx` (input / integrity / context / dependency /
  policy / capability / self-check / version / engine).
- **Tests** `tests/`: unit, failure, regression, schema-subset, router-integration,
  and the **10 mandatory scenarios** (fresh temp env, parameter-change trace,
  raw-data tamper, dependency-upgrade drift, missing seed, schema major break,
  mid-run crash recovery, repeat-run byte-identical, external-source snapshot
  fallback, manual-overwrite hash detection).
- **Evals** `evals/`: `cases.yaml` + `run_evals.py` (offline, real CLI subprocess,
  M1–M7 indicators) + `metrics.md` + `bootstrap/run_bootstrap.py` (self-bootstrap
  reproduction: real end-to-end manifest → lock → run → rerun → hash-compare loop).
- **Router registration**: `skill.yaml` `capabilities: ["reproducibility", …]`
  matches the router's `reproducibility` bare capability token (already declared
  in `obsidian-skill-router/tools/osr/planner.ts`); registry indexes the skill as
  `usable` and the planner routes a reproducibility request to it.

### Notes
- The `opencode-dev` repository is **not** a git repository. All versioning tools
  detect git and fall back to a deterministic directory fingerprint when absent,
  and record the absence as a risk. A `git init` is recommended for long-lived
  MICP studies.
- No `data/` layered tree exists at the repo root yet; the skill scaffolds one
  with `reproduce`/`init` and the bootstrap demo materializes the full
  `data/raw → processed` chain under its sandbox.
