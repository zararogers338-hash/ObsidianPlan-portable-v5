"""Evidence Card export: JSON, YAML, and CSV.

- JSON: cards as a compact JSON array (the machine contract).
- YAML: stdlib-compatible YAML emission (a safe hand-rolled emitter for the
  types we produce — dict/list/str/number/bool/None — no external dependency).
- CSV: one row per (card, quantity) pair so each quantity keeps its group_id /
  timepoint_id / unit / normalized_value / acquisition_mode / source locator.

All exporters are deterministic: same cards in -> byte-identical out.
"""

from __future__ import annotations

import csv
import io
import json
from typing import Any


def to_json(cards: list[dict[str, Any]]) -> str:
    return json.dumps(cards, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


# ---------------------------------------------------------------------------
# Minimal YAML emitter (stdlib-only)
# ---------------------------------------------------------------------------

def _yaml_str(value: Any) -> str:
    text = str(value)
    if text == "" or text in ("null", "true", "false", "~", "yes", "no", "on", "off") \
            or any(ch in text for ch in ":#{}[]&*!|>'\"%@`") \
            or text.startswith(("-", "?", " ", "\t")) \
            or "\n" in text:
        quoted = text.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{quoted}"'
    return text


def _yaml_scalar(node: Any) -> str:
    if node is None:
        return "null"
    if isinstance(node, bool):
        return "true" if node else "false"
    if isinstance(node, (int, float)):
        return repr(node)
    return _yaml_str(node)


def _yaml_lines(node: Any, indent: int) -> list[str]:
    """Return YAML lines for a node at a given indent level (no leading pad)."""
    pad = "  " * indent
    if isinstance(node, dict):
        if not node:
            return [pad + "{}"]
        out: list[str] = []
        for key, value in node.items():
            k = _yaml_str(key)
            if isinstance(value, (dict, list)):
                out.append(f"{pad}{k}:")
                out.extend(_yaml_lines(value, indent + 1))
            else:
                out.append(f"{pad}{k}: {_yaml_scalar(value)}")
        return out
    if isinstance(node, list):
        if not node:
            return [pad + "[]"]
        out = []
        for item in node:
            if isinstance(item, (dict, list)):
                head, *rest = _yaml_lines(item, indent + 1)
                out.append(pad + "- " + head.strip())
                out.extend(rest)
            else:
                out.append(pad + "- " + _yaml_scalar(item))
        return out
    return [pad + _yaml_scalar(node)]


def to_yaml(cards: list[dict[str, Any]]) -> str:
    return "\n".join(_yaml_lines(cards, 0)) + "\n"


# ---------------------------------------------------------------------------
# CSV: one row per quantity
# ---------------------------------------------------------------------------

_QUANTITY_KEYS = ("value", "unit", "normalized_value", "normalized_unit",
                  "acquisition_mode", "statistic_type", "n", "uncertainty_type",
                  "uncertainty_value", "group_id", "timepoint_id", "epistemic_tag")


def _flatten_quantities(cards: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []

    def walk(node: Any, path: str, card: dict[str, Any]) -> None:
        if isinstance(node, dict):
            if "normalized_unit" in node and "acquisition_mode" in node \
                    and "value" in node and "epistemic_tag" in node:
                row: dict[str, Any] = {
                    "card_id": card.get("card_id"),
                    "result_key": path,
                    "title": card.get("literature", {}).get("title"),
                    "year": card.get("literature", {}).get("year"),
                    "doi": card.get("literature", {}).get("doi"),
                    "group_label": _group_label(card, node.get("group_id")),
                    "timepoint_label": _timepoint_label(card, node.get("timepoint_id")),
                    "scale": (card.get("scope") or {}).get("scale"),
                }
                for k in _QUANTITY_KEYS:
                    row[k] = node.get(k)
                locs = [str(s.get("locator") or s.get("page") or "")
                        for s in (node.get("sources") or [])]
                row["source_locators"] = " | ".join(locs)
                rows.append(row)
                return
            for k, v in node.items():
                walk(v, f"{path}.{k}" if path else k, card)
        elif isinstance(node, list):
            for i, item in enumerate(node):
                walk(item, f"{path}[{i}]", card)

    for card in cards:
        walk(card.get("results", {}), "results", card)
        walk(card.get("conditions", {}), "conditions", card)
    return rows


def _group_label(card: dict[str, Any], gid: Any) -> str:
    for g in card.get("experimental_groups") or []:
        if g.get("group_id") == gid:
            return str(g.get("label"))
    return ""


def _timepoint_label(card: dict[str, Any], tid: Any) -> str:
    for t in card.get("time_points") or []:
        if t.get("timepoint_id") == tid:
            return str(t.get("label"))
    return ""


def to_csv(cards: list[dict[str, Any]]) -> str:
    rows = _flatten_quantities(cards)
    if not rows:
        return "card_id,result_key,group_label,timepoint_label\n"
    fields = ["card_id", "title", "year", "doi", "result_key", "group_label",
              "timepoint_label", "scale", "value", "unit", "normalized_value",
              "normalized_unit", "acquisition_mode", "statistic_type", "n",
              "uncertainty_type", "uncertainty_value", "epistemic_tag",
              "source_locators"]
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=fields, extrasaction="ignore", lineterminator="\n")
    writer.writeheader()
    for row in rows:
        writer.writerow({k: ("" if row.get(k) is None else row.get(k)) for k in fields})
    return buf.getvalue()
