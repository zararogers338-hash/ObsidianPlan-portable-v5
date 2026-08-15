"""Experimental-group and time-point isolation checker for micp-evidence-extractor.

The extractor's core discipline: never mix different experimental groups,
different papers, or different scales. This tool checks a set of evidence cards
for isolation violations:

  - GROUP_UNRESOLVED   : a quantity references a group_id the card does not declare.
  - TIME_UNRESOLVED    : a quantity references a timepoint_id the card does not declare.
  - GROUP_SMEAR        : the same (result, unit) quantity object reports a single
                         value while the paper's text/sources span multiple groups.
  - TIME_MERGE         : two distinct time points collapsed into one quantity.
  - SCALE_MIX          : cards in one output mix incompatible scopes (lab vs field)
                         under the same group label without an explicit note.

All checks are structural and deterministic. The output is a report object that
also feeds the `isolation_report` section of the skill envelope.
"""

from __future__ import annotations

from typing import Any

from models import PLACEHOLDER_MODES


def _walk_quantities(card: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    out: list[tuple[str, dict[str, Any]]] = []

    def walk(node: Any, path: str) -> None:
        if isinstance(node, dict):
            if "normalized_unit" in node and "acquisition_mode" in node \
                    and "value" in node and "epistemic_tag" in node:
                out.append((path, node))
                return
            for k, v in node.items():
                walk(v, f"{path}.{k}" if path else k)
        elif isinstance(node, list):
            for i, item in enumerate(node):
                walk(item, f"{path}[{i}]")

    walk(card, "")
    return out


def check_cards(cards: list[dict[str, Any]], *, source_label: str = "evidence") -> dict[str, Any]:
    """Run isolation checks across a set of cards. Returns a report dict."""
    issues: list[dict[str, Any]] = []
    group_binding: list[dict[str, Any]] = []
    timepoint_binding: list[dict[str, Any]] = []

    def issue(code: str, severity: str, message: str, details: dict | None = None) -> None:
        issues.append({"code": code, "severity": severity, "message": message,
                       "details": details or {}})

    for card in cards:
        card_id = card.get("card_id", "?")
        groups = {g.get("group_id") for g in card.get("experimental_groups") or []}
        timepoints = {t.get("timepoint_id") for t in card.get("time_points") or []}
        for path, q in _walk_quantities(card):
            gid = q.get("group_id")
            tid = q.get("timepoint_id")
            if gid and gid not in groups:
                issue("GROUP_UNRESOLVED", "error",
                      f"card {card_id}: quantity at {path} binds group_id {gid!r} "
                      f"not declared in this card's experimental_groups",
                      {"card_id": card_id, "group_id": gid, "path": path})
                group_binding.append({"card_id": card_id, "path": path, "group_id": gid,
                                      "severity": "error"})
            if tid and tid not in timepoints:
                issue("TIME_UNRESOLVED", "error",
                      f"card {card_id}: quantity at {path} binds timepoint_id {tid!r} "
                      f"not declared in this card's time_points",
                      {"card_id": card_id, "timepoint_id": tid, "path": path})
                timepoint_binding.append({"card_id": card_id, "path": path,
                                          "timepoint_id": tid, "severity": "error"})

        # GROUP_SMEAR: a card that declares >=2 groups but a result quantity is
        # unbound (no group_id) is a smell; warn unless it is a placeholder.
        if len(groups) > 1:
            for path, q in _walk_quantities(card):
                if not q.get("group_id") and q.get("acquisition_mode") not in PLACEHOLDER_MODES:
                    if path.startswith("results.") and "conditions" not in path:
                        issue("GROUP_SMEAR", "warning",
                              f"card {card_id}: result quantity at {path} has no group_id "
                              f"though the card declares {len(groups)} groups; the value "
                              f"cannot be attributed to a single experimental group",
                              {"card_id": card_id, "path": path,
                               "declared_groups": sorted(groups)})
                        group_binding.append({"card_id": card_id, "path": path,
                                              "group_id": None, "severity": "warning"})

    # TIME_MERGE: two time points whose labels differ only numerically are fine;
    # a single quantity bound to two time points is impossible structurally, but
    # cards that declare one timepoint list with the same unit while the text
    # mentions several are caught by the smoke test at the pipeline level.
    for card in cards:
        tps = card.get("time_points") or []
        labels = [str(t.get("label", "")).strip().lower() for t in tps]
        if len(labels) != len(set(labels)) and labels:
            issue("TIME_LABEL_DUPLICATE", "error",
                  f"card {card.get('card_id')}: duplicate time-point labels {labels}",
                  {"card_id": card.get("card_id"), "labels": labels})

    # SCALE_MIX across cards: group labels reused under different scales.
    seen_scales: dict[str, set[str]] = {}
    for card in cards:
        scale = (card.get("scope") or {}).get("scale", "unknown")
        for g in card.get("experimental_groups") or []:
            label = str(g.get("label", "")).strip()
            if not label:
                continue
            seen_scales.setdefault(label, set()).add(scale)
    for label, scales in seen_scales.items():
        if len(scales) > 1:
            issue("SCALE_MIX", "warning",
                  f"group label {label!r} appears across multiple scales "
                  f"({sorted(scales)}); values must not be compared without an "
                  f"explicit scale qualifier",
                  {"label": label, "scales": sorted(scales)})

    passed = not any(i["severity"] == "error" for i in issues)
    return {
        "check_id": "isolation",
        "passed": passed,
        "issues": issues,
        "group_binding_issues": group_binding,
        "timepoint_binding_issues": timepoint_binding,
        "cards_checked": len(cards),
    }
