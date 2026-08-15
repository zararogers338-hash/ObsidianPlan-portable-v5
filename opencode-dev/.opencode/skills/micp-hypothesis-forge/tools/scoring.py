"""Falsifiability / measurability / discriminability scoring tool.

Input (one JSON on stdin):
  {
    "statements": [
      {
        "id": "H1",
        "statement": "High urease activity raises porosity...",
        "refutation": "If NH4+ accumulation exceeds 100 mM ...",
        "observables": ["NH4+ concentration (mM)"],
        "time_scale": "days",
        "scope": "sand-column ureolytic MICP at 10-30C, 0.5-1.5 M cementation"
      }, ...
    ]
  }

Outputs per-statement scores in [0,1] computed deterministically from field
features, plus a machine-readable verdict. Pure stdlib, offline.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import ToolError, as_dict, emit_ok, run_tool
from mhfx import models as M

TOOL = "scoring"


def score_falsifiability(statement: str, refutation: str) -> dict:
    v = M.is_falsifiable(statement, refutation)
    verdict = v["verdict"]
    if verdict == "FALSIFIABLE":
        score = 1.0
    elif verdict == "PARTIALLY_FALSIFIABLE":
        score = 0.5
    else:
        score = 0.0
    return {"score": score, "verdict": verdict, "reason": v["reason"],
            "checks": v["checks"]}


def score_measurability(card: dict) -> dict:
    """Rate how measurable the hypothesis is from its declared observables.

    Higher score when the card names at least one quantified observable with a
    plausible unit and a stated time scale / location.
    """
    obs = card.get("observables") or []
    if isinstance(obs, str):
        obs = [obs]
    obs = [o for o in obs if isinstance(o, str) and o.strip()]
    if not obs:
        return {"score": 0.0, "reason": "no observable variables declared",
                "n_observables": 0}
    # A quantified observable: contains a digit or a unit-ish token
    quantified = sum(1 for o in obs if re_search_number(o))
    time_ok = bool((card.get("time_scale") or "").strip())
    scope_ok = bool((card.get("scope") or "").strip())
    score = 0.4 + 0.3 * (quantified / len(obs)) + 0.15 * int(time_ok) + 0.15 * int(scope_ok)
    return {"score": round(min(1.0, score), 3), "reason": (
        f"{quantified}/{len(obs)} observables quantified; "
        f"time_scale={'present' if time_ok else 'missing'}; "
        f"scope={'present' if scope_ok else 'missing'}"),
        "n_observables": len(obs)}


def score_discriminability(statement: str, refutation: str, alternatives: list[str]) -> dict:
    """How well a hypothesis separates itself from alternatives.

    0.0 if no alternatives; otherwise 0.5 base + 0.5 * (non-overlap of
    observables naming). Full score when its refutation names an observable
    that none of the alternatives name.
    """
    ref_obs = M.refutation_classification(refutation)["text"]
    alts = [a for a in alternatives if isinstance(a, str) and a.strip()]
    if not alts:
        return {"score": 0.0, "reason": "no competing alternatives supplied",
                "n_alternatives": 0}
    # crude but deterministic overlap detector: any distinct token in ref_obs
    # that also appears in an alternative is "shared"
    ref_tokens = {w for w in ref_obs.split() if len(w) > 3}
    alt_tokens = set()
    for a in alts:
        alt_tokens |= {w for w in a.lower().split() if len(w) > 3}
    distinct = ref_tokens - alt_tokens
    base = 0.5 + 0.5 * min(1.0, len(distinct) / max(1, len(ref_tokens)))
    return {"score": round(min(1.0, base), 3),
            "reason": f"{len(distinct)}/{len(ref_tokens)} distinctive tokens vs {len(alts)} alternatives",
            "n_alternatives": len(alts), "distinctive_tokens": sorted(distinct)}


def re_search_number(text: str) -> bool:
    import re
    return bool(re.search(r"\d", text))


def main(payload: Any) -> dict:
    payload = as_dict(payload)
    statements = payload.get("statements")
    if statements is None:
        raise ToolError("MHX-E102", "missing required field `statements`.", exit_code=2)
    if not isinstance(statements, list):
        raise ToolError("MHX-E105", "statements must be an array.", exit_code=2)
    if not statements:
        raise ToolError("MHX-E102", "statements is empty; nothing to score.", exit_code=2)

    alternatives_by_id: dict[str, list[str]] = {}
    for st in statements:
        if not isinstance(st, dict):
            raise ToolError("MHX-E105", "each statement must be an object.", exit_code=2)
        for key in ("id", "statement", "refutation"):
            if not isinstance(st.get(key), str) or not st[key].strip():
                raise ToolError("MHX-E102", f"statement missing non-empty `{key}`.", exit_code=2)
    for st in statements:
        alternatives_by_id[st["id"]] = [
            s["statement"] for s in statements if s["id"] != st["id"]
        ]

    results = []
    for st in statements:
        fals = score_falsifiability(st["statement"], st["refutation"])
        meas = score_measurability(st)
        disc = score_discriminability(st["statement"], st["refutation"],
                                      alternatives_by_id[st["id"]])
        results.append({
            "id": st["id"],
            "falsifiability": fals,
            "measurability": meas,
            "discriminability": disc,
            "overall": round(
                min(1.0, 0.4 * fals["score"] + 0.35 * meas["score"] + 0.25 * disc["score"]), 3),
        })

    return {
        "results": results,
        "summary": {
            "min_overall": min(r["overall"] for r in results),
            "max_overall": max(r["overall"] for r in results),
            "mean_overall": round(sum(r["overall"] for r in results) / len(results), 3),
            "n_non_falsifiable": sum(1 for r in results
                                     if r["falsifiability"]["verdict"] != "FALSIFIABLE"),
        },
    }


if __name__ == "__main__":
    run_tool(TOOL, main)
