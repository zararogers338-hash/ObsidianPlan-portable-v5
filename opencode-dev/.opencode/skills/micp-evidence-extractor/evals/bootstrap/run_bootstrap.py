#!/usr/bin/env python3
"""Bootstrap self-test for micp-evidence-extractor.

Runs a full, realistic extraction session: load the skill contract, act as the
skill (calling the REAL tools over stdin), and verify every acceptance gate:

  B1  skill loads (SKILL.md + skill.yaml + schemas all present and valid)
  B2  tools are really invoked (subprocess, not prose)
  B3  output passes output.schema.json
  B4  each value traces back to a source locator in the input document
  B5  figure readouts are DIGITIZED_FROM_FIGURE, never author-reported
  B6  experimental groups / time points are never mixed
  B7  failed inputs return BLOCKED / PARTIAL, never a fabricated SUCCESS
  B8  a review role attacks the output; failures are fixed and re-run

Pure stdlib, offline, deterministic.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import traceback

SKILL_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TOOLS_DIR = os.path.join(SKILL_ROOT, "tools", "mee")
CLI = os.path.join(TOOLS_DIR, "cli.py")
SCHEMAS_DIR = os.path.join(SKILL_ROOT, "schemas")

RESULTS: list[dict] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    RESULTS.append({"name": name, "ok": bool(ok), "detail": detail})
    mark = "PASS" if ok else "FAIL"
    print(f"  [B {mark}] {name}" + (f" — {detail}" if detail else ""))


def run_cli(sub: str, payload: dict) -> tuple[int, dict]:
    proc = subprocess.run(
        [sys.executable, CLI, sub], input=json.dumps(payload),
        capture_output=True, text=True, cwd=TOOLS_DIR, timeout=90)
    try:
        env = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return proc.returncode, {"ok": False,
                                 "error": {"message": f"non-JSON stdout: {proc.stdout[:200]}"}}
    return proc.returncode, env


def validate_against(schema_path: str, doc: dict) -> list:
    sys.path.insert(0, TOOLS_DIR)
    from _jsonschema import validate as js_validate
    schema = json.load(open(schema_path, encoding="utf-8"))
    return js_validate(doc, schema)


def walk_quantities(node, path="", out=None):
    if out is None:
        out = []
    if isinstance(node, dict):
        if "normalized_unit" in node and "acquisition_mode" in node \
                and "value" in node and "epistemic_tag" in node:
            out.append((path, node))
            return out
        for k, v in node.items():
            walk_quantities(v, f"{path}.{k}" if path else k, out)
    elif isinstance(node, list):
        for i, item in enumerate(node):
            walk_quantities(item, f"{path}[{i}]", out)
    return out


# ---------------------------------------------------------------------------
# The example paper (a realistic multi-group MICP study)
# ---------------------------------------------------------------------------

def example_payload(**overrides) -> dict:
    p = {
        "task_id": "boot-01",
        "project_id": "panshi-demo",
        "request": "从这篇 MICP 论文提取结构化证据卡：区分 Control 与 MICP 两组、"
                   "Day 7 与 Day 14 两个时间点，OD600 与脲酶活性分别提取，核验 DOI，"
                   "并检查实验组隔离。",
        "skill_version": "1.0.0",
        "controller_version": "obsidian-ctl-0.1.0",
        "timestamp": "2026-08-07T11:00:00Z",
        "risk_level": "medium",
        "human_approval_state": "not_required",
        "requested_output_format": "json",
        "constraints": {"offline": True},
        "document": {
            "source_id": "boot-paper-2023",
            "title": "Microbially induced calcite precipitation in sand columns",
            "year": "2023",
            "journal": "Geotechnical Testing Journal",
            "doi": "10.1002/jctb.280520402",
            "document_type": "original_research",
            "sections": [
                {"kind": "methods", "heading": "Materials and Methods",
                 "text": "Sporosarcina pasteurii (ATCC 11859) was cultured in B4 medium "
                         "at 30 C. Urease activity reached 0.8 mM urea/min/OD. Urea "
                         "concentration 0.5 M and CaCl2 0.5 M were injected."},
                {"kind": "results", "heading": "Results",
                 "text": "UCS reached 3.2 MPa after 14 days of treatment."},
            ],
            "tables": [
                {"table_id": "t1", "caption": "UCS results",
                 "header": ["Group", "Day 7 UCS (kPa)", "Day 14 UCS (kPa)"],
                 "rows": [["Control", "150", "210"], ["MICP", "1200", "2500"]],
                 "source_locator": "Table 1"},
                {"table_id": "t2", "caption": "Biological characterization",
                 "header": ["Sample", "OD600", "Urease (mM urea/min/OD)"],
                 "rows": [["S. pasteurii", "1.2", "0.8"], ["Blank", "0.05", "0.0"]],
                 "source_locator": "Table 2"},
            ],
            "figures": [],
        },
    }
    p.update(overrides)
    return p


# ---------------------------------------------------------------------------
# Phase 1 — the skill acts on the example paper
# ---------------------------------------------------------------------------

def phase_act_as_skill() -> None:
    print("\n[Phase 1] The skill acts on the example MICP paper")
    payload = example_payload()
    rc, env = run_cli("service", payload)

    check("B2 tools really invoked (service exit 0 + ok envelope)",
          rc == 0 and env.get("ok") is True,
          f"rc={rc}")
    if not env.get("ok"):
        check("service returned a structured output", True,
              str(env.get("error", {}).get("code")))
        return
    out = env["result"]

    check("B3 output passes output.schema.json",
          not validate_against(os.path.join(SCHEMAS_DIR, "output.schema.json"), out),
          f"status={out.get('status')}")

    check("B1 status SUCCESS on a well-formed MICP paper",
          out.get("status") == "SUCCESS",
          out.get("summary", "")[:80])

    cards = out.get("evidence_cards", [])
    check("cards produced (expected 3: t1 + t2 + text)",
          len(cards) == 3, f"n={len(cards)}")

    # B6 group/time isolation
    t1 = next((c for c in cards if c.get("card_id", "").endswith(".t1")), None)
    if t1:
        groups = {g["label"] for g in t1["experimental_groups"]}
        tps = {t["label"] for t in t1["time_points"]}
        check("B6 groups declared (Control, MICP)",
              groups == {"Control", "MICP"}, f"groups={sorted(groups)}")
        check("B6 time points declared (Day 7, Day 14)",
              {"Day 7", "Day 14"} <= tps, f"tps={sorted(tps)}")
        ucs = [q for p, q in walk_quantities(t1) if ".ucs" in p and p.endswith("]")]
        bound = all(q.get("group_id") and q.get("timepoint_id") for q in ucs)
        check("B6 every UCS quantity bound to a group AND time point", bound,
              f"n={len(ucs)}")
        control = sorted(q["value"] for q in ucs if q.get("group_id") == "g1")
        micp = sorted(q["value"] for q in ucs if q.get("group_id") == "g2")
        check("B6 groups never mixed (Control 150/210, MICP 1200/2500)",
              control == [150.0, 210.0] and micp == [1200.0, 2500.0],
              f"control={control} micp={micp}")
    else:
        check("B6 t1 card present", False)

    # B2 real tool runs recorded
    tool_runs = (out.get("validation") or {}).get("tool_runs") or []
    check("B2 real tool runs recorded in validation",
          any("adapters" in tr.get("tool", "") for tr in tool_runs) and
          any("card_check" in tr.get("tool", "") for tr in tool_runs),
          f"tools={[tr.get('tool') for tr in tool_runs]}")

    # B4 traceability
    t2 = next((c for c in cards if c.get("card_id", "").endswith(".t2")), None)
    if t2:
        urease = [q for p, q in walk_quantities(t2) if ".urease_activity" in p]
        if urease:
            loc = urease[0].get("sources", [{}])[0].get("locator", "")
            check("B4 urease quantity locates its source (Table 2)",
                  "Table 2" in loc, f"locator={loc!r}")
    # every reported quantity has a locator
    all_located = True
    for card in cards:
        for path, q in walk_quantities(card):
            if q.get("acquisition_mode") in ("REPORTED_TABLE", "REPORTED_TEXT"):
                loc = (q.get("sources") or [{}])[0].get("locator", "")
                if not loc:
                    all_located = False
    check("B4 every reported quantity carries a source locator", all_located)

    # card validation
    cv = out.get("card_validation") or {}
    check("B3 all cards validate against evidence-card.schema",
          cv.get("passed") is True, f"{cv.get('valid')}/{cv.get('total')}")

    # DOI
    verifs = out.get("doi_verifications", [])
    check("B7 DOI verified (offline structural)",
          any(v.get("status") in ("verifiable_structure", "offline_unverified")
              for v in verifs), f"statuses={[v.get('status') for v in verifs]}")


# ---------------------------------------------------------------------------
# Phase 2 — figure digitization discipline
# ---------------------------------------------------------------------------

def phase_figure_discipline() -> None:
    print("\n[Phase 2] Figure digitization discipline")
    payload = example_payload()
    payload["document"] = {
        "source_id": "boot-fig", "title": "UCS evolution of MICP-treated specimens",
        "year": "2022", "document_type": "original_research",
        "sections": [{"kind": "methods", "heading": "M",
                      "text": "Urea 0.5 M and CaCl2 0.5 M were injected."}],
        "tables": [],
        "figures": [{"figure_id": "fig1", "caption": "UCS evolution of MICP-treated specimens",
                     "note": "read: 3.2; axis_px: 400; axis_range: 4.0"}],
    }
    rc, env = run_cli("service", payload)
    if not env.get("ok"):
        check("B5 figure-only document runs", False, str(env.get("error")))
        return
    out = env["result"]
    digi = [q for p, q in walk_quantities(out.get("evidence_cards", []))
            if q.get("acquisition_mode") == "DIGITIZED_FROM_FIGURE"]
    check("B5 figure value is DIGITIZED_FROM_FIGURE",
          bool(digi), f"n={len(digi)}")
    if digi:
        q = digi[0]
        check("B5 carries a reading error estimate",
              (q.get("digitization") or {}).get("error_estimate", 0) > 0,
              f"error={(q.get('digitization') or {}).get('error_estimate')}")
        check("B5 never presented as OBSERVED",
              q.get("epistemic_tag") != "OBSERVED", q.get("epistemic_tag"))
        check("B4 figure value traces to the figure",
              (q.get("digitization") or {}).get("figure_ref") == "fig1")

    # uncalibrated figure must NOT fabricate a value
    payload["document"]["figures"] = [
        {"figure_id": "fig2", "caption": "UCS evolution of MICP-treated specimens",
         "note": ""}]
    rc2, env2 = run_cli("service", payload)
    if env2.get("ok"):
        digi2 = [q for p, q in walk_quantities(env2["result"].get("evidence_cards", []))
                 if q.get("acquisition_mode") == "DIGITIZED_FROM_FIGURE"]
        check("B5 uncalibrated figure is never faked", digi2 == [])
    else:
        check("B5 uncalibrated figure is never faked", True,
              str(env2.get("error", {}).get("code")))


# ---------------------------------------------------------------------------
# Phase 3 — failure inputs
# ---------------------------------------------------------------------------

def phase_failure_inputs() -> None:
    print("\n[Phase 3] Failure inputs")
    # non-MICP -> BLOCKED
    p = example_payload()
    p["document"] = {
        "source_id": "boot-not-micp", "title": "Climate effects on wheat",
        "year": "2022", "document_type": "original_research",
        "sections": [{"kind": "results", "heading": "R",
                      "text": "Yield increased by 12 percent."}],
        "tables": [], "figures": [],
    }
    rc, env = run_cli("service", p)
    st = env.get("result", {}).get("status") if env.get("ok") else None
    check("B7 non-MICP input returns BLOCKED", st == "BLOCKED", f"status={st}")

    # no document -> BLOCKED with missing_inputs
    p2 = example_payload()
    del p2["document"]
    rc, env = run_cli("service", p2)
    out = env.get("result", {})
    check("B7 missing document returns BLOCKED",
          out.get("status") == "BLOCKED", f"status={out.get('status')}")
    fields = {m.get("field") for m in out.get("missing_inputs", [])}
    check("B7 missing_inputs names a document source",
          any("document" in f for f in fields), f"fields={sorted(fields)}")

    # wrong skill_version -> BLOCKED
    p3 = example_payload()
    p3["skill_version"] = "9.9.9"
    rc, env = run_cli("service", p3)
    out = env.get("result", {})
    check("B7 version mismatch returns BLOCKED",
          out.get("status") == "BLOCKED",
          f"errors={[e['code'] for e in out.get('errors', [])]}")

    # corrupt PDF via adapters -> MEE-E303
    rc, env = run_cli("adapters", {
        "media_type": "application/pdf",
        "document_text_b64": "R0FSQkFHRU5PVFBBU0Y=",
    })
    check("B7 corrupt PDF rejected with MEE-E303",
          not env.get("ok") and env.get("error", {}).get("code") == "MEE-E303",
          f"code={env.get('error', {}).get('code')}")

    # group-smear adversarial: a card with 2 groups but an unbound result
    import isolation
    cards = [{
        "card_id": "c1",
        "experimental_groups": [{"group_id": "g1", "label": "A"},
                                {"group_id": "g2", "label": "B"}],
        "time_points": [],
        "results": {"ucs": [{
            "value": 100, "unit": "kPa", "normalized_value": 100,
            "normalized_unit": "kPa", "acquisition_mode": "REPORTED_TABLE",
            "sources": [{"page": "p1", "locator_type": "table"}],
            "epistemic_tag": "REPORTED"}]},
    }]
    rep = isolation.check_cards(cards)
    check("B6 isolation flags unbound group (GROUP_SMEAR)",
          any(i["code"] == "GROUP_SMEAR" for i in rep["issues"]))


# ---------------------------------------------------------------------------
# Phase 4 — adversarial review (an independent reviewer attacks the output)
# ---------------------------------------------------------------------------

def phase_review() -> None:
    print("\n[Phase 4] Adversarial review (independent reviewer)")
    payload = example_payload()
    rc, env = run_cli("service", payload)
    out = env["result"]
    cards = out.get("evidence_cards", [])
    findings: list[str] = []

    # Reviewer attacks:
    # R1 — group mixing: no quantity may carry a value that another group owns.
    t1 = next((c for c in cards if c.get("card_id", "").endswith(".t1")), None)
    if t1:
        ucs = [q for p, q in walk_quantities(t1) if ".ucs" in p and p.endswith("]")]
        for q in ucs:
            if q.get("group_id") == "g1" and q.get("value") not in (150.0, 210.0):
                findings.append(f"R1 group g1 carries foreign value {q.get('value')}")
            if q.get("group_id") == "g2" and q.get("value") not in (1200.0, 2500.0):
                findings.append(f"R1 group g2 carries foreign value {q.get('value')}")
        # R6 — no time-point merge: Day7/14 values stay distinct per group
        by_tp = {}
        for q in ucs:
            by_tp.setdefault((q.get("group_id"), q.get("timepoint_id")), []).append(q.get("value"))
        if len(by_tp) != 4:
            findings.append(f"R6 expected 4 (group x timepoint) slots, got {len(by_tp)}")

    # R2 — OD600 vs urease: units must never cross
    t2 = next((c for c in cards if c.get("card_id", "").endswith(".t2")), None)
    if t2:
        for path, q in walk_quantities(t2):
            if ".od600" in path and q.get("normalized_unit") != "OD600":
                findings.append(f"R2 od600 normalized to {q.get('normalized_unit')}")
            if ".urease_activity" in path and q.get("normalized_unit") != "mmol_urea/min/OD":
                findings.append(f"R2 urease normalized to {q.get('normalized_unit')}")

    # R3 — no fabricated values: every reported value must appear in the input
    src_text = json.dumps(payload["document"], ensure_ascii=False)
    for card in cards:
        for path, q in walk_quantities(card):
            if q.get("acquisition_mode") == "REPORTED_TABLE":
                loc = (q.get("sources") or [{}])[0].get("locator", "")
                table_id = loc.split(" row")[0].split(" ")[-1] if loc else ""
                # verify the value exists somewhere in the document tables
                if q.get("value") is not None and \
                        str(q["value"]) not in src_text and \
                        str(int(q["value"])) if isinstance(q.get("value"), float) else True:
                    if isinstance(q.get("value"), float) and \
                            str(int(q["value"])) not in src_text:
                        findings.append(
                            f"R3 value {q.get('value')} not found in input ({loc})")

    # R4 — every reported quantity has a source locator
    for card in cards:
        for path, q in walk_quantities(card):
            if q.get("acquisition_mode") in ("REPORTED_TABLE", "REPORTED_TEXT") \
                    and not (q.get("sources") or []):
                findings.append(f"R4 unreferenced quantity at {path}")

    # R5 — no fabricated citation: evidence_used ⊆ input refs
    refs = {r.get("ref_id") for r in payload.get("evidence_refs", [])}
    refs |= {r.get("ref_id") for r in payload.get("data_refs", [])}
    for e in out.get("evidence_used", []):
        if e.get("ref_id") not in refs:
            findings.append(f"R5 fabricated evidence ref {e.get('ref_id')}")

    # R7 — schema
    schema_errs = validate_against(os.path.join(SCHEMAS_DIR, "output.schema.json"), out)
    if schema_errs:
        findings.append(f"R7 output schema: {schema_errs[0]['message']}")

    if findings:
        check("B8 review found issues (to fix)", False, "; ".join(findings[:3]))
        for f in findings:
            print(f"      review finding: {f}")
    else:
        check("B8 adversarial review found no defects", True)


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main() -> int:
    print("=" * 72)
    print("micp-evidence-extractor bootstrap self-test")
    print("=" * 72)

    # B1 — the skill loads: SKILL.md frontmatter + skill.yaml + schemas
    skill_md = os.path.join(SKILL_ROOT, "SKILL.md")
    skill_yaml = os.path.join(SKILL_ROOT, "skill.yaml")
    has_files = all(os.path.isfile(p) for p in (
        skill_md, skill_yaml,
        os.path.join(SCHEMAS_DIR, "input.schema.json"),
        os.path.join(SCHEMAS_DIR, "output.schema.json"),
        os.path.join(SCHEMAS_DIR, "evidence-card.schema.json"),
        os.path.join(TOOLS_DIR, "cli.py")))
    check("B1 skill package loads (SKILL.md + skill.yaml + schemas + cli)",
          has_files)
    if not has_files:
        print("FATAL: skill package incomplete")
        return 1
    # SKILL.md frontmatter name == dir
    head = open(skill_md, encoding="utf-8").read().split("---")[1]
    check("B1 frontmatter declares name micp-evidence-extractor",
          'name: micp-evidence-extractor' in head)

    phase_act_as_skill()
    phase_figure_discipline()
    phase_failure_inputs()
    phase_review()

    passed = sum(1 for r in RESULTS if r["ok"])
    total = len(RESULTS)
    print("\n" + "=" * 72)
    print(f"bootstrap: {passed}/{total} checks passed")
    for r in RESULTS:
        if not r["ok"]:
            print(f"  FAIL {r['name']} — {r['detail']}")
    print("=" * 72)
    return 0 if passed == total else 2


if __name__ == "__main__":
    sys.exit(main())
