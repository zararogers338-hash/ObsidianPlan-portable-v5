# micp-data-analyst

MICP Data Analyst — 数据清洗、统计推断与可视化

A governed professional skill of the **Obsidian Plan (Panshi)** research
system. It turns MICP experiment and simulation data into **traceable
cleaning, statistical inference, effect-size and uncertainty quantification,
and engineering visualization**.

## What it does

- **Schema, unit, missing, range, batch, time and independence checks** before
  any inference (`tools/micp/qc.py`).
- **Pseudo-replication detection**: rows sharing a sampling unit
  (specimen/column/layer/well/time point) are flagged, and group effect sizes
  are computed on the *independent* units, not the row count.
- **Statistical inference** (`tools/micp/stats.py`): descriptive statistics,
  t CIs, normality screening (with an explicit n<8 no-power caveat), outlier
  policies, Hedges' g effect sizes with CIs, power estimation, OLS regression,
  one-way ANOVA, spatial-uniformity indices, and reproducibility hashes.
- **Sensitivity analysis**: mean under keep / winsorize 1.5×IQR / winsorize
  3SD / trim 5%.
- **Engineering judgment**: effect sizes and CIs are reported alongside
  p-values; statistical significance is never presented as engineering value.
- **Epistemic discipline**: every load-bearing claim carries one of
  OBSERVED / REPORTED / CALCULATED / INFERRED / HYPOTHESIS / RECOMMENDATION.
- **Unified envelope**: machine-readable input/output contracts
  (`schemas/`), MDA-E### error taxonomy, status codes, and provenance.

## Install / load

The skill lives in the OpenCode config tree:

```
skills/micp-data-analyst/
```

- OpenCode discovers it via `SKILL.md` frontmatter (`name`, `description`).
- The Obsidian Skill Router indexes it automatically from `skill.yaml`
  (capabilities, inputs, outputs, units, permissions, network:false).
- No registration step is needed; no build step; no network.

## Quick start

```bash
cd skills/micp-data-analyst

# Full pipeline (validate -> version gate -> qc -> stats -> self-check)
python tools/micp/cli.py service < examples/01-clean-infer.json

# Data-quality + pseudo-replication checks only
python tools/micp/cli.py qc < input.json

# Single statistics operation
echo '{"op":"cohens_d","a":[10,11,12,13,14],"b":[5,6,7,8,9]}' | \
  python tools/micp/cli.py stats

# Validate an envelope against the input contract
python tools/micp/cli.py validate < input.json
```

Every tool reads one JSON document on stdin and writes the envelope to stdout.
Progress goes to stderr. Exit codes: 0 success, 2 input/validation,
3 graph/contract, 4 internal.

## Test / eval

```bash
cd skills/micp-data-analyst
python -m pytest tests/          # unit + failure + regression + schema-subset + integration
python evals/run_evals.py        # offline eval: 10 cases, 7 performance indicators
```

All tests and evals are offline and deterministic (no numpy/scipy/network).

## Package layout

```
skills/micp-data-analyst/
├── SKILL.md                  # frontmatter + triggers/boundaries + workflow + error codes
├── skill.yaml                # machine-readable manifest for the OSR registry
├── prompts/system.md         # minimal system prompt (identity, workflow, stop rules)
├── schemas/
│   ├── input.schema.json     # strict input contract (draft 2020-12 subset)
│   └── output.schema.json    # strict output contract + status/validity gates
├── tools/
│   ├── README.md             # tool contracts
│   └── micp/
│       ├── cli.py            # stdin/stdout entry (service|qc|stats|validate)
│       ├── service.py        # full pipeline orchestration
│       ├── qc.py             # schema/unit/missing/pseudo-replication checks
│       ├── stats.py          # inference, effect size, sensitivity, uniformity
│       ├── _numerics.py      # norm/t/F/chi-square primitives (verified)
│       ├── _jsonschema.py    # JSON Schema 2020-12 subset validator
│       ├── _common.py        # envelope + numeric/type guards
│       └── errors.py         # MDA-E### taxonomy (single source of truth)
├── tests/                    # unit, failure, regression, schema-subset, integration
├── evals/
│   ├── cases.yaml            # 10 cases (positive/conflict/adversarial/boundary)
│   └── run_evals.py          # offline runner reporting the 7 indicators
├── examples/                 # 3 runnable invocations
├── references/sources.md     # method + domain sources, access dates, limitations
└── CHANGELOG.md              # version policy + release notes
```

## Limitations

- Mixed-effects, response-surface, multi-objective, and full time-series models
  are routed to `obsidian-modeling-optimizer` via `NEED_ADDITIONAL_SKILL`, not
  implemented here.
- Normality screening is approximate for n in [8, 30) and refuses to certify at
  n < 8.
- Visualization PNG/HTML renderers are declared in the output contract but not
  shipped; a companion rendering skill is the intended producer.
- Power estimates use a normal approximation to the noncentral t (planning
  grade).

## Version policy

- Breaking contract changes → major version bump.
- New optional fields → minor bump.
- Implementation fixes only → patch bump.
- Old-version outputs are rejected with `MDA-E801` unless migrated.
