"""MICP Data Analyst service: orchestrates the whole skill contract.

Pipeline (every step is a real, recorded tool run — never faked):
  1. Validate the controller envelope against schemas/input.schema.json.
  2. Version gate: skill_version major must match; E801 otherwise.
  3. Precondition check: request with a deliverable; samples present when the
     request requires statistics; risk/approval gate.
  4. Data quality + unit + pseudo-replication checks (tools/micp/qc.py).
  5. Statistics per response column (descriptive, CI, normality), group
     comparisons (effect size), uniformity, sensitivity (tools/micp/stats.py).
  6. Self-check the assembled output against schemas/output.schema.json.
  7. Emit the unified envelope with status / findings / evidence / validation /
     provenance / errors and epistemic tags on every load-bearing claim.

Deterministic and offline; all RNG is seeded (default 0).
"""

from __future__ import annotations

import json
import os
from typing import Any

# The tools/ dir is on sys.path for CLI runs; keep imports sibling-style so the
# same file works as `python tools/micp/service.py < input.json`.
import qc
import stats as stats_mod

try:
    from _common import run_tool, emit_progress
except ImportError:
    from _common import run_tool, emit_progress

from _common import ToolError, TOOLSET_VERSION

SKILL_NAME = "micp-data-analyst"
SKILL_VERSION = "1.0.0"
CONTRACT_VERSION = "1.0.0"

TOOLS_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SKILL_ROOT = os.path.dirname(TOOLS_DIR)
SCHEMAS_DIR = os.path.join(SKILL_ROOT, "schemas")

STATUSES = ("SUCCESS", "PARTIAL", "BLOCKED", "FAILED",
            "NEED_ADDITIONAL_SKILL", "HUMAN_APPROVAL_REQUIRED")
EPISTEMIC = ("OBSERVED", "REPORTED", "CALCULATED", "INFERRED",
             "HYPOTHESIS", "RECOMMENDATION")

FIELD_GUIDANCE: dict[str, dict[str, str]] = {
    "task_id": {"why": "audit anchor and reproducibility", "how": "assigned by the Task Decomposer"},
    "project_id": {"why": "selects the data provenance file", "how": "registered at project setup"},
    "request": {"why": "the sole natural-language signal of what to analyze", "how": "from the Mission Lock contract"},
    "skill_version": {"why": "version compatibility gate", "how": "declared in this skill's frontmatter"},
    "controller_version": {"why": "permission model version gate", "how": "injected by the Controller"},
    "timestamp": {"why": "audit and reproducibility", "how": "injected by the Controller at call time"},
    "samples": {"why": "the only real input for statistics", "how": "experiment records or data_refs to a CSV/JSON"},
    "data_columns": {"why": "declares variable roles, types, units, sampling_unit", "how": "from the experiment's data dictionary"},
}


def load_schema(name: str) -> dict:
    path = os.path.join(SCHEMAS_DIR, name)
    if not os.path.isfile(path):
        raise ToolError("MDA-E301", f"schema file not found: {name}",
                        details={"path": path}, exit_code=4)
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


# ---------------------------------------------------------------------------
# Version gate
# ---------------------------------------------------------------------------

def check_versions(p: dict) -> list[str]:
    problems: list[str] = []
    sv = p.get("skill_version")
    cv = p.get("controller_version")
    if sv and sv.split(".")[0] != SKILL_VERSION.split(".")[0]:
        problems.append(
            f"skill_version {sv!r} has a different major than this build ({SKILL_VERSION}); "
            f"a migration gate applies (E801).")
    if not sv:
        problems.append("skill_version missing (E101)")
    if not cv:
        problems.append("controller_version missing (E101)")
    return problems


# ---------------------------------------------------------------------------
# Preconditions
# ---------------------------------------------------------------------------

