#!/usr/bin/env python3
"""self_audit.py — acceptance-gate checks for a decomposition output.

Runs the mechanical acceptance gates from the skill contract:
  G1: no implicit dependencies — every node's declared inputs must be covered by
      its upstream closure or by the request's external inputs
  G2: every node has exactly one primary skill and at most one collaborator
  G3: every node has a verifiable definition of done
  G4: graph is a DAG (delegates to dag_check analysis)
  G5: depth/iteration ceilings present; human-approval gates present for
      high-risk / irreversible node kinds
  G6: epistemic tagging — every finding carries a valid epistemic tag

stdin: {"output": <candidate skill output object (pre-artifact-wrapping)>,
        "external_inputs": ["evidence_refs", "data_refs", ...] (optional)}

stdout: {"pass": bool, "gates": {G1..G6: {pass, violations: [...]}}, ...}
"""

from __future__ import annotations

import os
import sys
from collections import defaultdict, deque

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from _common import ToolError, as_dict, as_list, run_tool
from dag_check import _analyze, _extract_graph

VALID_TAGS = {"OBSERVED", "REPORTED", "CALCULATED", "INFERRED", "HYPOTHESIS", "RECOMMENDATION"}
HUMAN_GATE_KINDS = {"human_wait"}
HUMAN_GATE_RISK = {"high"}


def _upstream_coverage(nodes: list[dict]) -> dict[str, set[str]]:
    deps = {n["id"]: set(n.get("depends_on", [])) for n in nodes}
    closure: dict[str, set[str]] = {n: set() for n in deps}
    for nid in deps:
        stack = list(deps[nid])
        while stack:
            cur = stack.pop()
            if cur in closure[nid]:
                continue
            closure[nid].add(cur)
            stack.extend(deps.get(cur, ()))
    return closure


def main(payload):
    doc = as_dict(payload, "$")
    out = as_dict(doc.get("output"), "$.output")
    external = set(doc.get("external_inputs", []) or [])

    gates: dict[str, dict] = {}
    nodes = out.get("dag", {}).get("nodes")
    if not isinstance(nodes, list) or not nodes:
        raise ToolError("E_OUTPUT_SHAPE", "output.dag.nodes must be a non-empty array")

    # G4 first — other gates assume parseable graph
    ids, deps, duplicates = _extract_graph({"nodes": nodes})
    structural = _analyze(ids, deps, duplicates)
    g4_violations = []
    if duplicates:
        g4_violations.append(f"duplicate ids: {sorted(set(duplicates))}")
    for c in structural["cycles"]:
        g4_violations.append(f"cycle: {' -> '.join(c.get('walk', c['nodes']))}")
    for u in structural["unknown_dependencies"]:
        g4_violations.append(f"unknown dependency referenced: {u}")
    for s in structural["self_loops"]:
        g4_violations.append(f"self loop: {s}")
    gates["G4_acyclic"] = {"pass": not g4_violations, "violations": g4_violations}

    by_id = {n["id"]: n for n in nodes if isinstance(n, dict) and "id" in n}
    closure = _upstream_coverage([{"id": k, "depends_on": list(v)} for k, v in deps.items()])

    # G1: implicit dependencies — declared inputs not produced upstream nor external
    g1_violations = []
    EXTERNAL_PRODUCERS = {"request", "context", "constraints"}
    EXTERNAL_PREFIXES = ("evidence_refs:", "data_refs:", "upstream_outputs:")
    for nid, node in by_id.items():
        for inp in node.get("inputs", []) or []:
            if not isinstance(inp, str):
                g1_violations.append(f"{nid}: non-string input entry")
                continue
            producer = inp.split(":", 1)[0]  # "node_id:artifact" convention
            if producer in external or producer in EXTERNAL_PRODUCERS:
                continue
            if inp.startswith(EXTERNAL_PREFIXES):
                continue
            if producer in by_id and producer in closure[nid]:
                continue
            if producer in by_id:
                g1_violations.append(
                    f"{nid}: input '{inp}' comes from node '{producer}' which is not an ancestor — implicit dependency")
            else:
                g1_violations.append(
                    f"{nid}: input '{inp}' has no producer node and is not declared external")
    gates["G1_no_implicit_dependencies"] = {"pass": not g1_violations, "violations": g1_violations}

    # G2: single owner
    g2_violations = []
    for nid, node in by_id.items():
        if not node.get("primary_skill"):
            g2_violations.append(f"{nid}: missing primary_skill")
        collab = node.get("collaborator_skill")
        if isinstance(collab, list) and len(collab) > 1:
            g2_violations.append(f"{nid}: {len(collab)} collaborators (max 1)")
    gates["G2_single_owner"] = {"pass": not g2_violations, "violations": g2_violations}

    # G3: definition of done
    g3_violations = []
    for nid, node in by_id.items():
        dod = node.get("definition_of_done")
        if not isinstance(dod, dict) or not dod.get("artifact") or not dod.get("acceptance_criteria"):
            g3_violations.append(f"{nid}: definition_of_done needs artifact + acceptance_criteria")
    gates["G3_verifiable_dod"] = {"pass": not g3_violations, "violations": g3_violations}

    # G5: ceilings + human approval gates
    g5_violations = []
    limits = out.get("execution_limits")
    if not isinstance(limits, dict):
        g5_violations.append("execution_limits missing")
    else:
        if not isinstance(limits.get("max_call_depth"), int) or limits.get("max_call_depth", 0) < 1:
            g5_violations.append("execution_limits.max_call_depth must be a positive integer")
        if not isinstance(limits.get("max_iterations"), int) or limits.get("max_iterations", 0) < 1:
            g5_violations.append("execution_limits.max_iterations must be a positive integer")
    for nid, node in by_id.items():
        needs_gate = (node.get("kind") in HUMAN_GATE_KINDS
                      or node.get("risk_level") in HUMAN_GATE_RISK
                      or node.get("irreversible") is True)
        if needs_gate and node.get("human_approval_gate") is not True:
            g5_violations.append(
                f"{nid}: kind={node.get('kind')} risk={node.get('risk_level')} requires human_approval_gate: true")
    gates["G5_limits_and_human_gates"] = {"pass": not g5_violations, "violations": g5_violations}

    # G6: epistemic tags on findings
    g6_violations = []
    for i, f in enumerate(out.get("findings", []) or []):
        if not isinstance(f, dict):
            g6_violations.append(f"findings[{i}] is not an object")
            continue
        tag = f.get("epistemic_tag")
        if tag not in VALID_TAGS:
            g6_violations.append(f"findings[{i}]: epistemic_tag must be one of {sorted(VALID_TAGS)}")
        if tag == "OBSERVED" and not f.get("source"):
            g6_violations.append(f"findings[{i}]: OBSERVED claims must name their source")
    gates["G6_epistemic_tags"] = {"pass": not g6_violations, "violations": g6_violations}

    overall = all(g["pass"] for g in gates.values())
    return {
        "pass": overall,
        "gates": gates,
        "violation_count": sum(len(g["violations"]) for g in gates.values()),
        "note": "Gates are mechanical necessary conditions, not proof of research quality (CALCULATED).",
    }


if __name__ == "__main__":
    run_tool("self_audit", main)
