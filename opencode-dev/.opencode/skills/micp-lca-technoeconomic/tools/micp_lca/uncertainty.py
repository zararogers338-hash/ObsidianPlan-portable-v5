"""Uncertainty: Monte Carlo propagation and sensitivity analysis.

Monte Carlo
  Each impact factor with a declared coefficient-of-variation is sampled
  (lognormal, geometric-mean anchored at the factor value). The analysis-year
  multiplier is constant (no price/escalation model in v1 — declared as a
  limitation). Deterministic: seed = caller `random_seed` (default 42) via the
  stdlib `random.Random`. Two identical runs -> byte-identical output.

Sensitivity
  - One-at-a-time: perturb each input/factor by +/- delta_pct around the base,
    report the relative change in the chosen output (tornado data).
  - Global (morris-like): each factor gets K random increments from its
    uncertainty distribution; elementary effects normalized by
    sigma_factor * delta; report mean abs and std. Uses the same seeded RNG.

Outputs feed the hotspot (Pareto) generator and scenario comparison.
"""

from __future__ import annotations

import math
import random
from statistics import mean, stdev

from _common import ToolError, as_number
from errors import LcaErrorCode
from factors import FactorDatabase
from units import convert

DEFAULT_SEED = 42


def _rng(seed: int) -> random.Random:
    return random.Random(seed)


def _sample_factor(rng: random.Random, factor: dict) -> float:
    """Lognormal draw anchored at the factor value, sigma from CV."""
    mu = float(factor["value"])
    cv = float((factor.get("uncertainty") or {}).get("value", 0.0))
    if cv <= 0:
        return mu
    sigma = mu * cv
    if mu <= 0:
        return mu
    # lognormal with geometric mean mu (approx for moderate CV)
    sg = math.sqrt(math.log(1.0 + (sigma / mu) ** 2))
    mg = math.log(mu) - 0.5 * sg * sg
    return math.exp(mg + sg * rng.gauss(0.0, 1.0))


def run_monte_carlo(eval_fn, factor_ids: list[str], db: FactorDatabase,
                    n_iter: int, seed: int) -> dict:
    """Sample factors, call eval_fn(factor_overrides) each iteration.

    eval_fn: callable(overrides: dict[str, float]) -> float  (target metric,
    e.g. scenario total GWP). Returns {samples, mean, sd, p05, p50, p95,
    ci90, min, max, n, seed}.
    """
    if n_iter < 20:
        raise ToolError(LcaErrorCode.NUMERICAL_FAILURE.code,
                        "Monte Carlo requires at least 20 iterations",
                        details={"n": n_iter})
    rng = _rng(seed)
    samples: list[float] = []
    factors = [db.get(fid) for fid in factor_ids]
    for _ in range(n_iter):
        overrides = {f["id"]: _sample_factor(rng, f) for f in factors}
        samples.append(float(eval_fn(overrides)))
    samples.sort()
    q = lambda p: samples[min(len(samples) - 1, max(0, int(math.ceil(p * len(samples))) - 1))]
    mu = mean(samples)
    sd = stdev(samples) if len(samples) > 1 else 0.0
    return {
        "n": n_iter, "seed": seed,
        "samples": [round(x, 6) for x in samples],
        "mean": round(mu, 6), "sd": round(sd, 6),
        "p05": round(q(0.05), 6), "p50": round(q(0.50), 6), "p95": round(q(0.95), 6),
        "ci90_low": round(q(0.05), 6), "ci90_high": round(q(0.95), 6),
        "min": round(samples[0], 6), "max": round(samples[-1], 6),
    }


def run_oats(eval_fn, inputs: dict, output_key: str, delta_pct: float = 10.0,
             keys: list[str] | None = None) -> dict:
    """One-at-a-time sensitivity on numeric input quantities.

    inputs: dict of {key: value}; eval_fn(copy_of_inputs) -> dict of outputs.
    Returns per-key: base_output, minus (value*(1-d)), plus, rel change.
    """
    base_out = eval_fn(dict(inputs))
    base = float(base_out[output_key])
    results: list[dict] = []
    for key, value in inputs.items():
        if keys is not None and key not in keys:
            continue
        if not isinstance(value, (int, float)) or value == 0:
            continue
        lo = dict(inputs); lo[key] = value * (1 - delta_pct / 100.0)
        hi = dict(inputs); hi[key] = value * (1 + delta_pct / 100.0)
        try:
            lo_out = float(eval_fn(lo)[output_key])
            hi_out = float(eval_fn(hi)[output_key])
        except Exception:  # noqa: BLE001
            continue
        results.append({
            "key": key, "base": value, "output_base": base,
            "minus_delta": round(lo_out, 6), "plus_delta": round(hi_out, 6),
            "rel_change_minus": round((lo_out - base) / base, 6) if base else None,
            "rel_change_plus": round((hi_out - base) / base, 6) if base else None,
        })
    results.sort(key=lambda r: abs(r.get("rel_change_plus") or 0.0), reverse=True)
    return {"delta_pct": delta_pct, "output_key": output_key, "results": results}