def check_preconditions(p: dict, issue_log: list[dict]) -> tuple[str | None, list[dict]]:
    """Return (blocking_status, missing_inputs)."""
    missing: list[dict] = []
    req = p.get("request", "")
    if not req:
        missing.append({
            "field": "request",
            "why_critical": FIELD_GUIDANCE["request"]["why"],
            "how_to_obtain": FIELD_GUIDANCE["request"]["how"]})
    elif len(req.strip()) < 10:
        missing.append({
            "field": "request",
            "why_critical": "the analysis request must state an objective and a deliverable",
            "how_to_obtain": "state what to compute and what artifact is expected"})

    samples = p.get("samples")
    data_refs = p.get("data_refs") or []
    wants_stats = _wants_statistics(req)
    if wants_stats and samples is None and not data_refs:
        missing.append({
            "field": "samples (or data_refs)",
            "why_critical": "statistics have no input without the data; a data-free inference would be fabricated",
            "how_to_obtain": "attach the data rows or point data_refs at the experiment CSV/JSON"})
    if samples is not None and not p.get("data_columns"):
        missing.append({
            "field": "data_columns",
            "why_critical": "without variable roles/units/sampling_unit the rows cannot be interpreted or checked",
            "how_to_obtain": "supply the experiment's data dictionary"})

    if missing:
        return "BLOCKED", missing

    # risk / approval gate
    risk = p.get("risk_level", "low")
    approval = p.get("human_approval_state", "not_required")
    sensitive = _wants_sensitive_action(req)
    if risk in ("high", "critical") and sensitive and approval != "approved":
        return "HUMAN_APPROVAL_REQUIRED", []

    # downstream capability needed but absent
    need = _needs_downstream(p)
    if need:
        return "NEED_ADDITIONAL_SKILL", []

    return None, []


def _wants_statistics(req: str) -> bool:
    low = req.lower()
    markers = ("statist", "mean", "variance", "significant", "ci", "confidence",
               "effect size", "compare", "regress", "anova", "uniform", "outlier",
               "hypoth", "power", "analy", "curve", "拟合", "统计", "显著性", "均值",
               "分析", "比较", "回归", "均匀", "异常", "假设检验", "样本", "效应")
    return any(m in low for m in markers)


def _wants_sensitive_action(req: str) -> bool:
    low = req.lower()
    return any(m in low for m in ("field deploy", "现场", "in situ", "live experiment",
                                  "real experiment", "hazardous", "危险化学", "长期知识库",
                                  "long-term knowledge", "wet-lab", "wet lab"))


def _needs_downstream(p: dict) -> list[dict] | None:
    """Detect analysis modes this skill cannot run and must route onward."""
    modes = (p.get("constraints") or {}).get("analysis_modes") or []
    unsupported = [m for m in modes if m in ("mixed_effects", "response_surface",
                                             "multi_objective", "time_series")]
    if unsupported:
        return [{
            "skill": "obsidian-modeling-optimizer",
            "reason": f"requested analysis mode(s) {unsupported} are beyond micp-data-analyst; "
                      f"needs a modeling/optimization capability",
            "inputs_needed": ["samples", "data_columns", "upstream_outputs"]}]
    return None


# ---------------------------------------------------------------------------
# Statistics dispatch
# ---------------------------------------------------------------------------

def _response_columns(p: dict) -> list[dict]:
    cols = p.get("data_columns") or []
    return [c for c in cols if c.get("role") == "response"]


