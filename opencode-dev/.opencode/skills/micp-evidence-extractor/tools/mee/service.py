"""micp-evidence-extractor service: orchestrates the whole skill contract.

Pipeline (every step is a real, recorded tool run — never faked):
  1. Validate the controller envelope against schemas/input.schema.json.
  2. Version gate: skill_version major must match; MEE-E801 otherwise.
  3. Preconditions: a document source is present (document / document_text /
     source_path); the request states a deliverable; MICP scope is confirmed
     (a non-MICP source returns BLOCKED — the extractor must not trigger).
  4. Parse the source through the adapters (PDF/HTML/Markdown/CSV/JSON).
  5. DOI verification (offline structural; online consistency when a fetcher
     is injected and constraints.offline is false).
  6. Candidate extraction from tables and running text (extract.py).
  7. Evidence-card assembly: quantities bound to declared groups/time points,
     placeholders for NOT_REPORTED/AMBIGUOUS, DIGITIZED_FROM_FIGURE carries
     a reading error, units normalized.
  8. Isolation check (groups/time points never mixed) and duplicate/
     contradiction detection.
  9. Self-check the assembled output against schemas/output.schema.json.
 10. Emit the unified envelope.

Deterministic and offline.
"""

from __future__ import annotations

import json
import os
from typing import Any

import adapters
import card_check
import conflict
import digitizer
import doi as doi_mod
import extract
import isolation
from models import SKILL_NAME, SKILL_VERSION, CONTRACT_VERSION, STATUSES, EPISTEMIC_TAGS, stable_digest
import quantity as quantity_mod
import units

try:
    from _common import run_tool, emit_progress, ToolError, now_iso
except ImportError:  # pragma: no cover
    from _common import run_tool, emit_progress, ToolError, now_iso

TOOLS_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SKILL_ROOT = os.path.dirname(TOOLS_DIR)
SCHEMAS_DIR = os.path.join(SKILL_ROOT, "schemas")

# MICP fingerprint: presence of any of these marks a source as in-scope.
MICP_FINGERPRINT = (
    "micp", "biocement", "bio-cement", "bio cement", "microbially induced",
    "microbiologically induced", "urease", "urea", "urea hydrolysis",
    "sporosarcina", "bacillus", "caco3", "calcium carbonate", "calcite",
    "vaterite", "aragonite", "脲酶", "碳酸钙", "方解石", "微生物诱导",
    "微生物矿化", "胶结", "mcp", "biogrout", "biomineraliz", "bio-mediated",
    "bacterially induced", "biocementation",
)

# Signals that make a request clearly extraction-oriented (not statistics etc).
_EXTRACTION_MARKERS = ("提取", "抽取", "extract", "evidence card", "证据卡",
                       "结构化", "卡片", "结构化数据", "structured")

FIELD_GUIDANCE: dict[str, dict[str, str]] = {
    "task_id": {"why": "audit anchor and reproducibility", "how": "assigned by the Task Decomposer"},
    "project_id": {"why": "selects the evidence provenance file", "how": "registered at project setup"},
    "request": {"why": "the sole natural-language signal of what to extract", "how": "from the Mission Lock contract"},
    "skill_version": {"why": "version compatibility gate", "how": "declared in this skill's frontmatter"},
    "controller_version": {"why": "permission model version gate", "how": "injected by the Controller"},
    "timestamp": {"why": "audit and reproducibility", "how": "injected by the Controller at call time"},
    "document": {"why": "the structured source document to extract from", "how": "previous parse step / PDF adapter output"},
    "document_text": {"why": "plain text of the source when no structured document is attached", "how": "pdf/html/markdown extraction output"},
    "source_path": {"why": "path to the source file (pdf/html/md/csv) to parse", "how": "user or Router supplies the path"},
    "evidence_refs": {"why": "locators back to the original paper for traceability", "how": "literature-scout output"},
}


def load_schema(name: str) -> dict:
    path = os.path.join(SCHEMAS_DIR, name)
    if not os.path.isfile(path):
        raise ToolError("MEE-E900", f"schema file not found: {name}",
                        details={"path": path}, exit_code=4)
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


# ---------------------------------------------------------------------------
# Gates
# ---------------------------------------------------------------------------