def run_morris(eval_fn, factor_ids: list[str], db: FactorDatabase,
               k_samples: int = 20, seed: int = DEFAULT_SEED) -> dict:
    """Morris-style global sensitivity on impact factors.

    Each factor is perturbed by an increment drawn from its uncertainty
    distribution; the elementary effect of factor i is
      ee_i = (f(x+delta_i) - f(x)) / sigma_i
    normalized by the factor's own uncertainty so scales are comparable.
    eval_fn returns a scalar metric.
    """
    rng = _rng(seed)
    factors = [db.get(fid) for fid in factor_ids]
    effects: dict[str, list[float]] = {f["id"]: [] for f in factors}
    for _ in range(k_samples):
        base = {f["id"]: float(f["value"]) for f in factors}
        out_base = float(eval_fn(base))
        for f in factors:
            sig = float(f["value"]) * float((f.get("uncertainty") or {}).get("value", 0.0))
            if sig <= 0:
                continue
            bumped = dict(base)
            bumped[f["id"]] = _sample_factor(rng, f)
            out_bumped = float(eval_fn(bumped))
            ee = (out_bumped - out_base) / sig
            effects[f["id"]].append(ee)
    report = []
    for fid, es in effects.items():
        if not es:
            continue
        report.append({
            "factor_id": fid,
            "mu_star": round(mean([abs(e) for e in es]), 6),
            "sigma": round(stdev(es) if len(es) > 1 else 0.0, 6),
            "k": len(es),
        })
    report.sort(key=lambda r: r["mu_star"], reverse=True)
    return {"method": "morris_elementary_effects", "k_samples": k_samples,
            "seed": seed, "results": report}


def pareto_hotspots(breakdown: list[dict], top_n: int = 6) -> dict:
    """Rank contributions and compute cumulative share (Pareto).

    breakdown: list of {item, contribution}. Returns ranked list with
    cumulative_pct and a `pareto` flag when the item is inside the 80% frontier.
    """
    ranked = sorted(breakdown, key=lambda b: b.get("contribution", 0.0), reverse=True)
    total = sum(b.get("contribution", 0.0) for b in ranked)
    if total <= 0:
        return {"total": 0.0, "items": [], "note": "no positive contributions"}
    cum = 0.0
    out = []
    for b in ranked:
        pct = (b.get("contribution", 0.0) / total) * 100.0
        cum += pct
        out.append({**b, "pct": round(pct, 2), "cumulative_pct": round(cum, 2),
                    "pareto": cum <= 80.0})
    return {"total": total, "items": out[:top_n] if top_n else out,
            "note": f"top-{top_n} items shown; Pareto frontier = cumulative <= 80%"}


def compare_scenarios(rows: list[dict], metrics: list[str]) -> dict:
    """Scenario comparison table across metrics.

    rows: list of {scenario_id, **{metric: value}}. Returns per-metric min/max
    and a delta-vs-min (best scenario baseline) table.
    """
    if not rows:
        raise ToolError(LcaErrorCode.INPUT_SCHEMA_VIOLATION.code,
                        "scenario comparison needs at least one row",
                        details={})
    table: list[dict] = []
    for metric in metrics:
        vals = {r["scenario_id"]: r.get(metric) for r in rows if r.get(metric) is not None}
        if not vals:
            continue
        best = min(vals.values())
        table.append({
            "metric": metric,
            "best_scenario": next(s for s, v in vals.items() if v == best),
            "best_value": best,
            "rows": [{"scenario_id": s, "value": v,
                      "delta_vs_best_pct": round((v - best) / best * 100.0, 2) if best else None}
                     for s, v in vals.items()],
        })
    return {"metrics": table}
