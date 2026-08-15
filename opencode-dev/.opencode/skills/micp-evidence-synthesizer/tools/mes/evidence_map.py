"""Evidence matrix + conflict matrix generators (SKILL.md §能力要求-4).

evidence_matrix: one row per (card, quantitative outcome) with
  ref_id, outcome, value, unit, normalized_value, evidence_level, layer,
  risk_of_bias.
conflict_matrix: one row per detected conflict with
  conflict_id, between[ref_ids], type, direction, severity, explanation.
"""

from __future__ import annotations

from typing import Any

from .unit_map import normalize


def build_evidence_matrix(cards: list[dict], pico_unit: str | None = None) -> list[dict]:
    rows: list[dict] = []
    for card in cards:
        ref_id = card.get("ref_id")
        outcome = card.get("outcome") or {}
        value = outcome.get("value")
        unit = outcome.get("unit")
        normalized_value = None
        if isinstance(value, (int, float)) and isinstance(unit, str) and unit:
            q = normalize(value, unit, pico_unit)
            normalized_value = q.normalized_value if q.normalized_value is not None else value

        rob = "unclear"
        if isinstance(card.get("risk_of_bias"), dict) and card["risk_of_bias"].get("overall"):
            rob = card["risk_of_bias"]["overall"]

        rows.append({
            "ref_id": ref_id,
            "outcome": outcome.get("name") if isinstance(outcome, dict) else None,
            "value": value,
            "unit": unit,
            "normalized_value": normalized_value,
            "evidence_level": card.get("evidence_level"),
            "layer": card.get("layer", "other"),
            "risk_of_bias": rob,
        })
    return rows


def build_conflict_matrix(cards: list[dict]) -> list[dict]:
    """Detect conflicts: explicit `conflicts_with` + numeric direction/magnitude
    disagreements on the same outcome within comparable units.

    Direction conflict: one higher_is_better + one lower_is_better on the same
    outcome, or value ordering opposite to direction semantics.
    Magnitude conflict: values diverge by > 2x on a ratio scale (when both
    positive) — flagged, not adjudicated.
    """
    conflicts: list[dict] = []
    seen: set[str] = set()
    cid = 0

    def _add(between: list[str], ctype: str, direction: str, severity: str, explanation: str) -> None:
        nonlocal cid
        key = "|".join(sorted(between)) + "|" + ctype
        if key in seen:
            return
        seen.add(key)
        cid += 1
        conflicts.append({
            "conflict_id": f"CONF-{cid:03d}",
            "between": between,
            "type": ctype,
            "direction": direction,
            "severity": severity,
            "explanation": explanation,
        })

    # explicit declarations
    for card in cards:
        rid = card.get("ref_id")
        for other in (card.get("conflicts_with") or []):
            if isinstance(other, str) and other != rid:
                _add([rid, other], "explicit", "both", "medium",
                     f"card {rid} explicitly declares conflict with {other}")

    # numeric agreement check on the same outcome name with comparable units
    by_outcome: dict[str, list[dict]] = {}
    for card in cards:
        outcome = card.get("outcome") or {}
        name = outcome.get("name")
        value = outcome.get("value")
        unit = outcome.get("unit")
        direction = outcome.get("direction", "higher_is_better")
        if not name or not isinstance(value, (int, float)):
            continue
        by_outcome.setdefault(name, []).append({
            "ref_id": card.get("ref_id"), "value": value, "unit": unit,
            "direction": direction, "layer": card.get("layer"),
        })

    from .unit_map import comparable_unit, convert

    for name, entries in by_outcome.items():
        if len(entries) < 2:
            continue
        for i in range(len(entries)):
            for j in range(i + 1, len(entries)):
                a, b = entries[i], entries[j]
                if not comparable_unit(a["unit"], b["unit"]):
                    _add([a["ref_id"], b["ref_id"]], "unit", "both", "high",
                         f"same outcome '{name}' reported in non-comparable units "
                         f"({a['unit']} vs {b['unit']})")
                    continue
                va, vb = a["value"], b["value"]
                if a["unit"] and b["unit"] and a["unit"] != b["unit"]:
                    conv = convert(vb, b["unit"], a["unit"])
                    if conv is not None:
                        vb = conv
                # direction
                if a["direction"] != b["direction"]:
                    _add([a["ref_id"], b["ref_id"]], "direction", "direction", "high",
                         f"same outcome '{name}' reported with opposite direction semantics "
                         f"({a['direction']} vs {b['direction']})")
                    continue
                # magnitude disagreement
                if va > 0 and vb > 0:
                    ratio = max(va, vb) / min(va, vb)
                    if ratio >= 2.0:
                        _add([a["ref_id"], b["ref_id"]], "magnitude", "magnitude",
                             "medium" if ratio < 4.0 else "high",
                             f"same outcome '{name}': {va} vs {vb} (ratio {ratio:.2f}) — "
                             "conflict source must be explained, not averaged")

    return conflicts