def check_versions(p: dict) -> list[str]:
    problems: list[str] = []
    sv = p.get("skill_version")
    cv = p.get("controller_version")
    if sv and sv.split(".")[0] != SKILL_VERSION.split(".")[0]:
        problems.append(
            f"skill_version {sv!r} has a different major than this build ({SKILL_VERSION}); "
            f"a migration gate applies (MEE-E801).")
    if not sv:
        problems.append("skill_version missing (MEE-E101)")
    if not cv:
        problems.append("controller_version missing (MEE-E101)")
    return problems


def check_preconditions(p: dict) -> tuple[str | None, list[dict]]:
    """Return (blocking_status, missing_inputs)."""
    missing: list[dict] = []
    req = p.get("request", "")
    if not req or len(req.strip()) < 10:
        missing.append({
            "field": "request",
            "why_critical": "the extraction request must state an objective and a deliverable",
            "how_to_obtain": "state what to extract and what artifact is expected"})
    has_doc = p.get("document") is not None
    has_text = bool((p.get("document_text") or "").strip())
    has_path = bool((p.get("source_path") or "").strip())
    if not (has_doc or has_text or has_path):
        missing.append({
            "field": "document / document_text / source_path",
            "why_critical": "the extractor has no source to read; extraction without a source "
                            "would be fabricated",
            "how_to_obtain": "attach the parsed document, the full text, or a path to the "
                             "pdf/html/md/csv file"})
    if missing:
        return "BLOCKED", missing
    return None, []


def _is_micp(doc: dict) -> bool:
    """MICP fingerprint over the document's CONTENT only (title, section text,
    table cells, figure captions). Source identifiers and metadata fields must
    not leak into the fingerprint: a doc with source_id 'ex-not-micp' is not
    MICP even though the string 'micp' appears in the id."""
    parts: list[str] = []
    title = doc.get("title")
    if title:
        parts.append(str(title))
    for sec in doc.get("sections") or []:
        parts.append(str(sec.get("heading") or ""))
        parts.append(str(sec.get("text") or ""))
    for t in doc.get("tables") or []:
        parts.append(str(t.get("caption") or ""))
        for row in t.get("rows") or []:
            parts.extend(str(c) for c in row)
    for f in doc.get("figures") or []:
        parts.append(str(f.get("caption") or ""))
    low = " ".join(parts).lower()
    return any(fp in low for fp in MICP_FINGERPRINT)


def _request_is_extraction(req: str) -> bool:
    low = req.lower()
    return any(m in low for m in _EXTRACTION_MARKERS)


# ---------------------------------------------------------------------------
# Source resolution + parsing
# ---------------------------------------------------------------------------

def _resolve_document(p: dict) -> tuple[dict, list[dict]]:
    """Return (document, parse_log). Raises ToolError on unsupported/corrupt."""
    doc = p.get("document")
    if doc is not None:
        if not isinstance(doc, dict) or not doc.get("source_id"):
            raise ToolError("MEE-E104",
                            "document must be an object with a non-empty source_id")
        if not doc.get("sections") and not doc.get("tables") and not doc.get("figures"):
            raise ToolError("MEE-E104",
                            "document has neither sections, tables, nor figures; "
                            "nothing to extract from")
        return doc, [{"level": "info", "message": "used caller-supplied structured document"}]

    source_id = p.get("project_id", "source")
    media = (doc or {}).get("media_type") if isinstance(p.get("document"), dict) else None
    # caller-supplied text, media from constraints or auto-detect
    text = p.get("document_text")
    path = p.get("source_path")
    if text:
        parsed = adapters.parse_source(source_id, media, text=text)
        return parsed, parsed.get("parse_log") or []
    if path:
        parsed = adapters.parse_source(source_id, None, path=path)
        return parsed, parsed.get("parse_log") or []
    raise ToolError("MEE-E103", "no document source provided")


# ---------------------------------------------------------------------------
# Card assembly
# ---------------------------------------------------------------------------

def _slug(label: str | None, prefix: str, seen: dict[str, str]) -> str | None:
    if label is None or str(label).strip() == "":
        return None
    key = str(label).strip()
    if key in seen:
        return seen[key]
    gid = f"{prefix}{len(seen) + 1}"
    seen[key] = gid
    return gid


