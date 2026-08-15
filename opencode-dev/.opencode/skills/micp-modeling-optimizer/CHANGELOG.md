# CHANGELOG

## 1.0.0 — 2026-08-07

Initial delivery of `micp-modeling-optimizer` (MICP 机理建模、参数反演与多目标优化器).

### Added
- **Engine (tools/micp/)**: closed-form implicit-Euler kinetic-system solver
  (ureolysis MM/first-order, precipitation limiting-reactant/saturation-driven,
  biomass decay, Kozeny–Carman/Verma–Pruess/power-law permeability), multi-start
  least-squares fitting with Fisher-information and profile-likelihood
  identifiability, Sobol'/Morris global sensitivity, DOE (full factorial / CCD /
  Box–Behnken / LHS) + quadratic response surfaces, EGO Bayesian optimization,
  NSGA-II multi-objective with robustness, Monte-Carlo UQ, conservation /
  numerical-stability / grid-step-sensitivity self-checks, HTML/SVG reporting.
- **CLI**: `tools/modeling.py` stdin/stdout envelope with actions
  solve / fit / analyze / optimize / multiobjective / sensitivity / uq / doe /
  validate, plus `schema` and `selfcheck` subcommands.
- **Contract**: `schemas/input.schema.json`, `schemas/output.schema.json`,
  `schemas/model-spec.schema.json`, `schemas/optimization-result.schema.json`.
- **Engineering package**: SKILL.md, skill.yaml, manifest.json, README.md,
  prompts/system.md, references/sources.md, CHANGELOG.md.
- **Tests**: pytest suite covering the 10 mandatory acceptance tests
  (spec §九) plus unit/integration/failure/regression/router-integration layers.
- **Evals**: cases.yaml + run_evals.py + metrics.md measuring M1–M7.
- **Examples**: runnable payloads for every action.
- **Bootstrap & red-team**: work/ scripts, audit/ artifacts,
  references/bootstrap-log.md.

### Notes
- Determinism: all stochastic processes are seeded from
  `constraints.random_seed`; same input reproduces byte-for-byte (M6).
- Offline: numpy/scipy/jsonschema are optional accelerators; every module has a
  documented stdlib fallback.
- Router: skill.yaml declares `capabilities: ["modeling", ...]` (bare token the
  planner maps from `建模|数值模拟|优化|...`), making the skill routable.
