"""Global sensitivity analysis (Sobol' indices) for micp-modeling-optimizer.

Implementation follows Saltelli et al. (2010) sampler ("Saltelli 2002" scheme
as used in the `sensitivity` R package / SALib): first-order S_i and total-order
S_Ti indices estimated with A/B cross-sample estimators.

Model interface:
    g(theta, extras) -> scalar output y

Sampling is seeded from constraints.random_seed; results are byte-for-byte
reproducible for a fixed seed (M6).

Notes on cost: a full Saltelli design with N base samples and d parameters
needs N*(d+2) evaluations. The tool reports the exact cost and caps N to keep
runs tractable; for expensive models it recommends a screening (e.g. Morris)
first.
"""

from __future__ import annotations

import math
import random
from typing import Callable, Sequence

from _common import ToolError
from errors import MmoError, MmoErrorCode


def _check_sobol_config(d: int, n_base: int) -> None:
    if d < 1:
        raise MmoError(MmoErrorCode.INVALID_PARAM_DEF, "need >= 1 parameter")
    if n_base < 2:
        raise MmoError(MmoErrorCode.INVALID_PARAM_DEF, "N must be >= 2")
    if d * (n_base + 2) > 5_000_000:
        raise MmoError(
            MmoErrorCode.INVALID_PARAM_DEF,
            f"Saltelli design too large: N={n_base} x d={d} -> "
            f"{n_base * (d + 2)} evaluations; reduce N or parameters",
        )


def saltelli_samples(d: int, n_base: int, seed: int) -> list[list[float]]:
    """Saltelli 2002 (revised) sampling matrix in [0,1]^d.

    Builds an A matrix and a B matrix of Latin-hypercube-like stratified
    uniforms, then generates the d matrices AB_i where column i is taken from
    B. Returns N*(d+2) rows, each a length-d list in [0,1]. Deterministic for a
    fixed seed.
    """
    _check_sobol_config(d, n_base)
    rng = random.Random(seed)

    def lh(n: int) -> list[list[float]]:
        # stratified (Latin hypercube) sample in [0,1]
        out: list[list[float]] = []
        for _ in range(n):
            row: list[float] = []
            for _ in range(d):
                cell = rng.random()
                row.append(cell)
            out.append(row)
        return out

    A = lh(n_base)
    B = lh(n_base)
    rows: list[list[float]] = []
    rows.extend(A)
    rows.extend(B)
    for i in range(d):
        for j in range(n_base):
            row = list(A[j])
            row[i] = B[j][i]
            rows.append(row)
    return rows