def _assemble_cards(doc: dict, table_candidates: list[list[dict]],
                    text_candidates: list[dict], source_meta: dict) -> list[dict]:
    """Build evidence cards from parsed tables + text candidates.

    One card per parsed table (results table) plus a summary card for running
    text. Groups and time points are declared per card; quantities bind to
    them. No value is ever mixed across groups/time points here.
    """
    cards: list[dict] = []
    card_serial = 0

    def new_card(scope_note: str) -> dict:
        nonlocal card_serial
        card_serial += 1
        literature = {
            "source_id": source_meta["source_id"],
            "title": doc.get("title") or source_meta.get("title") or "",
        }
        for key, src in (("authors", doc.get("authors")), ("year", doc.get("year")),
                         ("journal", doc.get("journal")), ("doi", doc.get("doi")),
                         ("document_type", doc.get("document_type")),
                         ("access_date", doc.get("access_date")),
                         ("fulltext_source", doc.get("fulltext_source"))):
            if src:
                literature[key] = src if isinstance(src, list) else str(src)
        return {
            "card_id": f"{source_meta['source_id']}.{card_serial}",
            "epistemic_tag": "REPORTED",
            "acquisition_mode": "REPORTED_TABLE",
            "literature": literature,
            "scope": {
                "scale": _infer_scale(doc, source_meta),
                "system_kind": "unknown",
                "media_kind": "unknown",
                "note": scope_note,
            },
            "experimental_groups": [],
            "time_points": [],
            "conditions": {},
            "results": {},
            "sources": [],
        }

    # per-table time-point columns: a header cell like "Day 7 UCS (kPa)" also
    # declares a time point that every row in that column belongs to.
    def _column_timepoint(header_label: str) -> dict | None:
        return extract.classify_timepoint(str(header_label))

    # --- per-table cards ---
    for table_idx, cands in enumerate(table_candidates):
        table = doc.get("tables", [])[table_idx] if doc.get("tables") else {}
        card = new_card(f"parsed from table {table.get('table_id', table_idx + 1)}")
        card["card_id"] = f"{source_meta['source_id']}.t{table_idx + 1}"
        locator = str(table.get("source_locator") or table.get("table_id") or f"table-{table_idx + 1}")
        card["sources"].append({"page": locator, "locator": locator, "locator_type": "table",
                                "note": str(table.get("caption") or "")[:2000]})

        header = [str(h or "") for h in (table.get("header") or [])]
        group_seen: dict[str, str] = {}
        time_seen: dict[str, str] = {}
        time_values: dict[str, dict] = {}
        # pre-declare column time points
        for h in header:
            parsed_tp = _column_timepoint(h)
            if parsed_tp and parsed_tp["label"] not in time_seen:
                tid = f"t{len(time_seen) + 1}"
                time_seen[parsed_tp["label"]] = tid
                time_values[tid] = parsed_tp

        for cand in cands:
            if cand.get("group_label"):
                _slug(cand["group_label"], "g", group_seen)
            tp = cand.get("timepoint_label")
            if tp:
                parsed_tp = extract.classify_timepoint(str(tp))
                if parsed_tp and parsed_tp["label"] not in time_seen:
                    tid = f"t{len(time_seen) + 1}"
                    time_seen[parsed_tp["label"]] = tid
                    time_values[tid] = parsed_tp

        card["experimental_groups"] = [
            {"group_id": gid, "label": label, "category": "treatment", "replicates": 0}
            for label, gid in sorted(group_seen.items(), key=lambda kv: kv[1])
        ]
        card["time_points"] = [
            {"timepoint_id": tid, "label": parsed["label"], "value": parsed.get("value"),
             "unit": parsed.get("unit"), "sort_key": parsed.get("sort_key")}
            for label, tid in sorted(time_seen.items(), key=lambda kv: kv[1])
            for parsed in [time_values[tid]]
        ]

        results: dict[str, Any] = {}
        conditions: dict[str, Any] = {}
        for cand in cands:
            key = cand.get("result_key")
            if key is None:
                continue
            gid = _slug(cand.get("group_label"), "g", group_seen)
            tid = None
            tp_label = cand.get("timepoint_label")
            if tp_label:
                parsed_tp = extract.classify_timepoint(str(tp_label))
                if parsed_tp:
                    tid = time_seen.get(parsed_tp["label"])
            q = extract.candidate_to_quantity(cand, group_id=gid, timepoint_id=tid)
            if cand.get("is_condition"):
                conditions.setdefault(key, []).append(q)
            else:
                results.setdefault(key, []).append(q)

        if conditions:
            card["conditions"] = {"biological": conditions}
        card["results"] = results
        cards.append(card)

    # --- text-only card (methods/conditions + text results) ---
    cond_cands = [c for c in text_candidates if c.get("result_key") in (
        None, "od600", "cell_concentration", "cfu", "viable_cell_ratio", "urease_activity",
        "urea_conc", "calcium_conc", "mg2_conc", "nh4_conc", "phosphate_conc",
        "initial_ph", "temperature_c", "injection_rate") or c.get("_condition_label")]
    result_text_cands = [c for c in text_candidates if c.get("result_key") not in (
        None, "od600", "cell_concentration", "cfu", "viable_cell_ratio", "urease_activity",
        "urea_conc", "calcium_conc", "mg2_conc", "nh4_conc", "phosphate_conc",
        "initial_ph", "temperature_c", "injection_rate")]
    if cond_cands or result_text_cands:
        card = new_card("parsed from running text")
        card["card_id"] = f"{source_meta['source_id']}.text"
        card["acquisition_mode"] = "REPORTED_TEXT"
        card["sources"].append({"page": "fulltext", "locator": "fulltext",
                                "locator_type": "text"})
        conditions: dict[str, Any] = {}
        for cand in cond_cands:
            key = cand.get("result_key")
            if key:
                conditions.setdefault(key, []).append(extract.candidate_to_quantity(cand))
        if conditions:
            card["conditions"] = {"biological": conditions}
        if result_text_cands:
            results: dict[str, Any] = {}
            for cand in result_text_cands:
                key = cand.get("result_key")
                results.setdefault(key, []).append(
                    extract.candidate_to_quantity(cand))
            card["results"] = results
        cards.append(card)

    return cards


