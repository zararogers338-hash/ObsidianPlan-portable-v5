# micp-modeling-optimizer — tools

`tools/modeling.py` is the only file that touches stdin/stdout. All scientific
modules live in `tools/micp/` and are pure Python 3.10+ (stdlib), with
optional accelerators.

## Envelope and exit codes

stdout carries ONE JSON object per invocation:

- Success: `{ok: true, tool: "modeling", version: "1.0.0", result: {…envelope…}}`
  — the envelope is the unified output document (schemas/output.schema.json).
- Failure: `{ok: false, tool: "modeling", version: "1.0.0", error: {code,
  message, details, retryable}}`.

Exit codes:

| code | meaning |
|---|---|
| 0 | an envelope was produced (its `status` field carries the outcome) |
| 2 | malformed / unusable payload or hard contract violation |
| 3 | missing dependency |
| 4 | internal engine failure |

Progress and diagnostics go to **stderr**; stdout stays machine-pure.

## Modules

| module | purpose |
|---|---|
| `_common.py` | envelope plumbing, safe type extraction, constants, seeded RNG |
| `errors.py` | MMO-E1xx..E8xx taxonomy (source of truth for error codes) |
| `kinetics.py` | rate models + closed-form implicit-Euler kinetic solver + mass balance |
| `optimizer.py` | ODE solve, multi-start least-squares fit, Fisher/prof likelihood identifiability, CV/hold-out |
| `sensitivity.py` | Sobol' (Saltelli 2002) + Morris elementary effects |
| `doe.py` | full factorial / CCD / Box–Behnken / LHS generation + quadratic response surface |
| `bayesopt.py` | EGO (GP + EI) Bayesian optimization |
| `multiobjective.py` | NSGA-II + Monte-Carlo robustness |
| `uncertainty.py` | seeded Monte-Carlo UQ (uniform / truncated normal) |
| `checks.py` | conservation (6 residuals), numerical stability, grid/step sensitivity |
| `modelspec.py` | model-spec validation (MODEL_BLOCKED), parameter-fit policy, report assembly |
| `reporting.py` | inline-SVG/HTML visualization artifacts (offline) |
| `validate.py` | JSON-Schema validation (jsonschema or built-in subset fallback) |
| `service.py` | action dispatch, envelope, self-checks, status mapping |

## Determinism

Every stochastic process (multi-start guesses, Saltelli sampling, MC
perturbation, GP initialization, NSGA-II mutation) is seeded from
`constraints.random_seed`. Identical input reproduces identical output
byte-for-byte (eval metric M6).

## Subcommands

```bash
python tools/modeling.py schema                # print input schema
python tools/modeling.py selfcheck out.json    # validate against output schema (exit 1 on failure)
python tools/modeling.py < payload.json        # service mode: dispatch on payload.action
```
