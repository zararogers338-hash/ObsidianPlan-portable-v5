#!/usr/bin/env python3
"""Reagent & material quantity calculator for micp-experiment-designer.

Computes reagent masses / volumes from the experiment's concentrations,
volumes, and molar masses, and validates the arithmetic against the unit
engine. Every numeric field is a strict {value, unit} quantity and must be
dimensional-checked.

MICP-relevant conversions supported out of the box:
  - molar mass lookups for the common reagents (urea, CaCl2, cementation
    solution components, etc.);
  - molar concentration (mol/L) -> mass (g) given a volume and molar mass;
  - mass concentration (g/L) -> mass (g);
  - dilution: C1*V1 = C2*V2  (stock -> working);
  - urease / cell broth volume math (per-volume units) is intentionally
    NOT auto-invented — the caller must give concentration and volume.

Hard rules:
  - Unknown molar mass or unit is a hard error (never guessed).
  - Value/unit records are validated via tools/unit_validate (dimension check).
  - All results are returned with units so a downstream SOP generator can
    embed them directly.
"""

from __future__ import annotations

import math
from typing import Any

from ._common import ToolError, as_list, as_number, as_str, run_tool
from .unit_validate import Quantity, parse_reagent_units

TOOL = "quantity_calc"

# Known molar masses (g/mol). Sources: CRC Handbook of Chemistry & Physics and
# standard IUPAC atomic weights (see references/sources.md S5).
# When the caller supplies a molar_mass, it overrides the lookup; the lookup is
# authoritative only when present in this table.
MOLAR_MASSES: dict[str, float] = {
    "urea": 60.06,            # CH4N2O
    "CaCl2": 110.98,          # anhydrous
    "CaCl2·2H2O": 147.01,     # dihydrate
    "CaCl2.2H2O": 147.01,
    "NaHCO3": 84.007,
    "Na2CO3": 105.988,
    "Ca(OH)2": 74.093,
    "CaCO3": 100.086,
    "NH4Cl": 53.49,
    "NaOH": 39.997,
    "KOH": 56.106,
    "MgCl2": 95.211,
    "MgCl2·6H2O": 203.30,
    "MgCl2.6H2O": 203.30,
    "glucose": 180.156,
    "yeast_extract": None,     # undefined — must be supplied by caller
    "peptone": None,           # undefined — must be supplied by caller
}


def _require_quantity(value: Any, unit: Any, path: str) -> Quantity:
    return parse_reagent_units(value, unit, path=path)


def _mass_from_molar(conc: Quantity, volume: Quantity, molar_mass: float) -> dict[str, Any]:
    """mass (g) = concentration (mol/L) * volume (L) * molar_mass (g/mol)."""
    # conc dimension must be amount/volume; volume must be volume
    if conc.dim != _dim_amount_per_volume():
        raise ToolError("E_UNIT_INCOMPATIBLE",
                        f"concentration '{conc.unit}' is not an amount-per-volume unit",
                        details={"unit": conc.unit, "dim": _dim_str(conc.dim)})
    if volume.dim != _dim_volume():
        raise ToolError("E_UNIT_INCOMPATIBLE",
                        f"volume '{volume.unit}' is not a volume unit",
                        details={"unit": volume.unit, "dim": _dim_str(volume.dim)})
    moles = conc.value * (conc.scale or 1.0) * volume.value * (volume.scale or 1.0)
    mass_g = moles * molar_mass
    return {
        "mass_g": mass_g,
        "mass_unit": "g",
        "moles": moles,
        "moles_unit": "mol",
        "method": "molar_mass",
    }


def _mass_from_mass_conc(conc: Quantity, volume: Quantity) -> dict[str, Any]:
    if conc.dim != _dim_mass_per_volume():
        raise ToolError("E_UNIT_INCOMPATIBLE",
                        f"concentration '{conc.unit}' is not a mass-per-volume unit",
                        details={"unit": conc.unit, "dim": _dim_str(conc.dim)})
    if volume.dim != _dim_volume():
        raise ToolError("E_UNIT_INCOMPATIBLE",
                        f"volume '{volume.unit}' is not a volume unit",
                        details={"unit": volume.unit, "dim": _dim_str(volume.dim)})
    mass_g = conc.value * (conc.scale or 1.0) * volume.value * (volume.scale or 1.0) / 1000.0  # to g
    return {
        "mass_g": mass_g,
        "mass_unit": "g",
        "method": "mass_concentration",
    }