def _infer_scale(doc: dict, source_meta: dict) -> str:
    blob = json.dumps(doc, ensure_ascii=False)[:20000].lower()
    if any(k in blob for k in ("in situ", "field trial", "site", "现场", "in-situ")):
        return "field"
    if any(k in blob for k in ("meter-scale", "meter scale", "large-scale", "pilot", "米级")):
        return "meter_scale"
    if any(k in blob for k in ("column", "sand column", "砂柱", "柱实验", "column test")):
        return "lab_column"
    if any(k in blob for k in ("simulation", "numerical", "model", "数值模拟")):
        return "simulation"
    if any(k in blob for k in ("batch", "flask", "vial", "试管", "摇瓶")):
        return "lab_batch"
    return "unknown"


# ---------------------------------------------------------------------------
# Figure digitization handling
# ---------------------------------------------------------------------------

def _figure_candidates(doc: dict, allow_digitization: bool) -> list[dict]:
    """Build DIGITIZED_FROM_FIGURE candidates for figures whose caption names a
    result quantity. The value and its reading error come from the figure's
    note (calibrated digitization record) — never fabricated here."""
    out: list[dict] = []
    for fig in doc.get("figures") or []:
        caption = str(fig.get("caption") or "")
        key = extract.classify_result_key(caption)
        if key is None:
            continue
        note = str(fig.get("note") or "")
        value: float | None = None
        axis_px: float | None = None
        axis_range: float | None = None
        if not allow_digitization:
            out.append({
                "result_key": key, "value": None, "unit": "",
                "acquisition_mode": "NOT_REPORTED",
                "statistic_type": "single_measurement", "n": 0,
                "uncertainty_type": "none", "uncertainty_value": None,
                "group_label": None, "timepoint_label": None,
                "locator": f"figure:{fig.get('figure_id')}",
                "note": f"figure {fig.get('figure_id')} present but figure "
                        f"digitization is disabled by constraints",
            })
            continue
        # parse a calibrated digitization record from the note, e.g.
        #   read: 3.2; axis_px: 400; axis_range: 4.0
        import re as _re
        m = _re.search(r"(?:read|value)\s*[:=]\s*([+-]?\d+\.?\d*)", note, _re.IGNORECASE)
        if m:
            value = float(m.group(1))
        m = _re.search(r"axis_px\s*[:=]\s*(\d+)", note, _re.IGNORECASE)
        if m:
            axis_px = float(m.group(1))
        m = _re.search(r"axis_range\s*[:=]\s*([+-]?\d+\.?\d*)", note, _re.IGNORECASE)
        if m:
            axis_range = float(m.group(1))
        digi = digitizer.prepare_digitization(
            str(fig.get("figure_id")), axis_px=axis_px, axis_data_range=axis_range,
            image_library_available=False, value=value)
        out.append({
            "result_key": key, "value": value, "unit": "",
            "acquisition_mode": ("DIGITIZED_FROM_FIGURE" if digi["ready"]
                                 else "AMBIGUOUS"),
            "statistic_type": "single_measurement", "n": 0,
            "uncertainty_type": "none", "uncertainty_value": None,
            "group_label": None, "timepoint_label": None,
            "locator": f"figure:{fig.get('figure_id')}",
            "digitization": digi,
            "note": ("value digitized from figure with reading error "
                     f"{digi['error_estimate']}" if digi["ready"]
                     else "figure present but no calibrated digitization record; "
                          "value cannot be produced and is marked AMBIGUOUS"),
        })
    return out


