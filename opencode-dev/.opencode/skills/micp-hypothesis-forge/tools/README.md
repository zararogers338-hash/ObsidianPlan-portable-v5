# tools/README.md — stdio tool contract

All tools in `tools/` follow one contract (shared with the rest of Obsidian
Plan's Python skills, e.g. obsidian-task-decomposer):

## Contract

- **stdin**: exactly one JSON document.
- **stdout**: exactly one JSON document. Never log to stdout; progress/warnings
  go to stderr.
- **exit codes**:
  - `0` success
  - `2` input / validation problem (`MHX-E10x`, `MHX-E20x` where input-shaped)
  - `3` graph / contract problem (cycles, self-loops, unknown refs)
  - `4` internal error (unexpected exception)

## Envelope

```
success: {"ok": true,  "version": "1.0.0", "tool": "<name>", "result": {...}}
failure: {"ok": false, "version": "1.0.0", "tool": "<name>",
          "error": {"code": "MHX-…", "message": "…",
                    "retryable": bool, "details": {...}}}
```

`retryable=true` means a controller may safely re-run the same tool with the
same input; `false` means the input or environment must change first.

## Numerical discipline

- Non-numeric / NaN / ±Inf values are rejected (`MHX-E301`) — never silently
  coerced.
- Scores are clamped to [0,1] after validation.
- Information-gain and priority numbers are deterministic given the same input.

## Determinism

The same stdin always produces the same stdout (no RNG, no time, no network,
no hidden global state). This is what `repeat_run_consistency` measures.

## Tools

| Tool | Input highlights | Output highlights |
|---|---|---|
| `dag.py` | `mechanism_chain` (string or list) or `chains` (list of chains) | DAG, edges, topological order, ancestry/descendants, `acyclic` |
| `scoring.py` | `statements[]` with `id/statement/refutation/observables/time_scale/scope` | per-card falsifiability/measurability/discriminability/overall + summary |
| `card-validate.py` | `schema` ∈ {hypothesis-card, card-set} + `document` | schema errors + audit checks |
| `competing-matrix.py` | `hypotheses[]` (min 3) with statement/refutation/observables | predicted directions, discriminating experiments, info gain per pair |
| `experiment-priority.py` | `experiments[]` with gain/cost_rank/risk_level/time_scale_days/feasibility | ranked list with scores |
| `self-audit.py` | full output document | gates G1–G7 pass/fail |

## Running

Run from the skill root so schema paths resolve:

```bash
cd skills/micp-hypothesis-forge
python tools/dag.py < input.json
```

The tools never write files and never touch the network.
