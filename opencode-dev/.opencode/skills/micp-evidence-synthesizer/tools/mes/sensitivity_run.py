"""Leave-one-out sensitivity analysis (SKILL.md §自举测试-3).

Runs the pooling pipeline with one high-risk / one arbitrary study removed and
reports the pooled effect delta. Also exposes `sensitivity.exclusions` for
single-study removal scenarios.
"""

from __future__ import annotations

from typing import Optional

from .errors import MesError, MesErrorCode
from .meta_analyze import meta_analyze


def run_sensitivity(effects: list[dict], model: str = "random_effects",
                    remove_high_bias: bool = True, remove_one: Optional[str] = None) -> dict:
    """Compute leave-one-out sensitivity.

    Returns {runs: [ {name, excluded, pooled_effect, delta} ]}.
    `delta` is the change vs the full-pool pooled effect (None when the
    full pool is unavailable).
    """
    if not effects or len(effects) < 2:
        raise MesError(MesErrorCode.INSUFFICIENT_POOLING,
                       "sensitivity requires >=2 poolable studies")

    full = meta_analyze(effects, model=model)
    base = full.pooled_effect
    runs: list[dict] = []

    # LOO over every study (deterministic order: keep input order)
    for i in range(len(effects)):
        subset = effects[:i] + effects[i + 1:]
        if len(subset) < 2:
            continue
        removed = [effects[i]["ref_id"]]
        try:
            res = meta_analyze(subset, model=model)
            delta = (res.pooled_effect - base) if base is not None else None
            runs.append({
                "name": f"leave-one-out:{effects[i]['ref_id']}",
                "excluded": removed,
                "pooled_effect": res.pooled_effect,
                "delta": round(delta, 4) if delta is not None else None,
            })
        except MesError:
            runs.append({
                "name": f"leave-one-out:{effects[i]['ref_id']}",
                "excluded": removed,
                "pooled_effect": None,
                "delta": None,
            })

    # drop the highest risk-of-bias card if requested (marked via ref_ids with
    # a special provenance entry — the caller passes the high-bias ref id)
    if remove_high_bias and remove_one and remove_one not in {e.get("ref_id") for e in effects}:
        # not present; caller decides. Only remove when the ref is in the pool.
        remove_one = None
    if remove_one:
        subset = [e for e in effects if e.get("ref_id") != remove_one]
        if len(subset) >= 2:
            try:
                res = meta_analyze(subset, model=model)
                delta = (res.pooled_effect - base) if base is not None else None
                runs.append({
                    "name": f"exclude-high-bias:{remove_one}",
                    "excluded": [remove_one],
                    "pooled_effect": res.pooled_effect,
                    "delta": round(delta, 4) if delta is not None else None,
                })
            except MesError:
                pass

    return {"runs": runs}
