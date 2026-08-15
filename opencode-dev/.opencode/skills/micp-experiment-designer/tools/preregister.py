#!/usr/bin/env python3
"""Preregistration & raw-data template generator for micp-experiment-designer.

Produces:
  - a preregistration summary (hypothesis, primary & secondary endpoints,
    design, sample size justification, exclusion rules, analysis plan,
    stopping rules, human-approval statement) suitable for deposit before data
    collection begins;
  - a raw data template (column schema) that matches the design's endpoints,
    so data collection is structured from day one and can be audited later.

The generator DOES NOT fabricate a p-value, a conclusion, or a sample size:
  - sample size must be computed first with the DOE tool (doe_power.py) and
    passed in `sample_size`; if missing, the preregistration is emitted with
    `sample_size: "TBD"` and a blocking advisory that power analysis must run
    before data collection.
  - the output carries the ephemeral status "PREREGISTERED-DRAFT" so it can be
    versioned and frozen, but only the controller may mark it final.
"""

from __future__ import annotations

import json
from typing import Any

from ._common import ToolError, as_dict, as_int, as_list, as_str, now_iso, run_tool

TOOL = "preregister"

_TEMPLATE_VERSIONS = ["v1.0"]


def _endpoint_columns(endpoints: list[Any]) -> list[dict[str, str]]:
    cols = []
    for i, e in enumerate(endpoints):
        if not isinstance(e, dict):
            raise ToolError("E_TYPE", f"design.endpoints[{i}] must be an object")
        name = as_str(e.get("name", ""), f"design.endpoints[{i}].name", min_len=1)
        unit = as_str(e.get("unit", ""), f"design.endpoints[{i}].unit", min_len=1)
        cols.append({"column": f"{name}_{unit.replace('/', '_')}", "endpoint": name, "unit": unit})
    return cols


def _analysis_plan(design: dict[str, Any]) -> dict[str, Any]:
    stats = design.get("statistical_analysis") or {}
    if isinstance(stats, dict):
        return {
            "test": as_str(stats.get("test", "not-specified"), "design.statistical_analysis.test", min_len=0) or "not-specified",
            "alpha": stats.get("alpha", 0.05),
            "two_sided": bool(stats.get("two_sided", True)),
            "multiplicity_correction": as_str(stats.get("multiplicity_correction", "none"), "design.statistical_analysis.multiplicity_correction", min_len=0) or "none",
        }
    return {"test": "not-specified", "alpha": 0.05, "two_sided": True, "multiplicity_correction": "none"}


def main(payload: dict[str, Any]) -> dict[str, Any]:
    design = as_dict(payload.get("design", {}), "design")
    sample_size = payload.get("sample_size")
    sample_size_justification = as_str(
        design.get("sample_size_justification", ""), "design.sample_size_justification", min_len=0)

    endpoints = as_list(design.get("endpoints", []), "design.endpoints", min_len=1)
    groups = as_list(design.get("groups", []), "design.groups", min_len=2)
    if sample_size is None:
        sample_size = "TBD"
        blocking_advisory = ("sample size not provided; run the DOE/power tool and fill "
                             "`sample_size` before freezing the preregistration")
    else:
        sample_size = as_int(sample_size, "sample_size", min_v=1)
        blocking_advisory = None

    prereg = {
        "title": as_str(design.get("objective", "Untitled"), "design.objective", min_len=1),
        "primary_hypothesis": as_str(design.get("primary_hypothesis", ""), "design.primary_hypothesis", min_len=1),
        "alternative_hypothesis": as_str(design.get("alternative_hypothesis", ""), "design.alternative_hypothesis", min_len=0) or "not specified",
        "endpoints": [e.get("name") for e in endpoints],
        "groups": [as_str(g, f"design.groups[{i}]", min_len=1) if isinstance(g, str) else g.get("name") for i, g in enumerate(groups)],
        "randomization": as_str(design.get("randomization", ""), "design.randomization", min_len=0) or "see randomization allocation table",
        "blinding": as_str(design.get("blinding", "none"), "design.blinding", min_len=0),
        "sample_size": sample_size,
        "sample_size_justification": sample_size_justification,
        "exclusion_rules": as_str(design.get("data_exclusion", ""), "design.data_exclusion", min_len=0),
        "stopping_rules": as_str(design.get("stop_condition", ""), "design.stop_condition", min_len=0),
        "analysis_plan": _analysis_plan(design),
        "human_approval_required": bool(payload.get("human_approval_required", True)),
        "status": "PREREGISTERED-DRAFT",
        "generated_at": now_iso(),
        "template_version": _TEMPLATE_VERSIONS[0],
    }

    data_columns = [{"column": "unit_id", "type": "string"},
                    {"column": "experiment_id", "type": "string"},
                    {"column": "group", "type": "string"},
                    {"column": "block", "type": "string"},
                    {"column": "sampling_point", "type": "number"},
                    {"column": "date", "type": "date-time"}]
    data_columns.extend(_endpoint_columns(endpoints))
    data_columns.append({"column": "notes", "type": "string"})

    return {
        "preregistration": prereg,
        "data_template": {
            "format": "csv",
            "columns": data_columns,
            "filename_hint": f"raw_data_{payload.get('task_id', 'task')}.csv",
        },
        "blocking_advisory": blocking_advisory,
        "pass": blocking_advisory is None,
        "next_action": ("freeze the preregistration (controller approval) before data collection"
                        if blocking_advisory is None
                        else "run the DOE/power tool to compute sample_size, then regenerate"),
    }


if __name__ == "__main__":
    run_tool(TOOL, main)