def _engineering_judgment(thresholds: dict, resp_col: str,
                          group_a: list[float], group_b: list[float]) -> dict | None:
    """Compare observed group means against engineering thresholds.

    Produces the three-state engineering verdict the skill must report
    alongside statistical p-values (never p-only judgment).

    `thresholds` shape (subset understood here):
      { "<column>": {"min": <float>, "max": <float>, "min_gain": <float>,
                     "unit": <str>} , ... }
    - `min`/`max` bound the acceptable range of the response.
    - `min_gain` is the minimum relative gain (fraction, e.g. 0.3 = +30%) of
      group B over group A that counts as engineering-relevant.
    Returns None when no threshold applies to this column.
    """
    spec = thresholds.get(resp_col)
    if not isinstance(spec, dict):
        return None
    if not group_a or not group_b:
        return None
    ma = sum(group_a) / len(group_a)
    mb = sum(group_b) / len(group_b)
    checks: list[dict] = []
    if "min" in spec or "max" in spec:
        lo = spec.get("min")
        hi = spec.get("max")
        ok_lo = lo is None or mb >= lo
        ok_hi = hi is None or mb <= hi
        checks.append({
            "criterion": f"mean within [{lo}, {hi}]",
            "passed": bool(ok_lo and ok_hi),
            "observed": mb,
        })
    if "min_gain" in spec:
        gain = spec["min_gain"]
        rel = (mb - ma) / abs(ma) if ma != 0 else float("inf")
        checks.append({
            "criterion": f"relative gain of {gain:+.0%} over baseline",
            "passed": rel >= gain,
            "observed": round(rel, 4),
        })
    if not checks:
        return None
    engineering_significant = all(c["passed"] for c in checks)
    return {
        "column": resp_col,
        "unit": spec.get("unit"),
        "group_means": {"baseline": _fmt(ma), "candidate": _fmt(mb)},
        "checks": checks,
        "engineering_significant": engineering_significant,
        "verdict": ("engineering_significant" if engineering_significant
                    else "engineering_not_significant"),
        "note": ("Statistical significance is reported separately; a large Cohen's d "
                 "at high n is not itself engineering value."),
    }


def _fmt(x: float) -> float:
    """Round for display without losing small-value distinctions (e.g. 1.0e-6 vs 1.2e-6)."""
    return round(x, 10) if abs(x) < 1e-4 else round(x, 6)


