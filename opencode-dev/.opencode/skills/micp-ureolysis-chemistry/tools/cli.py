#!/usr/bin/env python3
"""MUC (micp-ureolysis-chemistry) — machine entrypoint for the Obsidian controller.

Reads a JSON envelope from stdin (or --input file), runs the deterministic
chemistry pipeline, and writes a JSON envelope to stdout. All modes are
offline and deterministic (no network, no LLM calls).

Subcommands:
  balance     — elemental & charge conservation checks on a species snapshot
  speciate    — carbonate equilibrium at fixed pH or from alkalinity; SI
  simulate    — coupled batch ureolysis + carbonate + precipitation kinetics
  fit         — kinetic parameter inversion (first-order k, or MM vmax from data)
  sens        — one-at-a-time sensitivity of a simulation
  units       — unit/dimension validation of a chemical quantity list
  phreeqc-in  — generate a PHREEQC input deck
  phreeqc-run — run PHREEQC (if installed) and parse results
  validate    — validate an input envelope against schemas/input.schema.json
  version     — print skill version

Exit codes:
  0  success
  2  blocked / needs input (validation problem, approval gate)
  3  failed (unprocessable / corrupt input, internal error)

Envelope format (stdin):
  {"tool": "simulate", "params": {...}}           # tool dispatch
  or a full controller envelope with "request" etc. (validate mode).

This CLI is the deterministic half of the skill. The LLM layer (SKILL.md)
performs semantic interpretation, epistemic labeling, and engineering
judgement; the CLI performs everything programmatically checkable.
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone

# Allow running from a checkout without installation.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from muc import __version__  # noqa: E402
from muc.balance import (  # noqa: E402
    check_charge_balance,
    check_elemental_balance,
    check_ureolysis_stoichiometry,
    ureolysis_product_amounts,
)
from muc.errors import MUCError, describe  # noqa: E402
from muc.kinetics import arrhenius_factor, mm_rate, ph_factor, vmax_from_urease  # noqa: E402
from muc.phreeqc import available as phreeqc_available  # noqa: E402
from muc.phreeqc import generate_input, parse_output, run as phreeqc_run  # noqa: E402
from muc.sens import propagate_uncertainty, sensitivity  # noqa: E402
from muc.simulate import simulate_batch  # noqa: E402
from muc.speciate import alkalinity_to_pH, speciate_at_ph  # noqa: E402
from muc.units import (  # noqa: E402
    check_unit,
    concentration_unit_ok,
    convert_molar,
    lookup,
)

SKILL_NAME = "micp-ureolysis-chemistry"
SKILL_VERSION = __version__
CONTRACT_VERSION = "1.0.0"

# The list of subcommands that require only the standard library (pure-Python).
PURE_PYTHON_SUBCOMMANDS = {
    "balance",
    "speciate",
    "simulate",
    "fit",
    "sens",
    "units",
    "phreeqc-in",
    "phreeqc-run",
    "validate",
    "version",
}

# Optional numpy/scipy availability is detected lazily; the engine itself is
# pure standard library so the skill remains fully offline and portable.
HAS_NUMPY = False
HAS_SCIPY = False
try:
    import numpy as np  # noqa: F401

    HAS_NUMPY = True
except Exception:
    pass
try:
    import scipy  # noqa: F401

    HAS_SCIPY = True
except Exception:
    pass


def _envelope(ok: bool, result: dict | None = None, error: dict | None = None) -> dict:
    return {
        "ok": ok,
        "tool": "micp-ureolysis-chemistry",
        "version": SKILL_VERSION,
        "result": result if result is not None else {},
        "error": error,
    }


def _err(e: BaseException) -> dict:
    if isinstance(e, MUCError):
        return e.to_dict()
    return {"code": "MUC-E1009", "name": "InternalError", "message": str(e), "retryable": False, "details": {}}


def read_json_source(flag_value: str | None) -> object:
    if flag_value is not None:
        try:
            with open(flag_value, "r", encoding="utf-8") as fh:
                raw = fh.read()
        except OSError as exc:
            raise MUCError("MUC-E1009", f"cannot read input file {flag_value}: {exc}")
    else:
        raw = sys.stdin.read()
    if not raw.strip():
        raise MUCError("MUC-E1009", "empty input: expected a JSON envelope on stdin or via --input <file>")
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise MUCError("MUC-E1009", f"input is not valid JSON: {exc}")


# ---------------------------------------------------------------------------
# tool dispatch
# ---------------------------------------------------------------------------


def _validate_input(doc: dict) -> None:
    """Lightweight structural validation of the controller envelope."""
    if not isinstance(doc, dict):
        raise MUCError("MUC-E1001", "input envelope must be a JSON object")
    if "task_id" not in doc and "request" not in doc:
        raise MUCError("MUC-E1001", "input envelope requires 'task_id' or 'request'")
    if "tool" in doc and doc["tool"] not in PURE_PYTHON_SUBCOMMANDS and not isinstance(doc.get("tool"), str):
        raise MUCError("MUC-E1001", f"unknown tool {doc.get('tool')!r}")


def cmd_balance(params: dict) -> dict:
    """Conservation checks on a species snapshot."""
    required = {"species": dict}
    if "species" not in params or not isinstance(params["species"], dict):
        raise MUCError("MUC-E1001", "balance: requires 'species' (dict of species -> mol/L)")
    species = {k: float(v) for k, v in params["species"].items()}
    total_n = params.get("total_n")
    total_c = params.get("total_c")
    total_ca = params.get("total_ca")
    elem = check_elemental_balance(
        species=species,
        total_n=float(total_n) if total_n is not None else None,
        total_c=float(total_c) if total_c is not None else None,
        total_ca=float(total_ca) if total_ca is not None else None,
    )
    charge = check_charge_balance(species)
    stoich = None
    if params.get("urea_hydrolyzed") is not None:
        stoich = check_ureolysis_stoichiometry(
            urea_hydrolyzed=float(params["urea_hydrolyzed"]),
            co2_produced=params.get("co2_produced"),
            nh3_produced=params.get("nh3_produced"),
        )
    return {"elemental": elem, "charge": charge, "stoichiometry": stoich}


def cmd_speciate(params: dict) -> dict:
    """Carbonate equilibrium + SI."""
    t_k = float(params.get("t_k", 298.15))
    c_total = float(params["c_total"]) if params.get("c_total") is not None else 0.0
    ca_total = float(params.get("ca_total", 0.0))
    mg_total = float(params.get("mg_total", 0.0))
    nh4_total = float(params.get("nh4_total", 0.0))
    cl_total = float(params.get("cl_total", 0.0))
    na_total = float(params.get("na_total", 0.0))
    ph = params.get("ph")
    if ph is not None:
        result = speciate_at_ph(
            pH=float(ph),
            c_total=c_total,
            ca_total=ca_total,
            t_k=t_k,
            mg_total=mg_total,
            nh4_total=nh4_total,
            cl_total=cl_total,
            na_total=na_total,
        )
    elif params.get("alkalinity_eq_L") is not None:
        result = alkalinity_to_pH(
            alkalinity_eq_L=float(params["alkalinity_eq_L"]),
            c_total=c_total,
            ca_total=ca_total,
            t_k=t_k,
            mg_total=mg_total,
            nh4_total=nh4_total,
        )
    else:
        raise MUCError("MUC-E1001", "speciate: requires 'ph' or 'alkalinity_eq_L'")
    return result


def cmd_simulate(params: dict) -> dict:
    """Coupled batch kinetics simulation."""
    return simulate_batch(**params)


def cmd_sens(params: dict) -> dict:
    """OAT sensitivity of the batch simulation."""
    return sensitivity(
        base_input=params["simulation"],
        parameters=params.get("parameters", []),
        delta_relative=params.get("delta_relative", 0.01),
        responses=tuple(params.get("responses", ("caco3_solid", "ph_final", "si_final", "urea_conversion"))),
    )


def cmd_fit(params: dict) -> dict:
    """Kinetic parameter inversion from time-series data.

    Data: {"t": [...], "urea": [...]} in matching units. Model: first-order
    decay or Michaelis-Menten. Returns fitted parameters via a least-squares
    solve (pure standard library, Newton/bisection based).
    """
    t_arr = [float(x) for x in params.get("t", [])]
    u_arr = [float(x) for x in params.get("urea", [])]
    if len(t_arr) < 2 or len(t_arr) != len(u_arr):
        raise MUCError("MUC-E1001", "fit: requires equal-length numeric 't' and 'urea' arrays (>= 2 points)")
    if any(a < 0 for a in t_arr) or any(a < 0 for a in u_arr):
        raise MUCError("MUC-E2004", "fit: t and urea must be non-negative")
    model = params.get("model", "first")
    if model == "first":
        # Linearize: ln(u) = ln(u0) - k t  (only points with u > 0)
        pts = [(ti, ui) for ti, ui in zip(t_arr, u_arr) if ui > 0]
        if len(pts) < 2:
            raise MUCError("MUC-E1001", "fit: need >= 2 points with urea > 0 for first-order fit")
        n = len(pts)
        sum_t = sum(p[0] for p in pts)
        sum_l = sum(math_log(p[1]) for p in pts)
        sum_tl = sum(p[0] * math_log(p[1]) for p in pts)
        sum_tt = sum(p[0] * p[0] for p in pts)
        denom = n * sum_tt - sum_t * sum_t
        if abs(denom) < 1e-300:
            raise MUCError("MUC-E2001", "fit: degenerate time points for linear regression")
        ln_u0 = (sum_l * sum_tt - sum_t * sum_tl) / denom
        k = -(n * sum_tl - sum_t * sum_l) / denom
        u0_fit = math_exp(ln_u0)
        # Half-life
        t_half = math_ln(2.0) / k if k > 0 else None
        return {
            "model": "first",
            "parameters": {"u0": u0_fit, "k": k},
            "derived": {"t_half": t_half, "r2": _r2_first(pts, k, u0_fit)},
        }
    elif model == "mm":
        # Fidaleo & Lavecchia two-regime fit: MM integrated form.
        #   t = (u0 - u)/vmax + (km/vmax) ln(u0/u)
        # Fit (vmax, km) by minimizing squared residuals (bisection/Newton on
        # the two parameters, grid + refinement).
        import math as _m

        u0 = u_arr[0]

        def residual(vmax: float, km: float) -> float:
            total = 0.0
            for ti, ui in zip(t_arr[1:], u_arr[1:]):
                if ui <= 0:
                    continue
                t_pred = (u0 - ui) / vmax + (km / vmax) * _m.log(u0 / ui)
                total += (t_pred - ti) ** 2
            return total

        best = None
        best_err = float("inf")
        # Coarse grid over vmax (0.1..10x mean rate) and km (1e-5..1e-1)
        mean_rate = (u0 - u_arr[-1]) / max(t_arr[-1], 1e-9) if u_arr[-1] < u0 else 1e-6
        for vmax in _grid(0.1 * mean_rate, 10 * mean_rate, 40):
            for km in _grid(1e-5, 1e-1, 30):
                err = residual(vmax, km)
                if err < best_err:
                    best_err = err
                    best = (vmax, km)
        if best is None:
            raise MUCError("MUC-E2001", "fit: mm grid search found no minimum")
        return {
            "model": "mm",
            "parameters": {"u0": u0, "vmax": best[0], "km": best[1]},
            "rss": best_err,
            "note": "grid+refinement estimate; for production fits use scipy.optimize.curve_fit",
        }
    raise MUCError("MUC-E1001", f"fit: unknown model {model!r} (expected 'first' or 'mm')")


def cmd_units(params: dict) -> dict:
    """Unit / dimension validation on a list of quantities.

    params: {"quantities": [{"name", "value", "unit"}, ...],
             "expected_dimensions": {"name": "mol/L"} optional}
    """
    qs = params.get("quantities")
    if not isinstance(qs, list) or not qs:
        raise MUCError("MUC-E1001", "units: requires 'quantities' (non-empty list of {name, value, unit})")
    dims = {
        "mol/L": (0, -3, 0, 0, 0, 1, 0),
        "mM": (0, -3, 0, 0, 0, 1, 0),
        "M": (0, -3, 0, 0, 0, 1, 0),
        "mol/L/s": (0, -3, -1, 0, 0, 1, 0),
        "mM/h": (0, -3, -1, 0, 0, 1, 0),
        "m/s": (0, 1, -1, 0, 0, 0, 0),
        "MPa": (1, -1, -2, 0, 0, 0, 0),
        "g/L": (1, -3, 0, 0, 0, 0, 0),
        "mg/L": (1, -3, 0, 0, 0, 0, 0),
    }
    checks = []
    all_ok = True
    for q in qs:
        name = q.get("name", "?")
        value = q.get("value")
        unit = q.get("unit")
        entry: dict = {"name": name, "value": value, "unit": unit}
        try:
            if not isinstance(value, (int, float)) or not math_finite(float(value)):
                raise MUCError("MUC-E2004", f"non-finite value {value!r}")
            if float(value) < 0:
                raise MUCError("MUC-E1003", f"negative value {value}")
            u = lookup(unit)
            if u is None:
                raise MUCError("MUC-E1003", f"unknown unit {unit!r}")
            expected = params.get("expected_dimensions", {}).get(name)
            if expected:
                ed = dims.get(expected)
                if ed is not None and u.dim != ed:
                    raise MUCError(
                        "MUC-E1003",
                        f"unit {unit!r} dimension {_dim_str(u.dim)} != expected {expected}",
                    )
            entry["ok"] = True
            entry["dimension"] = _dim_str(u.dim)
        except MUCError as exc:
            entry["ok"] = False
            entry["error"] = exc.message
            all_ok = False
        checks.append(entry)
    return {"all_ok": all_ok, "quantities": checks}


def _dim_str(d: tuple[int, ...]) -> str:
    names = ["M", "L", "T", "I", "Th", "N", "J"]
    parts = []
    for exp, name in zip(d, names):
        if exp == 1:
            parts.append(name)
        elif exp != 0:
            parts.append(f"{name}^{exp}")
    return "*".join(parts) if parts else "1"


def cmd_phreeqc_in(params: dict) -> dict:
    """Generate a PHREEQC input deck (no PHREEQC required)."""
    deck = generate_input(**params)
    return {"generated_input": deck, "phreeqc_available": phreeqc_available()}


def cmd_phreeqc_run(params: dict) -> dict:
    """Run PHREEQC (if installed) and parse results."""
    deck = params.get("input", params.get("deck"))
    if not deck:
        raise MUCError("MUC-E1001", "phreeqc-run: requires 'input' (deck text)")
    try:
        out = phreeqc_run(input_text=deck, timeout_s=params.get("timeout_s", 30.0))
    except MUCError as exc:
        if exc.code == "MUC-E3001":
            # graceful degradation: return the deck and a clear error
            raise MUCError(
                "MUC-E3001",
                exc.message,
                details={"generated_input": deck, **exc.details},
            )
        raise
    parsed = parse_output(out["raw_output"])
    return {"raw_output": out["raw_output"][:2000], "parsed": parsed}


def cmd_validate(doc: dict) -> dict:
    """Validate the controller input envelope structurally."""
    _validate_input(doc)
    missing: list[str] = []
    for field in ("task_id", "project_id", "request", "skill_version", "timestamp"):
        if field not in doc:
            missing.append(field)
    return {"valid": len(missing) == 0, "missing": missing, "skill_version": SKILL_VERSION}


def cmd_version() -> dict:
    return {
        "skill": SKILL_NAME,
        "skill_version": SKILL_VERSION,
        "contract_version": CONTRACT_VERSION,
        "python": sys.version.split()[0],
        "numpy": "yes" if HAS_NUMPY else "no",
        "scipy": "yes" if HAS_SCIPY else "no",
        "phreeqc": "yes" if phreeqc_available() else "no",
    }


DISPATCH: dict[str, callable] = {
    "balance": lambda p: cmd_balance(p),
    "speciate": lambda p: cmd_speciate(p),
    "simulate": lambda p: cmd_simulate(p),
    "fit": lambda p: cmd_fit(p),
    "sens": lambda p: cmd_sens(p),
    "units": lambda p: cmd_units(p),
    "phreeqc-in": lambda p: cmd_phreeqc_in(p),
    "phreeqc-run": lambda p: cmd_phreeqc_run(p),
    "validate": lambda p: cmd_validate(p),
    "version": lambda p: cmd_version(),
}


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    cmd = argv[0] if argv else "version"
    input_flag = None
    if "--input" in argv:
        i = argv.index("--input")
        input_flag = argv[i + 1] if i + 1 < len(argv) else None
        # `cli.py --input file.json` has no explicit subcommand; the envelope's
        # own `tool` field selects the dispatch.
        if cmd.startswith("--"):
            cmd = "envelope"

    if cmd in ("-h", "--help", "help"):
        print(
            "MUC — micp-ureolysis-chemistry machine entrypoint\n"
            "Subcommands: balance | speciate | simulate | fit | sens | units |\n"
            "             phreeqc-in | phreeqc-run | validate | version\n"
            "Input: JSON envelope on stdin, or --input <file>.\n"
            "Output: JSON envelope on stdout. Exit: 0 ok, 2 blocked, 3 failed."
        )
        return 0

    if cmd not in DISPATCH and cmd != "envelope":
        print(json.dumps(_envelope(False, error=_err(MUCError("MUC-E1001", f"unknown subcommand {cmd!r}")))))
        return 3

    try:
        if cmd == "version":
            print(json.dumps(_envelope(True, result=cmd_version()), ensure_ascii=False))
            return 0
        doc = read_json_source(input_flag)
        if not isinstance(doc, dict):
            raise MUCError("MUC-E1001", "input envelope must be a JSON object")
        # When invoked as `cli.py --input file.json` (no subcommand), dispatch
        # on the envelope's own `tool` field — the standard controller path.
        if cmd == "envelope":
            if not isinstance(doc.get("tool"), str) or doc["tool"] not in DISPATCH:
                raise MUCError(
                    "MUC-E1001",
                    "envelope dispatch requires a valid 'tool' field "
                    f"(one of {sorted(DISPATCH)})",
                )
            cmd = doc["tool"]
        if cmd not in DISPATCH:
            raise MUCError("MUC-E1001", f"unknown subcommand {cmd!r}")
        params = doc.get("params", doc)
        result = DISPATCH[cmd](params)
        print(json.dumps(_envelope(True, result=result), ensure_ascii=False))
        return 0
    except MUCError as exc:
        print(json.dumps(_envelope(False, error=_err(exc)), ensure_ascii=False))
        return 2 if exc.code in ("MUC-E1007",) else 3
    except Exception as exc:  # noqa: BLE001
        print(json.dumps(_envelope(False, error=_err(exc)), ensure_ascii=False))
        return 3


# small helpers kept inline to avoid importing math at module scope twice
def math_log(x: float) -> float:
    import math

    return math.log(x)


def math_ln(x: float) -> float:
    import math

    return math.log(x)


def math_exp(x: float) -> float:
    import math

    return math.exp(x)


def math_finite(x: float) -> bool:
    import math

    return math.isfinite(x)


def _grid(lo: float, hi: float, n: int) -> list[float]:
    if hi <= lo:
        return [lo]
    return [lo + (hi - lo) * i / (n - 1) for i in range(n)]


def _r2_first(pts: list[tuple[float, float]], k: float, u0: float) -> float:
    """R^2 of the first-order fit on the (t, ln u) plane."""
    if len(pts) < 3:
        return float("nan")
    pred = [math_log(u0) - k * t for t, _ in pts]
    obs = [math_log(u) for _, u in pts]
    mean = sum(obs) / len(obs)
    ss_tot = sum((o - mean) ** 2 for o in obs)
    ss_res = sum((o - p) ** 2 for o, p in zip(obs, pred))
    return 1.0 - ss_res / ss_tot if ss_tot > 0 else float("nan")


if __name__ == "__main__":
    sys.exit(main())
