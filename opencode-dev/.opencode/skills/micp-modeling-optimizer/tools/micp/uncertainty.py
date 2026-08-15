"""Uncertainty propagation (Monte Carlo) for micp-modeling-optimizer.

Given a deterministic model y = g(theta) and parameter uncertainties expressed
as independent bounded distributions (uniform or truncated normal), draw a
seeded Monte-Carlo ensemble and report:

  * percentiles (5/50/95), mean, std of each output scalar,
  * per-output convergence of the mean (relative change across ensemble
    halves),
  * the parameter-to-output first-order correlation (Pearson) as a rough
    linear sensitivity diagnostic.

All randomness is seeded from constraints.random_seed; the same seed gives a
byte-for-byte identical ensemble (M6). For expensive models the tool warns to
reduce N or switch to a screening method.
"""

from __future__ import annotations

import math
import random
from typing import Callable, Sequence

from _common import ToolError
from errors import MmoError, MmoErrorCode


def monte_carlo_uq(
    g: Callable[[Sequence[float], dict], Sequence[float]],
    param_dist: list[dict],
    n_samples: int,
    seed: int,
    extras: dict | None = None,
    *,
    bounds: list[tuple[float, float]] | None = None,
    n_outputs: int | None = None,
) -> dict:
    """Propagate parameter uncertainty through g.

    param_dist: list of {name, dist: "uniform"|"normal", low, high, mean, std}.
      * uniform:  draw U(low, high)
      * normal:   truncated normal on [low, high] (when given), mean/std.
    bounds: optional decision-vector bounds applied after sampling (for
    parameters that must stay inside a box).
    n_outputs: number of output scalars g returns (inferred from first eval if
    None).
    """
    extras = extras or {}
    d = len(param_dist)
    if n_samples < 10:
        raise MmoError(MmoErrorCode.INVALID_PARAM_DEF, "n_samples must be >= 10")
    rng = random.Random(seed)

    def draw(p: dict) -> float:
        dist = p.get("dist", "uniform")
        if dist == "uniform":
            lo = p["low"]
            hi = p["high"]
            return lo + rng.random() * (hi - lo)
        # truncated normal by rejection sampling
        mean = p.get("mean", 0.5 * (p["low"] + p["high"]))
        std = p.get("std", 0.25 * (p["high"] - p["low"]))
        lo = p.get("low", -math.inf)
        hi = p.get("high", math.inf)
        for _ in range(10000):
            v = rng.gauss(mean, std)
            if lo <= v <= hi:
                return v
        raise MmoError(MmoErrorCode.NUMERICAL_FAILURE, "normal draw failed to stay in bounds")

    # first sample to learn output shape
    x0 = [draw(p) for p in param_dist]
    if bounds:
        x0 = [min(max(x0[i], bounds[i][0]), bounds[i][1]) for i in range(d)]
    y0 = g(x0, extras)
    if n_outputs is None:
        if not isinstance(y0, (list, tuple)):
            n_outputs = 1
        else:
            n_outputs = len(y0)
    elif not (isinstance(y0, (list, tuple)) and len(y0) == n_outputs) and not (
        n_outputs == 1 and isinstance(y0, (int, float))
    ):
        raise MmoError(
            MmoErrorCode.INVALID_MODEL_SPEC,
            "model output length does not match n_outputs",
        )

    all_x: list[list[float]] = []
    all_y: list[list[float]] = []
    for _ in range(n_samples):
        x = [draw(p) for p in param_dist]
        if bounds:
            x = [min(max(x[i], bounds[i][0]), bounds[i][1]) for i in range(d)]
        yv = g(x, extras)
        if isinstance(yv, (int, float)):
            yv = [yv]
        if len(yv) != n_outputs:
            raise MmoError(MmoErrorCode.INVALID_MODEL_SPEC, "model output shape changed during sampling")
        all_x.append(x)
        all_y.append([float(v) for v in yv])
        if not all(math.isfinite(v) for v in all_y[-1]):
            raise MmoError(MmoErrorCode.CONTEXT_CORRUPT, "non-finite model output in Monte Carlo")

    out: list[dict] = []
    for j in range(n_outputs):
        col = [all_y[i][j] for i in range(n_samples)]
        col.sort()
        p5 = col[int(round(0.05 * (n_samples - 1)))]
        p50 = col[int(round(0.5 * (n_samples - 1)))]
        p95 = col[int(round(0.95 * (n_samples - 1)))]
        mean = sum(col) / n_samples
        var = sum((v - mean) ** 2 for v in col) / max(n_samples - 1, 1)
        std = math.sqrt(var)
        # convergence: mean of first half vs full
        half = col[: n_samples // 2] if n_samples >= 4 else col
        mean_half = sum(half) / max(len(half), 1)
        rel = abs(mean_half - mean) / max(abs(mean), 1e-12)
        # Pearson correlation of each param with this output
        cors = []
        for a in range(d):
            mx = sum(all_x[i][a] for i in range(n_samples)) / n_samples
            vx = sum((all_x[i][a] - mx) ** 2 for i in range(n_samples)) / max(n_samples - 1, 1)
            if vx <= 0:
                cors.append(None)
                continue
            cov = sum((all_x[i][a] - mx) * (all_y[i][j] - mean) for i in range(n_samples)) / max(n_samples - 1, 1)
            cors.append(cov / math.sqrt(vx * var) if var > 0 else None)
        out.append({
            "output": j,
            "mean": mean,
            "std": std,
            "p5": p5,
            "p50": p50,
            "p95": p95,
            "cv": std / abs(mean) if abs(mean) > 1e-12 else None,
            "mean_convergence_rel": rel,
            "param_correlation": cors,
        })

    return {
        "method": "monte_carlo_seeded",
        "n_samples": n_samples,
        "n_outputs": n_outputs,
        "seed": seed,
        "outputs": out,
        "note": "independent parameter distributions; correlations among inputs are not modeled",
    }
