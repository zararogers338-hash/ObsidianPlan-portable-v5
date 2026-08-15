"""Mechanism-chain -> causal DAG tool for micp-hypothesis-forge.

Input (one JSON on stdin):
  {
    "mechanism_chain": ["A", "B", "C"],      # or "A -> B -> C"
    "variables": [{"id": "B", "kind": "enzyme_activity"}],   # optional context
    "node_labels": {...},                                    # optional
    "detect_self_loops": true,                               # default true
    "detect_cycles": true                                    # default true
  }

A "mechanism chain" is a linear causal path; multiple competing mechanisms are
expressed as several chains under `chains`. This tool validates acyclicity and
ancestry, rejects unknown cross-references, and emits a normalized DAG plus
topological order. All edge checks are deterministic and offline.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import ToolError, read_payload, as_dict, emit_ok, emit_error, run_tool
from mhfx import models as M

TOOL = "dag"


def _parse_chains(payload: dict) -> list[list[str]]:
    """Return list of normalized chains (each a list of step strings)."""
    if "mechanism_chain" in payload:
        # A single chain: either a string "A -> B -> C" or a flat list of steps.
        chain = payload.get("mechanism_chain")
        if isinstance(chain, list) and all(isinstance(c, str) for c in chain):
            chains = [M.normalize_chain(chain)]
        else:
            chains = [M.normalize_chain(chain)]
    elif "chains" in payload:
        # A list of chains; each chain is a string or a list of steps.
        chains_src = payload.get("chains")
        if not isinstance(chains_src, list):
            raise ToolError(
                "MHX-E105", "`chains` must be an array of chains.",
                exit_code=2,
            )
        chains = [M.normalize_chain(c) for c in chains_src]
    else:
        raise ToolError(
            "MHX-E102",
            "missing mechanism chain: provide `mechanism_chain` (list or 'A -> B') "
            "or `chains` (list of chains).",
            exit_code=2,
        )
    chains = [c for c in chains if c]
    if not chains:
        raise ToolError("MHX-E102", "mechanism chains resolved to empty.", exit_code=2)
    if any(len(c) < 2 for c in chains):
        raise ToolError(
            "MHX-E105",
            "a mechanism chain must have at least 2 steps (cause -> effect); "
            "single-step 'chains' are not mechanisms.",
            exit_code=2,
        )
    return chains


def build_graph(chains: list[list[str]], node_labels: dict) -> tuple[list[dict], set]:
    """Build node list + edge set from chains. Dedup by id. Raises on self-loop."""
    ids: list[str] = []
    seen: set[str] = set()
    for chain in chains:
        for step in chain:
            if step not in seen:
                seen.add(step)
                ids.append(step)
    edges: set[tuple[str, str]] = set()
    for chain in chains:
        for a, b in zip(chain, chain[1:]):
            if a == b:
                raise ToolError(
                    "MHX-E105",
                    f"self-loop edge {a!r} -> {a!r} in mechanism chain.",
                    details={"edge": [a, a]},
                    exit_code=3,
                )
            edges.add((a, b))
    # Attach depends_on to each node so topo_sort / ancestors see the edges.
    deps: dict[str, list[str]] = {nid: [] for nid in ids}
    for a, b in edges:
        deps[b].append(a)
    nodes = [{"id": nid, "label": node_labels.get(nid, nid),
              "depends_on": sorted(deps[nid])} for nid in ids]
    return nodes, edges


def _edge_list(edges: set) -> list[list[str]]:
    return [list(e) for e in sorted(edges)]


def main(payload: Any) -> dict:
    payload = as_dict(payload)
    chains = _parse_chains(payload)
    node_labels = payload.get("node_labels") or {}
    if not isinstance(node_labels, dict):
        raise ToolError("MHX-E105", "node_labels must be an object.", exit_code=2)

    nodes, edges = build_graph(chains, node_labels)

    # Validate variable references if provided
    variables = payload.get("variables") or []
    if variables:
        if not isinstance(variables, list):
            raise ToolError("MHX-E105", "variables must be an array.", exit_code=2)
        var_ids = {v.get("id") for v in variables if isinstance(v, dict)}
        node_ids = {n["id"] for n in nodes}
        unknown = node_ids - var_ids
        if unknown:
            raise ToolError(
                "MHX-E107",
                f"variable references unresolved for node(s): {sorted(unknown)}.",
                details={"unknown": sorted(unknown), "known_variables": sorted(var_ids)},
                exit_code=3,
            )

    # Cycle detection (Kahn)
    detect_cycles = payload.get("detect_cycles", True)
    topo: list[str] = []
    if detect_cycles:
        try:
            topo = M.topo_sort(nodes)
        except ValueError as exc:
            raise ToolError(
                "MHX-E105",
                f"mechanism graph contains a cycle: {exc}",
                details={"cycle_nodes": str(exc)},
                exit_code=3,
            ) from exc
    else:
        topo = [n["id"] for n in nodes]

    # Ancestry / descendants for every node
    ancestry = {}
    for nid in node_ids_of(nodes):
        ancestry[nid] = {
            "ancestors": sorted(M.ancestors(nodes, nid)),
            "descendants": sorted(M.descendants(nodes, nid)),
        }

    return {
        "chains": [M.normalize_chain(c) for c in chains],
        "node_count": len(nodes),
        "edge_count": len(edges),
        "nodes": nodes,
        "edges": _edge_list(edges),
        "topological_order": topo,
        "acyclic": detect_cycles and len(topo) == len(nodes),
        "ancestry": ancestry,
        "notes": [
            "edges follow the direction of the mechanism chain (cause -> effect); "
            "ancestors/descendants are transitive closures over the union of all chains."
        ],
    }


def node_ids_of(nodes: list[dict]) -> list[str]:
    return [n["id"] for n in nodes]


if __name__ == "__main__":
    run_tool(TOOL, main)
