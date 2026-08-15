"""Competing-hypothesis matrix tool.

Input (one JSON on stdin):
  {
    "hypotheses": [
      {"id": "H1", "statement": "...", "mechanism": "...", "observables": ["..."],
       "refutation": "...", "evidence_for": [...], "evidence_against": [...], "epistemic_label": "HYPOTHESIS"},
      ...
    ],
    "min_hypotheses": 3          # optional; default 3 (main + 2 competing)
  }

Emits:
  - support/refute direction per hypothesis vs each observable
  - which experiments would discriminate which pairs (uniquely discriminable)
  - information-gain estimate per discriminating experiment
  - a machine-readable matrix consumable by the Experiment Designer skill.

Pure stdlib, deterministic, offline.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import ToolError, as_dict, emit_ok, run_tool
from mhfx import models as M

TOOL = "competing-matrix"


def _hyp(card: dict) -> dict:
    for key in ("id", "statement", "refutation"):
        if not isinstance(card.get(key), str) or not card[key].strip():
            raise ToolError("MHX-E102", f"hypothesis missing non-empty `{key}`.", exit_code=2)
    return card


def _normalize_obs(h: dict) -> list[str]:
    obs = h.get("observables") or []
    if isinstance(obs, str):
        obs = [obs]
    return [o for o in obs if isinstance(o, str) and o.strip()]


def _experiment_observables(exp: dict, obs_union: list[str]) -> list[str]:
    """Which observables an experiment measures. Default: every observable
    named in its `measures` field; if absent, fall back to the full union so
    that synthesized experiments stay discriminating."""
    measures = exp.get("measures") or []
    if isinstance(measures, str):
        measures = [measures]
    measures = [m for m in measures if isinstance(m, str) and m.strip()]
    return measures or obs_union


def build_matrix(hypotheses: list[dict]) -> dict:
    ids = [h["id"] for h in hypotheses]
    if len(set(ids)) != len(ids):
        raise ToolError("MHX-E102", "hypothesis ids must be unique.", exit_code=2)

    obs_union: list[str] = []
    seen: set[str] = set()
    for h in hypotheses:
        for o in _normalize_obs(h):
            if o not in seen:
                seen.add(o)
                obs_union.append(o)

    # Predicted direction per (hypothesis, observable). Priority:
    #   1. explicit per-observable map `observable_predictions`
    #   2. explicit whole-card `prediction_direction`
    #   3. keyword inference from statement + refutation text
    # A null direction means the hypothesis makes no prediction on that observable.
    up_kw = ("increase", "rise", "raises", "elevates", "above", "higher",
             "faster", "exceed", "accumulat", "grow", "up")
    down_kw = ("decrease", "decline", "declines", "reduces", "reduce",
               "fall", "below", "lower", "slower", "dissolv", "deplet",
               "impairs", "lowers", "drop")
    dirs: dict[str, dict[str, str | None]] = {}
    for h in hypotheses:
        obs = _normalize_obs(h)
        per_obs = h.get("observable_predictions") or {}
        if not isinstance(per_obs, dict):
            raise ToolError("MHX-E105",
                            "observable_predictions must be an object mapping "
                            "observable -> increase/decrease/no_change/non_monotonic/null",
                            exit_code=2)
        explicit = h.get("prediction_direction")
        if explicit in ("increase", "decrease", "no_change", "non_monotonic", "null"):
            card_direction = {"increase": "positive", "decrease": "negative"}.get(explicit)
        else:
            text = f"{h.get('statement', '')} {h.get('refutation', '')}".lower()
            if any(k in text for k in up_kw):
                card_direction = "positive"
            elif any(k in text for k in down_kw):
                card_direction = "negative"
            else:
                card_direction = None

        row: dict[str, str | None] = {}
        for o in obs:
            if o in per_obs:
                v = per_obs[o]
                if v not in ("increase", "decrease", "no_change", "non_monotonic", "null"):
                    raise ToolError("MHX-E105",
                                    f"bad per-observable prediction {v!r} for {o!r} "
                                    "(increase/decrease/no_change/non_monotonic/null).",
                                    exit_code=2)
                row[o] = {"increase": "positive", "decrease": "negative"}.get(v)
            else:
                row[o] = card_direction
        dirs[h["id"]] = row

    # Experiments (from optional field or synthesized "observe <obs>")
    experiments = []
    exp_seen: set[str] = set()
    for h in hypotheses:
        for e in (h.get("discriminating_experiments") or []):
            if isinstance(e, str) and e not in exp_seen:
                exp_seen.add(e)
                experiments.append({"id": f"EXP-{len(experiments)+1:02d}", "name": e})
    if not experiments and obs_union:
        for i, o in enumerate(obs_union[:8], start=1):
            experiments.append({"id": f"EXP-{i:02d}",
                                "name": f"measure {o} under controlled conditions",
                                "measures": [o]})

    # For each experiment: which hypothesis pairs would be separated if the
    # measured outcome fell in each direction.
    pair_discrim = []
    hyp_pairs = [(a, b) for i, a in enumerate(ids) for b in ids[i + 1:]]
    for (a, b) in hyp_pairs:
        ha, hb = hyp_by_id(hypotheses, a), hyp_by_id(hypotheses, b)
        discriminating = []
        for exp in experiments:
            exp_obs = _experiment_observables(exp, obs_union)
            # A hypothesis pair is separated by an experiment when the measured
            # observable is (a) shared and predicted in opposite directions, or
            # (b) predicted by exactly one of the two (exclusive prediction).
            sep = False
            for o in exp_obs:
                da = dirs.get(a, {}).get(o)
                db = dirs.get(b, {}).get(o)
                if da is not None and db is not None and da != db:
                    sep = True
                    break
                if (da is None) != (db is None):
                    sep = True
                    break
            if sep:
                discriminating.append(exp["id"])
        pair_discrim.append({
            "pair": [a, b],
            "discriminating_experiments": discriminating,
            "uniquely_discriminable": len(discriminating) >= 1,
        })

    # Information-gain estimate (expected bits) for the best discriminating experiment
    # of each pair, using a symmetric prior p=0.5 and test sensitivity/specificity
    # carried on the experiment (default 0.9 / 0.9).
    igs = []
    for pd in pair_discrim:
        if not pd["discriminating_experiments"]:
            igs.append({**pd, "best_information_gain_bits": 0.0})
            continue
        best = None
        for exp_id in pd["discriminating_experiments"]:
            exp = next((e for e in experiments if e["id"] == exp_id), {})
            sens = float(exp.get("sensitivity", 0.9))
            spec = float(exp.get("specificity", 0.9))
            eig = M.expected_information_gain(0.5, sens, spec)
            if best is None or eig > best[1]:
                best = (exp_id, eig)
        igs.append({**pd, "best_information_gain_bits": round(best[1], 4),
                    "best_experiment": best[0]})

    return {
        "hypotheses": [{"id": h["id"], "statement": h["statement"],
                        "epistemic_label": h.get("epistemic_label", "HYPOTHESIS"),
                        "observables": _normalize_obs(h)} for h in hypotheses],
        "observables_union": obs_union,
        "predicted_directions": dirs,
        "experiments": experiments,
        "pair_discrimination": igs,
        "notes": [
            "predicted directions are derived from refutation keywords; a null "
            "direction means the hypothesis makes no prediction on that observable.",
            "information gain assumes a symmetric prior (p=0.5) and experiment "
            "sensitivity/specificity (default 0.9/0.9); override via experiment fields.",
        ],
    }


def hyp_by_id(hypotheses: list[dict], hid: str) -> dict:
    for h in hypotheses:
        if h["id"] == hid:
            return h
    raise KeyError(hid)


def main(payload: Any) -> dict:
    payload = as_dict(payload)
    hypotheses = payload.get("hypotheses")
    if hypotheses is None:
        raise ToolError("MHX-E102", "missing required field `hypotheses`.", exit_code=2)
    if not isinstance(hypotheses, list) or not hypotheses:
        raise ToolError("MHX-E102", "hypotheses must be a non-empty array.", exit_code=2)
    hypotheses = [_hyp(h) for h in hypotheses]

    min_hyp = int(payload.get("min_hypotheses", 3))
    if len(hypotheses) < min_hyp:
        raise ToolError(
            "MHX-E102",
            f"need at least {min_hyp} hypotheses (1 main + {min_hyp-1} competing); "
            f"got {len(hypotheses)}.",
            details={"required": min_hyp, "got": len(hypotheses)},
            exit_code=2,
        )

    result = build_matrix(hypotheses)
    result["min_hypotheses_satisfied"] = True
    return result


if __name__ == "__main__":
    run_tool(TOOL, main)