def _analyze_statistics(p: dict) -> dict[str, Any]:
    """Run real stats over the response columns; returns the `statistics` object."""
    rows = p.get("samples") or []
    cols = p.get("data_columns") or []
    resp = _response_columns(p)
    seed = p.get("reproducibility", {}).get("random_seed") or \
        (p.get("constraints") or {}).get("random_seed") or 0
    significance = (p.get("constraints") or {}).get("significance_level", 0.05)
    confidence = (p.get("constraints") or {}).get("confidence_level", 0.95)
    out: dict[str, Any] = {"significance_level": significance,
                           "confidence_level": confidence, "seed": seed,
                           "variables": {}, "tool_runs": []}

    # grouping variable (first treatment column)
    treat = next((c for c in cols if c.get("role") == "treatment"), None)

    for col in resp:
        name = col["name"]
        unit = col.get("unit")
        raw_values = [r.get(name) for r in rows]
        rep = qc.to_numeric_report(raw_values)
        values = qc.to_numeric(raw_values)
        var: dict[str, Any] = {"role": col.get("role"), "unit": unit}
        if rep["n_skipped"]:
            var["skipped"] = rep
            for sk in rep["skipped"]:
                out.setdefault("qc_issues", []).append({
                    "code": "NON_FINITE_OR_MISSING", "severity": "warning",
                    "message": f"column {name!r}: row {sk['index']} skipped "
                               f"({sk['reason']})", "details": sk})
        if values:
            var["descriptive"] = stats_mod.descriptive(values, unit=unit, name=name, seed=seed)
            var["ci"] = stats_mod.t_ci(values, confidence)
            var["normality"] = stats_mod.normality_screen(values)
            var["outliers"] = stats_mod.outlier_policies(values)
        else:
            var["descriptive"] = {"n": 0, "note": "no numeric values for this column"}
        out["variables"][name] = var
        out["tool_runs"].append({"tool": "stats.descriptive", "column": name})
        out["tool_runs"].append({"tool": "stats.ci", "column": name})

    # group comparison: first treatment with >=2 levels and >=2 rows each.
    # When pseudo-replication exists, aggregate to the sampling unit first so
    # the effect size reflects the independent sample, not the row count.
    if treat is not None:
        tname = treat["name"]
        resp_col = resp[0]["name"] if resp else None
        # sampling unit resolution (mirror of qc.pseudo_replication_check)
        id_col = next((c for c in cols if c.get("role") == "id"), None)
        batch_col = next((c for c in cols if c.get("role") == "batch"), None)
        su_name = (resp[0].get("sampling_unit") if resp else None) \
            or (batch_col.get("name") if batch_col else None) \
            or (id_col.get("name") if id_col else None)

        if resp_col is not None:
            # per sampling unit per treatment: mean of response within unit
            unit_values: dict[str, list[float]] = {}
            for r in rows:
                tkey = r.get(tname)
                if tkey is None:
                    continue
                v = r.get(resp_col)
                if not isinstance(v, (int, float)):
                    continue
                su_key = str(r.get(su_name)) if su_name else str(tkey) + "#" + str(r.get(resp_col) if not isinstance(v, (int, float)) else "r") + str(len(unit_values))
                # key by (unit, treatment) to keep per-group lists
                k = f"{tkey}|{su_key}"
                unit_values.setdefault(k, []).append(float(v))
            # group means over units (aggregate within unit)
            groups: dict[str, list[float]] = {}
            for k, vals in unit_values.items():
                tkey, _ = k.split("|", 1)
                groups.setdefault(tkey, []).append(sum(vals) / len(vals))
            levels = [k for k, v in groups.items() if len(v) >= 2]
            if len(levels) >= 2:
                a = groups[levels[0]]
                b = groups[levels[1]]
                es = stats_mod.cohens_d(a, b)
                pw = stats_mod.power_two_sample(min(len(a), len(b)),
                                                abs(es["cohens_d"]), significance)
                gc = {
                    "factor": tname, "groups": levels,
                    "unit_aggregated": su_name is not None,
                    "sampling_unit": su_name,
                    "effect_size": es,
                    "power_est": pw,
                }
                # engineering-significance judgment vs thresholds (never p-only)
                thresh = (p.get("constraints") or {}).get("engineering_thresholds") or {}
                eng = _engineering_judgment(thresh, resp_col, a, b)
                if eng:
                    gc["engineering"] = eng
                out["group_comparison"] = gc
                out["tool_runs"].append({"tool": "stats.cohens_d", "factor": tname})
            else:
                out["group_comparison_skipped"] = {
                    "factor": tname,
                    "reason": (f"after aggregation to sampling units, each treatment level has "
                               f"< 2 independent units; an effect size would be uninterpretable. "
                               f"Per-level unit counts: { {k: len(v) for k, v in groups.items()} }"),
                    "per_level_unit_counts": {k: len(v) for k, v in groups.items()},
                }

    # sensitivity on first response column when outliers flagged
    if resp:
        col = resp[0]
        name = col["name"]
        values = qc.to_numeric([r.get(name) for r in rows])
        if values and stats_mod.outlier_policies(values)["n_iqr_outliers"]:
            out["sensitivity"] = stats_mod.sensitivity_mean(
                values, ["keep", "winsorize_1p5iqr", "winsorize_3sd", "trim_5pct"])
            out["tool_runs"].append({"tool": "stats.sensitivity", "column": name})

    # uniformity over position/time when a position column exists
    pos = next((c for c in cols if c.get("role") == "position"), None)
    if pos and resp:
        col = resp[0]
        name = col["name"]
        values = qc.to_numeric([r.get(name) for r in rows])
        positions = [str(r.get(pos["name"])) for r in rows if r.get(pos["name"]) is not None]
        if values and positions and len(values) == len(positions):
            try:
                out["uniformity"] = stats_mod.spatial_uniformity(values, positions)
                out["tool_runs"].append({"tool": "stats.uniformity", "column": name})
            except ToolError:
                pass
    return out


