# Changelog

## 1.0.0 — 2026-08-06

Initial release of `micp-porous-media-transport` as a governed Obsidian Plan skill.

### Added

- `SKILL.md`: trigger/non-trigger/boundary cases (6 positive, 4 negative, 4 boundary), capability boundaries, input/output contract, error-code table, performance metrics, version policy.
- `skill.yaml`: machine-readable manifest (entry, dependencies, permissions, compatibility, cost estimate).
- `schemas/input.schema.json` + `schemas/output.schema.json`: strict draft-2020-12 contracts (`additionalProperties: false`).
- `prompts/system.md`: minimal system prompt (identity, boundaries, epistemic labels, stop rules).
- `tools/`:
  - `micp/errors.py` — OPM-E### error taxonomy (input/evidence/context/tooling/approval/capability/self-check/compat).
  - `micp/models.py` — constants, statuses, epistemic labels, stoichiometry.
  - `micp/units.py` — quantity/unit/range validation with SI normalization.
  - `micp/dimensionless.py` — Péclet / Damköhler / residence-time analysis.
  - `micp/solver.py` — deterministic 1D operator-splitting reactive-transport solver (upwind advection, central dispersion, implicit-Euler ureolysis + precipitation, Kozeny-Carman clogging feedback, flux/head BCs, mass accounting).
  - `micp/clogging.py` — clogging criteria (porosity / K-K0) + propensity ranking.
  - `micp/validate.py` — conservation / stoichiometry / finiteness / grid-sensitivity checks + schema validation.
  - `micp/scenario.py` — scenario normalization (raw dict -> SI solver config, MODEL_BLOCKED on missing boundary conditions).
  - `micp/service.py` — MicpService facade (the action pipeline).
  - `micp/observability.py` — JSON-lines logging with bounded ring buffer.
  - `transport.py` — stdin/stdout CLI adapter.
- `tests/`: unit, integration (real CLI), failure, regression suites.
- `evals/`: `cases.yaml` (normal/missing/conflict/adversarial/boundary), `metrics.py`, `run.py`.
- `examples/`: 3 runnable invocation examples.
- `references/sources.md`: domain + implementation sources with confidence labels.
- `README.md`, `CHANGELOG.md`.

### Verified

- Constant-flux and constant-head scenarios reproduce, clogging detection fires at the porosity threshold, MODEL_BLOCKED returns per-field guidance for missing porosity/flow, conservation residuals < 2% and grid sensitivity < 5% on reference cases.

### Known limitations

- 1D continuum; carbonate single-species surrogate; constant biomass; dispersion default `0.1·u·L`. See README §已知限制.
