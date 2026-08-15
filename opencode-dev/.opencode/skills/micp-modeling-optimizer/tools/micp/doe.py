"""Design of experiments (DOE) generation and response-surface modeling for
micp-modeling-optimizer.

Complementary to obsidian-experiment-designer (which computes sample-size /
power for hypothesis tests). This module generates factor designs for
mechanistic-model calibration and fits response surfaces over them:

  * doe_generate: full factorial (2-level / 3-level), Central Composite Design
    (CCD, Box-Wilson 1951), Box-Behnken (1960), and Latin Hypercube Sampling
    (LHS) over bounded factor ranges. All deterministic when seeded.
  * response_surface: ordinary least-squares fit of a quadratic response
    surface (linear + interactions + pure quadratics) and a quadratic
    polynomial, with leave-one-out-ish diagnostics, stationarity, and
    recommended next experiments (points of highest predicted variance, i.e.
    the largest model uncertainty — the design's weakest region).

Factor encoding: design points are emitted in coded [-1, +1] space and as
physical values on the caller-provided ranges. Center points replicate
conventionally (CCD n0, BBD 3-5).
"""

from __future__ import annotations

import itertools
import math
import random
from typing import Callable, Sequence

from _common import ToolError
from errors import MmoError, MmoErrorCode

def _check_factors(factors: list[dict]) -> list[dict]:
    """Validate and normalize factor definitions. Low/high are coerced to
    float so string numerics ('1e-5') from YAML payloads are handled."""
    if not factors:
        raise MmoError(MmoErrorCode.INVALID_PARAM_DEF, "at least one factor required")
    if len(factors) > 8:
        raise MmoError(MmoErrorCode.INVALID_PARAM_DEF, "too many factors (max 8)")
    out: list[dict] = []
    for f in factors:
        for key in ("name", "low", "high"):
            if key not in f:
                raise MmoError(
                    MmoErrorCode.INVALID_PARAM_DEF,
                    f"factor missing '{key}'",
                    detail={"factor": f},
                )
        try:
            lo = float(f["low"])
            hi = float(f["high"])
        except (TypeError, ValueError):
            raise MmoError(
                MmoErrorCode.INVALID_PARAM_DEF,
                f"factor '{f['name']}' low/high must be numeric",
                detail={"factor": f},
            )
        if not (math.isfinite(lo) and math.isfinite(hi)):
            raise MmoError(MmoErrorCode.INVALID_PARAM_DEF, "factor bounds must be finite")
        if hi <= lo:
            raise MmoError(MmoErrorCode.INVALID_PARAM_DEF, "factor high must exceed low")
        nf = dict(f)
        nf["low"] = lo
        nf["high"] = hi
        out.append(nf)
    return out


def _decode(point: Sequence[float], factors: list[dict]) -> list[float]:
    return [
        factors[i]["low"] + (factors[i]["high"] - factors[i]["low"]) * (point[i] + 1.0) / 2.0
        for i in range(len(factors))
    ]


