"""Mass-balance checker (质量守恒检查器).

Checks that chemical/material balances close within an engineering tolerance:

  - element balances (C, N, Ca, O, ...) across reactants/products
  - molar/mass conservation across a reaction scheme
  - water (H2O) balance and ammonia (NH4+) accounting
  - inflow == outflow + accumulation for transport/injection scenarios

Input shape (`reactions`):
  [
    {
      "name": "urea hydrolysis",
      "reactants": [{"species": "CO(NH2)2", "amount_mol": 1.0}],
      "products":  [{"species": "2NH3", "amount_mol": 2.0},
                    {"species": "CO2", "amount_mol": 1.0}],
      "unit": "mol"
    },
    ...
  ]

Elements are parsed from chemical formulas (C, N, O, H, Ca, Mg, S, P, Cl, K).
Molar mass is used for mass closure. Tolerance default 5% unless overridden.

Offline, deterministic, pure stdlib.
"""

from __future__ import annotations

import re
from typing import Any

from common import ToolError, emit_progress
from errors import OrtErrorCode, OrtError

ATOMIC_MASS: dict[str, float] = {
    "H": 1.008, "C": 12.011, "N": 14.007, "O": 15.999, "P": 30.974,
    "S": 32.06, "Ca": 40.078, "Mg": 24.305, "K": 39.098, "Cl": 35.45,
    "Na": 22.990, "Fe": 55.845, "Si": 28.085, "Al": 26.982, "Mn": 54.938,
    "Cu": 63.546, "Zn": 65.38, "B": 10.81, "F": 18.998, "Br": 79.904,
}

_FORMULA_RE = re.compile(r"([A-Z][a-z]?)(\d*)")


def parse_formula(species: str) -> dict[str, int]:
    """Parse a chemical formula like 'CaCO3' or 'CO(NH2)2' or '2NH3'.

    Returns element -> atom count (multiplier folded in). Handles parentheses
    at one nesting level and the leading coefficient.
    """
    s = species.strip()
    coeff = 1
    m = re.match(r"^(\d+)\s*(.*)$", s)
    if m:
        coeff = int(m.group(1))
        s = m.group(2).strip()

    # strip charge suffix like 2- / 3+ / (aq)
    s = re.sub(r"\(\s*(?:aq|s|l|g)\s*\)", "", s)
    s = re.sub(r"\d*[+-]$", "", s)

    counts: dict[str, int] = {}

    def add_group(group: str, mult: int) -> None:
        for elem, num in _FORMULA_RE.findall(group):
            n = int(num) if num else 1
            counts[elem] = counts.get(elem, 0) + n * mult

    # handle one level of parentheses: group ( ... )^k
    while "(" in s:
        start = s.find("(")
        depth = 1
        end = start + 1
        while depth > 0 and end < len(s):
            if s[end] == "(":
                depth += 1
            elif s[end] == ")":
                depth -= 1
            end += 1
        inner = s[start + 1:end - 1]
        rest = s[end:]
        mult_match = re.match(r"^(\d+)", rest)
        mult = int(mult_match.group(1)) if mult_match else 1
        add_group(inner, mult)
        s = s[:start] + rest[mult_match.end() if mult_match else 0:]
    add_group(s, 1)

    return {elem: n * coeff for elem, n in counts.items()}


def species_mass(species: str) -> float:
    counts = parse_formula(species)
    return sum(counts.get(e, 0) * ATOMIC_MASS.get(e, 0.0) for e in counts)


def _close_balance(reaction: dict[str, Any], tolerance: float) -> dict[str, Any]:
    name = str(reaction.get("name", "reaction"))
    reactants = reaction.get("reactants") or []
    products = reaction.get("products") or []

    def total_elements(items: list[dict]) -> dict[str, int]:
        out: dict[str, int] = {}
        for it in items:
            sp = str(it.get("species", ""))
            amt = float(it.get("amount_mol", 0.0))
            if not sp:
                continue
            for e, n in parse_formula(sp).items():
                out[e] = out.get(e, 0) + n * amt
        return out

    def total_mass(items: list[dict]) -> float:
        total = 0.0
        for it in items:
            sp = str(it.get("species", ""))
            amt = float(it.get("amount_mol", 0.0))
            total += species_mass(sp) * amt
        return total

    r_elems = total_elements(reactants)
    p_elems = total_elements(products)
    all_elems = set(r_elems) | set(p_elems)
    element_issues = []
    for e in sorted(all_elems):
        diff = abs(r_elems.get(e, 0) - p_elems.get(e, 0))
        ref = max(abs(r_elems.get(e, 0)), abs(p_elems.get(e, 0)), 1e-12)
        rel = diff / ref
        if rel > tolerance:
            element_issues.append({
                "element": e,
                "reactants": r_elems.get(e, 0),
                "products": p_elems.get(e, 0),
                "absolute_difference": diff,
                "relative_error": round(rel, 6),
            })

    r_mass = total_mass(reactants)
    p_mass = total_mass(products)
    mass_ref = max(r_mass, p_mass, 1e-12)
    mass_rel = abs(r_mass - p_mass) / mass_ref

    closed = not element_issues and mass_rel <= tolerance
    return {
        "name": name,
        "closed": closed,
        "element_issues": element_issues,
        "reactant_mass_g": round(r_mass, 6),
        "product_mass_g": round(p_mass, 6),
        "mass_relative_error": round(mass_rel, 6),
        "tolerance": tolerance,
    }


def _check_flow(payload: dict[str, Any]) -> list[dict]:
    """Inflow == outflow + accumulation for injection scenarios."""
    findings: list[dict] = []
    for f in payload.get("flows") or []:
        inflow = float(f.get("inflow", 0.0))
        outflow = float(f.get("outflow", 0.0))
        accum = float(f.get("accumulation", 0.0))
        lhs = inflow
        rhs = outflow + accum
        ref = max(abs(lhs), abs(rhs), 1e-12)
        rel = abs(lhs - rhs) / ref
        if rel > float(f.get("tolerance", 0.05)):
            findings.append({
                "flow_id": str(f.get("id", "?")),
                "species": str(f.get("species", "?")),
                "inflow": inflow,
                "outflow": outflow,
                "accumulation": accum,
                "relative_error": round(rel, 6),
                "severity": "CRITICAL",
            })
    return findings


def main(payload: dict[str, Any]) -> dict[str, Any]:
    emit_progress("balance: checking mass/element conservation")
    reactions = payload.get("reactions")
    if not reactions and not payload.get("flows"):
        raise OrtError(OrtErrorCode.INPUT_SCHEMA_VIOLATION,
                       "balance: reactions (or flows) array is required",
                       detail={"how_to_fix": "attach the reaction scheme with species and amounts, "
                                             "or the inflow/outflow/accumulation flows"})
    tolerance = float(payload.get("tolerance", 0.05))
    results = [_close_balance(r, tolerance) for r in (reactions or [])]
    flow_findings = _check_flow(payload)
    violations = [r for r in results if not r["closed"]]

    return {
        "reactions": results,
        "flow_findings": flow_findings,
        "summary": {
            "reactions_checked": len(results),
            "closed": sum(1 for r in results if r["closed"]),
            "violating": [r["name"] for r in violations],
            "flow_violations": len(flow_findings),
            "blocking_violation": bool(violations) or bool(flow_findings),
            "tolerance": tolerance,
        },
    }


if __name__ == "__main__":
    from common import read_stdin_envelope, run_tool
    run_tool("balance", lambda: main(read_stdin_envelope()))
