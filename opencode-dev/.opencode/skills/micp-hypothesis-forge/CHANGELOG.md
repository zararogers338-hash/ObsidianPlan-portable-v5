# CHANGELOG

All notable changes to **micp-hypothesis-forge** are recorded here. Format:
[Keep a Changelog](https://keepachangelog.com/en/1.0.0/); version policy:
semantic (`skill.yaml` `version_policy`).

## [1.0.0] — 2026-08-06

Initial governed-skill release.

### Added
- **SKILL.md** — identity, 6 positive triggers, 4 negative triggers, 4 boundary
  cases, error-code table, stop rules, version.
- **skill.yaml** — machine manifest (project-custom), entry points, schemas,
  semantic version policy, 7 evaluation indicators with thresholds.
- **Schemas** — `input.schema.json`, `output.schema.json`,
  `hypothesis-card.schema.json`, `card-set.schema.json` (subset-compatible:
  only keywords the bundled validator implements).
- **prompts/system.md** — governed role, epistemic labels, falsifiability rule,
  forging procedure, statuses, prohibitions, collaboration handoff.
- **Tools (pure stdlib, offline, deterministic)**
  - `dag.py` — mechanism chain(s) → causal DAG; cycle / self-loop / unknown-ref
    detection; ancestry closure.
  - `scoring.py` — falsifiability / measurability / discriminability scores.
  - `card-validate.py` — card & card-set schema validation + compliance audit.
  - `competing-matrix.py` — discriminating experiments per hypothesis pair,
    direction inference, information gain.
  - `experiment-priority.py` — gain × cost × risk ranking with budget cap.
  - `self-audit.py` — output gates G1–G7.
  - `tools/mhfx/` — `errors.py` (MHX-E code taxonomy, single source of truth),
    `models.py` (epistemic/falsifiability/DAG/info-gain logic), `jsonschema.py`
    (bundled subset validator).
- **Tests** — unit / failure / integration / regression suites (pytest).
- **Evals** — `evals/cases.yaml` (≥8 cases incl. adversarial/boundary),
  `evals/run_evals.py`, `evals/metrics.py`; 7 indicators with measurement +
  thresholds; results recorded to `evals/results/`.
- **Examples** — 3 runnable scenarios (ureolysis strength loss, inlet clogging,
  non-uniform calcite) + `run-examples.sh`.
- **references/sources.md** — method (Popper/Chamberlain/Platt/Bayes), MICP
  domain constraints (S-UR ammonium mass balance), repo conventions,
  limitations.
- **README.md** — install / invoke / tools / tests / limits / troubleshooting.

### Fixed during self-testing
- `dag.py`: flat-list `mechanism_chain` was mis-parsed as multiple single-step
  chains; `depends_on` now attached to nodes so cycle/ancestry checks see edges.
- `jsonschema.py`: SKILL_ROOT path resolution corrected (one level deeper) so
  schema files resolve from the skill directory.
- `competing-matrix.py`: direction inference now reads statement+refutation
  (was refutation-only) and honors explicit `prediction_direction`; pair
  discrimination now includes exclusive predictions, not just opposite signs.
- `self-audit.py`: per-gate error lists are independent (G1/G7 no longer share).
