# Changelog

All notable changes to `obsidian-experiment-designer` are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.0.0] - 2026-08-06

### Added
- Initial release. First version of the experiment-designer skill for the
  Obsidian Plan / Panshi research core.

### Skill contract
- `schemas/input.schema.json` — controller envelope (task_id, request,
  hypothesis_card, design, constraints, approval state, versions).
- `schemas/output.schema.json` — machine-readable result envelope (status,
  design, sop, preregistration, validation, provenance, errors) with
  epistemic labels and `OED-E####` error codes.

### Tools (deterministic, offline, stdlib-first Python >= 3.10)
- `doe_power.py` — two-group means (t-test), two-group proportions (z-test),
  one-way ANOVA; power/sample-size and finite-budget trade-offs; scipy
  optional (exact distributions) with documented normal-approx fallback.
- `randomizer.py` — complete/blocked randomization with FNV-1a-derived seed,
  opaque experiment-number generation, allocation checksum.
- `quantity_calc.py` — molar-mass reagent math, mass-concentration math,
  C1·V1=C2·V2 dilution; unit/dimension checked via `unit_validate`.
- `sop_check.py` — SOP generation and structural consistency checking
  (negative/positive controls, replicates, endpoints, exclusion rules,
  stop conditions, MICP ammonium/N-balance discipline).
- `preregister.py` — preregistration draft + raw-data CSV template.
- `validate.py` — schema validation (bundled schemas or inline) via the
  skill's minimal JSON-Schema subset validator.

### Engineering
- `tools/_common.py` — envelope protocol, numeric guards, ToolError taxonomy.
- `tools/jsonschema_subset.py` — auditable draft-2020-12 subset validator.
- `tools/unit_validate.py` — dimensional unit engine (SI bases + MICP units).
- Deterministic-by-construction: identical input -> identical output.
- Offline-capable: all tests run without network.
