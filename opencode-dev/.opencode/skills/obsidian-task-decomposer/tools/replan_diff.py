#!/usr/bin/env python3
"""replan_diff.py — local replanning after new evidence or node failure.

Goal (per skill contract): when a node fails or new evidence arrives, replan
ONLY the affected subgraph. Confirmed facts and completed work are never lost.

Algorithm (deterministic, offline):
  1. Compute the downstream closure of the trigger nodes (failed/changed).
  2. Classify every node:
       completed + upstream-of-change  -> PRESERVED (never reopened)
       completed + downstream          -> PRESERVED (work stands) but flagged
                                          STALE (its inputs changed; auditor decides)
       pending    + downstream         -> INVALIDATED (must be re-decomposed/retried)
       pending    + unrelated          -> PRESERVED unchanged
       trigger nodes themselves        -> REWORK (kept in the graph as a re-do
                                          marker so downstream preserved nodes
                                          keep valid dependencies)
  3. INVALIDATED pending nodes are dropped from the graph. REWORK and PRESERVED
     nodes stay. Author-provided `replacement_nodes` may rebuild dropped work
     (a replacement sharing a REWORK node's id replaces it in place); to remove
     a node explicitly, list it in `remove_node_ids`.
  4. Emits a machine-readable diff: preserved / stale / invalidated / rework /
     added / removed, plus the resulting plan.

stdin:
  {"plan": {"nodes": [{"id", "depends_on", "status"?, ...}]},
   "trigger": {"failed_node_ids"?: [...], "changed_node_ids"?: [...],
               "reason": "...", "new_evidence_refs"?: [...]},
   "replacement_nodes"?: [ <node objects> ],
   "remove_node_ids"?: [...]}

node.status: "completed" | "in_progress" | "pending" | "failed" (default "pending")
"""

from __future__ import annotations

import os
import sys
from collections import defaultdict, deque

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from _common import ToolError, as_dict, as_list, as_str, run_tool
from dag_check import _analyze, _extract_graph

VALID_STATUS = {"completed", "in_progress", "pending", "failed"}


def _closure(trigger: set[str], deps: dict[str, list[str]]) -> set[str]:
    """All nodes that transitively depend on any trigger node."""
    succ: dict[str, list[str]] = defaultdict(list)
    for nid, dlist in deps.items():
        for d in dlist:
            succ[d].append(nid)
    seen: set[str] = set()
    queue = deque(sorted(trigger))
    while queue:
        node = queue.popleft()
        for nxt in succ.get(node, []):
            if nxt not in seen:
                seen.add(nxt)
                queue.append(nxt)
    return seen


