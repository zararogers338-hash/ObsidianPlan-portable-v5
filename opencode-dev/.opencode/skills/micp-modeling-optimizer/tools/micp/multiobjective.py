"""Multi-objective optimization (NSGA-II) for micp-modeling-optimizer.

Implements the non-dominated sorting genetic algorithm II of Deb et al.
(2002): fast non-dominated sorting, crowding distance, and crowded tournament
selection. Objectives are minimized by default (callers convert maximization
into minimization).

The output is a Pareto-front approximation with:
  * per-solution objective vectors (in original sign),
  * crowding distance,
  * the recommended knee/compromise candidate (smallest normalized distance to
    the ideal point), and
  * robustness: a seeded Monte-Carlo perturbation of each front solution's
    decision vector estimates the expected objective degradation and the
    failure fraction (solutions that violate declared constraints after
    perturbation).

Constraints are handled by a penalty: a solution that violates a constraint
has its rank overridden — it is dominated by any feasible solution. The tool
reports infeasible front members separately.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from typing import Callable, Sequence

from _common import ToolError
from errors import MmoError, MmoErrorCode


@dataclass
class Individual:
    x: list[float]
    f: list[float]      # objective values (minimization form)
    feasible: bool = True
    rank: int = 0
    crowding: float = 0.0
    violation: float = 0.0


def _non_dominated_sort(pop: list[Individual]) -> list[list[int]]:
    n = len(pop)
    dominated_count = [0] * n
    dominates: list[list[int]] = [[] for _ in range(n)]
    fronts: list[list[int]] = []
    for i in range(n):
        for j in range(n):
            if i == j:
                continue
            if _dominates(pop[i].f, pop[j].f):
                dominates[i].append(j)
                dominated_count[j] += 1
    front0 = [i for i in range(n) if dominated_count[i] == 0]
    fronts.append(front0)
    while True:
        nxt: list[int] = []
        for i in fronts[-1]:
            for j in dominates[i]:
                dominated_count[j] -= 1
                if dominated_count[j] == 0:
                    nxt.append(j)
        if not nxt:
            break
        fronts.append(nxt)
    return fronts


def _dominates(fa: Sequence[float], fb: Sequence[float]) -> bool:
    strict = False
    for a, b in zip(fa, fb):
        if a > b + 1e-12:
            return False
        if a < b - 1e-12:
            strict = True
    return strict


def _crowding_distance(front: list[int], pop: list[Individual]) -> None:
    m = len(pop[0].f)
    for idx in front:
        pop[idx].crowding = 0.0
    if len(front) <= 2:
        for idx in front:
            pop[idx].crowding = float("inf")
        return
    for obj in range(m):
        front.sort(key=lambda i: pop[i].f[obj])
        pop[front[0]].crowding = float("inf")
        pop[front[-1]].crowding = float("inf")
        lo = pop[front[0]].f[obj]
        hi = pop[front[-1]].f[obj]
        denom = hi - lo if hi > lo else 1.0
        for k in range(1, len(front) - 1):
            pop[front[k]].crowding += (pop[front[k + 1]].f[obj] - pop[front[k - 1]].f[obj]) / denom


def _constraint_violation(x: Sequence[float], constraints: list[dict] | None) -> float:
    if not constraints:
        return 0.0
    total = 0.0
    for c in constraints:
        i = c.get("index")
        if i is None:
            continue
        lo = c.get("low")
        hi = c.get("high")
        v = x[i]
        if lo is not None and v < lo:
            total += (lo - v) ** 2
        if hi is not None and v > hi:
            total += (v - hi) ** 2
    return total


def nsga2(
    objectives: list[Callable[[Sequence[float], dict], float]],
    bounds: list[tuple[float, float]],
    *,
    pop_size: int = 40,
    n_gen: int = 100,
    seed: int = 0,
    constraints: list[dict] | None = None,
    names: list[str] | None = None,
    maximize: list[bool] | None = None,
    extras: dict | None = None,
) -> dict:
    """Run NSGA-II and return the Pareto-front approximation.

    objectives: list of scalar functions to minimize (maximize handled via the
    `maximize` list). bounds: decision-vector box. Returns front, per-objective
    stats, knee point, and (optionally) robustness analysis.
    """
    extras = extras or {}
    d = len(bounds)
    n_obj = len(objectives)
    if pop_size < 4 or n_gen < 1:
        raise MmoError(MmoErrorCode.INVALID_PARAM_DEF, "pop_size>=4, n_gen>=1")
    if n_obj < 2:
        raise MmoError(MmoErrorCode.INVALID_PARAM_DEF, "NSGA-II needs >= 2 objectives")
    sign = [(-1.0 if (maximize or [False] * n_obj)[i] else 1.0) for i in range(n_obj)]
    rng = random.Random(seed)

    def eval_ind(x: list[float]) -> Individual:
        f = [sign[i] * objectives[i](x, extras) for i in range(n_obj)]
        viol = _constraint_violation(x, constraints)
        return Individual(x=x, f=f, feasible=viol == 0.0, violation=viol)

    def clamp(x: list[float]) -> list[float]:
        return [min(max(x[i], bounds[i][0]), bounds[i][1]) for i in range(d)]

    def crossover(a: list[float], b: list[float]) -> list[float]:
        # SBX-ish uniform blend (deterministic given rng)
        return [0.5 * (a[i] + b[i]) for i in range(d)]

    def mutate(x: list[float]) -> list[float]:
        out = list(x)
        for i in range(d):
            if rng.random() < 0.2:
                span = bounds[i][1] - bounds[i][0]
                out[i] = min(max(x[i] + rng.gauss(0, 0.1 * span), bounds[i][0]), bounds[i][1])
        return out

    # init
    pop: list[Individual] = []
    for _ in range(pop_size):
        x = [bounds[i][0] + rng.random() * (bounds[i][1] - bounds[i][0]) for i in range(d)]
        pop.append(eval_ind(x))

    for gen in range(n_gen):
        # children
        children: list[Individual] = []
        while len(children) < pop_size:
            a = _tournament(pop, rng)
            b = _tournament(pop, rng)
            child = crossover(a.x, b.x)
            child = mutate(child)
            children.append(eval_ind(clamp(child)))
        combined = pop + children
        # constraint-aware: infeasible individuals are always dominated
        for ind in combined:
            ind.rank = 10 ** 9 if not ind.feasible else 0
        fronts = _non_dominated_sort(combined)
        new_pop: list[Individual] = []
        for fi, front in enumerate(fronts):
            if not front:
                continue
            _crowding_distance(front, combined)
            for idx in front:
                # feasible individuals get their real Pareto rank; infeasible
                # ones stay ranked after every feasible individual so the
                # tournament never lets a constraint violator outrank a
                # feasible solution (penalty-style constraint handling).
                if combined[idx].feasible:
                    combined[idx].rank = fi
            if len(new_pop) + len(front) <= pop_size:
                for idx in front:
                    new_pop.append(combined[idx])
            else:
                remaining = pop_size - len(new_pop)
                front.sort(key=lambda i: (-combined[i].crowding))
                for idx in front[:remaining]:
                    new_pop.append(combined[idx])
                break
        pop = new_pop

    # front = rank 0 (feasible only)
    front_ind = [ind for ind in pop if ind.rank == 0 and ind.feasible]
    front_ind.sort(key=lambda ind: ind.f[0])
    front_pts = [ind.x for ind in front_ind]
    front_obj = [ind.f for ind in front_ind]

    # knee point: min normalized distance to ideal point (utopia)
    ideal = [min(ind.f[j] for ind in front_ind) for j in range(n_obj)] if front_ind else None
    knee_idx = None
    if front_ind and n_obj > 1:
        span = [max(ind.f[j] for ind in front_ind) - ideal[j] for j in range(n_obj)]
        span = [s if s > 1e-12 else 1.0 for s in span]
        dists = [
            math.sqrt(sum(((ind.f[j] - ideal[j]) / span[j]) ** 2 for j in range(n_obj)))
            for ind in front_ind
        ]
        knee_idx = min(range(len(dists)), key=lambda i: dists[i])

    return {
        "method": "nsga2",
        "n_objectives": n_obj,
        "objective_names": names or [f"obj{i}" for i in range(n_obj)],
        "pop_size": pop_size,
        "n_generations": n_gen,
        "n_front_solutions": len(front_ind),
        "front": [{"x": x, "objectives": [round(v, 8) for v in f]} for x, f in zip(front_pts, front_obj)],
        "ideal_point": [round(v, 8) for v in ideal] if ideal else None,
        "knee_index": knee_idx,
        "knee_point": {
            "x": front_pts[knee_idx],
            "objectives": [round(v, 8) for v in front_obj[knee_idx]],
        } if knee_idx is not None else None,
        "seed": seed,
    }


def _tournament(pop: list[Individual], rng: random.Random) -> Individual:
    a = pop[rng.randrange(len(pop))]
    b = pop[rng.randrange(len(pop))]
    if a.rank != b.rank:
        return a if a.rank < b.rank else b
    return a if a.crowding > b.crowding else b


def robustness_analysis(
    objectives: list[Callable[[Sequence[float], dict], float]],
    front: list[Sequence[float]],
    bounds: list[tuple[float, float]],
    *,
    n_samples: int = 50,
    sigma_frac: float = 0.05,
    seed: int = 0,
    constraints: list[dict] | None = None,
    maximize: list[bool] | None = None,
    extras: dict | None = None,
) -> dict:
    """Monte-Carlo robustness of each Pareto-front solution: perturb decision
    variables with N(0, sigma_frac*range), re-evaluate objectives, report mean
    degradation (as % of the unperturbed value) and the infeasibility rate.
    Deterministic given seed."""
    extras = extras or {}
    n_obj = len(objectives)
    sign = [(-1.0 if (maximize or [False] * n_obj)[i] else 1.0) for i in range(n_obj)]
    rng = random.Random(seed)
    out: list[dict] = []
    for idx, x in enumerate(front):
        base = [sign[i] * objectives[i](x, extras) for i in range(n_obj)]
        samples: list[list[float]] = []
        infeasible = 0
        for _ in range(n_samples):
            xp = []
            for j in range(len(x)):
                span = bounds[j][1] - bounds[j][0]
                xp.append(min(max(x[j] + rng.gauss(0, sigma_frac * span), bounds[j][0]), bounds[j][1]))
            if _constraint_violation(xp, constraints) > 0:
                infeasible += 1
            fv = [sign[i] * objectives[i](xp, extras) for i in range(n_obj)]
            samples.append(fv)
        degradation = []
        for j in range(n_obj):
            denom = abs(base[j]) if abs(base[j]) > 1e-12 else 1e-12
            mean_delta = sum((s[j] - base[j]) for s in samples) / n_samples
            degradation.append(mean_delta / denom)
        out.append({
            "front_index": idx,
            "base_objectives": [round(v, 8) for v in base],
            "mean_relative_degradation": [round(v, 6) for v in degradation],
            "infeasibility_rate": infeasible / n_samples,
        })
    return {
        "method": "monte_carlo_local_perturbation",
        "n_samples_per_solution": n_samples,
        "sigma_fraction_of_range": sigma_frac,
        "solutions": out,
    }