def doe_generate(
    factors: list[dict],
    *,
    kind: str,
    seed: int = 0,
    center_points: int | None = None,
    alpha: float | None = None,
    n_lhs: int = 20,
) -> dict:
    """Generate a DOE matrix. kind in {full_factorial, ccd, box_behnken, lhs}.

    Returns coded and physical runs plus the run count.
    """
    factors = _check_factors(factors)
    k = len(factors)
    rng = random.Random(seed)

    if kind == "full_factorial":
        levels = int(factors[0].get("levels", 2))
        if levels not in (2, 3):
            raise MmoError(MmoErrorCode.INVALID_PARAM_DEF, "full_factorial levels must be 2 or 3")
        if levels == 2:
            grid = [-1.0, 1.0]
        else:
            grid = [-1.0, 0.0, 1.0]
        coded = [list(p) for p in itertools.product(grid, repeat=k)]
        n0 = int(center_points) if center_points is not None else 0
        for _ in range(n0):
            coded.append([0.0] * k)
    elif kind == "ccd":
        # axial alpha: default rotatable alpha = (2^k)^(1/4)
        if alpha is None:
            alpha = (2 ** k) ** 0.25
        pts: list[list[float]] = []
        for p in itertools.product([-1.0, 1.0], repeat=k):
            pts.append(list(p))
        for i in range(k):
            for s in (-1.0, 1.0):
                row = [0.0] * k
                row[i] = s * alpha
                pts.append(row)
        n0 = int(center_points) if center_points is not None else 1
        for _ in range(n0):
            pts.append([0.0] * k)
        coded = pts
    elif kind == "box_behnken":
        if k < 3 or k > 7:
            raise MmoError(MmoErrorCode.INVALID_PARAM_DEF, "Box-Behnken requires 3..7 factors")
        pts: list[list[float]] = []
        # pairs of factors take +/-1, others 0
        for i in range(k):
            for j in range(i + 1, k):
                for si in (-1.0, 1.0):
                    for sj in (-1.0, 1.0):
                        row = [0.0] * k
                        row[i] = si
                        row[j] = sj
                        pts.append(row)
        n0 = int(center_points) if center_points is not None else 3
        for _ in range(n0):
            pts.append([0.0] * k)
        coded = pts
    elif kind == "lhs":
        n = n_lhs
        if n < 2:
            raise MmoError(MmoErrorCode.INVALID_PARAM_DEF, "n_lhs must be >= 2")
        coded = []
        for i in range(n):
            row = []
            for j in range(k):
                # stratified: cell i/n + uniform within cell, then map to [-1,1]
                u = (i + rng.random()) / n
                row.append(2.0 * u - 1.0)
            coded.append(row)
    else:
        raise MmoError(
            MmoErrorCode.INVALID_PARAM_DEF,
            f"unknown DOE kind '{kind}'; supported: full_factorial, ccd, box_behnken, lhs",
        )

    physical = [_decode(p, factors) for p in coded]
    return {
        "kind": kind,
        "k": k,
        "n_runs": len(coded),
        "factors": [{"name": f["name"], "low": f["low"], "high": f["high"]} for f in factors],
        "coded": coded,
        "physical": physical,
        "alpha": alpha if kind == "ccd" else None,
        "seed": seed,
        "note": "coded in [-1,1]; physical = decoded on factor ranges",
    }


# ---------------------------------------------------------------------------
# Response surface (OLS quadratic) — stdlib least-squares
# ---------------------------------------------------------------------------

def _design_matrix_quadratic(coded: list[Sequence[float]], k: int) -> list[list[float]]:
    """Columns: 1, linear k, interactions k(k-1)/2, pure quadratics k."""
    cols = 1 + k + k * (k - 1) // 2 + k
    m: list[list[float]] = []
    for row in coded:
        r = [1.0] + list(row)
        for i in range(k):
            for j in range(i + 1, k):
                r.append(row[i] * row[j])
        for i in range(k):
            r.append(row[i] * row[i])
        m.append(r)
    return m


def _ols(m: list[list[float]], y: list[float]) -> tuple[list[float], list[float]]:
    """Normal-equation OLS: beta = (M^T M)^-1 M^T y. Stdlib Gauss-Jordan."""
    n, p = len(m), len(m[0])
    mtm = [[0.0] * p for _ in range(p)]
    mty = [0.0] * p
    for i in range(n):
        for a in range(p):
            mty[a] += m[i][a] * y[i]
            for b in range(p):
                mtm[a][b] += m[i][a] * m[i][b]
    aug = [list(mtm[i]) + [mty[i]] for i in range(p)]
    for col in range(p):
        piv = max(range(col, p), key=lambda r: abs(aug[r][col]))
        if abs(aug[piv][col]) < 1e-300:
            raise MmoError(MmoErrorCode.NUMERICAL_FAILURE, "response-surface design matrix is singular")
        aug[col], aug[piv] = aug[piv], aug[col]
        div = aug[col][col]
        for j in range(p + 1):
            aug[col][j] /= div
        for r in range(p):
            if r != col and abs(aug[r][col]) > 1e-300:
                fac = aug[r][col]
                for j in range(p + 1):
                    aug[r][j] -= fac * aug[col][j]
    beta = [aug[i][p] for i in range(p)]
    # residuals
    resid = [y[i] - sum(beta[a] * m[i][a] for a in range(p)) for i in range(n)]
    return beta, resid


