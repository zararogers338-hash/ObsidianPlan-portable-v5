"""Duplicate-value and internal-contradiction detection for micp-evidence-extractor.

Two families of checks run over a set of evidence cards:

1. DUPLICATE_VALUE   — the same numeric value appears for the same (result key,
   unit, group, timepoint) from distinct source locators. When two different
   sources claim the exact same value it is suspicious (copy-forward, repeated
   digitization) and is surfaced.

2. CONTRADICTION     — the same physical quantity is reported twice for the same
   (group, timepoint) with values that differ beyond a small tolerance, without
   a caveat. The skill never silently picks one; it reports the conflict so the
   downstream synthesizer can decide.

3. METHODS_RESULTS   — a numerical claim in the methods text (e.g. "urea 0.5 M")
   contradicts the results table (e.g. 0.05 M). This check accepts a
   `methods_claims` list produced by the pipeline.

Deterministic and structural: no model inference, only exact/delta rules with a
configurable relative tolerance (default 1%).
"""

from __future__ import annotations

import re
from typing import Any

from models import PLACEHOLDER_MODES


def _iter_result_quantities(cards: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []

    def walk(node: Any, key_path: str, card_id: str) -> None:
        if isinstance(node, dict):
            if "normalized_unit" in node and "acquisition_mode" in node \
                    and "value" in node and "epistemic_tag" in node:
                out.append({
                    "card_id": card_id,
                    # strip array indices so all values of one result column
                    # share the same slot key (results.ucs not results.ucs[0])
                    "key": re.sub(r"\[\d+\]", "", key_path),
                    "quantity": node,
                })
                return
            for k, v in node.items():
                walk(v, f"{key_path}.{k}" if key_path else k, card_id)
        elif isinstance(node, list):
            for i, item in enumerate(node):
                walk(item, f"{key_path}[{i}]", card_id)

    for card in cards:
        walk(card.get("results", {}), "results", str(card.get("card_id", "?")))
    return out


def _close(a: float, b: float, rel: float) -> bool:
    if a == b:
        return True
    scale = max(abs(a), abs(b), 1e-12)
    return abs(a - b) / scale <= rel


def _key_of(q: dict[str, Any]) -> tuple[str, str, str, str]:
    return (str(q.get("group_id") or ""), str(q.get("timepoint_id") or ""),
            str(q.get("normalized_unit") or q.get("unit") or ""),
            str(q.get("statistic_type") or ""))


def detect_issues(cards: list[dict[str, Any]], *, rel_tol: float = 0.01,
                  methods_claims: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Detect duplicates and contradictions across cards. Returns a report."""
    issues: list[dict[str, Any]] = []
    quantities = _iter_result_quantities(cards)

    # group by (result key, group, timepoint, unit, statistic_type)
    by_slot: dict[tuple[str, str, str, str], list[dict[str, Any]]] = {}
    for item in quantities:
        q = item["quantity"]
        if q.get("acquisition_mode") in PLACEHOLDER_MODES:
            continue
        if not isinstance(q.get("value"), (int, float)):
            continue
        slot = (item["key"],) + _key_of(q)
        by_slot.setdefault(slot, []).append(item)

    for (key, gid, tid, unit, stat), items in by_slot.items():
        if len(items) < 2:
            continue
        values = sorted(float(i["quantity"]["value"]) for i in items)
        # duplicates: identical values from different sources
        seen: dict[float, list[dict[str, Any]]] = {}
        for it in items:
            seen.setdefault(float(it["quantity"]["value"]), []).append(it)
        for val, same_val_items in seen.items():
            if len(same_val_items) >= 2:
                locs = _sources(same_val_items)
                issues.append({
                    "code": "DUPLICATE_VALUE", "severity": "warning",
                    "message": (f"result {key} ({unit}) for group={gid or '?'}, "
                                f"timepoint={tid or '?'} reports value {val} twice "
                                f"from distinct locators {locs}; check for "
                                f"copy-forward or repeated digitization"),
                    "details": {"key": key, "value": val, "sources": locs,
                                "group_id": gid, "timepoint_id": tid},
                })
        # contradictions: values differ beyond tolerance
        if len(values) >= 2 and (values[-1] - values[0]) / max(abs(values[-1]), 1e-12) > rel_tol:
            lo = [it for it in items if float(it["quantity"]["value"]) == values[0]]
            hi = [it for it in items if float(it["quantity"]["value"]) == values[-1]]
            issues.append({
                "code": "CONTRADICTION", "severity": "error",
                "message": (f"result {key} ({unit}) for group={gid or '?'}, "
                            f"timepoint={tid or '?'} is reported as {values[0]} "
                            f"({_sources(lo)}) and {values[-1]} ({_sources(hi)}) — "
                            f"difference beyond {rel_tol * 100:.0f}% tolerance; "
                            f"the extractor does not pick one, it surfaces both"),
                "details": {"key": key, "values": values, "low": _sources(lo),
                            "high": _sources(hi), "rel_tol": rel_tol,
                            "group_id": gid, "timepoint_id": tid},
            })

    # methods-vs-results contradiction
    for claim in methods_claims or []:
        cval = claim.get("value")
        crev = claim.get("result_value")
        if not isinstance(cval, (int, float)) or not isinstance(crev, (int, float)):
            continue
        if not _close(float(cval), float(crev), rel_tol):
            issues.append({
                "code": "METHODS_RESULTS_CONFLICT", "severity": "error",
                "message": (f"methods claim {claim.get('label')}: {cval} {claim.get('unit')} "
                            f"({claim.get('locator')}) conflicts with results value "
                            f"{crev} {claim.get('result_unit')} ({claim.get('result_locator')})"),
                "details": {"label": claim.get("label"), "methods_value": cval,
                            "methods_unit": claim.get("unit"),
                            "methods_locator": claim.get("locator"),
                            "result_value": crev,
                            "result_unit": claim.get("result_unit"),
                            "result_locator": claim.get("result_locator")},
            })

    passed = not any(i["severity"] == "error" for i in issues)
    return {
        "check_id": "duplicates_contradictions",
        "passed": passed,
        "issues": issues,
        "quantities_scanned": len(quantities),
    }


def _sources(items: list[dict[str, Any]]) -> list[str]:
    locs: list[str] = []
    for it in items:
        q = it["quantity"]
        for s in q.get("sources") or []:
            loc = str(s.get("locator") or s.get("page") or "")
            if loc and loc not in locs:
                locs.append(loc)
        if not locs:
            locs.append("(no locator)")
    return locs
