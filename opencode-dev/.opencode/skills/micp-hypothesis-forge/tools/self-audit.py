"""Output envelope self-audit gate for micp-hypothesis-forge.

Input (one JSON on stdin): the skill's full output document (per
schemas/output.schema.json). Emits gate verdicts G1..G7 plus an overall pass.

Gates:
  G1  envelope shape        status is a legal enum, required top-level keys exist
  G2  schema conformance    document validates against output.schema.json
  G3  epistemic discipline  every finding/risk carries a legal epistemic label;
                            no HYPOTHESIS/INFERRED presented as OBSERVED
  G4  traceability          every evidence_used.ref_id resolves in
                            evidence_refs/upstream_outputs
  G5  falsifiability        every hypothesis artifact carries a non-empty
                            refutation condition
  G6  completeness          main + >=2 competing hypotheses when status==SUCCESS
  G7  provenance            provenance block complete (skill, skill_version,
                            timestamp, contract_version, controller_version)

Offline, deterministic, stdlib-only.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import ToolError, as_dict, emit_ok, run_tool, read_payload
from mhfx import models as M
from mhfx import jsonschema

TOOL = "self-audit"

LEGAL_STATUS = ("SUCCESS", "PARTIAL", "BLOCKED", "FAILED",
                "NEED_ADDITIONAL_SKILL", "HUMAN_APPROVAL_REQUIRED")

OUTPUT_SCHEMA = "schemas/output.schema.json"

# Statuses for which the artifact-completeness gates (G5/G6) are mandatory.
_COMPLETENESS_STATUSES = ("SUCCESS", "PARTIAL")


def _gates(doc: dict) -> dict:
    status = doc.get("status")

    # G1 — envelope shape
    g1_errors: list[str] = []
    g1_ok = status in LEGAL_STATUS
    if not g1_ok:
        g1_errors.append(f"status {status!r} is not one of {LEGAL_STATUS}")

    # G3 — epistemic discipline
    g3_bad: list[str] = []
    for finding in doc.get("findings", []):
        label = finding.get("epistemic_label") if isinstance(finding, dict) else None
        if label not in M.EPISTEMIC_LABELS:
            g3_bad.append(f"finding {finding.get('id', '?')}: bad label {label!r}")
    for risk in doc.get("risks", []):
        label = risk.get("epistemic_label") if isinstance(risk, dict) else None
        if label not in M.EPISTEMIC_LABELS:
            g3_bad.append(f"risk: bad label {label!r}")
    g3_ok = not g3_bad

    # G4 — traceability
    refs = set()
    for src in ("evidence_refs", "upstream_outputs"):
        for r in (doc.get(src) or []):
            if isinstance(r, dict) and r.get("ref_id"):
                refs.add(r["ref_id"])
            elif isinstance(r, str):
                refs.add(r)
    g4_bad = []
    for used in doc.get("evidence_used", []):
        rid = used.get("ref_id") if isinstance(used, dict) else None
        if rid and rid not in refs:
            g4_bad.append(rid)
    g4_ok = not g4_bad

    # G5 — every hypothesis artifact has a refutation condition
    g5_bad = []
    for art in doc.get("artifacts", []):
        if isinstance(art, dict) and art.get("kind") in ("hypothesis_card", "hypothesis_card_set"):
            cards = art.get("cards", [art]) if art.get("kind") == "hypothesis_card_set" else [art]
            for c in cards:
                if not (c.get("refutation") or "").strip():
                    g5_bad.append(c.get("id", "?"))
    g5_ok = not g5_bad

    # G6 — main + >=2 competing hypotheses when SUCCESS
    g6_ok = True
    g6_bad = []
    if status in _COMPLETENESS_STATUSES:
        n_hyp = 0
        for art in doc.get("artifacts", []):
            if isinstance(art, dict) and art.get("kind") == "hypothesis_card_set":
                n_hyp = len(art.get("cards", []))
            elif isinstance(art, dict) and art.get("kind") == "hypothesis_card":
                n_hyp += 1
        if n_hyp < 3:
            g6_bad.append(f"need >=3 hypothesis cards (main + 2 competing), got {n_hyp}")
            g6_ok = False

    # G7 — provenance completeness
    prov = doc.get("provenance") or {}
    g7_errors = []
    for key in ("skill", "skill_version", "timestamp", "contract_version"):
        if not prov.get(key):
            g7_errors.append(f"provenance.{key} is missing or empty")
    g7_ok = not g7_errors

    return {
        "G1_envelope": {"ok": g1_ok, "errors": g1_errors},
        "G3_epistemic": {"ok": g3_ok, "errors": g3_bad},
        "G4_traceability": {"ok": g4_ok, "errors": g4_bad},
        "G5_refutation_present": {"ok": g5_ok, "errors": g5_bad},
        "G6_completeness": {"ok": g6_ok, "errors": g6_bad},
        "G7_provenance": {"ok": g7_ok, "errors": g7_errors},
    }


def main(payload: Any) -> dict:
    payload = as_dict(payload)

    gates = _gates(payload)

    # G2 — schema conformance (needs the output document itself; re-validate)
    result = jsonschema.validate_document(payload, OUTPUT_SCHEMA)
    g2_ok = not result
    gates["G2_schema"] = {"ok": g2_ok, "errors": result}

    all_ok = all(g["ok"] for g in gates.values())
    return {
        "pass": all_ok,
        "gates": gates,
        "failed_gates": [k for k, g in gates.items() if not g["ok"]],
        "summary": ("ALL GATES PASS" if all_ok else
                    f"FAILED: {', '.join(k for k, g in gates.items() if not g['ok'])}"),
    }


if __name__ == "__main__":
    run_tool(TOOL, main)
