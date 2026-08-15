#!/usr/bin/env python3
"""obsidian-red-team unified CLI.

Reads a JSON envelope on stdin and dispatches to a sub-tool:

  python tools/ort/cli.py review        < input.json   (full adversarial review)
  python tools/ort/cli.py validate      < input.json   (input schema validation)
  python tools/ort/cli.py citation      < input.json   (citation verifier)
  python tools/ort/cli.py provenance    < input.json   (evidence chain checker)
  python tools/ort/cli.py units         < input.json   (units/dimension checker)
  python tools/ort/cli.py balance       < input.json   (mass-balance checker)
  python tools/ort/cli.py stats         < input.json   (statistical structure checker)
  python tools/ort/cli.py pseudo        < input.json   (pseudo-replication detector)
  python tools/ort/cli.py modelcheck    < input.json   (model boundary checker)
  python tools/ort/cli.py escalation    < input.json   (state-escalation checker)
  python tools/ort/cli.py permissions   < input.json   (permission-boundary checker)
  python tools/ort/cli.py counterexamp  < input.json   (counterexample generator)
  python tools/ort/cli.py severity      < input.json   (severity scorer)
  python tools/ort/cli.py blocking      < input.json   (blocking rule engine)
  python tools/ort/cli.py retest        < input.json   (fix retest verifier)
  python tools/ort/cli.py check-self    < output.json  (output self-check)

Exit codes: 0 success; 2 validation/input; 3 contract/graph; 4 internal.
Progress goes to stderr; stdout carries only the JSON envelope.
"""

from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from common import ToolError, TOOLSET_VERSION  # noqa: E402

_SUBCOMMANDS = (
    "review", "validate", "citation", "provenance", "units", "balance",
    "stats", "pseudo", "modelcheck", "escalation", "permissions",
    "counterexamp", "severity", "blocking", "retest", "check-self",
)


def _dispatch(name: str, payload: dict) -> dict:
    if name == "review":
        from service import main as service_main
        return service_main(payload)
    if name == "validate":
        from service import main as service_main
        clean = dict(payload)
        clean.pop("action", None)
        return service_main({"action": "review", **clean})
    if name == "check-self":
        from check_self import main as check_main
        return check_main(payload)
    if name in ("citation", "provenance", "units", "balance", "stats",
                "pseudo", "modelcheck", "escalation", "permissions",
                "counterexamp", "severity", "blocking", "retest"):
        import importlib
        # subcommand name -> module name (blocking engine lives in blocking_rules.py)
        module_name = {"blocking": "blocking_rules"}.get(name, name)
        mod = importlib.import_module(module_name)
        return mod.main(payload)
    raise ToolError("ORT-E103", f"unknown subcommand {name!r}",
                    details={"allowed": list(_SUBCOMMANDS)})


def _read_stdin() -> dict:
    raw = sys.stdin.read()
    if not raw.strip():
        raise ToolError("ORT-E301", "stdin was empty; expected a JSON document", exit_code=2)
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ToolError("ORT-E301",
                        f"stdin is not valid JSON: {exc.msg} at line {exc.lineno}",
                        details={"line": exc.lineno}, exit_code=2)
    if not isinstance(payload, dict):
        raise ToolError("ORT-E301", "envelope must be a JSON object", exit_code=2)
    return payload


def main() -> None:
    name = sys.argv[1] if len(sys.argv) > 1 else "review"
    payload = _read_stdin()
    result = _dispatch(name, payload)
    json.dump({"ok": True, "tool": name, "version": TOOLSET_VERSION, "result": result},
              sys.stdout, ensure_ascii=False, indent=2, sort_keys=True)
    sys.stdout.write("\n")


if __name__ == "__main__":
    try:
        main()
        sys.exit(0)
    except ToolError as err:
        json.dump({"ok": False, "tool": "cli", "version": TOOLSET_VERSION,
                   "error": {"code": err.code, "message": err.message,
                             "retryable": err.retryable, "details": err.details}},
                  sys.stdout, ensure_ascii=False, indent=2, sort_keys=True)
        sys.stdout.write("\n")
        sys.exit(err.exit_code)
    except BrokenPipeError:
        sys.exit(0)
    except Exception as exc:  # noqa: BLE001
        json.dump({"ok": False, "tool": "cli", "version": TOOLSET_VERSION,
                   "error": {"code": "E_INTERNAL",
                             "message": f"unexpected internal error: {type(exc).__name__}: {exc}",
                             "retryable": True, "details": {}}},
                  sys.stdout, ensure_ascii=False, indent=2, sort_keys=True)
        sys.stdout.write("\n")
        sys.exit(4)
