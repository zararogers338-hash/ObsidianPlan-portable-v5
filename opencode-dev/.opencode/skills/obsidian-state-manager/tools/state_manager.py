#!/usr/bin/env python3
"""obsidian-state-manager CLI.

Contract:
  stdin   one JSON object conforming to schemas/input.schema.json
  stdout  one JSON object conforming to schemas/output.schema.json
  stderr  human-readable progress/diagnostics (never protocol data)
  exit    0 always when an output envelope was produced (status field carries
          the outcome); 2 only when stdin could not be parsed as JSON at all.

Store location: flag --store > env OBSIDIAN_STATE_STORE > <skill>/state_store/.
A repository override is not hardcoded anywhere; tests always pass --store.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from osm.errors import OsmError, OsmErrorCode  # noqa: E402
from osm.models import OutputStatus  # noqa: E402
from osm.service import SKILL_NAME, SKILL_VERSION, StateManagerService  # noqa: E402

DEFAULT_STORE = Path(__file__).resolve().parent.parent / "state_store"


def _resolve_store(argv: list[str]) -> Path:
    if "--store" in argv:
        i = argv.index("--store")
        if i + 1 >= len(argv):
            print("--store requires a path argument", file=sys.stderr)
            raise SystemExit(2)
        return Path(argv[i + 1]).expanduser().resolve()
    env = os.environ.get("OBSIDIAN_STATE_STORE")
    if env:
        return Path(env).expanduser().resolve()
    return DEFAULT_STORE


def _minimal_failure_envelope(message: str, store: Path) -> dict:
    return {
        "contract_version": "1.0",
        "skill": SKILL_NAME,
        "skill_version": SKILL_VERSION,
        "status": OutputStatus.BLOCKED.value,
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
                       "self_check": "not_run", "rebuild_matches_snapshot": None},
        "provenance": {"started_at": None, "completed_at": None,
                       "store_root": str(store), "host": None,
                       "events_appended": [], "head_revision": None, "head_hash": None},
        "errors": [{"code": OsmErrorCode.INPUT_SCHEMA_VIOLATION.code,
                    "message": message, "detail": {}, "retryable": False}],
    }


def _clock_from_env():
    """Deterministic clock for tests/evals: OSM_TEST_CLOCK pins recorded_at."""
    fixed = os.environ.get("OSM_TEST_CLOCK")
    if fixed:
        return lambda: fixed
    return None


def main(argv: list[str]) -> int:
    store = _resolve_store(argv)
    raw_text = sys.stdin.read()
    try:
        payload = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        out = _minimal_failure_envelope(
            f"stdin is not valid JSON: {exc.msg} at line {exc.lineno} col {exc.colno}", store)
        json.dump(out, sys.stdout, ensure_ascii=False, indent=2)
        sys.stdout.write("\n")
        return 0

    if not isinstance(payload, dict):
        out = _minimal_failure_envelope("stdin JSON must be an object", store)
        json.dump(out, sys.stdout, ensure_ascii=False, indent=2)
        sys.stdout.write("\n")
        return 0

    try:
        service = StateManagerService(store, clock=_clock_from_env())
        out = service.handle(payload)
    except OsmError as exc:  # store-level failures before envelope construction
        out = _minimal_failure_envelope(f"{exc.code.code}: {exc.message}", store)
        out["status"] = OutputStatus.FAILED.value
        out["errors"] = [exc.to_dict()]

    json.dump(out, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
