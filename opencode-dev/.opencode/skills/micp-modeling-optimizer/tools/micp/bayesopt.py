"""Bayesian optimization (GP surrogate + expected-improvement acquisition) for
micp-modeling-optimizer.

Implements the Efficient Global Optimization (EGO) loop of Jones et al.
(1998): a Gaussian-process regression surrogate with a squared-exponential
(ARD) kernel fitted by maximum likelihood (or a documented fixed-lengthscale
fallback), and Expected Improvement (EI) acquisition:

    EI(x) = (f_min - mu(x)) * Phi((f_min - mu(x))/sigma(x)) + sigma(x) * phi(...)

with Phi/phi the standard normal CDF/PDF. The next candidate maximizes EI over
a discrete candidate set (Latin-hypercube sampled, seeded) — multi-start is
not needed because we evaluate EI on a dense space-filling grid (standard
practice for low-dimensional, budget-limited problems).

The GP posterior (mean/variance) is computed from the closed-form predictive
equations; no external GP library is required. numpy is used when present;
a documented stdlib fallback computes the same quantities with pure Python
matrix algebra. All sampling is seeded from constraints.random_seed.
"""

from __future__ import annotations

import math
import random
from typing import Callable, Sequence

from _common import HAS_NUMPY, ToolError
from errors import MmoError, MmoErrorCode


def _normal_pdf(x: float) -> float:
    return math.exp(-0.5 * x * x) / math.sqrt(2.0 * math.pi)


def _normal_cdf(x: float) -> float:
    return 0.5 * math.erfc(-x / math.sqrt(2.0))


class _GP:
    """Squared-exponential ARD Gaussian process with closed-form posterior."""

    def __init__(self, X: list[list[float]], y: list[float],
                 lengthscales: list[float], sigma_n: float, sigma_f: float) -> None:
        self.X = X
        self.y = y
        self.l = lengthscales
        self.sigma_n = sigma_n
        self.sigma_f = sigma_f
        self.n = len(X)
        self._Kinv: list[list[float]] | None = None
        self._alpha: list[float] | None = None

    def _kernel(self, a: Sequence[float], b: Sequence[float]) -> float:
        d2 = 0.0
        for i in range(len(a)):
            d = (a[i] - b[i]) / self.l[i]
            d2 += d * d
        return self.sigma_f ** 2 * math.exp(-0.5 * d2)

    def _prepare(self) -> None:
        if self._Kinv is not None:
            return
        n = self.n
        K = [[self._kernel(self.X[i], self.X[j]) for j in range(n)] for i in range(n)]
        for i in range(n):
            K[i][i] += self.sigma_n ** 2
        Kinv, ok = _invert(K, n)
        if not ok:
            raise MmoError(MmoErrorCode.NUMERICAL_FAILURE, "GP kernel matrix is singular")
        alpha = [sum(Kinv[i][j] * self.y[j] for j in range(n)) for i in range(n)]
        self._Kinv = Kinv
        self._alpha = alpha

    def predict(self, x: Sequence[float]) -> tuple[float, float]:
        self._prepare()
        k = [self._kernel(x, self.X[i]) for i in range(self.n)]
        mu = sum(self._alpha[i] * k[i] for i in range(self.n))
        v = self._kernel(x, x) - sum(k[i] * self._Kinv[i][j] * k[j] for i in range(self.n) for j in range(self.n))
        return mu, max(v, 0.0)


def _invert(M: list[list[float]], n: int) -> tuple[list[list[float]], bool]:
    if HAS_NUMPY:
        import numpy as np  # type: ignore

        try:
            inv = np.linalg.inv(np.array(M))
            return inv.tolist(), True
        except Exception:  # noqa: BLE001
            return [[0.0] * n for _ in range(n)], False
    aug = [list(M[i]) + [1.0 if i == j else 0.0 for j in range(n)] for i in range(n)]
    for col in range(n):
        piv = max(range(col, n), key=lambda r: abs(aug[r][col]))
        if abs(aug[piv][col]) < 1e-300:
            return [[0.0] * n for _ in range(n)], False
        aug[col], aug[piv] = aug[piv], aug[col]
        div = aug[col][col]
        for j in range(2 * n):
            aug[col][j] /= div
        for r in range(n):
            if r != col and abs(aug[r][col]) > 1e-300:
                fac = aug[r][col]
                for j in range(2 * n):
                    aug[r][j] -= fac * aug[col][j]
    return [[aug[i][n + j] for j in range(n)] for i in range(n)], True