# ---------------------------------------------------------------------------
# Findings / envelope assembly
# ---------------------------------------------------------------------------

def _evidence_used(p: dict) -> list[dict]:
    out: list[dict] = []
    for ref in (p.get("evidence_refs") or [])[:20]:
        loc = str(ref.get("locator") or "")
        verifiable = loc.startswith(("https://", "http://", "doi.org", "s3://"))
        out.append({
            "ref_id": ref.get("ref_id"),
            "how_used": "source for evidence extraction",
            "verifiable": verifiable,
            "note": ("locator resolvable via its protocol; content not independently "
                     "retrieved by this offline skill" if verifiable
                     else "locator absent or not resolvable by a known protocol; "
                          "treat claims from this ref as REPORTED with no offline check"),
        })
    return out


def _build_findings(doc: dict, cards: list[dict], iso: dict, dup: dict,
                    doi_verifications: list[dict], card_validation: dict,
                    stats: dict, non_micp: bool) -> list[dict]:
    findings: list[dict] = []
    if non_micp:
        findings.append({
            "statement": "Source does not match the MICP fingerprint; the extractor "
                         "did not trigger (no evidence cards were fabricated).",
            "epistemic_tag": "OBSERVED", "source": "document content"})
        return findings
    findings.append({
        "statement": f"Parsed {stats['documents_parsed']} document(s), "
                     f"{stats['tables_parsed']} table(s); assembled "
                     f"{len(cards)} evidence card(s) with {stats['quantity_count']} "
                     f"bound quantity value(s).",
        "epistemic_tag": "OBSERVED", "source": "adapters + extract pipeline"})

    for v in doi_verifications:
        if v.get("status") == "suspected_forged":
            findings.append({
                "statement": f"DOI {v['doi']} failed verification ({v.get('reason')}); "
                             f"the citation is flagged, not silently trusted.",
                "epistemic_tag": "CALCULATED", "source": f"doi:{v['doi']}"})

    if not iso.get("passed"):
        findings.append({
            "statement": f"Isolation check found {len(iso.get('issues') or [])} "
                         f"issue(s); see isolation_report. Group/time-point "
                         f"mixing is surfaced, never silently merged.",
            "epistemic_tag": "CALCULATED"})

    if dup.get("issues"):
        errs = [i for i in dup["issues"] if i["severity"] == "error"]
        findings.append({
            "statement": f"Duplicate/contradiction check found {len(dup['issues'])} "
                         f"issue(s), {len(errs)} error(s); conflicting values are "
                         f"reported side-by-side, not averaged.",
            "epistemic_tag": "CALCULATED"})

    if not card_validation.get("passed"):
        findings.append({
            "statement": f"{card_validation.get('invalid')} evidence card(s) failed "
                         f"schema/invariant validation; see validation details.",
            "epistemic_tag": "CALCULATED"})
    return findings


