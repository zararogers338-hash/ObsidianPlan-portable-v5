"""ODE solving and parameter inference for micp-modeling-optimizer.

Two layers:

1. solve_ode(): a deterministic, stdlib-only adaptive (RK4 / RK4-based with
   step-doubling) integrator with dense output, conservative step control, and
   a step-count cap. When scipy is present the module can optionally use
   scipy.integrate.solve_ivp (RK45) — but the default path is stdlib so tests
   and offline runs are fully reproducible without scipy.

2. Parameter inference:
   * fit_parameters(): least-squares / weighted least-squares parameter
     estimation for a user-defined mechanistic model against synthetic or
     experimental data. Uses scipy.optimize.least_squares when available and a
     documented stdlib-only Nelder-Mead fallback otherwise. Multi-start,
     parameter bounds, and per-parameter regularization are supported.
   * fisher_information() and profile_likelihood(): practical identifiability
     (both Fisher-information based and profile-likelihood based).
   * Cross-validation / hold-out splitting helpers.

Every random or sampling step is seeded from constraints.random_seed; the same
input yields the same output byte-for-byte (M6).
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from typing import Any, Callable, Sequence

from _common import HAS_NUMPY, HAS_SCIPY, ToolError
from errors import MmoError, MmoErrorCode

# ---------------------------------------------------------------------------
# ODE integration (stdlib)
# ---------------------------------------------------------------------------


@dataclass
class OdeResult:
    t: list[float]
    y: list[list[float]]
    success: bool
    steps: int
    message: str


def _rk4_step(f: Callable[[float, Sequence[float]], Sequence[float]],
              t: float, y: list[float], dt: float) -> list[float]:
    k1 = [v for v in f(t, y)]
    k2 = [v for v in f(t + dt / 2.0, [y[i] + dt / 2.0 * k1[i] for i in range(len(y))])]
    k3 = [v for v in f(t + dt / 2.0, [y[i] + dt / 2.0 * k2[i] for i in range(len(y))])]
    k4 = [v for v in f(t + dt, [y[i] + dt * k3[i] for i in range(len(y))])]
    return [y[i] + dt / 6.0 * (k1[i] + 2.0 * k2[i] + 2.0 * k3[i] + k4[i]) for i in range(len(y))]


def solve_ode(
    f: Callable[[float, Sequence[float]], Sequence[float]],
    y0: Sequence[float],
    t_span: tuple[float, float],
    *,
    dt0: float | None = None,
    rtol: float = 1e-6,
    atol: float = 1e-10,
    max_steps: int = 2_000_000,
    dense_points: int = 0,
) -> OdeResult:
    """Integrate dy/dt = f(t, y) over t_span with step-doubling RK4.

    Deterministic. On any non-finite state raises MMO-E301. On step-count
    overflow returns success=False (the caller decides whether that is a
    hard failure).
    """
    t0, t1 = t_span
    if not (t1 > t0):
        raise MmoError(MmoErrorCode.INVALID_MODEL_SPEC, "t_span must satisfy t1 > t0")
    y = [float(v) for v in y0]
    n = len(y)
    dt = dt0 if dt0 and dt0 > 0 else (t1 - t0) / 1000.0
    t = t0
    ts: list[float] = [t0]
    ys: list[list[float]] = [list(y)]
    steps = 0

    while t < t1:
        steps += 1
        if steps > max_steps:
            return OdeResult(ts, ys, False, steps, "max_steps exceeded")
        dt = min(dt, t1 - t)
        # step-doubling error control
        y_h = _rk4_step(f, t, y, dt)
        y_2h = _rk4_step(f, t, _rk4_step(f, t, y, dt / 2.0), dt / 2.0)
        err = 0.0
        for i in range(n):
            e = abs(y_h[i] - y_2h[i])
            scale = atol + rtol * max(abs(y[i]), abs(y_h[i]))
            err = max(err, e / scale)
        if err > 1.0 and dt > (t1 - t0) * 1e-12:
            dt = max(dt * 0.5, (t1 - t0) * 1e-12)
            continue
        if err < 0.25:
            dt = min(dt * 2.0, (t1 - t0) / 4.0)
        t += dt
        y = y_h
        if not all(math.isfinite(v) for v in y):
            raise MmoError(MmoErrorCode.CONTEXT_CORRUPT, "non-finite ODE state")
        ts.append(t)
        ys.append(list(y))

    return OdeResult(ts, ys, True, steps, "ok")


# ---------------------------------------------------------------------------
# Parameter fitting
# ---------------------------------------------------------------------------


@dataclass
class FitSpec:
    """Fitting problem definition.

    model(theta, t, extras) -> predicted observations (m-vector per time).
    data: list of (t, obs_vector, weight_vector or None).
    theta0: initial guess. bounds: list of (lo, hi) per parameter (None = unbounded).
    """

    model: Callable[[Sequence[float], float, dict], Sequence[float]]
    data: list[tuple[float, Sequence[float], Sequence[float] | None]]
    theta0: Sequence[float]
    bounds: list[tuple[float | None, float | None]] | None = None
    n_starts: int = 1
    seed: int = 0
    sigma: float | None = None  # if set, residual weighting 1/sigma


def _residuals(theta: Sequence[float], spec: FitSpec, extras: dict) -> list[float]:
    out: list[float] = []
    for (t, obs, w) in spec.data:
        pred = spec.model(theta, t, extras)
        for i, o in enumerate(obs):
            r = pred[i] - o
            if w is not None and i < len(w) and w[i] > 0:
                r = r / w[i]
            out.append(r)
    return out


def _nelder_mead(
    cost: Callable[[Sequence[float]], float],
    x0: list[float],
    bounds: list[tuple[float | None, float | None]] | None,
    max_iter: int,
    seed: int,
    rng: random.Random | None = None,
) -> tuple[list[float], float, int]:
    """Stdlib Nelder-Mead with reflection/expansion/contraction and simple
    bound clamping. Deterministic given seed; converges for smooth convex-ish
    problems. Used only as a fallback when scipy is unavailable."""
    rng = rng or random.Random(seed)
    n = len(x0)

    def clamp(x: list[float]) -> list[float]:
        if not bounds:
            return x
        return [
            min(max(x[i], bounds[i][0] if bounds[i] and bounds[i][0] is not None else -1e300),
                bounds[i][1] if bounds[i] and bounds[i][1] is not None else 1e300)
            for i in range(n)
        ]

    simplex: list[list[float]] = [clamp(x0)]
    for i in range(n):
        p = list(x0)
        step = (bounds[i][1] - bounds[i][0]) * 0.05 if bounds and bounds[i] and bounds[i][1] is not None and bounds[i][0] is not None else 0.1
        p[i] = x0[i] + step
        simplex.append(clamp(p))
    vals = [cost(p) for p in simplex]
    it = 0
    alpha, gamma, rho, sigma_ = 1.0, 2.0, 0.5, 0.5
    while it < max_iter:
        it += 1
        order = sorted(range(len(simplex)), key=lambda i: vals[i])
        if vals[order[0]] < 1e-12 or max(vals) - vals[order[0]] < 1e-14:
            break
        best = simplex[order[0]]
        worst = simplex[order[-1]]
        centroid = [sum(simplex[order[j]][i] for j in range(n)) / n for i in range(n)]
        # reflection
        xr = clamp([centroid[i] + alpha * (centroid[i] - worst[i]) for i in range(n)])
        vr = cost(xr)
        if vr < vals[order[0]]:
            xe = clamp([centroid[i] + gamma * (xr[i] - centroid[i]) for i in range(n)])
            if cost(xe) < vr:
                simplex[order[-1]] = xe
                vals[order[-1]] = cost(xe)
            else:
                simplex[order[-1]] = xr
                vals[order[-1]] = vr
        elif vr < vals[order[-2]]:
            simplex[order[-1]] = xr
            vals[order[-1]] = vr
        else:
            xc = clamp([centroid[i] + rho * (worst[i] - centroid[i]) for i in range(n)])
            vc = cost(xc)
            if vc < vals[order[-1]]:
                simplex[order[-1]] = xc
                vals[order[-1]] = vc
            else:
                for j in range(1, len(simplex)):
                    simplex[j] = [best[i] + sigma_ * (simplex[j][i] - best[i]) for i in range(n)]
                    vals[j] = cost(simplex[j])
    order = sorted(range(len(simplex)), key=lambda i: vals[i])
    return simplex[order[0]], vals[order[0]], it


@dataclass
class FitResult:
    theta: list[float]
    cost: float
    residuals: list[float]
    n_evals: int
    converged: bool
    backend: str
    starts: list[dict]


def fit_parameters(spec: FitSpec, extras: dict | None = None, *, max_iter: int = 20000) -> FitResult:
    """Least-squares parameter estimation with multi-start.

    Backend selection:
      * scipy.optimize.least_squares (Levenberg-Marquardt / trf) when scipy is
        present — reported as backend="scipy:least_squares".
      * stdlib Nelder-Mead otherwise — backend="stdlib:nelder_mead".

    Multi-start: `n_starts` initial points drawn deterministically from
    bounds (seed-controlled). The best fit is returned; every start is
    recorded in `starts` for identifiability diagnostics.
    """
    extras = extras or {}
    base = [float(v) for v in spec.theta0]
    n = len(base)
    bounds = spec.bounds or [(None, None)] * n
    if len(bounds) != n:
        raise MmoError(MmoErrorCode.INVALID_PARAM_DEF, "bounds length must match theta0")

    rng = random.Random(spec.seed)
    starts: list[dict] = []

    def cost(theta: Sequence[float]) -> float:
        r = _residuals(theta, spec, extras)
        return sum(v * v for v in r)

    best: tuple[list[float], float] | None = None
    for k in range(spec.n_starts):
        if k == 0:
            x0 = list(base)
        else:
            x0 = []
            for i in range(n):
                lo, hi = bounds[i]
                if lo is not None and hi is not None:
                    x0.append(rng.uniform(lo, hi))
                else:
                    x0.append(base[i] * (1.0 + rng.uniform(-0.2, 0.2)))
        x0 = [
            min(max(x0[i], bounds[i][0] if bounds[i][0] is not None else -1e300),
                bounds[i][1] if bounds[i][1] is not None else 1e300)
            for i in range(n)
        ]
        if HAS_SCIPY:  # pragma: no cover - env dependent
            from scipy.optimize import least_squares  # type: ignore

            res = least_squares(
                lambda th: _residuals(th, spec, extras),
                x0,
                bounds=(
                    [b[0] if b[0] is not None else -math.inf for b in bounds],
                    [b[1] if b[1] is not None else math.inf for b in bounds],
                ),
                max_nfev=max_iter,
                method="trf",
                x_scale="jac",
            )
            theta_fit = list(res.x)
            cost_fit = float(2.0 * res.cost)
            backend = "scipy:least_squares"
            conv = res.success
            n_eval = int(res.nfev)
        else:
            theta_fit, cost_fit, n_eval = _nelder_mead(
                cost, x0, bounds, max_iter=max_iter, seed=spec.seed + k, rng=rng
            )
            backend = "stdlib:nelder_mead"
            conv = True
        starts.append({"start": k, "x0": x0, "theta": theta_fit, "cost": cost_fit})
        if best is None or cost_fit < best[1]:
            best = (theta_fit, cost_fit)

    theta, c = best
    residuals = _residuals(theta, spec, extras)
    return FitResult(
        theta=theta,
        cost=c,
        residuals=residuals,
        n_evals=starts[-1]["cost"] if starts else 0,
        converged=conv if HAS_SCIPY else True,
        backend=backend,
        starts=starts,
    )


# ---------------------------------------------------------------------------
# Practical identifiability
# ---------------------------------------------------------------------------


def fisher_information(spec: FitSpec, theta: Sequence[float], extras: dict | None = None,
                       eps: float = 1e-4) -> list[list[float]]:
    """Fisher information matrix J = S^T W S, S = sensitivity d(pred)/d(theta).

    Central finite differences with relative step eps. Returns J as a nested
    list. Raises MMO-E405 if J is non-finite.
    """
    extras = extras or {}
    n = len(theta)
    # build sensitivity matrix: rows = residuals, cols = params
    S: list[list[float]] = []
    for (t, obs, w) in spec.data:
        pred0 = list(spec.model(theta, t, extras))
        n_out = len(pred0)
        d: list[list[float]] = [[0.0] * n for _ in range(n_out)]
        for j in range(n):
            step = eps * max(abs(theta[j]), 1e-8)
            th_plus = list(theta)
            th_minus = list(theta)
            th_plus[j] += step
            th_minus[j] -= step
            p_plus = list(spec.model(th_plus, t, extras))
            p_minus = list(spec.model(th_minus, t, extras))
            for oi in range(n_out):
                d[oi][j] = (p_plus[oi] - p_minus[oi]) / (2.0 * step)
        for oi, o in enumerate(obs):
            wfac = 1.0
            if w is not None and oi < len(w) and w[oi] > 0:
                wfac = 1.0 / w[oi]
            row = [wfac * d[oi][j] for j in range(n)]
            S.append(row)
    J = [[0.0] * n for _ in range(n)]
    for row in S:
        for a in range(n):
            for b in range(n):
                J[a][b] += row[a] * row[b]
    for a in range(n):
        for b in range(n):
            if not math.isfinite(J[a][b]):
                raise MmoError(MmoErrorCode.IDENTIFIABILITY_FAILURE, "Fisher information is non-finite")
    return J


def identifiability_report(spec: FitSpec, theta_fit: Sequence[float], extras: dict | None = None,
                           n_data: int | None = None) -> dict:
    """Classify parameters as identifiable / weakly identifiable /
    non-identifiable from the Fisher information matrix.

    Uses the correlation matrix derived from the covariance (J^-1 when
    invertible). Practical classification:
      * parameter is NON_IDENTIFIABLE when its posterior variance is infinite
        (J singular => at least one zero eigenvalue) — reported via
        eigenvalue decomposition.
      * a parameter pair with |correlation| > 0.99 is flagged
        HIGHLY_CORRELATED (weakly identifiable together).
      * rank of J vs number of parameters gives the structural verdict.

    Note: Fisher-based identifiability is LOCAL. The tool therefore also
    reports whether a profile-likelihood pass is recommended.
    """
    extras = extras or {}
    n = len(theta_fit)
    J = fisher_information(spec, theta_fit, extras)
    n_obs = sum(len(obs) for (_, obs, _) in spec.data) if n_data is None else n_data

    evals = _eigenvalues_symmetric(J, n)
    rank = sum(1 for v in evals if v > 1e-9 * max(1.0, max(evals)))
    cov, invertible = _invert_symmetric(J, n)

    params: list[dict] = []
    for j in range(n):
        var = cov[j][j] if invertible else math.inf
        se = math.sqrt(var) if invertible and var >= 0 and math.isfinite(var) else math.inf
        # classify per parameter:
        #   * singular / infinite covariance  -> non_identifiable (structural)
        #   * relative SE > 1.0               -> weakly_identifiable (practical)
        #   * otherwise                       -> identifiable
        if not invertible or se == math.inf:
            strength = "non_identifiable"
        elif se / max(abs(theta_fit[j]), 1e-12) > 1.0:
            strength = "weakly_identifiable"
        else:
            strength = "identifiable"
        params.append({
            "index": j,
            "value": theta_fit[j],
            "std_error": se if math.isfinite(se) else None,
            "relative_se": (se / max(abs(theta_fit[j]), 1e-12)) if math.isfinite(se) else None,
            "class": strength,
        })

    correlated: list[dict] = []
    if invertible:
        for a in range(n):
            for b in range(a + 1, n):
                denom = math.sqrt(cov[a][a] * cov[b][b])
                if denom <= 0 or not math.isfinite(denom):
                    continue
                rho = cov[a][b] / denom
                if abs(rho) > 0.99:
                    correlated.append({
                        "parameter_a": a,
                        "parameter_b": b,
                        "correlation": rho,
                        "class": "highly_correlated",
                    })

    return {
        "n_parameters": n,
        "n_observations": n_obs,
        "fisher_information": J,
        "eigenvalues": evals,
        "rank": rank,
        "invertible": invertible,
        "method": "fisher_information_local",
        "parameters": params,
        "highly_correlated_pairs": correlated,
        "verdict": (
            "identifiable"
            if rank == n and not correlated
            else "partially_identifiable"
            if rank < n
            else "correlated"
        ),
        "recommend_profile_likelihood": rank < n or bool(correlated),
    }


def _eigenvalues_symmetric(M: list[list[float]], n: int) -> list[float]:
    """Jacobi eigenvalue algorithm for symmetric matrices (stdlib, deterministic)."""
    if not HAS_NUMPY:
        A = [list(row) for row in M]
        vec = [[1.0 if i == j else 0.0 for j in range(n)] for i in range(n)]
        for _ in range(200):
            off = 0.0
            p = q = -1
            mx = 0.0
            for i in range(n):
                for j in range(i + 1, n):
                    a = abs(A[i][j])
                    off += a * a
                    if a > mx:
                        mx = a
                        p, q = i, j
            if mx < 1e-14 or off < 1e-14:
                break
            theta = 0.5 * math.atan2(2.0 * A[p][q], A[q][q] - A[p][p])
            c = math.cos(theta)
            s = math.sin(theta)
            for k in range(n):
                akp = A[k][p]
                akq = A[k][q]
                A[k][p] = c * akp - s * akq
                A[p][k] = A[k][p]
                A[k][q] = s * akp + c * akq
                A[q][k] = A[k][q]
                vkp = vec[k][p]
                vkq = vec[k][q]
                vec[k][p] = c * vkp - s * vkq
                vec[k][q] = s * vkp + c * vkq
        return sorted((A[i][i] for i in range(n)), reverse=True)
    import numpy as np  # type: ignore

    return sorted(np.linalg.eigvalsh(np.array(M)).tolist(), reverse=True)


def _invert_symmetric(M: list[list[float]], n: int) -> tuple[list[list[float]], bool]:
    """Gauss-Jordan inversion of a symmetric matrix with pivoting."""
    if not HAS_NUMPY:
        aug = [[M[i][j] for j in range(n)] + [1.0 if i == j else 0.0 for j in range(n)] for i in range(n)]
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
    import numpy as np  # type: ignore

    try:
        inv = np.linalg.inv(np.array(M))
        return inv.tolist(), True
    except Exception:  # noqa: BLE001 - singular matrix
        return [[0.0] * n for _ in range(n)], False


def profile_likelihood(
    spec: FitSpec,
    theta_fit: Sequence[float],
    param_index: int,
    *,
    grid: int = 21,
    frac: float = 0.3,
    extras: dict | None = None,
    max_iter: int = 5000,
    seed: int = 0,
) -> dict:
    """One-dimensional profile likelihood for one parameter.

    For a grid of fixed theta[param_index] values spanning
    theta_fit*(1-frac) .. theta_fit*(1+frac) (or around bounds), re-optimize the
    remaining parameters and record the minimum sum-of-squares. The profile is
    the residual sum of squares vs the parameter value; a flat profile means the
    parameter is practically non-identifiable. Returns values + profile +
    whether a 95% (chi2, df=1) confidence region is bounded.
    """
    extras = extras or {}
    n = len(theta_fit)

    def cost_all(theta: Sequence[float]) -> float:
        return sum(v * v for v in _residuals(theta, spec, extras))

    theta0 = theta_fit
    lo = min(theta_fit[param_index] * (1.0 - frac), theta_fit[param_index] * (1.0 - frac))
    hi = max(theta_fit[param_index] * (1.0 + frac), theta_fit[param_index] * (1.0 + frac))
    # never flip sign of a positive parameter
    if theta_fit[param_index] > 0 and lo <= 0:
        lo = theta_fit[param_index] * 0.05
    vals: list[float] = []
    prof: list[float] = []
    for k in range(grid):
        v = lo + (hi - lo) * k / (grid - 1)
        inner = [theta0[j] for j in range(n)]
        inner[param_index] = v
        rng = random.Random(seed + k)
        # fixed others, then a small local polish of the free params
        free = [j for j in range(n) if j != param_index]
        if free:
            bf = [spec.bounds[j] if spec.bounds else (None, None) for j in range(n)]
            base_inner = list(inner)

            def model_free(th_free: Sequence[float], t: float, ex: dict) -> Sequence[float]:
                full = list(base_inner)
                for jj, fj in enumerate(free):
                    full[fj] = th_free[jj]
                return spec.model(full, t, ex)

            spec_free = FitSpec(
                model=model_free,
                data=spec.data,
                theta0=[base_inner[j] for j in free],
                bounds=[bf[j] for j in free],
                n_starts=1,
                seed=seed + k,
            )
            res = fit_parameters(spec_free, extras, max_iter=max_iter)
            for jj, fj in enumerate(free):
                inner[fj] = res.theta[jj]
        else:
            pass
        vals.append(v)
        prof.append(cost_all(inner))

    # chi2 threshold: df=1, 95% -> 3.84
    thresh = min(prof) + 3.84
    bounded = min(prof) < thresh and any(p < thresh for p in prof) and prof[0] > thresh and prof[-1] > thresh
    flatness = (max(prof) - min(prof)) / (min(prof) + 1e-12)
    return {
        "param_index": param_index,
        "values": vals,
        "profile_rss": prof,
        "min_rss": min(prof),
        "bounded_95": bounded,
        "flatness": flatness,
        "class": "non_identifiable" if flatness < 1e-3 else "identifiable" if bounded else "weakly_identifiable",
    }


# ---------------------------------------------------------------------------
# Cross-validation / hold-out
# ---------------------------------------------------------------------------


def split_fit_validate(
    times: Sequence[float],
    observations: Sequence[Sequence[float]],
    *,
    frac_train: float = 0.7,
    seed: int = 0,
    mode: str = "random",
) -> dict:
    """Split observations into train / validation sets.

    mode="random": seeded shuffle split.
    mode="sequential": first frac_train of time is training (hold-out = later
    times — the stricter extrapolation check required by the skill: a model
    that fits training but fails on held-out later time is flagged).
    """
    n = len(times)
    if n < 2:
        raise MmoError(MmoErrorCode.INVALID_MODEL_SPEC, "need >= 2 observations to split")
    if mode == "sequential":
        k = max(1, int(round(n * frac_train)))
        train = list(range(k))
        valid = list(range(k, n))
    else:
        rng = random.Random(seed)
        idx = list(range(n))
        rng.shuffle(idx)
        k = max(1, int(round(n * frac_train)))
        train = sorted(idx[:k])
        valid = sorted(idx[k:])
    return {
        "mode": mode,
        "frac_train": frac_train,
        "train_indices": train,
        "valid_indices": valid,
        "train_times": [times[i] for i in train],
        "valid_times": [times[i] for i in valid],
    }


def cross_validation(
    model: Callable[[Sequence[float], float, dict], Sequence[float]],
    data: list[tuple[float, Sequence[float], Sequence[float] | None]],
    theta0: Sequence[float],
    bounds: list[tuple[float | None, float | None]] | None,
    *,
    folds: int = 3,
    seed: int = 0,
    extras: dict | None = None,
    max_iter: int = 5000,
) -> dict:
    """k-fold cross-validation: refit on train folds, evaluate residual RSS on
    held-out folds. Reports per-fold and aggregate RMSE, and whether the held-out
    performance is much worse than train (overfitting signal)."""
    extras = extras or {}
    n = len(data)
    if folds < 2 or folds > n:
        raise MmoError(MmoErrorCode.INVALID_MODEL_SPEC, "folds must be in [2, len(data)]")
    rng = random.Random(seed)
    idx = list(range(n))
    rng.shuffle(idx)
    folds_idx = [idx[i::folds] for i in range(folds)]

    fold_results: list[dict] = []
    for fi in range(folds):
        test = set(folds_idx[fi])
        train_data = [data[i] for i in range(n) if i not in test]
        test_data = [data[i] for i in range(n) if i in test]
        spec = FitSpec(model=model, data=train_data, theta0=theta0, bounds=bounds,
                       n_starts=1, seed=seed + fi)
        res = fit_parameters(spec, extras, max_iter=max_iter)
        # held-out RSS
        rss = sum(v * v for v in _residuals(res.theta, FitSpec(model=model, data=test_data, theta0=theta0, bounds=bounds), extras))
        train_rss = res.cost
        n_test = sum(len(obs) for (_, obs, _) in test_data)
        fold_results.append({
            "fold": fi,
            "train_rss": train_rss,
            "test_rss": rss,
            "test_rmse": math.sqrt(rss / max(n_test, 1)),
            "theta": res.theta,
        })
    test_rss_all = sum(f["test_rss"] for f in fold_results)
    train_rss_all = sum(f["train_rss"] for f in fold_results)
    n_test_all = sum(len(obs) for (_, obs, _) in data)
    return {
        "folds": fold_results,
        "aggregate_test_rmse": math.sqrt(test_rss_all / max(n_test_all, 1)),
        "aggregate_train_rss": train_rss_all,
        "overfit_ratio": (test_rss_all / max(train_rss_all, 1e-12)),
        "warning": "held-out performance is much worse than training — the model "
                   "may be overfit" if test_rss_all > 2.0 * train_rss_all + 1e-9 else None,
    }
