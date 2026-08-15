# obsidian-task-decomposer — maintainer README

Decomposes a Mission Lock research contract into atomic, dependency-explicit,
verifiable research tasks and emits a machine-readable DAG for the Obsidian
Plan engineering loop. Governed by the Panshi constitution; invoked by the
Obsidian Controller.

- **Skill name (must match directory):** `obsidian-task-decomposer`
- **Version:** 1.0.0
- **License:** MIT (matching the OpenCode fork this project is built on)
- **Status:** shipping

## Installation

This skill lives in this repo at `.opencode/skills/obsidian-task-decomposer/`
and is discovered automatically by OpenCode. Discovery also scans
`~/.config/opencode/skills/`, `.claude/skills/`, and `.agents/skills/` — see
the loader in `packages/opencode/src/skill/index.ts`. For a one-off install in
a project without this repo, copy the whole directory to that project's
`.opencode/skills/`.

Requirements: Python ≥ 3.10 on PATH as `python` (all tools are stdlib-only;
no pip install, no network).

## Invocation

The controller (or a human) calls the skill with one JSON document that
satisfies `schemas/input.schema.json` and receives one JSON document that
satisfies `schemas/output.schema.json`. In an interactive OpenCode session the
skill is loaded on demand via the native `skill` tool; the executing agent then
runs the `tools/*.py` pipeline over stdin/stdout.

Example (the file `examples/01-basic-micp/run.sh` runs a full end-to-end
invocation and validates the result):

```bash
python3 tools/validate.py < examples/01-basic-micp/input.json > /dev/null   # schema check
# ...then, as the agent, run the pipeline: dag_check -> granularity_scorer ->
# budget_estimator -> critical_path -> self_audit
```

## Layout

```
SKILL.md                 Human/agent entry point; OpenCode frontmatter (name+description)
skill.yaml               Machine-readable manifest (controller / packaging / CI)
prompts/system.md        Minimal system prompt: identity, workflow, boundaries, stop rules
schemas/
  input.schema.json      Strict input contract   (v1.0.0)
  output.schema.json     Strict output contract  (v1.0.0)
  task-node.schema.json  One DAG node contract   (v1.0.0)
tools/
  _common.py             Envelope + validation shared helpers (toolset contract)
  _jsonschema.py         Minimal JSON Schema 2020-12 subset validator (offline)
  validate.py            Schema validation of a document
  dag_check.py           Kahn topo sort, cycle evidence, levels, parallelism
  granularity_scorer.py  Granularity verdicts (TOO_FINE/OK/TOO_COARSE/UNDER_SPECIFIED)
  budget_estimator.py    Reference-class effort/cost estimates (planning-fallacy guard)
  critical_path.py       CPM forward/backward pass, slack, critical path
  replan_diff.py         Local replan; preserves confirmed facts & completed work
  self_audit.py          Acceptance gates G1–G6
  README.md              Tool-by-tool contract (stdin/stdout/envelope/exit codes)
tests/                   pytest suite: unit, integration, failure, regression, schema-subset
evals/
  cases.yaml             ≥8 evaluation cases incl. adversarial/conflict/boundary
  run_evals.py           Offline runner producing a JSON report (no network, no LLM)
examples/                Three runnable end-to-end examples (input + expected + run script)
references/sources.md    Sources with access dates, usage, and key limitations
CHANGELOG.md             Version history and migration notes
```

## Tool contract (all tools)

- Read **exactly one JSON document on stdin**; write **exactly one JSON
  document on stdout**; progress only on stderr.
- Envelope: success `{"ok": true, "version": "1.0.0", "tool": <name>, "result": {...}}`;
  failure `{"ok": false, "tool": <name>, "version": "1.0.0", "error": {"code",
  "message", "retryable", "details"}}`.
- Exit codes: `0` ok; `2` input/validation problem; `3` graph/contract
  problem; `4` internal error.
- Numeric fields are rejected when non-finite, empty, or out of range. Unknown
  JSON fields are rejected where schemas say `additionalProperties: false`.
- Offline-only. No network, no clock dependence, no randomness: two runs on
  identical input produce byte-identical output.
- See `tools/README.md` for per-tool inputs/outputs.

## Workflow the executing agent must follow