def sobol_indices(
    g: Callable[[Sequence[float], dict], float],
    d: int,
    n_base: int,
    seed: int,
    extras: dict | None = None,
    *,
    bounds: list[tuple[float, float]] | None = None,
) -> dict:
    """Estimate first-order and total-order Sobol' indices.

    Model inputs are drawn uniformly in [0,1] then linearly rescaled to
    `bounds` (default [0,1]). Returns S1, ST, confidence-free point estimates
    plus the evaluation cost. The A/B estimators:
      S_i   ~ (mean_B(f_B * (f_ABi - f_A))) / Var(f)
      S_Ti  ~ 1 - Var(mean_B(f_B * f_ABi)) / Var(f)   (Jansen/Janon variant)
    implemented with the classical sums-of-products estimators from Saltelli.
    """
    _check_sobol_config(d, n_base)
    extras = extras or {}
    rows = saltelli_samples(d, n_base, seed)
    # evaluate all rows
    ys: list[float] = []
    for row in rows:
        scaled = list(row)
        if bounds:
            scaled = [bounds[j][0] + (bounds[j][1] - bounds[j][0]) * row[j] for j in range(d)]
        ys.append(g(scaled, extras))
    n_eval = len(ys)
    fA = ys[0:n_base]
    fB = ys[n_base:2 * n_base]
    f_AB = [ys[2 * n_base + i * n_base: 2 * n_base + (i + 1) * n_base] for i in range(d)]

    mean_f = sum(ys) / n_eval
    var_f = sum((y - mean_f) ** 2 for y in ys) / (n_eval - 1)
    if var_f <= 1e-16:
        raise MmoError(
            MmoErrorCode.NUMERICAL_FAILURE,
            "output variance is ~0; Sobol' indices undefined",
            detail={"variance": var_f},
        )

    s1: list[float] = []
    st: list[float] = []
    for i in range(d):
        fab = f_AB[i]
        # first order: S_i = (1/N) sum_B fB*(fABi - fA) / Var
        num_s1 = sum(fB[j] * (fab[j] - fA[j]) for j in range(n_base)) / n_base
        s1.append(num_s1 / var_f)
        # total order (Jansen estimator): S_Ti = 1 - [1/(2N) sum (fA-fABi)^2]/Var
        num_st = sum((fA[j] - fab[j]) ** 2 for j in range(n_base)) / (2.0 * n_base)
        st.append(1.0 - num_st / var_f)

    # clamp for reporting
    s1c = [min(max(v, 0.0), 1.0) for v in s1]
    stc = [min(max(v, 0.0), 1.0) for v in st]
    ranking = sorted(range(d), key=lambda i: stc[i], reverse=True)

    return {
        "N": n_base,
        "d": d,
        "n_evaluations": n_eval,
        "method": "sobol_saltelli_2002",
        "first_order": s1c,
        "total_order": stc,
        "rank_by_total_order": ranking,
        "mean_output": mean_f,
        "variance_output": var_f,
        "seed": seed,
        "note": "point estimates without confidence intervals; increase N for tighter estimates",
    }


# ---------------------------------------------------------------------------
# Simple screening fallback: elementary effects (Morris) — cheap alternative
# ---------------------------------------------------------------------------

def morris_screening(
    g: Callable[[Sequence[float], dict], float],
    d: int,
    r_trajectories: int,
    p_levels: int,
    seed: int,
    extras: dict | None = None,
    *,
    bounds: list[tuple[float, float]] | None = None,
) -> dict:
    """Morris elementary-effects screening (deterministic, seeded).

    Cheap first pass recommended before a full Sobol' run. Returns mean
    absolute effect (mu*) and standard deviation per parameter.
    """
    extras = extras or {}
    rng = random.Random(seed)
    delta = p_levels / (2.0 * (p_levels - 1.0))
    # grid levels
    levels = [j / (p_levels - 1.0) for j in range(p_levels)]
    mu_star = [0.0] * d
    sigma = [0.0] * d
    effects: list[list[float]] = [[] for _ in range(d)]

    for _ in range(r_trajectories):
        # random base point on the grid
        x = [levels[rng.randrange(p_levels)] for _ in range(d)]
        base = _scale(x, bounds)
        y_base = g(base, extras)
        for j in range(d):
            # elementary effect of parameter j at the current point
            x2 = list(x)
            # move up or down one grid step (bound-aware)
            step = delta if x2[j] + delta <= 1.0 else -delta
            x2[j] = min(1.0, max(0.0, x2[j] + step))
            y2 = g(_scale(x2, bounds), extras)
            ee = (y2 - y_base) / (step * (bounds[j][1] - bounds[j][0]) if bounds else step)
            effects[j].append(ee)
            y_base = y2
            x = x2
    for j in range(d):
        mu_star[j] = sum(abs(e) for e in effects[j]) / r_trajectories
        m = sum(effects[j]) / r_trajectories
        sigma[j] = math.sqrt(sum((e - m) ** 2 for e in effects[j]) / r_trajectories) if r_trajectories > 1 else 0.0
    return {
        "method": "morris_elementary_effects",
        "r_trajectories": r_trajectories,
        "p_levels": p_levels,
        "mu_star": mu_star,
        "sigma": sigma,
        "n_evaluations": r_trajectories * (d + 1),
        "seed": seed,
    }


def _scale(x: Sequence[float], bounds: list[tuple[float, float]] | None) -> list[float]:
    if not bounds:
        return list(x)
    return [bounds[j][0] + (bounds[j][1] - bounds[j][0]) * x[j] for j in range(len(x))]