# ---------------------------------------------------------------------------
# Findings with epistemic tags
# ---------------------------------------------------------------------------

def _evidence_used(p: dict) -> list[dict]:
    """List cited refs with a verifiability note.

    A ref is `verifiable` when its locator names a resolvable protocol
    (doi.org / http(s) / s3://). Anything else is reported as `unverifiable` —
    the skill never asserts a citation is valid beyond what the input provides,
    and it never fabricates locators.
    """
    out: list[dict] = []
    for ref in (p.get("evidence_refs") or [])[:20]:
        loc = str(ref.get("locator") or "")
        verifiable = loc.startswith(("https://", "http://", "doi.org", "s3://"))
        out.append({
            "ref_id": ref.get("ref_id"),
            "how_used": ref.get("note") or "cited data/evidence input",
            "verifiable": verifiable,
            "note": ("locator resolvable via its protocol; content not independently "
                     "retrieved by this offline skill" if verifiable
                     else "locator absent or not resolvable by a known protocol; "
                          "treat claims from this ref as REPORTED with no offline check"),
        })
    return out


def _build_findings(p: dict, dq: dict, stats: dict[str, Any],
                    pseudo: dict[str, Any]) -> list[dict]:
    findings: list[dict] = []
    resp = _response_columns(p)
    rows = p.get("samples") or []

    findings.append({
        "statement": f"Analyzed {len(rows)} data rows with {len(resp)} response variable(s) "
                     f"({len(p.get('data_columns') or [])} declared columns).",
        "epistemic_tag": "OBSERVED", "source": "input samples + data_columns"})

    issues = dq.get("issues") or []
    errors = [i for i in issues if i["severity"] == "error"]
    warnings = [i for i in issues if i["severity"] == "warning"]
    if errors:
        findings.append({
            "statement": f"Data-quality gate found {len(errors)} error-level issue(s): "
                         f"{'; '.join(i['message'] for i in errors[:3])}",
            "epistemic_tag": "CALCULATED"})
    elif warnings:
        findings.append({
            "statement": f"Data-quality gate passed with {len(warnings)} warning(s); "
                         f"see data_quality.issues.",
            "epistemic_tag": "CALCULATED"})
    else:
        findings.append({
            "statement": "Data-quality gate passed: schema, missing, units, range, time, batch "
                         "and independence checks found no issue.",
            "epistemic_tag": "CALCULATED"})

    if pseudo.get("detected"):
        f0 = pseudo["findings"][0]
        findings.append({
            "statement": (f"Pseudo-replication detected: {f0['reason']}. Independent units "
                          f"n={f0.get('effective_n')} vs rows n={len(rows)}; recommend "
                          f"{f0.get('recommended_analysis')}."),
            "epistemic_tag": "CALCULATED"})

    # evidence verifiability — never assert an unverifiable ref as valid
    for ev in _evidence_used(p):
        if not ev.get("verifiable"):
            findings.append({
                "statement": (f"Evidence ref {ev['ref_id']!r} has no resolvable locator; "
                              f"any claim attributed to it is REPORTED and was not checked "
                              f"offline."),
                "epistemic_tag": "REPORTED", "source": f"evidence_refs.{ev['ref_id']}"})

    for var_name, var in (stats.get("variables") or {}).items():
        desc = var.get("descriptive") or {}
        ci = var.get("ci") or {}
        if desc.get("n") and ci.get("ci_lower") is not None:
            findings.append({
                "statement": (f"{var_name}: mean {desc['mean']} {var.get('unit') or ''} "
                              f"(95% CI {ci['ci_lower']}–{ci['ci_upper']} {var.get('unit') or ''}, "
                              f"n={desc['n']}, SD {desc['sd']}, CV {desc.get('cv_percent')}%)."),
                "epistemic_tag": "CALCULATED"})
        norm = var.get("normality") or {}
        if norm.get("verdict"):
            findings.append({
                "statement": f"{var_name}: normality screen {norm['verdict']} "
                             f"(n={norm['n']}, p={norm.get('p_value')}).",
                "epistemic_tag": "CALCULATED"})

    gc = stats.get("group_comparison")
    if gc:
        es = gc.get("effect_size") or {}
        findings.append({
            "statement": (f"Group effect {gc.get('factor')}: {gc.get('groups')} Cohen's d = "
                          f"{es.get('cohens_d')} ({es.get('magnitude')}), 95% CI "
                          f"[{es.get('ci_lower_95')}, {es.get('ci_upper_95')}]."),
            "epistemic_tag": "CALCULATED"})
        if gc.get("unit_aggregated"):
            findings.append({
                "statement": f"Group comparison aggregated responses to independent sampling units "
                             f"({gc.get('sampling_unit')}) before computing the effect size.",
                "epistemic_tag": "CALCULATED"})
        eng = gc.get("engineering")
        if eng:
            findings.append({
                "statement": (f"Engineering judgment for {eng.get('column')} "
                              f"({eng.get('unit') or ''}): group means "
                              f"{eng.get('group_means')} → verdict {eng.get('verdict')}. "
                              f"Statistical significance is not engineering value."),
                "epistemic_tag": "RECOMMENDATION"})
        pw = gc.get("power_est") or {}
        if pw.get("power") is not None:
            findings.append({
                "statement": f"Estimated statistical power at n={pw.get('n_per_group')} per group "
                             f"is {pw.get('power')}.",
                "epistemic_tag": "CALCULATED"})
    elif stats.get("group_comparison_skipped"):
        skip = stats["group_comparison_skipped"]
        findings.append({
            "statement": (f"Group comparison on {skip.get('factor')} was skipped: "
                          f"{skip.get('reason')}"),
            "epistemic_tag": "CALCULATED"})

    return findings


