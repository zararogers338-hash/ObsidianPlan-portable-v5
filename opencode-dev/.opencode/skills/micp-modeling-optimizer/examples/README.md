# Examples — micp-modeling-optimizer

Every payload below is a complete, **runnable** stdin document. Run them with:

```bash
cd skills/micp-modeling-optimizer
python tools/modeling.py < examples/01-solve.json
```

| file | action | what it demonstrates |
|---|---|---|
| `01-solve.json` | solve | build + solve a ureolysis/precipitation kinetic model; conservation & numerical self-checks |
| `02-fit.json` | fit | parameter inversion on synthetic urea+CaCO3 data; identifiability + hold-out validation |
| `03-analyze.json` | analyze | full pipeline: solve → fit → Sobol sensitivity → NSGA-II → UQ |
| `04-optimize-single.json` | optimize | single-objective Bayesian optimization (maximize CaCO3 yield) |
| `05-multiobjective.json` | multiobjective | NSGA-II Pareto front + knee + robustness |
| `06-validate.json` | validate | schema-only dry-run gate |

`01` data was generated from the closed-form solver with k_ure = k_pre = 1e-4,
urea0 = ca0 = 500 mol/m3, t_end = 86400 s — the `fit` example inverts the same
kinetics, so the recovered k_ure ≈ 1e-4 demonstrates the pipeline end to end.
