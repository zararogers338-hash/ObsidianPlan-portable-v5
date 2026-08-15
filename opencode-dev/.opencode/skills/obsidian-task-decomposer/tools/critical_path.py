#!/usr/bin/env python3
"""critical_path.py — CPM analysis of a task DAG.

Implements the classic forward/backward pass (Kelley & Walker 1959, see
references/sources.md S6) over the DAG's topological order. Duration source per
node: `est_effort_hours` (falling back to config.default_duration_hours when a
node lacks an estimate; such nodes are flagged in `assumed_durations`).

stdin:
  {"nodes": [{"id", "depends_on", "est_effort_hours"?}, ...],
   "config": {"default_duration_hours": 4.0}?}

stdout result:
  {"critical_path": [ids], "critical_path_hours": float,
   "node_metrics": {id: {duration, earliest_start, earliest_finish,
                          latest_start, latest_finish, slack, critical}},
   "parallelism": {"max_width": int, "avg_width": float, "levels": [[ids]...]},
   "assumed_durations": [ids],
   "fallback_paths": {"optional": [...], "on_failure": {node_id: [recovery ids]}}}

Graph must be acyclic; cycles are reported via E_GRAPH_CYCLIC with evidence.
"""

from __future__ import annotations

import os
import sys
from collections import defaultdict, deque

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from _common import ToolError, as_dict, as_list, as_number, as_str, run_tool
from dag_check import _analyze, _extract_graph  # reuse the structural analysis


def _topo(ids, deps):
    result = _analyze(ids, deps, [])
    if not result["is_dag"]:
        raise ToolError(
            "E_GRAPH_CYCLIC",
            "graph is not a DAG; resolve cycles before scheduling",
            details={"cycles": result["cycles"],
                     "unknown_dependencies": result["unknown_dependencies"],
                     "self_loops": result["self_loops"]},
            exit_code=3,
        )
    return result


def main(payload):
    doc = as_dict(payload, "$")
    ids, deps, duplicates = _extract_graph(payload)
    if duplicates:
        raise ToolError("E_GRAPH_DUPLICATE_IDS",
                        f"duplicate node ids: {sorted(set(duplicates))}",
                        details={"duplicate_ids": sorted(set(duplicates))}, exit_code=3)
    structural = _topo(ids, deps)

    cfg = as_dict(doc.get("config", {}), "$.config")
    default_dur = as_number(cfg.get("default_duration_hours", 4.0),
                            "$.config.default_duration_hours", min_v=0.0, max_v=10000.0)

    nodes_raw = {as_dict(n, f"$.nodes[{i}]").get("id"): as_dict(n, f"$.nodes[{i}]")
                 for i, n in enumerate(as_list(doc.get("nodes"), "$.nodes"))}

    durations: dict[str, float] = {}
    assumed: list[str] = []
    for nid in ids:
        raw = nodes_raw[nid].get("est_effort_hours")
        if raw is None:
            durations[nid] = default_dur
            assumed.append(nid)
        else:
            durations[nid] = as_number(raw, f"node {nid}.est_effort_hours",
                                       min_v=0.0, max_v=10000.0)

    # Forward pass (earliest start/finish) over topo order
    es: dict[str, float] = {}
    ef: dict[str, float] = {}
    for nid in structural["topo_order"]:
        preds = [d for d in deps.get(nid, []) if d in durations]
        es[nid] = max((ef[p] for p in preds), default=0.0)
        ef[nid] = es[nid] + durations[nid]
    project_len = max(ef.values(), default=0.0)

    # Backward pass (latest start/finish)
    succ: dict[str, list[str]] = defaultdict(list)
    for nid, dlist in deps.items():
        for d in dlist:
            if d in durations:
                succ[d].append(nid)
    lf: dict[str, float] = {}
    ls: dict[str, float] = {}
    for nid in reversed(structural["topo_order"]):
        nexts = succ.get(nid, [])
        lf[nid] = min((ls[s] for s in nexts), default=project_len)
        ls[nid] = lf[nid] - durations[nid]

    slack = {nid: round(ls[nid] - es[nid], 9) for nid in ids}
    critical = [nid for nid in structural["topo_order"] if abs(slack[nid]) < 1e-9]

    metrics = {
        nid: {
            "duration_hours": round(durations[nid], 3),
            "earliest_start": round(es[nid], 3),
            "earliest_finish": round(ef[nid], 3),
            "latest_start": round(ls[nid], 3),
            "latest_finish": round(lf[nid], 3),
            "slack_hours": round(slack[nid], 3),
            "critical": abs(slack[nid]) < 1e-9,
        }
        for nid in ids
    }

    levels = structural["levels"] or []
    widths = [len(level) for level in levels]
    parallelism = {
        "max_width": max(widths, default=0),
        "avg_width": round(sum(widths) / len(widths), 3) if widths else 0.0,
        "levels": levels,
        "speedup_bound": round(sum(durations.values()) / project_len, 3) if project_len > 0 else 1.0,
    }

    # Fallback path extraction from node metadata (advisory; declared by author)
    optional_nodes = sorted(nid for nid in ids if nodes_raw[nid].get("optional") is True)
    on_failure: dict[str, list[str]] = {}
    for nid in ids:
        rec = nodes_raw[nid].get("on_failure_replan")
        if isinstance(rec, list) and rec:
            on_failure[nid] = [as_str(x, f"{nid}.on_failure_replan[]") for x in rec]

    return {
        "critical_path": critical,
        "critical_path_hours": round(project_len, 3),
        "node_metrics": metrics,
        "parallelism": parallelism,
        "assumed_durations": sorted(assumed),
        "fallback_paths": {"optional_nodes": optional_nodes, "on_failure_replan": on_failure},
        "note": "durations are estimates; slack inherits estimate error (CALCULATED, not OBSERVED)",
    }


if __name__ == "__main__":
    run_tool("critical_path", main)
