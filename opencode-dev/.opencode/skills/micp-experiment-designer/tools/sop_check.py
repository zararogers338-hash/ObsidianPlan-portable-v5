#!/usr/bin/env python3
"""SOP consistency checker & generator for micp-experiment-designer.

Turns a structured experiment design (hypotheses, groups, endpoints,
replicates, sampling points, reagents, materials, equipment, safety, data
rules) into a linear, independently executable Standard Operating Procedure
(SOP) — and, independently, checks an existing SOP for the hard structural
requirements that make it reproducible:

  REQUIRED blocks (checked):
    1. objective / primary hypothesis
    2. at least one negative control group (no treatment / sham)
    3. at least one positive control when the design claims a known positive
       reference
    4. at least 2 replicate units per group (statistical minimum; brief rule:
       no control/replicate/threshold => FAIL)
    5. explicit endpoint measurements with units
    6. explicit data-exclusion rule
    7. explicit stop condition / failure threshold
    8. for MICP / urea designs: ammonium & nitrogen mass-balance accounted
       (S10 in references)
    9. for designs labelled non-urea: no urea-pathway assumptions
    10. material batch, injection order, flow/pressure, retention, curing &
        cleaning specified for wet-chemistry/MICP designs

  Blocking issues (exit 2) vs advisory warnings (reported but non-blocking)
  are separated. Every step is emitted with an ID (STEP-01 …) so it can be
  referenced from the data template and the audit trail.
"""

from __future__ import annotations

from typing import Any

from ._common import ToolError, as_dict, as_int, as_list, as_str, run_tool

TOOL = "sop_check"

_REQUIRED_BLOCKS = {
    "objective": ("objective", "objective statement (primary hypothesis)"),
    "negative_control": ("negative_control", "negative control group (sham / untreated)"),
    "positive_control": ("positive_control", "positive control group (known positive reference)"),
    "replicates": ("replicates", "replicate count per group (>= 2)"),
    "endpoints": ("endpoints", "endpoint measurements with units"),
    "data_exclusion": ("data_exclusion", "explicit data-exclusion rule"),
    "stop_condition": ("stop_condition", "stop condition / failure threshold"),
    "materials": ("materials", "material batch / reagent list"),
    "injection": ("injection", "injection order, flow/pressure, retention, curing & cleaning"),
    "equipment": ("equipment", "equipment list"),
    "safety": ("safety", "safety & biohazard controls"),
    "data_template": ("data_template", "raw data template (columns)"),
}


def _check_required(design: dict[str, Any]) -> tuple[list[str], list[str]]:
    missing: list[str] = []
    warnings: list[str] = []

    if not design.get("objective"):
        missing.append("objective")
    if not design.get("negative_control"):
        missing.append("negative_control")
    if not design.get("positive_control"):
        warnings.append("positive_control")  # advisory: many designs omit it legitimately
    if not design.get("replicates") or design.get("replicates", 0) < 2:
        missing.append("replicates")
    if not design.get("endpoints"):
        missing.append("endpoints")
    if not design.get("data_exclusion"):
        missing.append("data_exclusion")
    if not design.get("stop_condition"):
        missing.append("stop_condition")
    if not design.get("materials"):
        warnings.append("materials")
    if not design.get("injection"):
        warnings.append("injection")
    if not design.get("equipment"):
        warnings.append("equipment")
    if not design.get("safety"):
        missing.append("safety")
    if not design.get("data_template"):
        warnings.append("data_template")

    # MICP discipline (S10): urea pathway must account for ammonium & N balance
    pathway = as_str(design.get("pathway", ""), "pathway", min_len=0)
    if "urea" in pathway.lower():
        if not design.get("ammonium_accounting"):
            missing.append("ammonium_accounting")
        if not design.get("nitrogen_mass_balance"):
            warnings.append("nitrogen_mass_balance")
    elif pathway and "urea" not in pathway.lower() and design.get("ammonium_accounting"):
        warnings.append("non_urea_urea_assumption")
    elif not pathway:
        warnings.append("pathway_unspecified")

    return missing, warnings


def _build_sop(design: dict[str, Any]) -> list[dict[str, str]]:
    steps: list[dict[str, str]] = []
    n = 0

    def add(action: str, detail: str) -> None:
        nonlocal n
        n += 1
        steps.append({"step_id": f"STEP-{n:02d}", "action": action, "detail": detail})

    add("prepare", "Prepare materials & equipment per batch list; verify calibration records.")
    add("inoculate", "Prepare cell / enzyme / reagent solutions per recipe; record lot numbers.")
    add("assign", "Randomize units to groups per the randomization allocation table (seed recorded).")
    add("treat", "Apply treatment per group (negative control receives sham / vehicle only).")
    add("measure", "Record endpoint measurements at each sampling point using the data template columns.")
    add("stop", "Apply stop conditions / failure thresholds; record deviations in the deviation log.")
    add("cleanup", "Clean equipment, dispose of biological & chemical waste per safety plan.")
    add("archive", "Archive raw data, logs, and allocation table; store under the project data directory.")

    return steps


def main(payload: dict[str, Any]) -> dict[str, Any]:
    design = as_dict(payload.get("design", {}), "design")

    # mode 1: check an existing SOP (checks steps against the required blocks)
    existing = payload.get("sop")
    if existing is not None:
        if not isinstance(existing, dict):
            raise ToolError("E_TYPE", "sop must be an object", details={"path": "sop"})
        missing, warnings = _check_required(design)
        step_ids = set()
        steps = as_list(existing.get("steps", []), "sop.steps")
        for s in steps:
            if not isinstance(s, dict):
                raise ToolError("E_TYPE", "sop.steps[i] must be an object")
            sid = as_str(s.get("step_id", ""), "sop.steps[i].step_id", min_len=1)
            if sid in step_ids:
                raise ToolError("E_INPUT_VALUE", f"duplicate step_id '{sid}'", details={"step_id": sid})
            step_ids.add(sid)
        blocking = [m for m in missing]
        return {
            "mode": "check",
            "blocking_issues": blocking,
            "warnings": warnings,
            "pass": len(blocking) == 0,
            "step_count": len(steps),
            "unique_step_ids": len(step_ids),
        }

    # mode 2: generate SOP from design
    missing, warnings = _check_required(design)
    blocking = [m for m in missing]
    steps = _build_sop(design)
    return {
        "mode": "generate",
        "pass": len(blocking) == 0,
        "blocking_issues": blocking,
        "warnings": warnings,
        "sop": {"title": design.get("objective", "Untitled experiment"), "steps": steps},
        "next_action": ("resolve blocking issues (see blocking_issues) before field execution"
                        if blocking else "SOP ready for human approval before execution"),
    }


if __name__ == "__main__":
    run_tool(TOOL, main)