def _dilution(c1: Quantity, v1: Quantity | None, c2: Quantity | None, v2: Quantity | None) -> dict[str, Any]:
    """C1*V1 = C2*V2 — given any three, solve the fourth (in same dimension)."""
    known = [(q, name) for q, name in ((c1, "c1"), (v1, "v1"), (c2, "c2"), (v2, "v2")) if q is not None]
    if len(known) != 3:
        raise ToolError("E_INPUT_VALUE", "dilution requires exactly 3 of {c1, v1, c2, v2}",
                        details={"provided": [n for _, n in known]})
    # all quantities must share a dimension pair: concentrations together,
    # volumes together
    concs = [q for q, n in known if n.startswith("c")]
    vols = [q for q, n in known if n.startswith("v")]
    if len(concs) == 2 and concs[0].dim != concs[1].dim:
        raise ToolError("E_UNIT_INCOMPATIBLE",
                        f"concentrations '{concs[0].unit}' and '{concs[1].unit}' differ in dimension",
                        details={"a": concs[0].unit, "b": concs[1].unit})
    if len(vols) == 2 and vols[0].dim != vols[1].dim:
        raise ToolError("E_UNIT_INCOMPATIBLE",
                        f"volumes '{vols[0].unit}' and '{vols[1].unit}' differ in dimension",
                        details={"a": vols[0].unit, "b": vols[1].unit})

    # solve for the missing variable using SI-normalized values
    def si(q: Quantity) -> float:
        return q.value * (q.scale or 1.0)

    missing = None
    if c1 is None or v1 is None or c2 is None or v2 is None:
        pass
    # determine which variable is missing
    if v2 is None:
        # c1*v1 = c2*v2 => v2 = c1*v1/c2
        v2_val = si(c1) * si(v1) / si(c2)
        missing = {"name": "v2", "si_value": v2_val, "si_unit": "m3"}
    elif v1 is None:
        v1_val = si(c2) * si(v2) / si(c1)
        missing = {"name": "v1", "si_value": v1_val, "si_unit": "m3"}
    elif c2 is None:
        c2_val = si(c1) * si(v1) / si(v2)
        missing = {"name": "c2", "si_value": c2_val, "si_unit": "mol/m3"}
    else:
        c1_val = si(c2) * si(v2) / si(v1)
        missing = {"name": "c1", "si_value": c1_val, "si_unit": "mol/m3"}

    return {
        "missing": missing["name"],
        "result_si": missing["si_value"],
        "result_si_unit": missing["si_unit"],
        "equation": "c1*v1 = c2*v2",
        "method": "dilution",
    }


def _dim_amount_per_volume():
    from fractions import Fraction
    from .unit_validate import _dim
    return _dim({"N": 1, "L": -3})


def _dim_mass_per_volume():
    from fractions import Fraction
    from .unit_validate import _dim
    return _dim({"M": 1, "L": -3})


def _dim_volume():
    from fractions import Fraction
    from .unit_validate import _dim
    return _dim({"L": 3})


def _dim_str(dim) -> str:
    from .unit_validate import _dim_str
    return _dim_str(dim)


def main(payload: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {"calculations": []}

    # 1. molar-mass lookup / reagent mass
    reagents = payload.get("reagents")
    if reagents is not None:
        for i, r in enumerate(as_list(reagents, "reagents")):
            if not isinstance(r, dict):
                raise ToolError("E_TYPE", f"reagents[{i}] must be an object")
            name = as_str(r.get("name", ""), f"reagents[{i}].name", min_len=1)
            mm = r.get("molar_mass")
            if mm is None:
                if name in MOLAR_MASSES and MOLAR_MASSES[name] is not None:
                    mm = MOLAR_MASSES[name]
                else:
                    raise ToolError("E_INPUT_VALUE",
                                    f"molar mass for '{name}' is unknown; provide reagents[{i}].molar_mass",
                                    details={"reagent": name, "known": sorted(k for k, v in MOLAR_MASSES.items() if v is not None)})
            molar_mass = as_number(mm, f"reagents[{i}].molar_mass", min_v=1e-6)
            conc = _require_quantity(r.get("concentration"), r.get("concentration_unit"), f"reagents[{i}].concentration")
            volume = _require_quantity(r.get("volume"), r.get("volume_unit"), f"reagents[{i}].volume")
            out = _mass_from_molar(conc, volume, molar_mass)
            out.update({"reagent": name, "molar_mass_g_per_mol": molar_mass,
                        "concentration": conc.value, "concentration_unit": conc.unit,
                        "volume": volume.value, "volume_unit": volume.unit})
            result["calculations"].append({"type": "mass_from_molar", **out})

    # 2. mass-concentration -> mass
    mass_conc = payload.get("mass_concentration_calculations")
    if mass_conc is not None:
        for i, r in enumerate(as_list(mass_conc, "mass_concentration_calculations")):
            if not isinstance(r, dict):
                raise ToolError("E_TYPE", f"mass_concentration_calculations[{i}] must be an object")
            conc = _require_quantity(r.get("concentration"), r.get("concentration_unit"), f"mass_concentration_calculations[{i}].concentration")
            volume = _require_quantity(r.get("volume"), r.get("volume_unit"), f"mass_concentration_calculations[{i}].volume")
            out = _mass_from_mass_conc(conc, volume)
            out.update({"concentration": conc.value, "concentration_unit": conc.unit,
                        "volume": volume.value, "volume_unit": volume.unit})
            result["calculations"].append({"type": "mass_from_mass_concentration", **out})

    # 3. dilution
    dilution = payload.get("dilution")
    if dilution is not None:
        if not isinstance(dilution, dict):
            raise ToolError("E_TYPE", "dilution must be an object")
        c1 = _require_quantity(dilution.get("c1_value"), dilution.get("c1_unit"), "dilution.c1") if "c1_value" in dilution else None
        v1 = _require_quantity(dilution.get("v1_value"), dilution.get("v1_unit"), "dilution.v1") if "v1_value" in dilution else None
        c2 = _require_quantity(dilution.get("c2_value"), dilution.get("c2_unit"), "dilution.c2") if "c2_value" in dilution else None
        v2 = _require_quantity(dilution.get("v2_value"), dilution.get("v2_unit"), "dilution.v2") if "v2_value" in dilution else None
        result["calculations"].append({"type": "dilution", **_dilution(c1, v1, c2, v2)})

    if not result["calculations"]:
        raise ToolError("E_INPUT_VALUE", "no calculation requested; provide reagents, mass_concentration_calculations or dilution")

    return result


if __name__ == "__main__":
    run_tool(TOOL, main)
