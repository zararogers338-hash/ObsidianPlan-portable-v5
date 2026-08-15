#!/usr/bin/env python3
"""dag_check.py — DAG construction and analysis for task graphs.

Implements Kahn's topological sort (Kahn 1962, see references/sources.md S7).
Detects: cycles (with node evidence), unknown dependency references, self loops,
duplicate ids, orphan nodes, and computes parallel levels (longest-path layering).

stdin: {"nodes": [{"id": ..., "depends_on": [...]}, ...]}
       Extra node fields are passed through untouched in `nodes` echo? No — only
       id/depends_on are consumed; the tool reports purely structural facts.

stdout result:
  {"is_dag": bool, "cycles": [{"nodes": [...], "edges": [[a,b],...]}],
   "topo_order": [...] (null if cyclic),
   "levels": [[ids at depth 0], [depth 1], ...] (null if cyclic),
   "max_parallelism": int, "unknown_dependencies": [...],
   "self_loops": [...], "duplicate_ids": [...], "orphans": [...],
   "node_count": int, "edge_count": int}
"""

from __future__ import annotations

import os
import sys
from collections import defaultdict, deque

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from _common import ToolError, as_dict, as_int, as_list, as_str, run_tool

MAX_NODES = 500
MAX_EDGES = 5000


def _extract_graph(payload) -> tuple[list[str], dict[str, list[str]]]:
    doc = as_dict(payload, "$")
    nodes = as_list(doc.get("nodes"), "$.nodes", min_len=1, max_len=MAX_NODES)

    ids: list[str] = []
    deps: dict[str, list[str]] = {}
    duplicates: list[str] = []
    for i, node in enumerate(nodes):
        n = as_dict(node, f"$.nodes[{i}]")
        nid = as_str(n.get("id"), f"$.nodes[{i}].id", min_len=1, max_len=128)
        raw_deps = n.get("depends_on", [])
        dlist = [as_str(d, f"$.nodes[{i}].depends_on[{j}]", min_len=1, max_len=128)
                 for j, d in enumerate(as_list(raw_deps, f"$.nodes[{i}].depends_on"))]
        if nid in deps:
            duplicates.append(nid)
        else:
            ids.append(nid)
            deps[nid] = list(dict.fromkeys(dlist))  # dedupe, keep order

    edge_count = sum(len(v) for v in deps.values())
    if edge_count > MAX_EDGES:
        raise ToolError("E_LIMIT_EXCEEDED", f"edge count {edge_count} exceeds limit {MAX_EDGES}",
                        details={"edge_count": edge_count, "limit": MAX_EDGES})
    return ids, deps, duplicates


def _analyze(ids, deps, duplicates):
    id_set = set(ids)
    unknown = sorted({d for dlist in deps.values() for d in dlist if d not in id_set})
    self_loops = sorted([nid for nid, dlist in deps.items() if nid in dlist])

    # Build adjacency: edge dep -> node (dep must finish before node starts)
    succ: dict[str, list[str]] = defaultdict(list)
    indeg: dict[str, int] = {nid: 0 for nid in ids}
    for nid, dlist in deps.items():
        for d in dlist:
            if d in id_set and d != nid:
                succ[d].append(nid)
                indeg[nid] += 1

    # Kahn's algorithm with deterministic ordering (sorted ready set)
    ready = sorted([nid for nid in ids if indeg[nid] == 0])
    queue = deque(ready)
    topo: list[str] = []
    depth: dict[str, int] = {}
    while queue:
        node = queue.popleft()
        topo.append(node)
        node_depth = depth.get(node, 0)
        promoted = []
        for nxt in succ.get(node, []):
            indeg[nxt] -= 1
            depth[nxt] = max(depth.get(nxt, 0), node_depth + 1)
            if indeg[nxt] == 0:
                promoted.append(nxt)
        for nxt in sorted(promoted):
            queue.append(nxt)

    is_dag = len(topo) == len(ids) and not self_loops and not unknown

    # Cycle evidence: nodes never reached by Kahn (still have indeg > 0)
    cycles = []
    if len(topo) < len(ids):
        remaining = [nid for nid in ids if nid not in set(topo)]
        remaining_set = set(remaining)
        # Extract concrete cycle walks via DFS on the remaining subgraph
        cycles = _find_cycles(remaining_set, deps)
        # Self loops are cycles of length 1 as well
        for nid in self_loops:
            cycles.append({"nodes": [nid], "edges": [[nid, nid]]})

    levels = None
    if is_dag:
        buckets: dict[int, list[str]] = defaultdict(list)
        for nid in ids:
            buckets[depth.get(nid, 0)].append(nid)
        levels = [sorted(buckets[k]) for k in sorted(buckets)]

    orphan_candidates = [nid for nid in ids
                         if not deps.get(nid) and not succ.get(nid)]
    # Orphans are informational only when the graph has more than one node
    orphans = sorted(orphan_candidates) if len(ids) > 1 else []

    return {
        "is_dag": is_dag,
        "cycles": cycles,
        "topo_order": topo if is_dag else None,
        "levels": levels,
        "max_parallelism": max((len(level) for level in levels), default=0) if levels else None,
        "unknown_dependencies": unknown,
        "self_loops": self_loops,
        "duplicate_ids": sorted(set(duplicates)),
        "orphans": orphans,
        "node_count": len(ids),
        "edge_count": sum(len(v) for v in deps.values()),
    }


def _find_cycles(remaining: set[str], deps: dict[str, list[str]]) -> list[dict]:
    """Extract elementary-ish cycle evidence from the remaining subgraph.

    Uses iterative DFS with color marking; reports each back-edge walk once.
    Deterministic: nodes visited in sorted order.
    """
    WHITE, GRAY, BLACK = 0, 1, 2
    color = {n: WHITE for n in remaining}
    cycles: list[dict] = []
    reported: set[frozenset] = set()

    def visit(start: str) -> None:
        stack: list[tuple[str, list[str]]] = [(start, [start])]
        color[start] = GRAY
        while stack:
            node, path = stack[-1]
            advanced = False
            for dep in sorted(deps.get(node, [])):
                if dep not in remaining:
                    continue
                if color[dep] == GRAY and dep in path:
                    idx = path.index(dep)
                    cycle_nodes = path[idx:]
                    # path order is following depends_on edges: a -> b means a depends on b
                    edges = []
                    for i in range(len(cycle_nodes)):
                        a = cycle_nodes[i]
                        b = cycle_nodes[(i + 1) % len(cycle_nodes)]
                        edges.append([a, b])
                    key = frozenset(cycle_nodes)
                    if key not in reported:
                        reported.add(key)
                        cycles.append({"nodes": sorted(cycle_nodes),
                                       "walk": cycle_nodes + [dep],
                                       "edges": edges})
                elif color[dep] == WHITE:
                    color[dep] = GRAY
                    stack.append((dep, path + [dep]))
                    advanced = True
                    break
            if not advanced:
                color[node] = BLACK
                stack.pop()

    for n in sorted(remaining):
        if color[n] == WHITE:
            visit(n)
    return cycles


def main(payload):
    ids, deps, duplicates = _extract_graph(payload)
    if duplicates:
        # Duplicates corrupt edge semantics; report as a hard structural error
        # but still run analysis so the caller sees everything at once.
        result = _analyze(ids, deps, duplicates)
        result["is_dag"] = False
        return result
    return _analyze(ids, deps, duplicates)


if __name__ == "__main__":
    run_tool("dag_check", main)
