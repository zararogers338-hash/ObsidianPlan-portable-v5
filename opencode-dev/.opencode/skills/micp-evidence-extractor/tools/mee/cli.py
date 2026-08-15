#!/usr/bin/env python3
"""micp-evidence-extractor unified CLI.

Reads a JSON envelope on stdin and dispatches to a sub-tool:

  python tools/mee/cli.py service    < input.json  (full extraction pipeline)
  python tools/mee/cli.py adapters   < input.json  (parse a source into a document)
  python tools/mee/cli.py doi        < input.json  (DOI verification)
  python tools/mee/cli.py units      < input.json  (unit normalization + dimension check)
  python tools/mee/cli.py extract    < input.json  (table/text candidate extraction)
  python tools/mee/cli.py validate   < input.json  (evidence-card schema validation)
  python tools/mee/cli.py isolation  < input.json  (group/time-point isolation check)
  python tools/mee/cli.py conflict   < input.json  (duplicates + contradictions)
  python tools/mee/cli.py export     < input.json  (cards -> JSON/YAML/CSV)
  python tools/mee/cli.py digitize   < input.json  (figure digitization interface)
  python tools/mee/cli.py check-self < input.json  (self-check a card set)

Exit codes: 0 success; 2 input/validation; 3 graph/contract; 4 internal.
Progress/logs go to stderr; stdout carries only the JSON envelope.
"""

from __future__ import annotations

import json
import os
import sys

from _common import run_tool, ToolError, emit_progress
from errors import MeeError, MeeErrorCode

_SUBCOMMANDS = ("service", "adapters", "doi", "units", "extract", "validate",
                "isolation", "conflict", "export", "digitize", "check-self")


def _dispatch(name: str, payload: dict) -> dict:
    if name == "service":
        from service import main as service_main
        return service_main(payload)
    if name == "adapters":
        import adapters as adapters_mod
        text = payload.get("document_text")
        path = payload.get("source_path")
        source_id = payload.get("source_id", payload.get("project_id", "source"))
        media = payload.get("media_type")
        binary_b64 = payload.get("document_text_b64") or payload.get("pdf_b64")
        if text is None and path is None and binary_b64 is None:
            raise MeeError(MeeErrorCode.DOCUMENT_UNPARSEABLE,
                           "adapters: document_text / source_path / document_text_b64 required")
        doc = adapters_mod.parse_source(source_id, media, text=text, path=path,
                                        binary_b64=binary_b64)
        return {"document": doc, "parse_log": doc.get("parse_log") or []}
    if name == "doi":
        import doi as doi_mod
        dois = payload.get("dois") or []
        if not dois:
            raise MeeError(MeeErrorCode.INPUT_SCHEMA_VIOLATION,
                           "doi: a non-empty 'dois' list is required")
        online = bool(payload.get("online", False))
        return {"verifications": doi_mod.verify_dois(
            dois, claimed_map=payload.get("claimed"), online=online)}
    if name == "units":
        import units as units_mod
        items = payload.get("quantities") or []
        out = []
        for item in items:
            role = item.get("role")
            label = item.get("label")
            norm = units_mod.normalize(item.get("value"), item.get("unit") or "",
                                       role=role, label=label)
            out.append({
                "label": label,
                "role": role,
                "dimension": units_mod.dimension_of(item.get("unit") or "",
                                                    role=role, label=label),
                **norm,
            })
        confl = units_mod.detect_distinct_conflation([
            {"role": x.get("role"), "unit": x.get("unit")} for x in items])
        return {"normalized": out, "conflation_issues": confl}
    if name == "extract":
        import extract as extract_mod
        sections = payload.get("sections") or []
        tables = payload.get("tables") or []
        out_tables = [extract_mod.extract_table_candidates(t) for t in tables]
        out_text = extract_mod.extract_text_candidates(sections)
        return {"table_candidates": out_tables, "text_candidates": out_text}
    if name == "validate":
        import card_check as cc
        cards = payload.get("cards") or []
        return cc.validate_cards(cards)
    if name == "isolation":
        import isolation as iso_mod
        cards = payload.get("cards") or []
        return iso_mod.check_cards(cards)
    if name == "conflict":
        import conflict as conflict_mod
        cards = payload.get("cards") or []
        claims = payload.get("methods_claims")
        return conflict_mod.detect_issues(cards, methods_claims=claims)
    if name == "export":
        import exporter
        cards = payload.get("cards") or []
        fmt = payload.get("format", "json")
        if fmt == "json":
            return {"format": "json", "content": exporter.to_json(cards)}
        if fmt == "yaml":
            return {"format": "yaml", "content": exporter.to_yaml(cards)}
        if fmt == "csv":
            return {"format": "csv", "content": exporter.to_csv(cards)}
        raise MeeError(MeeErrorCode.INPUT_SCHEMA_VIOLATION,
                       f"export: unknown format {fmt!r}", detail={"allowed": ["json", "yaml", "csv"]})
    if name == "digitize":
        import digitizer as dig_mod
        fig_id = payload.get("figure_id", "figure-1")
        return {"digitization": dig_mod.prepare_digitization(
            fig_id,
            axis_px=payload.get("axis_px"),
            axis_data_range=payload.get("axis_data_range"),
            image_library_available=bool(payload.get("image_library_available", False)),
            value=payload.get("value"))}
    if name == "check-self":
        from service import load_schema, _self_check
        out_schema = load_schema("output.schema.json")
        errs = _self_check(payload, out_schema)
        return {"passed": not errs, "errors": errs}
    raise MeeError(MeeErrorCode.INPUT_SCHEMA_VIOLATION,
                   f"unknown subcommand {name!r}",
                   detail={"allowed": list(_SUBCOMMANDS)})


def main() -> None:
    name = sys.argv[1] if len(sys.argv) > 1 else "service"
    if name == "--help":
        sys.stdout.write(__doc__)
        return
    run_tool(name, lambda payload: _dispatch(name, payload))


if __name__ == "__main__":
    try:
        main()
        sys.exit(0)
    except ToolError as err:
        from _common import envelope_err
        sys.stdout.write(envelope_err("cli", err) + "\n")
        sys.exit(err.exit_code)
    except BrokenPipeError:
        sys.exit(0)
    except Exception as exc:  # noqa: BLE001
        from _common import envelope_err, ToolError as _TE
        err = _TE("E_INTERNAL", f"unexpected internal error: {type(exc).__name__}: {exc}",
                  retryable=True, exit_code=4)
        sys.stdout.write(envelope_err("cli", err) + "\n")
        sys.exit(4)
