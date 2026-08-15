"""Minimal YAML-subset parser for evals/cases.yaml.

Pure stdlib. Supports exactly what cases.yaml uses:
  - nested mappings (2-space indent)
  - sequences: lists of maps ("- key: value") and lists of scalars ("- x")
  - "key: value", "key:" (child map or child list), "key: [a, b]" inline lists
  - scalars: str / int / float / bool / null, with '#' comments

The one structural decision that requires lookahead is `key:` followed by a
`- ` block: the value is a list, not a map. A line-index loop handles that.
Anything structurally different raises NotImplementedError so the runner never
silently misparses a case file. Deterministic.
"""

from __future__ import annotations

import re
from pathlib import Path


def _scalar(token: str):
    token = token.strip()
    if token == "" or token.lower() in ("null", "~"):
        return None
    if token.lower() in ("true", "yes"):
        return True
    if token.lower() in ("false", "no"):
        return False
    if re.fullmatch(r"[-+]?\d+", token):
        return int(token)
    if re.fullmatch(r"[-+]?(\d+\.\d*|\.\d+)", token):
        return float(token)
    # strip surrounding quotes (single or double)
    if len(token) >= 2 and token[0] == token[-1] and token[0] in ("'", '"'):
        token = token[1:-1]
    return token


class _Frame:
    __slots__ = ("kind", "value", "indent")

    def __init__(self, kind: str, value, indent: int):
        self.kind = kind
        self.value = value
        self.indent = indent


def _is_list_item(stripped: str) -> bool:
    return stripped.startswith("- ") or stripped == "-"


def parse(text: str) -> Any:  # noqa: ANN202
    lines = []
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].rstrip()
        if not line.strip():
            continue
        lines.append(line)
    if not lines:
        return None

    root: dict = {}
    stack: list[_Frame] = []
    current_map: dict = root
    i = 0
    n = len(lines)

    def container_for(indent: int) -> dict:
        """Return the map that a mapping entry at `indent` writes into."""
        while stack and indent <= stack[-1].indent:
            stack.pop()
        if not stack:
            return root
        top = stack[-1]
        if top.kind == "map":
            return top.value
        # top is a list; the key belongs to its last element (a dict)
        if not top.value or not isinstance(top.value[-1], dict):
            raise NotImplementedError("key under a list of scalars")
        return top.value[-1]

    while i < n:
        line = lines[i]
        indent = len(line) - len(line.lstrip(" "))
        stripped = line.strip()

        if _is_list_item(stripped):
            # -------- list item --------
            while stack and indent <= stack[-1].indent:
                stack.pop()
            if not stack or stack[-1].kind != "list":
                raise NotImplementedError(
                    f"list item at indent {indent} has no parent list: {line!r}")
            parent = stack[-1]
            target_list = parent.value

            body = stripped[2:].strip() if stripped != "-" else ""
            if ":" in body:
                key, _, rest = body.partition(":")
                key = key.strip()
                val_token = rest.strip()
                child_map: dict = {}
                target_list.append(child_map)
                current_map = child_map
                if val_token == "":
                    # child map or child list follows on deeper lines
                    if i + 1 < n and _is_list_item(lines[i + 1].strip()):
                        child_list: list = []
                        child_map[key] = child_list
                        stack.append(_Frame("list", child_list, indent))
                    else:
                        stack.append(_Frame("map", child_map, indent))
                else:
                    child_map[key] = _scalar(val_token)
            else:
                target_list.append(_scalar(body))
                # current_map stays wherever it was
        else:
            # -------- mapping entry --------
            if ":" not in stripped:
                raise NotImplementedError(f"expected 'key: value' got {line!r}")
            key, _, rest = stripped.partition(":")
            key = key.strip()
            val_token = rest.strip()
            current_map = container_for(indent)

            if val_token == "":
                if i + 1 < n and _is_list_item(lines[i + 1].strip()):
                    child_list: list = []
                    current_map[key] = child_list
                    stack.append(_Frame("list", child_list, indent))
                else:
                    child: dict = {}
                    current_map[key] = child
                    stack.append(_Frame("map", child, indent))
            elif val_token.startswith("[") and val_token.endswith("]"):
                inner = val_token[1:-1].strip()
                current_map[key] = [_scalar(x) for x in inner.split(",")] if inner else []
            else:
                current_map[key] = _scalar(val_token)
        i += 1

    return root


def load(path: str | Path) -> dict:
    text = Path(path).read_text(encoding="utf-8")
    data = parse(text)
    if not isinstance(data, dict):
        raise NotImplementedError("cases.yaml root must be a mapping")
    return data
