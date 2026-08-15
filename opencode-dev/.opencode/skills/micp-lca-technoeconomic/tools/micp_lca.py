#!/usr/bin/env python3
"""micp-lca-technoeconomic unified CLI.

Reads a JSON envelope on stdin and dispatches to a sub-tool:

  python tools/micp_lca.py service    < input.json   (full skill pipeline)
  python tools/micp_lca.py validate   < input.json   (input schema validation only)
  python tools/micp_lca.py inventory  < input.json   (inventory + environment only)
  python tools/micp_lca.py cost       < input.json   (cost model only)
  python tools/micp_lca.py mc         < input.json   (Monte Carlo only)
  python tools/micp_lca.py sensitivity < input.json  (OAT + Morris only)

Exit codes: 0 success; 2 input/validation; 3 graph/contract; 4 internal.
Progress goes to stderr; stdout carries only the JSON envelope.
"""

from __future__ import annotations

import json
import os
import sys

# The package lives next to this entry point; make it importable regardless
# of the caller's working directory.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "micp_lca"))

from _common import ToolError, read_json_stdin, envelope_ok, envelope_err, reject_non_finite
from errors import LcaError

_SUBCOMMANDS = ("service", "validate", "inventory", "cost", "mc", "sensitivity")
_VERSION = "1.0.0"


def _dispatch(name: str, payload: dict) -> dict:
    if name == "service":
        from service import service_main
        return service_main(payload)
    if name == "validate":
        from service import validate_input
        return validate_input(payload)
    if name == "inventory":
        from service import _Pipeline
        pipe = _Pipeline(payload)
        pipe.gate_envelope()
        pipe.gate_version()
        pipe.gate_scope()
        scenarios = pipe._require_scenarios()
        return {
            "scenarios": [pipe.evaluate_scenario(s, label=f"scenario-{i+1}")
                          for i, s in enumerate(scenarios)],
            "functional_unit": pipe.functional_unit,
        }
    if name == "cost":
        from service import _Pipeline
        pipe = _Pipeline(payload)
        pipe.gate_envelope()
        pipe.gate_version()
        pipe.gate_scope()
        scenarios = pipe._require_scenarios()
        from cost import build_cost_model
        return {"scenarios": [build_cost_model(s, pipe.functional_unit, pipe.scope, pipe.db,
                                               pipe.year)
                              for s in scenarios]}
    if name == "mc":
        from service import _Pipeline
        pipe = _Pipeline(payload)
        pipe.gate_envelope()
        pipe.gate_version()
        pipe.gate_scope()
        scenario = (payload.get("scenarios") or [{}])[0]
        return pipe.run_mc(scenario)
    if name == "sensitivity":
        from service import _Pipeline
        pipe = _Pipeline(payload)
        pipe.gate_envelope()
        pipe.gate_version()
        pipe.gate_scope()
        scenario = (payload.get("scenarios") or [{}])[0]
        from inventory import build_inventory
        result = {"environmental": build_inventory(scenario, pipe.functional_unit,
                                                   pipe.scope, pipe.db, pipe.year)["environmental_results"]}
        return pipe.run_sensitivity(scenario, result)
    raise LcaError(LcaErrorCode.UNKNOWN_ACTION,
                   f"unknown subcommand {name!r}",
                   detail={"allowed": list(_SUBCOMMANDS)})


def main() -> None:
    name = sys.argv[1] if len(sys.argv) > 1 else "service"
    if name not in _SUBCOMMANDS:
        # tolerate `service` default without subcommand
        name = "service"
    payload = reject_non_finite(read_json_stdin())
    result = _dispatch(name, payload)
    sys.stdout.write(envelope_ok(name, result) + "\n")


if __name__ == "__main__":
    try:
        main()
        sys.exit(0)
    except LcaError as err:
        sys.stdout.write(envelope_err("cli", err) + "\n")
        sys.exit(err.exit_code)
    except ToolError as err:
        sys.stdout.write(envelope_err("cli", err) + "\n")
        sys.exit(err.exit_code)
    except BrokenPipeError:
        sys.exit(0)
    except Exception as exc:  # noqa: BLE001
        sys.stdout.write(json.dumps(
            {"ok": False, "tool": "cli", "version": _VERSION,
             "error": {"code": "E_INTERNAL",
                       "message": f"unexpected internal error: {type(exc).__name__}: {exc}",
                       "retryable": True, "details": {}}},
            ensure_ascii=False, indent=2, sort_keys=True) + "\n")
        sys.exit(4)