def main(payload):
    doc = as_dict(payload, "$")
    plan = as_dict(doc.get("plan"), "$.plan")
    ids, deps, duplicates = _extract_graph({"nodes": plan.get("nodes")})
    if duplicates:
        raise ToolError("E_GRAPH_DUPLICATE_IDS",
                        f"duplicate node ids: {sorted(set(duplicates))}",
                        details={"duplicate_ids": sorted(set(duplicates))}, exit_code=3)

    structural = _analyze(ids, deps, duplicates)
    if not structural["is_dag"]:
        raise ToolError("E_GRAPH_CYCLIC",
                        "existing plan is not a DAG; fix cycles before replanning",
                        details={"cycles": structural["cycles"]}, exit_code=3)

    nodes_raw = {}
    for i, n in enumerate(as_list(plan.get("nodes"), "$.plan.nodes")):
        nd = as_dict(n, f"$.plan.nodes[{i}]")
        status = nd.get("status", "pending")
        if status not in VALID_STATUS:
            raise ToolError("E_INPUT_RANGE",
                            f"node {nd.get('id')}: status must be one of {sorted(VALID_STATUS)}",
                            details={"got": status})
        nodes_raw[nd["id"]] = nd

    trigger = as_dict(doc.get("trigger"), "$.trigger")
    reason = as_str(trigger.get("reason"), "$.trigger.reason", min_len=1)
    failed = {as_str(x, "$.trigger.failed_node_ids[]") for x in trigger.get("failed_node_ids", []) or []}
    changed = {as_str(x, "$.trigger.changed_node_ids[]") for x in trigger.get("changed_node_ids", []) or []}
    if not failed and not changed:
        raise ToolError("E_INPUT_MISSING_FIELD",
                        "trigger must name at least one failed or changed node id",
                        details={"field": "trigger.failed_node_ids | trigger.changed_node_ids"})
    unknown_triggers = sorted((failed | changed) - set(ids))
    if unknown_triggers:
        raise ToolError("E_GRAPH_UNKNOWN_NODE",
                        f"trigger references unknown node(s): {unknown_triggers}",
                        details={"unknown": unknown_triggers}, exit_code=3)

    removals = {as_str(x, "$.remove_node_ids[]") for x in doc.get("remove_node_ids", []) or []}
    unknown_removals = sorted(removals - set(ids))
    if unknown_removals:
        raise ToolError("E_GRAPH_UNKNOWN_NODE",
                        f"remove_node_ids references unknown node(s): {unknown_removals}",
                        details={"unknown": unknown_removals}, exit_code=3)

    downstream = _closure(failed | changed, deps)

    preserved, stale, invalidated, rework = [], [], [], []
    for nid in ids:
        status = nodes_raw[nid].get("status", "pending")
        if nid in (failed | changed):
            rework.append(nid)
        elif nid in downstream:
            if status == "completed":
                stale.append(nid)      # work kept, but premises changed
                preserved.append(nid)
            else:
                invalidated.append(nid)
        else:
            preserved.append(nid)

    # Replacements: an id matching a REWORK node replaces it in place; a new id
    # is added as a fresh node. Clash only with PRESERVED (kept) nodes.
    replacements = []
    for i, raw in enumerate(doc.get("replacement_nodes", []) or []):
        rn = as_dict(raw, f"$.replacement_nodes[{i}]")
        rid = as_str(rn.get("id"), f"$.replacement_nodes[{i}].id", min_len=1)
        as_list(rn.get("depends_on", []), f"$.replacement_nodes[{i}].depends_on")
        replacements.append(rn)

    replacement_ids = {r["id"] for r in replacements}
    clashes = sorted(replacement_ids & set(preserved))
    if clashes:
        raise ToolError("E_REPLAN_ID_CLASH",
                        f"replacement node ids collide with preserved nodes: {clashes}",
                        details={"clashes": clashes}, exit_code=3)

    # Nodes to drop from the merged graph:
    #   - invalidated pending nodes (their work is void)
    #   - explicitly removed ids
    #   - a REWORK node that a replacement is shadowing in place
    dropped = set(invalidated) | removals
    dropped |= {nid for nid in rework if nid in replacement_ids}
    merged_nodes = ([nodes_raw[nid] for nid in ids if nid not in dropped]
                    + replacements)
    merged_ids, merged_deps, merged_dups = _extract_graph({"nodes": merged_nodes})
    merged_struct = _analyze(merged_ids, merged_deps, merged_dups)
    if not merged_struct["is_dag"]:
        raise ToolError(
            "E_REPLAN_INVALID",
            "merged plan after replan is not a valid DAG",
            details={"cycles": merged_struct["cycles"],
                     "unknown_dependencies": merged_struct["unknown_dependencies"],
                     "hint": "replacement nodes must not depend on removed nodes"},
            exit_code=3,
        )

    # Dependents of removed nodes that were not themselves removed/invalidated:
    # after invalidated nodes are dropped, any remaining node referencing a
    # dropped id is a dangling-risk the author must resolve with replacements.
    dangling_risk = sorted(
        nid for nid in merged_ids
        if set(deps.get(nid, [])) & dropped and nid not in replacement_ids
    )

    return {
        "reason": reason,
        "trigger_nodes": sorted(failed | changed),
        "preserved": sorted(preserved),
        "stale_completed": sorted(stale),
        "invalidated": sorted(invalidated),
        "rework": sorted(rework),
        "added": sorted(replacement_ids),
        "removed": sorted(removals),
        "dangling_risk": dangling_risk,
        "new_evidence_refs": trigger.get("new_evidence_refs", []) or [],
        "merged_plan": {"nodes": merged_nodes},
        "merged_graph": {"topo_order": merged_struct["topo_order"],
                         "levels": merged_struct["levels"],
                         "node_count": merged_struct["node_count"],
                         "edge_count": merged_struct["edge_count"]},
        "guarantees": [
            "PRESERVED nodes (incl. all completed work not downstream of the trigger) are byte-identical",
            "stale_completed lists finished work whose inputs changed; it is flagged, never silently reopened",
            "confirmed facts upstream of the trigger are not touched",
        ],
    }


if __name__ == "__main__":
    run_tool("replan_diff", main)
