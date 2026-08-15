#!/usr/bin/env python3
"""micp-biosafety-environment-auditor CLI.

Contract:
  stdin   one JSON object conforming to schemas/input.schema.json
  stdout  one JSON object conforming to schemas/output.schema.json
  stderr  human-readable diagnostics (never protocol data)
  exit    0 always when an output envelope was produced (status field carries
          the outcome); 2 only when stdin could not be parsed as JSON at all.

Fully offline. No network, no file writes (unless --output given for evals).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from mbs.errors import MbsErrorCode  # noqa: E402
from mbs.service import SKILL_NAME, SKILL_VERSION, BiosafetyAuditorService  # noqa: E402


def _minimal_failure_envelope(message: str) -> dict:
    return {
        "contract_version": "1.0",
        "skill": SKILL_NAME,
        "skill_version": SKILL_VERSION,
        "status": "BLOCKED",
        "summary": message,
        "action": None,
        "project_id": None,
        "task_id": None,
        "findings": [],
        "assumptions": [],
        "evidence_used": [],
        "uncertainty": [],
        "risks": [],
        "artifacts": [],
        "requested_next_skills": [],
        "state": None,
        "validation": {"input_schema": "failed", "output_schema": "pending",
                       "self_check": "not_run"},
        "provenance": {"started_at": None, "completed_at": None, "host": None},
        "errors": [{"code": MbsErrorCode.INPUT_SCHEMA_VIOLATION.code,
                    "message": message, "detail": {}, "retryable": False}],
        "hazards": [], "exposure_pathways": [], "nitrogen_balance": None,
        "waste_streams": [], "regulatory_context": None,
        "monitoring_requirements": None, "control_measures": [],
        "residual_risk": [], "approval_requirements": [], "stop_conditions": [],
        "emergency_actions": [],
    }


def _write_output(out: dict, output_path: str | None) -> None:
    text = json.dumps(out, ensure_ascii=False, indent=2) + "\n"
    if output_path:
        Path(output_path).write_text(text, encoding="utf-8")
        sys.stdout.write(json.dumps({"status": out.get("status"),
                                     "written": output_path}, ensure_ascii=False) + "\n")
    else:
        sys.stdout.write(text)


def main(argv: list[str]) -> int:
    output_path = None
    if "--output" in argv:
        i = argv.index("--output")
        if i + 1 >= len(argv):
            print("--output requires a path argument", file=sys.stderr)
            return 2
        output_path = argv[i + 1]

    raw_text = sys.stdin.read()
    try:
        payload = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        _write_output(_minimal_failure_envelope(
            f"stdin is not valid JSON: {exc.msg} at line {exc.lineno} col {exc.colno}"), output_path)
        return 0
    if not isinstance(payload, dict):
        _write_output(_minimal_failure_envelope("stdin JSON must be an object"), output_path)
        return 0

    service = BiosafetyAuditorService()
    out = service.handle(payload)
    _write_output(out, output_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
