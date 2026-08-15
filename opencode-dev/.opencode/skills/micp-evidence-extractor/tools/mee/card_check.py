"""Evidence Card validation for micp-evidence-extractor.

Validates every card against schemas/evidence-card.schema.json (through the
shared _jsonschema engine) and then applies the extraction-specific invariant
checks that JSON Schema cannot express:

  - group_id / timepoint_id references resolve to the card's declared groups
    and time points (isolation discipline: never mix groups or time points).
  - placeholder acquisition modes carry value=null and never participate in a
    calculation.
  - DIGITIZED_FROM_FIGURE quantities carry digitization.error_estimate.
  - OBSERVED/REPORTED quantities carry a source locator.
  - epistemic_tag is one of the six tags.
  - OD600/CFU/cell/viable/urease quantities are never conflated (units.py
    detect_distinct_conflation).
"""

from __future__ import annotations

import json
import os
from typing import Any

from _common import ToolError, emit_log
from models import EPISTEMIC_TAGS, ACQUISITION_MODES, PLACEHOLDER_MODES
from _jsonschema import validate as js_validate
import units

_SCHEMA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))), "schemas")


def load_card_schema() -> dict:
    path = os.path.join(_SCHEMA_DIR, "evidence-card.schema.json")
    if not os.path.isfile(path):
        raise ToolError("MEE-E900", f"card schema not found: {path}", exit_code=4)
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def _walk_quantities(card: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    """Yield (path, quantity) for every quantity-shaped value in a card."""
    out: list[tuple[str, dict[str, Any]]] = []

    def walk(node: Any, path: str) -> None:
        if isinstance(node, dict):
            if "normalized_unit" in node and "acquisition_mode" in node \
                    and "value" in node and "epistemic_tag" in node:
                out.append((path, node))
                return  # a quantity; don't descend into its own internals
            for k, v in node.items():
                walk(v, f"{path}.{k}" if path else k)
        elif isinstance(node, list):
            for i, item in enumerate(node):
                walk(item, f"{path}[{i}]")

    walk(card, "")
    return out


def check_invariants(card: dict[str, Any]) -> list[dict[str, Any]]:
    """Extraction-specific invariant checks. Returns issue dicts."""
    issues: list[dict[str, Any]] = []
    groups = {g.get("group_id") for g in card.get("experimental_groups") or []}
    timepoints = {t.get("timepoint_id") for t in card.get("time_points") or []}

    def issue(code: str, severity: str, message: str, details: dict | None = None) -> None:
        issues.append({"code": code, "severity": severity, "message": message,
                       "details": details or {}})

    card_epi = card.get("epistemic_tag")
    if card_epi not in EPISTEMIC_TAGS:
        issue("EPISTEMIC_TAG", "error",
              f"card epistemic_tag {card_epi!r} not in {EPISTEMIC_TAGS}")

    # group/timepoint references resolve
    for path, q in _walk_quantities(card):
        gid = q.get("group_id")
        tid = q.get("timepoint_id")
        if gid and gid not in groups:
            issue("UNRESOLVED_GROUP", "error",
                  f"quantity at {path} references group_id {gid!r} not declared in experimental_groups",
                  {"path": path, "group_id": gid})
        if tid and tid not in timepoints:
            issue("UNRESOLVED_TIMEPOINT", "error",
                  f"quantity at {path} references timepoint_id {tid!r} not declared in time_points",
                  {"path": path, "timepoint_id": tid})

        mode = q.get("acquisition_mode")
        if mode not in ACQUISITION_MODES:
            issue("ACQ_MODE", "error",
                  f"quantity at {path} has unknown acquisition_mode {mode!r}")
            continue
        if mode == "NOT_REPORTED":
            if q.get("value") is not None:
                issue("PLACEHOLDER_WITH_VALUE", "error",
                      f"NOT_REPORTED quantity at {path} must carry value=null, got {q.get('value')!r}",
                      {"path": path})
        if mode == "AMBIGUOUS":
            # An AMBIGUOUS quantity keeps its raw value but must NOT carry a
            # normalized value (its unit is not determinable).
            if q.get("normalized_value") is not None or q.get("normalized_unit"):
                issue("AMBIGUOUS_WITH_NORMALIZATION", "error",
                      f"AMBIGUOUS quantity at {path} must not carry a normalized "
                      f"value/unit (unit is not determinable)",
                      {"path": path, "normalized_value": q.get("normalized_value"),
                       "normalized_unit": q.get("normalized_unit")})
        if mode == "DIGITIZED_FROM_FIGURE":
            est = (q.get("digitization") or {}).get("error_estimate")
            if not (isinstance(est, (int, float)) and not isinstance(est, bool) and est >= 0):
                issue("FIGUREREAD_ERROR_MISSING", "error",
                      f"DIGITIZED_FROM_FIGURE quantity at {path} must carry "
                      f"digitization.error_estimate",
                      {"path": path})
        if q.get("epistemic_tag") not in EPISTEMIC_TAGS:
            issue("EPISTEMIC_TAG", "error",
                  f"quantity at {path} has epistemic_tag {q.get('epistemic_tag')!r} "
                  f"not in {EPISTEMIC_TAGS}",
                  {"path": path})
        if q.get("epistemic_tag") in ("OBSERVED", "REPORTED") and not q.get("sources"):
            issue("SOURCE_MISSING", "warning",
                  f"{q.get('epistemic_tag')} quantity at {path} has no source locator",
                  {"path": path})

    # distinct-quantity conflation guard (OD600/CFU/cell/viable/urease)
    for path, q in _walk_quantities(card):
        role = _role_of(path)
        if role is None:
            continue
        for confl in units.detect_distinct_conflation([
            {"role": role, "unit": q.get("unit"), "label": ""}
        ]):
            confl["details"] = {**(confl.get("details") or {}), "path": path}
            issues.append(confl)

    return issues


def _role_of(path: str) -> str | None:
    """Derive a quantity role from its JSON path segment (od600, cfu, ...)."""
    for token in ("od600", "cell_concentration", "cfu", "viable_cell_ratio", "urease_activity"):
        if f".{token}" in path or path == token or f"[{token}]" in path:
            return token
    return None


def validate_card(card: dict[str, Any]) -> dict[str, Any]:
    """Validate one card. Returns {valid, schema_errors, invariant_issues}."""
    schema = load_card_schema()
    schema_errors = js_validate(card, schema)
    invariant_issues = check_invariants(card)
    return {
        "valid": not schema_errors and not any(
            i["severity"] == "error" for i in invariant_issues),
        "schema_errors": schema_errors,
        "invariant_issues": invariant_issues,
    }


def validate_cards(cards: list[dict[str, Any]]) -> dict[str, Any]:
    """Validate all cards; returns a summary for the output envelope."""
    results = [validate_card(c) for c in cards]
    errors: list[dict[str, Any]] = []
    for i, r in enumerate(results):
        if not r["valid"]:
            errors.append({
                "card_index": i,
                "card_id": cards[i].get("card_id"),
                "schema_errors": r["schema_errors"][:5],
                "invariant_issues": [x for x in r["invariant_issues"]
                                     if x["severity"] == "error"][:5],
            })
    return {
        "total": len(cards),
        "valid": sum(1 for r in results if r["valid"]),
        "invalid": sum(1 for r in results if not r["valid"]),
        "errors": errors,
        "passed": len(errors) == 0,
    }