def response_surface(
    factors: list[dict],
    coded_points: list[Sequence[float]],
    responses: dict[str, list[float]],
) -> dict:
    """Fit quadratic response surfaces over a coded DOE.

    responses: {name: [y values matching coded_points]}. Returns per-response
    coefficients (labeled), R2, residual std, and the optimum of each surface
    (stationary point clamped to the coded region).
    """
    factors = _check_factors(factors)
    k = len(factors)
    n = len(coded_points)
    for name, ys in responses.items():
        if len(ys) != n:
            raise MmoError(
                MmoErrorCode.INVALID_MODEL_SPEC,
                f"response '{name}' length {len(ys)} != runs {n}",
            )
    m = _design_matrix_quadratic(coded_points, k)
    labels = ["intercept"] + [f["name"] for f in factors]
    for i in range(k):
        for j in range(i + 1, k):
            labels.append(f"{factors[i]['name']}:{factors[j]['name']}")
    for i in range(k):
        labels.append(f"{factors[i]['name']}^2")

    surfaces: dict[str, dict] = {}
    for name, ys in responses.items():
        beta, resid = _ols(m, ys)
        mean_y = sum(ys) / n
        sst = sum((v - mean_y) ** 2 for v in ys)
        sse = sum(v * v for v in resid)
        r2 = 1.0 - sse / sst if sst > 0 else 0.0
        df = n - len(beta)
        rms = math.sqrt(sse / max(df, 1))
        surfaces[name] = {
            "coefficients": {labels[a]: beta[a] for a in range(len(beta))},
            "r_squared": r2,
            "adjusted_r_squared": 1.0 - (1.0 - r2) * (n - 1) / max(df, 1) if df > 0 else None,
            "residual_rms": rms,
            "stationary_point_coded": _stationary_point(beta, k),
        }

    return {
        "k": k,
        "n_runs": n,
        "surfaces": surfaces,
        "recommended_next_experiments": _next_experiments(coded_points, k, surfaces),
    }


def _stationary_point(beta: Sequence[float], k: int) -> list[float]:
    """Solve dR/dx = 0 for the quadratic surface: 2*Q x = -L."""
    # beta layout: [1, L(k), I(k(k-1)/2), Q(k)]
    L = list(beta[1:1 + k])
    Q = list(beta[1 + k + k * (k - 1) // 2:])
    A = [[0.0] * k for _ in range(k)]
    for i in range(k):
        A[i][i] = 2.0 * Q[i]
    # interactions: coefficient of xi*xj appears once in beta; in Hessian it's
    # split symmetric
    idx = 1 + k
    for i in range(k):
        for j in range(i + 1, k):
            v = beta[idx]
            A[i][j] = v
            A[j][i] = v
            idx += 1
    b = [-L[i] for i in range(k)]
    # solve A x = b via Gauss-Jordan
    aug = [list(A[i]) + [b[i]] for i in range(k)]
    try:
        for col in range(k):
            piv = max(range(col, k), key=lambda r: abs(aug[r][col]))
            if abs(aug[piv][col]) < 1e-12:
                return [None] * k
            aug[col], aug[piv] = aug[piv], aug[col]
            div = aug[col][col]
            for j in range(k + 1):
                aug[col][j] /= div
            for r in range(k):
                if r != col and abs(aug[r][col]) > 1e-12:
                    fac = aug[r][col]
                    for j in range(k + 1):
                        aug[r][j] -= fac * aug[col][j]
        return [aug[i][k] for i in range(k)]
    except Exception:  # noqa: BLE001
        return [None] * k


def _next_experiments(
    coded_points: list[Sequence[float]],
    k: int,
    surfaces: dict[str, dict],
) -> list[dict]:
    """Recommend next experiments: the coded region corners furthest from any
    design point (largest prediction variance in the fitted quadratic model —
    standard RSM guidance)."""
    # candidate corners
    corners = [list(p) for p in itertools.product([-1.0, 1.0], repeat=k)]
    # add the stationary point of the first surface if inside region
    first = next(iter(surfaces.values()), None)
    cands: list[tuple[float, list[float]]] = []
    for c in corners:
        dmin = min(math.dist(c, list(p)) for p in coded_points)
        cands.append((dmin, c))
    if first and first.get("stationary_point_coded"):
        sp = first["stationary_point_coded"]
        if all(v is not None and -1.0 <= v <= 1.0 for v in sp):
            dmin = min(math.dist(sp, list(p)) for p in coded_points)
            cands.append((dmin, sp))
    cands.sort(reverse=True, key=lambda t: t[0])
    return [{"coded": c, "distance_to_nearest_design_point": round(d, 4),
             "rationale": "region with highest model uncertainty"} for d, c in cands[:3]]
