# Tools — obsidian-task-decomposer

All tools are pure **Python 3.10+ standard library**, offline, and
deterministic. They are the *computation and validation* layer of the skill;
facts live in `references/`, proof lives in `tests/` and `evals/`.

## Common contract

- **stdin:** exactly one JSON document.
- **stdout:** exactly one JSON document (never log here; progress → stderr).
- **Envelope:**
  - success: `{"ok": true, "version": "1.0.0", "tool": "<name>", "result": {...}}`
  - failure: `{"ok": false, "tool": "<name>", "version": "1.0.0",
    "error": {"code", "message", "retryable", "details"}}`
- **Exit codes:** `0` success · `2` input/validation problem · `3` graph or
  contract problem · `4` internal error.
- **Strictness:** numeric fields reject empty, non-finite (`NaN`/`Inf`), and
  out-of-range values; schemas reject unknown properties where
  `additionalProperties: false`.
- **Determinism:** two runs on identical input produce byte-identical output.

## Tool reference

### validate.py
- **stdin:** `{"schema": "<path relative to skill root, e.g. schemas/input.schema.json>",
  "document": <any JSON>}`
- **result:** `{"valid": bool, "errors": [{path, message}], "schema": ...}`
- Schema loader rejects paths that escape the skill directory
  (`E_PATH_ESCAPE`). Uses the local subset validator `_jsonschema.py`.

### dag_check.py
- **stdin:** `{"nodes": [{"id": ..., "depends_on": [...]}, ...]}`
- **result:** `{"is_dag", "cycles", "topo_order", "levels", "max_parallelism",
  "unknown_dependencies", "self_loops", "duplicate_ids", "orphans",
  "node_count", "edge_count"}`
- Implements Kahn's algorithm (`references/sources.md` S7). Cycle walks are
  concrete and evidence-bearing; duplicates corrupt edge semantics and are
  reported as hard structural errors.

### granularity_scorer.py
- **stdin:** `{"nodes": [<task-node objects>], "config"?: {weights, bounds,
  ok_threshold}}`
- **result:** per-node `{id, score, verdict, subscores, issues, suggestions}`
  + `summary` (verdict histogram, ok_ratio, mean_score).
- Verdicts: `TOO_FINE`, `TOO_COARSE`, `UNDER_SPECIFIED`, `OK`. Weights must
  sum to 1.0 (else `E_CONFIG`). An under-specified node can never be `OK`
  regardless of size.

### budget_estimator.py
- **stdin:** `{"tasks": [{"id", "kind", "risk_level"?, "data_sensitivity"?,
  "est_context_tokens"?}...], "config"?: {buffer, cost_per_hour, currency}}`
- **result:** `{"estimates": {id: {...}}, "totals": {hours, cost, currency},
  "warnings", "method"}`
- Reference-class forecasting (outside view, `sources.md` S5). Unknown kinds
  fall back to `synthesis` with a warning. `est_effort_hours` and
  `max_cost_budget` are `CALCULATED`.

### critical_path.py
- **stdin:** `{"nodes": [{"id", "depends_on", "est_effort_hours"?}...],
  "config"?: {"default_duration_hours"}}`
- **result:** `{"critical_path", "critical_path_hours", "node_metrics",
  "parallelism", "assumed_durations", "fallback_paths", "note"}`
- CPM forward/backward pass (`sources.md` S6). Nodes without an estimate use
  the default and are listed in `assumed_durations`. Cycles → `E_GRAPH_CYCLIC`
  (exit 3) with evidence.

### replan_diff.py
- **stdin:** `{"plan": {"nodes": [...]}, "trigger": {"reason", "failed_node_ids"?
  , "changed_node_ids"?, "new_evidence_refs"?}, "replacement_nodes"?, "remove_node_ids"?}`
- **result:** `{"reason", "trigger_nodes", "preserved", "stale_completed",
  "invalidated", "rework", "added", "removed", "dangling_risk",
  "new_evidence_refs", "merged_plan", "merged_graph", "guarantees"}`
- Local replan only: downstream closure of the trigger is re-planned; upstream
  and unrelated nodes are preserved byte-for-byte. Completed nodes downstream
  of the trigger are preserved but flagged `stale_completed` (never silently
  reopened). Merged graph must remain a DAG (`E_REPLAN_INVALID` if not).

### self_audit.py
- **stdin:** `{"output": <candidate skill output (pre-artifact-wrapping)>,
  "external_inputs"?: [...]}`
- **result:** `{"pass", "gates", "violation_count", "note"}`
- Gates:
  - **G1** no implicit dependencies (every `inputs` producer is upstream or
    external)
  - **G2** exactly one primary skill, ≤1 collaborator
  - **G3** verifiable definition of done
  - **G4** acyclic (cycle evidence), no unknown deps, no self-loops
  - **G5** execution ceilings present; human gates on `human_wait`/`high`/
    irreversible nodes
  - **G6** epistemic tags valid; `OBSERVED` claims name their source

## Adding a tool

1. Put the logic in `tools/<name>.py`; import from `_common` (`as_dict`,
   `as_number`, `as_list`, `as_str`, `run_tool`). The `main(payload)` function
   returns the `result` dict; `run_tool("<name>", main)` handles the envelope
   and exit codes.
2. Use the existing guards — never accept empty, non-finite, or out-of-range
   numerics; never trust unknown fields.
3. Register the entry point in `skill.yaml` (`entry_points`).
4. Add tests in `tests/` (unit + a failure case with a real envelope/exit-code
   assertion) and a row in `tools/README.md`.
5. Run the full suite and `evals/run_evals.py`.