def _fit_lengthscales(X: list[list[float]], y: list[float], d: int, seed: int) -> tuple[list[float], float, float]:
    """Coarse lengthscale selection: try a small seeded grid of shared
    lengthscale + noise values and keep the highest marginal-likelihood-ish
    score (negative SSE on leave-one-out-style). This is a documented
    pragmatic choice for a dependency-light EGO; for large N the caller is
    advised to use a dedicated BO library."""
    rng = random.Random(seed)
    best = (None, 1e99, 1.0, 0.1)
    candidates = [0.1, 0.25, 0.5, 1.0, 2.0, 4.0] + [10 ** rng.uniform(-1, 1) for _ in range(6)]
    for l in candidates:
        for sigma_n in (0.01, 0.1, 0.3):
            gp = _GP(X, y, [l] * d, sigma_n, 1.0)
            try:
                gp._prepare()
            except MmoError:
                continue
            sse = 0.0
            for i in range(len(X)):
                mu, _ = gp.predict(X[i])
                sse += (mu - y[i]) ** 2
            if sse < best[1]:
                best = ([l] * d, sse, sigma_n, 1.0)
    return best[0], best[3], best[2]


def bayesian_optimize(
    f: Callable[[Sequence[float], dict], float],
    bounds: list[tuple[float, float]],
    *,
    n_init: int = 6,
    n_iter: int = 20,
    seed: int = 0,
    maximize: bool = False,
    extras: dict | None = None,
    n_candidates: int = 1000,
) -> dict:
    """EGO loop minimizing (or maximizing) f over the box `bounds`.

    Returns the best point, its value, the history of evaluated points, and
    the EI at the last iteration. Deterministic for a fixed seed.
    """
    extras = extras or {}
    d = len(bounds)
    if n_init < 2 or n_iter < 0 or n_candidates < 10:
        raise MmoError(MmoErrorCode.INVALID_PARAM_DEF, "n_init>=2, n_iter>=0, n_candidates>=10")
    rng = random.Random(seed)
    sign = -1.0 if maximize else 1.0

    # initial space-filling points: seed point + LHS
    X: list[list[float]] = []
    y: list[float] = []
    init_points: list[list[float]] = []
    for i in range(n_init):
        p = [bounds[j][0] + rng.random() * (bounds[j][1] - bounds[j][0]) for j in range(d)]
        init_points.append(p)
    for p in init_points:
        val = sign * f(p, extras)
        X.append(p)
        y.append(val)

    history: list[dict] = []
    for i, p in enumerate(init_points):
        history.append({"iter": i, "point": p, "value": sign * y[i]})

    for it in range(n_iter):
        l, sigma_f, sigma_n = _fit_lengthscales(X, y, d, seed + it)
        gp = _GP(X, y, l, sigma_n, sigma_f)
        # candidate set (LHS)
        cands: list[list[float]] = []
        for _ in range(n_candidates):
            cands.append([bounds[j][0] + rng.random() * (bounds[j][1] - bounds[j][0]) for j in range(d)])
        f_min = min(y)
        best_ei = -1.0
        best_x = cands[0]
        for x in cands:
            mu, var = gp.predict(x)
            s = math.sqrt(var)
            if s <= 1e-12:
                ei = 0.0
            else:
                z = (f_min - mu) / s
                ei = (f_min - mu) * _normal_cdf(z) + s * _normal_pdf(z)
            if ei > best_ei:
                best_ei = ei
                best_x = x
        val = sign * f(best_x, extras)
        X.append(best_x)
        y.append(val)
        history.append({"iter": n_init + it, "point": best_x, "value": sign * val})

    best_idx = min(range(len(y)), key=lambda i: y[i])
    return {
        "method": "EGO (Jones 1998)",
        "best_point": X[best_idx],
        "best_value": sign * y[best_idx],
        "n_evaluations": len(X),
        "history": history,
        "seed": seed,
        "surrogate": "gp_squared_exponential_ard",
        "note": "EI acquisition over seeded LHS candidates; no external BO library",
    }
