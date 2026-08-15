#!/usr/bin/env python3
"""Minimal YAML subset parser for micp-experiment-designer evals.

Parses exactly the subset of YAML that `evals/cases.yaml` uses — block maps,
block lists (`- `), flow maps `{...}`, flow lists `[...]`, and scalar values
(int / float / bool / null / quoted / bare string). Comments and blank lines
are ignored. Anything outside this subset raises MiniYamlError.

This exists so the eval suite is fully offline and dependency-free (no PyYAML
required). It is intentionally NOT a general YAML parser.
"""

from __future__ import annotations

import re
from typing import Any


class MiniYamlError(ValueError):
    pass


def _strip_comment(line: str) -> str:
    # remove a trailing "# ..." comment (not inside quotes — the cases file
    # does not put # inside quoted strings)
    out: list[str] = []
    in_s = False
    in_d = False
    for ch in line:
        if ch == "'" and not in_d:
            in_s = not in_s
        elif ch == '"' and not in_s:
            in_d = not in_d
        if ch == "#" and not in_s and not in_d:
            break
        out.append(ch)
    return "".join(out).rstrip()


def _parse_scalar(s: str) -> Any:
    s = s.strip()
    if len(s) >= 2 and s[0] == s[-1] and s[0] in "\"'":
        return s[1:-1]
    low = s.lower()
    if low == "true":
        return True
    if low == "false":
        return False
    if low in ("null", "~"):
        return None
    # numbers (int or float); reject things like "eval-01"
    try:
        if re.fullmatch(r"-?\d+", s):
            return int(s)
        if re.fullmatch(r"-?\d+\.\d+([eE][+-]?\d+)?", s):
            return float(s)
    except ValueError:
        pass
    return s


def _split_flow(s: str) -> list[str]:
    """Split a flow container on top-level commas."""
    parts: list[str] = []
    depth = 0
    cur = ""
    for ch in s:
        if ch in "{[":
            depth += 1
        elif ch in "}]":
            depth -= 1
            if depth < 0:
                raise MiniYamlError(f"unbalanced '}}' in flow: {s!r}")
        if ch == "," and depth == 0:
            if cur.strip():
                parts.append(cur)
            cur = ""
            continue
        cur += ch
    if cur.strip():
        parts.append(cur)
    return parts


def _parse_flow(s: str) -> Any:
    s = s.strip()
    # bracket-balance pre-check so unbalanced flow raises MiniYamlError
    depth = 0
    for ch in s:
        if ch in "{[":
            depth += 1
        elif ch in "}]":
            depth -= 1
            if depth < 0:
                raise MiniYamlError(f"unbalanced '}}' or ']' in flow: {s!r}")
    if depth != 0:
        raise MiniYamlError(f"unbalanced flow container: {s!r}")
    if s.startswith("{") and s.endswith("}") and len(s) >= 2:
        inner = s[1:-1].strip()
        if not inner:
            return {}
        result: dict[str, Any] = {}
        for seg in _split_flow(inner):
            if ":" not in seg:
                raise MiniYamlError(f"flow map entry without ':' -> {seg!r}")
            k, _, v = seg.partition(":")
            result[k.strip()] = _parse_flow(v)
        return result
    if s.startswith("[") and s.endswith("]"):
        inner = s[1:-1].strip()
        if not inner:
            return []
        return [_parse_flow(seg) for seg in _split_flow(inner)]
    return _parse_scalar(s)


def _split_key_val(content: str) -> tuple[str, str]:
    if ":" not in content:
        raise MiniYamlError(f"expected 'key: value' got {content!r}")
    k, _, v = content.partition(":")
    return k.strip(), v.strip()


def _parse_block(lines: list[tuple[int, str]], i: int, indent: int) -> tuple[Any, int]:
    if lines[i][0] != indent:
        raise MiniYamlError(f"indent mismatch: expected {indent}, got {lines[i][0]} at {lines[i][1]!r}")
    if lines[i][1].startswith("- "):
        return _parse_list(lines, i, indent)
    return _parse_map(lines, i, indent)


def _parse_map(lines: list[tuple[int, str]], i: int, indent: int) -> tuple[dict[str, Any], int]:
    result: dict[str, Any] = {}
    while i < len(lines) and lines[i][0] == indent and not lines[i][1].startswith("- "):
        key, val = _split_key_val(lines[i][1])
        i += 1
        if val:
            result[key] = _parse_flow(val)
            continue
        # nested block
        if i < len(lines) and lines[i][0] > indent:
            child, i = _parse_block(lines, i, lines[i][0])
            result[key] = child
        else:
            result[key] = {}
    return result, i


def _parse_list(lines: list[tuple[int, str]], i: int, indent: int) -> tuple[list[Any], int]:
    result: list[Any] = []
    while i < len(lines) and lines[i][0] == indent and lines[i][1].startswith("- "):
        item = lines[i][1][2:].strip()
        i += 1
        if not item:
            if i < len(lines) and lines[i][0] > indent:
                child, i = _parse_block(lines, i, lines[i][0])
                result.append(child)
            else:
                result.append(None)
            continue
        # flow container on its own list item: `- {...}` / `- [...]`
        if item.startswith("{") or item.startswith("["):
            result.append(_parse_flow(item))
            continue
        if ":" in item:
            # `- key: value` → a one-line map item, possibly continued below
            key, val = _split_key_val(item)
            entry: dict[str, Any] = {}
            if val:
                entry[key] = _parse_flow(val)
            elif i < len(lines) and lines[i][0] > indent:
                child, i = _parse_block(lines, i, lines[i][0])
                entry[key] = child
            else:
                entry[key] = {}
            # continuation keys at deeper indent
            while i < len(lines) and lines[i][0] > indent:
                k, v = _split_key_val(lines[i][1])
                if k in entry:
                    raise MiniYamlError(f"duplicate key '{k}' in list item")
                i += 1
                if v:
                    entry[k] = _parse_flow(v)
                elif i < len(lines) and lines[i][0] > indent:
                    child, i = _parse_block(lines, i, lines[i][0])
                    entry[k] = child
                else:
                    entry[k] = {}
            result.append(entry)
            continue
        result.append(_parse_flow(item))
    return result, i


def loads(text: str) -> Any:
    """Parse a YAML-subset document into a Python value."""
    lines: list[tuple[int, str]] = []
    for raw in text.splitlines():
        if "\t" in raw[: len(raw) - len(raw.lstrip())]:
            raise MiniYamlError("tabs are not allowed in indentation")
        stripped = _strip_comment(raw)
        if not stripped.strip():
            continue
        indent = len(stripped) - len(stripped.lstrip(" "))
        lines.append((indent, stripped.strip()))
    if not lines:
        return {}
    if lines[0][1].startswith("- "):
        return _parse_list(lines, 0, lines[0][0])[0]
    return _parse_map(lines, 0, lines[0][0])[0]


if __name__ == "__main__":
    import json
    import sys

    if len(sys.argv) != 2:
        print("usage: python mini_yaml.py <file.yaml>", file=sys.stderr)
        sys.exit(2)
    with open(sys.argv[1], encoding="utf-8") as fh:
        doc = loads(fh.read())
    print(json.dumps(doc, ensure_ascii=False, indent=2))