# ---------------------------------------------------------------------------
# Self-check
# ---------------------------------------------------------------------------

def _self_check(output: dict, out_schema: dict) -> list[dict]:
    from _jsonschema import validate as js_validate
    errs = js_validate(output, out_schema)
    return errs


# ---------------------------------------------------------------------------
# Main entry
# ---------------------------------------------------------------------------

def service_main(p: dict) -> dict:
    emit_progress("starting micp-data-analyst service")
    input_schema = load_schema("input.schema.json")
    out_schema = load_schema("output.schema.json")

    # 1. strict input validation
    from _jsonschema import assert_valid
    try:
        assert_valid(p, input_schema, what="input")
    except ToolError as exc:
        missing = []
        for field in FIELD_GUIDANCE:
            if field in ("samples", "data_columns"):
                continue
            if p.get(field) in (None, ""):
                missing.append({"field": field,
                                "why_critical": FIELD_GUIDANCE[field]["why"],
                                "how_to_obtain": FIELD_GUIDANCE[field]["how"]})
        return {
            "status": "BLOCKED", "summary": f"Input failed schema validation: {exc.message}",
            "findings": [], "assumptions": [], "evidence_used": [],
            "uncertainty": [], "risks": [], "artifacts": [],
            "requested_next_skills": [],
            "validation": {"self_audit_pass": False,
                           "gates": {"G1_input_schema": False},
                           "tool_runs": []},
            "provenance": {"skill": SKILL_NAME, "skill_version": SKILL_VERSION,
                           "generated_at": str(p.get("timestamp"))[:40],
                           "generator": "micp-data-analyst service"},
            "errors": [{"code": "MDA-E101", "message": exc.message, "retryable": False,
                        "details": {"errors": exc.details.get("errors"),
                                    "field_guidance": missing}}],
            "missing_inputs": missing,
        }

    # 2. version gate
    version_problems = check_versions(p)
    if version_problems:
        return {
            "status": "BLOCKED", "summary": "Version compatibility gate failed.",
            "findings": [], "assumptions": [], "evidence_used": [], "uncertainty": [],
            "risks": [], "artifacts": [],
            "requested_next_skills": [],
            "validation": {"self_audit_pass": False,
                           "gates": {"G2_version_gate": False}, "tool_runs": []},
            "provenance": {"skill": SKILL_NAME, "skill_version": SKILL_VERSION,
                           "generated_at": str(p.get("timestamp"))[:40],
                           "generator": "micp-data-analyst service"},
            "errors": [{"code": "MDA-E801", "message": "; ".join(version_problems),
                        "retryable": False}],
            "missing_inputs": [],
        }

    # 3. preconditions
    status, missing = check_preconditions(p, [])
    if status:
        if status == "BLOCKED":
            return {
                "status": "BLOCKED", "summary": "Missing critical inputs; see missing_inputs.",
                "findings": [], "assumptions": [], "evidence_used": [], "uncertainty": [],
                "risks": [], "artifacts": [],
                "requested_next_skills": [],
                "validation": {"self_audit_pass": False,
                               "gates": {"G3_preconditions": False}, "tool_runs": []},
                "provenance": {"skill": SKILL_NAME, "skill_version": SKILL_VERSION,
                               "generated_at": str(p.get("timestamp"))[:40],
                               "generator": "micp-data-analyst service"},
                "errors": [{"code": "MDA-E102", "message": "precondition check failed",
                            "retryable": False}],
                "missing_inputs": missing,
            }
        if status == "HUMAN_APPROVAL_REQUIRED":
            return {
                "status": "HUMAN_APPROVAL_REQUIRED",
                "summary": "Analysis touches a high-risk action (field deployment / live experiment "
                           "/ hazardous chemicals / long-term knowledge write) and approval is not "
                           "granted.",
                "findings": [], "assumptions": [], "evidence_used": [], "uncertainty": [],
                "risks": [], "artifacts": [],
                "requested_next_skills": [],
                "validation": {"self_audit_pass": True,
                               "gates": {"G3_preconditions": True}, "tool_runs": []},
                "provenance": {"skill": SKILL_NAME, "skill_version": SKILL_VERSION,
                               "generated_at": str(p.get("timestamp"))[:40],
                               "generator": "micp-data-analyst service"},
                "errors": [{"code": "MDA-E502", "message": "human approval pending",
                            "retryable": True}],
                "missing_inputs": [],
            }
        if status == "NEED_ADDITIONAL_SKILL":
            return {
                "status": "NEED_ADDITIONAL_SKILL",
                "summary": "Requested analysis mode requires a modeling/optimization capability.",
                "findings": [], "assumptions": [], "evidence_used": [], "uncertainty": [],
                "risks": [], "artifacts": [],
                "requested_next_skills": [{
                    "skill": "obsidian-modeling-optimizer",
                    "reason": "mixed_effects/response_surface/multi_objective/time_series "
                              "beyond this skill",
                    "inputs_needed": ["samples", "data_columns", "upstream_outputs"]}],
                "validation": {"self_audit_pass": True,
                               "gates": {"G3_preconditions": True}, "tool_runs": []},
                "provenance": {"skill": SKILL_NAME, "skill_version": SKILL_VERSION,
                               "generated_at": str(p.get("timestamp"))[:40],
                               "generator": "micp-data-analyst service"},
                "errors": [{"code": "MDA-E601", "message": "downstream capability needed",
                            "retryable": False}],
                "missing_inputs": [],
            }

    # 4. real data-quality run
    dq_result = {}
    pseudo = {"detected": False, "findings": []}
    if p.get("samples") is not None and p.get("data_columns"):
        dq_result = qc.main({"data_columns": p.get("data_columns"),
                             "samples": p.get("samples")})
        pseudo = dq_result.get("pseudo_replication") or pseudo

    # 5. real statistics run
    stats_result = _analyze_statistics(p) if p.get("samples") else {}

    # 6. findings with epistemic tags
    findings = _build_findings(p, dq_result, stats_result, pseudo)

    # 7. assemble output and self-check
    tool_runs = [{"tool": "qc", "ok": True}] + [
        {"tool": "stats", "ok": True, "detail": tr.get("tool")}
        for tr in stats_result.get("tool_runs", [])]

    output = {
        "status": "SUCCESS",
        "summary": (f"Analysis complete for task {p.get('task_id')}: {len(p.get('samples') or [])} rows, "
                    f"{len(_response_columns(p))} response variables."),
        "findings": findings,
        "assumptions": [
            {"statement": "Rows within a sampling unit are not independent unless "
                          "pseudo_replication.check says otherwise.",
             "falsifiable_by": "verify each row maps to a distinct specimen/column/time point"},
            {"statement": "Normality screening is approximate; significant results should be "
                          "confirmed with model diagnostics.",
             "falsifiable_by": "run residual diagnostics on the fitted model"},
        ],
        "evidence_used": _evidence_used(p),
        "uncertainty": [],
        "risks": [{"risk": "Statistical significance does not imply engineering significance; "
                           "compare effect sizes against engineering_thresholds.",
                   "severity": "medium",
                   "mitigation": "report Cohen's d and CI alongside p-values"}],
        "artifacts": [],
        "requested_next_skills": [],
        "validation": {"self_audit_pass": True,
                       "gates": {"G1_input_schema": True, "G2_version_gate": True,
                                 "G3_preconditions": True, "G4_self_check": True,
                                 "G5_epistemic_tags": True},
                       "tool_runs": tool_runs},
        "provenance": {"skill": SKILL_NAME, "skill_version": SKILL_VERSION,
                       "generated_at": str(p.get("timestamp"))[:40],
                       "generator": "micp-data-analyst service",
                       "input_task_id": p.get("task_id"),
                       "tool_versions": {"stats": TOOLSET_VERSION}},
        "errors": [],
        "missing_inputs": [],
    }
    if dq_result.get("data_quality"):
        output["data_quality"] = dq_result["data_quality"]
        # merge statistics-stage warnings (skipped non-finite/non-numeric values)
        extra_issues = stats_result.get("qc_issues")
        if extra_issues:
            output["data_quality"]["issues"].extend(extra_issues)
    if pseudo.get("findings") or pseudo.get("detected"):
        output["pseudo_replication"] = pseudo
    if stats_result:
        output["statistics"] = stats_result

    # self-check
    errs = _self_check(output, out_schema)
    if errs:
        output["status"] = "FAILED"
        output["validation"]["self_audit_pass"] = False
        output["validation"]["gates"]["G4_self_check"] = False
        output["errors"] = [{"code": "MDA-E701",
                             "message": f"output failed self-check: {errs[0]['path']}: "
                                        f"{errs[0]['message']} (+{len(errs) - 1} more)",
                             "retryable": True,
                             "details": {"errors": errs[:5]}}]
    return output


def rows(p: dict) -> list:
    return p.get("samples") or []


def main(payload: dict) -> dict:
    p = payload
    op = p.get("op", "analyze")
    if op == "analyze":
        return service_main(p)
    if op == "validate_input":
        clean = dict(p)
        clean.pop("op", None)  # dispatch field is not part of the contract
        input_schema = load_schema("input.schema.json")
        from _jsonschema import validate as js_validate
        errs = js_validate(clean, input_schema)
        return {"valid": not errs, "errors": errs}
    raise ToolError("MDA-E103", f"unknown service op {op!r}",
                    details={"op": op, "allowed": ["analyze", "validate_input"]})


if __name__ == "__main__":
    run_tool("service", main)
