# Tools — micp-data-analyst

All tools are pure Python 3.10+ **standard library**, offline, and
deterministic (RNG draws are seeded via `reproducibility.random_seed`, default
0). They communicate over stdin/stdout with a fixed envelope and exit codes.

## Envelope

Success:

```json
{ "ok": true, "tool": "<name>", "version": "1.0.0", "result": { ... } }
```

Failure:

```json
{ "ok": false, "tool": "<name>", "version": "1.0.0",
  "error": { "code": "MDA-E...", "message": "...", "retryable": false,
             "details": { ... } } }
```

## Exit codes

| Code | Meaning |
|---|---|
| 0 | success |
| 2 | input/validation problem |
| 3 | graph/contract problem |
| 4 | internal error |

Progress and diagnostics go to **stderr**; stdout carries only the envelope.

## CLI

```
python tools/micp/cli.py service    < input.json   # full pipeline
python tools/micp/cli.py qc         < input.json   # data quality + units + pseudo-replication
python tools/micp/cli.py stats      < input.json   # single statistics op
python tools/micp/cli.py validate   < input.json   # input schema validation only
```

## stats ops

| op | input fields | returns |
|---|---|---|
| `descriptive` | `values`, `unit?`, `name?`, `seed?`, `bootstrap?` | n/mean/median/SD/CV/quartiles/skew/kurtosis, bootstrap CI |
| `ci` | `values`, `confidence?` (0.5–0.9999) | t CI on the mean |
| `cohens_d` | `a`, `b` | Hedges' g + 95% CI + magnitude |
| `power` | `n`, `d`, `alpha?` | balanced two-sample power (approx) |
| `normality` | `values` | skew/kurt z-scores + omnibus, n-caveat |
| `outliers` | `values` | IQR/3SD flags, bounds, winsorized/trimmed means |
| `sensitivity` | `values`, `strategies?` | mean under each strategy + spread |
| `regression` | `x`, `y` | OLS slope/intercept/R²/t/p + residual sd |
| `anova` | `groups` | F/df/p/η² + group means |
| `uniformity` | `values`, `positions?`, `segments?` | segment CV + uniformity index |
| `repro_hash` | `frames` | deterministic sha256 of the analysis frames |

All numeric inputs reject non-finite values (NaN/Inf) with a clean error.

## Design rules

- `_common.py` owns the envelope + guards; `_numerics.py` owns math; `qc.py`
  owns data quality; `stats.py` owns inference; `service.py` orchestrates.
- `cli.py` is the only file that touches stdin/stdout (besides the shared
  `run_tool` wrapper).
- Every tool is deterministic: identical input → byte-identical output.
- No keys, tokens, or network calls anywhere in the tool suite.
