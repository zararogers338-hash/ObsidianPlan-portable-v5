#!/usr/bin/env python3
"""micp-modeling-optimizer CLI entry point.

stdin: one JSON object conforming to schemas/input.schema.json.
stdout: one JSON object conforming to schemas/output.schema.json.
stderr: human-readable diagnostics.

Subcommands (positional, default "service"):
  service   full pipeline dispatch on payload.action
  schema    print the input schema (dry-run / introspection)
  selfcheck validate a JSON document against the output schema

Exit codes (documented in tools/README.md):
  0  an envelope was produced (its `status` field carries the outcome)
  2  malformed / unusable payload or hard contract violation
  3  missing dependency
  4  internal engine failure
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
# modules use flat imports (from _common / from errors / ...), so tools/micp
# must be on sys.path; the parent tools/ dir is added too for package access.
sys.path.insert(0, str(TOOLS / "micp"))
sys.path.insert(0, str(TOOLS))

from _common import SKILL_NAME, SKILL_VERSION, emit_progress  # noqa: E402
from errors import MmoError, MmoErrorCode  # noqa: E402


def _minimal_failure_envelope(message: str) -> dict:
    return {
        "contract_version": "1.0",
        "skill": SKILL_NAME,
        "skill_version": SKILL_VERSION,
        "status": "FAILED",
        "summary": message,
        "findings": [],
        "assumptions": [],
        "evidence_used": [],
        "uncertainty": [],
        "risks": [],
        "artifacts": [],
        "requested_next_skills": [],
        "validation": {"input_schema": False, "output_schema": False, "self_check": None, "checks": []},
        "provenance": {"skill": SKILL_NAME, "skill_version": SKILL_VERSION},
        "errors": [{"code": "MMO-E000", "message": message, "retryable": False, "details": {}}],
    }


def _print_envelope(out: dict) -> None:
    print(json.dumps(out, ensure_ascii=False, indent=2))


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    cmd = "service"
    rest: list[str] = []
    for a in argv:
        if a.startswith("--"):
            continue
        if cmd == "service":
            cmd = a
        else:
            rest.append(a)

    if cmd == "schema":
        schema = (Path(__file__).resolve().parent.parent / "schemas" / "input.schema.json").read_text(encoding="utf-8")
        print(schema)
        return 0

    if cmd == "selfcheck":
        if not rest:
            print(json.dumps(_minimal_failure_envelope("selfcheck requires a file argument")))
            return 2
        path = Path(rest[0])
        if not path.is_file():
            print(json.dumps(_minimal_failure_envelope(f"selfcheck file not found: {path}")))
            return 2
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            print(json.dumps(_minimal_failure_envelope(f"selfcheck: invalid JSON: {exc}")))
            return 2
        from validate import check_output_schema

        try:
            check_output_schema(doc)
            print(json.dumps({"ok": True, "schema": "output"}))
            return 0
        except MmoError as exc:
            print(json.dumps({"ok": False, "schema": "output", "error": exc.message}))
            return 1

    # service (default)
    raw = sys.stdin.read()
    try:
        payload = json.loads(raw)
        if not isinstance(payload, dict):
            raise MmoError(MmoErrorCode.INPUT_SCHEMA_VIOLATION, "payload must be a JSON object")
    except json.JSONDecodeError as exc:
        _print_envelope(_minimal_failure_envelope(f"invalid JSON on stdin: {exc}"))
        return 2
    except MmoError as exc:
        _print_envelope(_minimal_failure_envelope(exc.message))
        return 2

    from service import handle

    try:
        out = handle(payload)
        _print_envelope(out)
        return 0
    except MmoError as exc:
        _print_envelope(_minimal_failure_envelope(exc.message))
        return 2
    except Exception as exc:  # noqa: BLE001
        emit_progress(f"internal error: {exc}")
        _print_envelope(_minimal_failure_envelope(f"internal error: {exc}"))
        return 4


if __name__ == "__main__":
    sys.exit(main())