1. Validate the input contract (`validate.py`).
2. Build the DAG node list; check structure (`dag_check.py`).
3. Score granularity; adjust until every node is `OK`
   (`granularity_scorer.py`).
4. Estimate budgets (`budget_estimator.py`), check against `constraints`.
5. Compute critical path / parallelism (`critical_path.py`).
6. Run self-audit gates G1–G6 (`self_audit.py`); fix until it passes.
7. On `replan_of`: `replan_diff.py` for a local diff that preserves confirmed
   facts and completed work.

## Testing

```bash
python -m pytest tests/ -q            # unit + integration + failure + regression + schema-subset
python evals/run_evals.py             # offline eval report (≥8 cases, incl. adversarial)
```

Run the full suite before any release. Tests are deterministic and offline;
`tests/test_schema_subset.py` proves our own schemas stay inside the subset
`_jsonschema.py` supports, so a schema change cannot silently rely on
unsupported JSON Schema semantics.

## Versioning and compatibility

Semantic versioning on the **contracts** (`schemas/*.json`, error-code table,
tool exit codes). Per `skill.yaml` `version_policy`:

- **Major** — breaking contract changes (removing/renaming required fields,
  status enum changes, error-code renumbering, exit-code changes).
- **Minor** — additive (new optional fields/enums/tools). Old documents stay
  valid.
- **Patch** — implementation-only fixes.

Migration/rejection: the controller must never feed an artifact into
`replan_diff` when its `provenance.skill_version` MAJOR differs from the
installed skill; it regenerates under the new contract or applies the
documented conversion in `CHANGELOG.md`. `E_VERSION_MISMATCH` is reported in
`provenance` and `errors`.

## Known limitations and failure modes

- **File-list sampling:** OpenCode's `skill` tool enumerates a *sampled*
  subset of skill files (limit 10). This skill never relies on enumeration —
  every needed file is referenced by relative path from the SKILL.md/prompt
  text and read on demand.
- **Estimates are estimates:** budgets and critical-path slack inherit
  planning-fallacy error. They are `CALCULATED` reference-class values, never
  promises (`references/sources.md` S5, S6).
- **Gate violations vs. quality:** `self_audit.py` proves mechanical
  necessary conditions (no implicit deps, single owner, verifiable DoD,
  ceilings, tags). It does not prove research quality; the red-team skill
  (`obsidian-red-team`) is the adversary for content.
- **Truncation / long runs:** the agent must phase-save progress and continue;
  it must not stop silently if a command output is truncated. Record `errors`,
  degrade, and complete independent parts.
- **No human-granting:** the skill marks `human_approval_gate` nodes; it never
  approves them.
- **MICP domain:** ureolysis decompositions MUST include ammonium
  fate/mass-balance tasks (stoichiometric, `references/sources.md` S12).
  Non-ureolytic pathways must not inherit the urea model.

## Troubleshooting

| Symptom | Likely cause / fix |
|---|---|
| `validate.py` exits 2 with `E_FILE_MISSING` | Schema path must be relative to the skill root (`schemas/...`) or absolute; check it exists. |
| `dag_check` reports cycles you did not write | A node's `depends_on` transitively loops; resolve before scheduling. |
| `granularity_scorer` marks nodes `UNDER_SPECIFIED` | Missing `definition_of_done`, `primary_skill`, `failure_modes`, or `retry_policy`; fix per the reported issues. |
| `self_audit` fails G1 | An `inputs` entry names a producer that is neither upstream nor `request`/`context`/`constraints`/`evidence_refs:*`/`data_refs:*` — implicit dependency. |
| `replan_diff` reports `E_REPLAN_INVALID` | Replacement nodes reference removed nodes; fix `depends_on`. |
| A test fails after a schema edit | Run `tests/test_schema_subset.py` first: the keyword you added may be outside the supported subset. |

## Handover notes

Everything a second engineer needs to pick this up lives in this directory:
schemas for the contracts, tools/README.md for the tool contracts,
references/sources.md for every source and its limitations, tests/ and
evals/ for proof, CHANGELOG.md for history. If you change any contract, bump
the version per `version_policy`, update the schemas' `$id`, add a CHANGELOG
entry, and re-run the full suite.


---

> 原 `README-ZIP.md` 已归档至 [`audit/README-ZIP.md`](audit/README-ZIP.md)。
