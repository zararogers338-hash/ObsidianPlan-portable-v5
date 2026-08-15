"""obsidian-decision-gate CLI: stdin=JSON, stdout=JSON, fully offline.

Envelope contract: {"ok": bool, "tool": str, "version": str,
                    "result": {...} | null, "error": {...} | null}
exit codes: 0 ok · 2 input/validation error · 3 engine/rule error · 4 usage error

Subcommands:
  service    full gate evaluation (gate.evaluate)
  score      evidence-maturity / dimension scoring only
  blockers   blocking-rule check only
  mcda       multi-criteria decision analysis
  risk       risk-benefit matrix
  memo       Decision Memo generation from a prior evaluation
  transition state-transition request evaluation
  expiry     review-expiry / supersession check
  compare    decision-drift comparison against history
  validate   schema validation of an input envelope
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from odg.errors import OdgError, OdgErrorCode  # noqa: E402
from odg.rules import RuleTable  # noqa: E402
from odg.models import OutputStatus, ResearchState  # noqa: E402

VERSION = "1.0.0"

_EXIT_OK = 0
_EXIT_INPUT = 2
_EXIT_ENGINE = 3
_EXIT_USAGE = 4


def _emit(ok: bool, tool: str, result: Any = None, error: dict | None = None) -> None:
    sys.stdout.write(
        json.dumps({"ok": ok, "tool": tool, "version": VERSION,
                    "result": result, "error": error}, ensure_ascii=False)
        + "\n"
    )


def _load_input() -> dict:
    raw = sys.stdin.read()
    if not raw.strip():
        raise OdgError(OdgErrorCode.INPUT_SCHEMA_VIOLATION, "empty stdin")
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise OdgError(OdgErrorCode.INPUT_SCHEMA_VIOLATION, f"stdin is not valid JSON: {exc}") from exc


def _rule_table() -> RuleTable:
    return RuleTable.load()


def cmd_validate(payload: dict) -> dict:
    from odg.validate import validate_input
    try:
        validate_input(payload)
        return {"valid": True, "violations": []}
    except OdgError as exc:
        return {"valid": False, "violations": exc.detail.get("violations", []), "error": exc.to_dict()}


def cmd_score(payload: dict) -> dict:
    from odg.scoring import score_dimensions
    dims = score_dimensions(payload)
    return {"dimensions": {d: s.to_dict() for d, s in dims.items()}}


def cmd_blockers(payload: dict) -> dict:
    from odg.rules import evaluate_blockers
    table = _rule_table()
    source = ResearchState(payload["current_state"])
    target = ResearchState(payload["proposed_state"]) if payload.get("proposed_state") else None
    blockers = evaluate_blockers(payload, table, source, target) if target else []
    return {"blockers": [b.to_dict() for b in blockers]}


def cmd_mcda(payload: dict) -> dict:
    from odg.scoring import mcda_analysis
    table = _rule_table()
    target = ResearchState(payload["proposed_state"]) if payload.get("proposed_state") else ResearchState.SUPPORTED
    return mcda_analysis(payload, table, target)


def cmd_risk(payload: dict) -> dict:
    from odg.scoring import risk_benefit_matrix, score_dimensions
    scores = {d: s.score for d, s in score_dimensions(payload).items()}
    return risk_benefit_matrix(payload, scores)


def cmd_expiry(payload: dict) -> dict:
    from odg.expiry import check_expiry
    return check_expiry(payload).to_dict()


def cmd_compare(payload: dict) -> dict:
    from odg.compare import compare_decisions
    table = _rule_table()
    current = {
        "decision": payload.get("decision") or "PASS",
        "current_state": payload.get("current_state"),
        "proposed_state": payload.get("proposed_state"),
        "blocking_items": payload.get("blocking_items", []),
        "gate_results": payload.get("gate_results", {}),
    }
    return compare_decisions(payload, table, current, now="")


def cmd_transition(payload: dict) -> dict:
    from odg.service import evaluate
    res = evaluate(payload, dry_run=True)
    return {
        "status": res.status.value,
        "decision": res.envelope.get("decision"),
        "state_transition_request": res.envelope.get("state_transition_request"),
        "required_human_approvals": res.envelope.get("required_human_approvals"),
    }


def cmd_memo(payload: dict) -> dict:
    from odg.service import evaluate
    res = evaluate(payload, dry_run=True)
    return {"memo": res.envelope.get("decision_memo")}


def cmd_service(payload: dict) -> dict:
    from odg.service import evaluate
    res = evaluate(payload, dry_run=bool((payload.get("context") or {}).get("dry_run", False)))
    return res.envelope


_HANDLERS = {
    "service": cmd_service,
    "score": cmd_score,
    "blockers": cmd_blockers,
    "mcda": cmd_mcda,
    "risk": cmd_risk,
    "expiry": cmd_expiry,
    "compare": cmd_compare,
    "transition": cmd_transition,
    "memo": cmd_memo,
    "validate": cmd_validate,
}


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    tool = "service"
    if argv:
        tool = argv[0]
        if tool in ("--version", "-v"):
            _emit(True, "version", {"version": VERSION})
            return _EXIT_OK
        if tool in ("--help", "-h"):
            _emit(True, "help", {"subcommands": sorted(_HANDLERS), "envelope": "ok/tool/version/result/error"})
            return _EXIT_OK
        if tool not in _HANDLERS:
            _emit(False, "cli", None, {
                "code": "ODG-E104", "message": f"unknown subcommand {tool!r}",
                "retryable": False,
            })
            return _EXIT_USAGE

    try:
        payload = _load_input()
        if isinstance(payload, dict) and (payload.get("context") or {}).get("dry_run") and tool == "service":
            pass
        result = _HANDLERS[tool](payload)
        _emit(True, tool, result)
        return _EXIT_OK
    except OdgError as exc:
        _emit(False, tool, None, exc.to_dict())
        if exc.code in (OdgErrorCode.INPUT_SCHEMA_VIOLATION, OdgErrorCode.MISSING_REQUIRED_FIELD,
                        OdgErrorCode.INVALID_STATE_NAME, OdgErrorCode.INVALID_ACTION):
            return _EXIT_INPUT
        return _EXIT_ENGINE
    except (KeyError, TypeError, ValueError) as exc:
        _emit(False, tool, None, {
            "code": "ODG-E401", "message": f"engine error: {exc}", "retryable": False,
        })
        return _EXIT_ENGINE


if __name__ == "__main__":
    os.environ.setdefault("ODG_TEST_CLOCK", os.environ.get("ODG_TEST_CLOCK", ""))
    sys.exit(main())