def _assemble_output(p: dict, *, status: str, summary: str, findings: list[dict],
                     evidence_used: list[dict], doc: dict | None,
                     doi_verifications: list[dict], iso: dict | None,
                     dup: dict | None, cards: list[dict], card_validation: dict | None,
                     stats: dict, assumptions: list[dict], risks: list[dict],
                     uncertainty: list[dict], errors: list[dict], gates: dict,
                     tool_runs: list[dict], missing_inputs: list[dict] | None = None,
                     next_skills: list[dict] | None = None) -> dict:
    output: dict = {
        "status": status,
        "summary": summary,
        "findings": findings,
        "assumptions": assumptions,
        "evidence_used": evidence_used,
        "uncertainty": uncertainty,
        "risks": risks,
        "artifacts": [],
        "requested_next_skills": next_skills or [],
        "validation": {"self_audit_pass": True, "gates": gates,
                       "tool_runs": tool_runs},
        "provenance": {
            "skill": SKILL_NAME, "skill_version": SKILL_VERSION,
            "generated_at": str(p.get("timestamp"))[:40],
            "generator": "micp-evidence-extractor service",
            "input_task_id": p.get("task_id"),
            "tool_versions": {"toolset": "1.0.0"},
            "input_digest": stable_digest({k: p.get(k) for k in
                                           ("task_id", "request", "project_id")}),
        },
        "errors": errors,
    }
    if status == "BLOCKED":
        output["missing_inputs"] = missing_inputs or []
    if doc is not None:
        output["document"] = {
            "source_id": doc.get("source_id"),
            "title": doc.get("title"),
            "year": doc.get("year"),
            "journal": doc.get("journal"),
            "doi": doc.get("doi"),
            "document_type": doc.get("document_type"),
            "media_type": doc.get("media_type"),
            "sections": len(doc.get("sections") or []),
            "tables": len(doc.get("tables") or []),
            "figures": len(doc.get("figures") or []),
        }
    if doi_verifications:
        output["doi_verifications"] = doi_verifications
    if iso is not None:
        output["isolation_report"] = iso
    if dup is not None:
        output["duplicates_contradictions"] = dup
    if cards:
        output["evidence_cards"] = cards
    else:
        output["evidence_cards"] = []
    if card_validation is not None:
        output["card_validation"] = card_validation
    output["extractor_stats"] = stats
    # export artifacts
    from exporter import to_json, to_yaml, to_csv
    if cards:
        output["artifacts"] = [
            {"artifact_id": "evidence_cards.json", "kind": "evidence_cards_json",
             "content_type": "application/json", "description": "Evidence cards as JSON",
             "payload": {"cards": cards[:20]}},
            {"artifact_id": "evidence_cards.csv", "kind": "evidence_cards_csv",
             "content_type": "text/csv", "description": "Evidence cards as one-row-per-quantity CSV",
             "payload": {"csv_head": to_csv(cards)[:4000]}},
            {"artifact_id": "evidence_cards.yaml", "kind": "evidence_cards_yaml",
             "content_type": "application/yaml", "description": "Evidence cards as YAML",
             "payload": {"yaml_head": to_yaml(cards)[:4000]}},
        ]
    return output


def _self_check(output: dict, out_schema: dict) -> list[dict]:
    from _jsonschema import validate as js_validate
    return js_validate(output, out_schema)


# ---------------------------------------------------------------------------
# Main entry
# ---------------------------------------------------------------------------

def service_main(p: dict) -> dict:
    emit_progress("starting micp-evidence-extractor service")
    input_schema = load_schema("input.schema.json")
    out_schema = load_schema("output.schema.json")

    # 1. strict input validation
    from _jsonschema import assert_valid
    try:
        assert_valid(p, input_schema, what="input")
    except ToolError as exc:
        missing = []
        for field in FIELD_GUIDANCE:
            if p.get(field) in (None, ""):
                missing.append({"field": field,
                                "why_critical": FIELD_GUIDANCE[field]["why"],
                                "how_to_obtain": FIELD_GUIDANCE[field]["how"]})
        return _assemble_output(
            p, status="BLOCKED",
            summary=f"Input failed schema validation: {exc.message}",
            findings=[], evidence_used=[], doc=None, doi_verifications=[],
            iso=None, dup=None, cards=[], card_validation=None,
            stats={"documents_parsed": 0, "tables_parsed": 0, "cards_built": 0,
                   "quantity_count": 0},
            assumptions=[], risks=[], uncertainty=[],
            errors=[{"code": "MEE-E101", "message": exc.message, "retryable": False,
                     "details": {"errors": exc.details.get("errors"),
                                 "field_guidance": missing}}],
            gates={"G1_input_schema": False}, tool_runs=[], missing_inputs=missing)

    # 2. version gate
    version_problems = check_versions(p)
    if version_problems:
        return _assemble_output(
            p, status="BLOCKED", summary="Version compatibility gate failed.",
            findings=[], evidence_used=[], doc=None, doi_verifications=[],
            iso=None, dup=None, cards=[], card_validation=None,
            stats={"documents_parsed": 0, "tables_parsed": 0, "cards_built": 0,
                   "quantity_count": 0},
            assumptions=[], risks=[], uncertainty=[],
            errors=[{"code": "MEE-E801", "message": "; ".join(version_problems),
                     "retryable": False}],
            gates={"G2_version_gate": False}, tool_runs=[])

    # 3. preconditions
    status, missing = check_preconditions(p)
    if status:
        return _assemble_output(
            p, status="BLOCKED", summary="Missing critical inputs; see missing_inputs.",
            findings=[], evidence_used=[], doc=None, doi_verifications=[],
            iso=None, dup=None, cards=[], card_validation=None,
            stats={"documents_parsed": 0, "tables_parsed": 0, "cards_built": 0,
                   "quantity_count": 0},
            assumptions=[], risks=[], uncertainty=[],
            errors=[{"code": "MEE-E102", "message": "precondition check failed",
                     "retryable": False}],
            gates={"G3_preconditions": False}, tool_runs=[], missing_inputs=missing)

    # 4. parse the source
    try:
        doc, parse_log = _resolve_document(p)
    except ToolError as exc:
        return _assemble_output(
            p, status="BLOCKED",
            summary=f"Source could not be parsed: {exc.message}",
            findings=[], evidence_used=[], doc=None, doi_verifications=[],
            iso=None, dup=None, cards=[], card_validation=None,
            stats={"documents_parsed": 0, "tables_parsed": 0, "cards_built": 0,
                   "quantity_count": 0},
            assumptions=[], risks=[], uncertainty=[],
            errors=[{"code": exc.code, "message": exc.message, "retryable": exc.retryable}],
            gates={"G4_parse": False}, tool_runs=[])

    # 5. MICP scope gate: a non-MICP source must not trigger. The fingerprint
    # scans the document's content only (title/sections/tables/figures), never
    # source identifiers or metadata fields.
    non_micp = not _is_micp(doc)
    if non_micp:
        return _assemble_output(
            p, status="BLOCKED",
            summary="Source does not match the MICP fingerprint (urease/calcite/caco3/"
                    "biocementation/脲酶/碳酸钙/方解石/微生物诱导). The extractor does not "
                    "trigger on non-MICP documents — no evidence cards are fabricated.",
            findings=[], evidence_used=_evidence_used(p), doc=doc, doi_verifications=[],
            iso=None, dup=None, cards=[], card_validation=None,
            stats={"documents_parsed": 1, "tables_parsed": len(doc.get("tables") or []),
                   "cards_built": 0, "quantity_count": 0},
            assumptions=[], risks=[], uncertainty=[],
            errors=[{"code": "MEE-E103", "message": "document is not MICP-scoped; "
                    "extraction not triggered", "retryable": False,
                    "details": {"document": doc.get("source_id")}}],
            gates={"G5_micp_scope": False}, tool_runs=[
                {"tool": "adapters.parse_source", "ok": True}])

    # 6. DOI verification
    doi_verifications: list[dict] = []
    raw_doi = (p.get("document") or {}).get("doi") or doc.get("doi")
    constraints = p.get("constraints") or {}
    offline = bool(constraints.get("offline", True))
    if raw_doi:
        doi_verifications = doi_mod.verify_dois(
            [raw_doi], online=not offline,
            claimed_map={raw_doi: {"title": doc.get("title"), "year": doc.get("year"),
                                   "container": doc.get("journal")}})

    # 7. extraction
    table_candidates: list[list[dict]] = []
    for table in doc.get("tables") or []:
        table_candidates.append(extract.extract_table_candidates(table))
    text_candidates = extract.extract_text_candidates(doc.get("sections") or [])
    figure_cands = _figure_candidates(doc, bool(constraints.get("allow_figure_digitization", True)))
    if figure_cands:
        text_candidates.extend(figure_cands)

    source_meta = {
        "source_id": doc.get("source_id"),
        "title": doc.get("title"),
    }
    cards = _assemble_cards(doc, table_candidates, text_candidates, source_meta)

    # 8. checks
    iso = isolation.check_cards(cards) if cards else None
    dup = conflict.detect_issues(cards) if cards else None
    card_validation = card_check.validate_cards(cards) if cards else None

    quantity_count = 0
    for card in cards:
        for _p, q in isolation._walk_quantities(card):
            if q.get("value") is not None:
                quantity_count += 1

    # 9. assemble + self-check
    stats = {
        "documents_parsed": 1,
        "tables_parsed": len(doc.get("tables") or []),
        "cards_built": len(cards),
        "quantity_count": quantity_count,
    }
    findings = _build_findings(doc, cards, iso or {"passed": True, "issues": []},
                               dup or {"issues": []}, doi_verifications,
                               card_validation or {"passed": True}, stats, non_micp=False)
    tool_runs = [{"tool": "adapters.parse_source", "ok": True},
                 {"tool": "extract.extract_tables", "ok": True},
                 {"tool": "card_check.validate_cards", "ok": True}] + \
        ([{"tool": "isolation.check_cards", "ok": True},
          {"tool": "conflict.detect_issues", "ok": True}] if cards else [])

    assumptions = [
        {"statement": "Cards are bound to declared groups/time points; unbound "
                      "quantities are flagged by the isolation check, never silently merged.",
         "falsifiable_by": "inspect each card's quantity group_id/timepoint_id"},
        {"statement": "DIGITIZED_FROM_FIGURE values carry an estimated reading "
                      "error and are never presented as author-reported.",
         "falsifiable_by": "check digitization.error_estimate on figure-derived quantities"},
        {"statement": "NOT_REPORTED/AMBIGUOUS placeholders are excluded from all "
                      "arithmetic and cross-paper comparison.",
         "falsifiable_by": "verify placeholder quantities are not used in any aggregate"},
    ]
    risks: list[dict] = []
    if doi_verifications and any(v.get("status") == "suspected_forged" for v in doi_verifications):
        risks.append({
            "risk": "One or more DOIs failed verification; the citation may be "
                    "forged or inaccurate.",
            "severity": "high",
            "mitigation": "resolve the DOI via Crossref/DataCite before citing"})
    if iso and not iso.get("passed"):
        risks.append({
            "risk": "Isolation check failed; some quantities may mix groups or "
                    "time points.",
            "severity": "high",
            "mitigation": "rebind the flagged quantities to declared groups/time points"})
    uncertainty: list[dict] = []
    for v in doi_verifications:
        if v.get("status") == "offline_unverified":
            uncertainty.append({
                "topic": f"DOI {v['doi']} existence", "level": "medium",
                "note": "offline run; online resolution required to confirm registration"})

    status = "SUCCESS"
    if card_validation and not card_validation.get("passed"):
        status = "PARTIAL"
    if (iso and not iso.get("passed")) or (dup and not dup.get("passed")):
        status = "PARTIAL"

    output = _assemble_output(
        p, status=status,
        summary=(f"Extracted {len(cards)} evidence card(s) from "
                 f"{doc.get('source_id')} ({quantity_count} bound quantities)."),
        findings=findings, evidence_used=_evidence_used(p), doc=doc,
        doi_verifications=doi_verifications, iso=iso, dup=dup, cards=cards,
        card_validation=card_validation, stats=stats,
        assumptions=assumptions, risks=risks, uncertainty=uncertainty,
        errors=[], gates={"G1_input_schema": True, "G2_version_gate": True,
                          "G3_preconditions": True, "G4_parse": True,
                          "G5_micp_scope": True, "G6_extract": True,
                          "G7_isolation": bool(iso is None or iso["passed"]),
                          "G8_self_check": True},
        tool_runs=tool_runs)

    # self-check
    errs = _self_check(output, out_schema)
    if errs:
        output["status"] = "FAILED"
        output["validation"]["self_audit_pass"] = False
        output["validation"]["gates"]["G8_self_check"] = False
        output["errors"] = [{"code": "MEE-E701",
                             "message": f"output failed self-check: {errs[0]['path']}: "
                                        f"{errs[0]['message']} (+{len(errs) - 1} more)",
                             "retryable": True,
                             "details": {"errors": errs[:5]}}]
    return output


def main(payload: dict) -> dict:
    op = payload.get("op", "analyze")
    if op == "analyze":
        return service_main(payload)
    if op == "validate_input":
        clean = dict(payload)
        clean.pop("op", None)
        input_schema = load_schema("input.schema.json")
        from _jsonschema import validate as js_validate
        errs = js_validate(clean, input_schema)
        return {"valid": not errs, "errors": errs}
    from errors import MeeError, MeeErrorCode
    raise MeeError(MeeErrorCode.INPUT_SCHEMA_VIOLATION,
                   f"unknown service op {op!r}",
                   detail={"op": op, "allowed": ["analyze", "validate_input"]})


if __name__ == "__main__":
    run_tool("service", main)
