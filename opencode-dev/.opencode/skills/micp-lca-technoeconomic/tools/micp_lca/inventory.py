"""Life-cycle inventory calculator.

Turns a scenario's declared inputs (materials, energy, water, transport,
labour, waste, monitoring, ...) into a normalized, per-functional-unit
inventory, then applies impact factors to produce environmental results.

Dimensions and their factor-id prefix:
  gwp        -> kg CO2eq      (factor ids `gwp.*`)
  energy     -> MJ            (factor ids `en.*`)
  water      -> m3            (factor ids with category "water")
  nitrogen_load -> kg NH3-N   (from urea stoichiometry, mass balance)
  eutrophication -> kg PO4eq  (factor id `eut.urea_n`)
  material_demand -> kg       (sum of major inputs)

Design rules:
- Every input line must carry `quantity`, `unit`, and a factor id. A missing
  factor raises LCA-E207 — the skill never invents a factor.
- Quantities are normalized to the functional unit via
  units.reference_flow_ratio (reference flow / analysis size).
- Transport is computed from mass x distance as t-km inventory lines.
- Waste (ammonium-rich effluent) is explicit: the caller declares a `route`
  (nitrification / stripping / anammox / none). NH3-N load is derived from
  urea hydrolysis stoichiometry (0.466 g N per g urea) unless declared, and
  is always reported even when the treatment route is "none" (direct
  discharge) — with a warning, never silently zeroed.
- All results carry `provenance` listing every factor id + version + source.
"""

from __future__ import annotations

from _common import ToolError, as_number
from errors import LcaErrorCode
from factors import FactorDatabase
from units import reference_flow_ratio

# Urea hydrolysis: CO(NH2)2 + H2O -> CO2 + 2 NH3. As N: 28.01 g N per 60.06 g urea.
NH3_N_FRACTION = 28.01 / 60.06  # 0.466 g N per g urea hydrolysed

# dimension -> factor-id prefix used to collect contributions
_DIMENSION_PREFIX = {
    "gwp": "gwp.",
    "energy": "en.",
    "eutrophication": "eut.",
    "water": None,   # collected by category
}

# Map a gwp-factor id on an inventory item to its primary-energy (en.*) factor
# so the energy dimension is computed from the same quantities without
# duplicating inventory lines.
_EN_EQUIVALENT = {
    "gwp.electricity_cn_avg": "en.electricity_cn",
    "gwp.diesel": "en.diesel",
    "gwp.natural_gas": "en.natural_gas",
    "gwp.urea": "en.urea",
    "gwp.cacl2": "en.cacl2",
    "gwp.cement_pc425": "en.cement",
    "gwp.water_industrial": "en.water_industrial",
    "gwp.transport_road": "en.transport_road",
}


def _qty(value: float, unit: str) -> dict:
    return {"value": value, "unit": unit}


def build_inventory(scenario: dict, functional_unit: dict, scope: dict,
                    db: FactorDatabase, analysis_year: int = 2026) -> dict:
    """Compute per-FU inventory + environmental results for one scenario.

    Returns { inventory, environmental_results, mass_balance, provenance,
              labour_hours_per_fu, scale_ratio }.
    """
    ratio = reference_flow_ratio(functional_unit, scope)
    scenario_type = scenario.get("type") or scenario.get("kind")
    if scenario_type == "micp":
        return _build_micp(scenario, ratio, db, analysis_year)
    if scenario_type in ("cement", "grouting", "chemical", "baseline"):
        return _build_conventional(scenario, ratio, db, analysis_year)
    raise ToolError(LcaErrorCode.INPUT_SCHEMA_VIOLATION.code,
                    f"unknown scenario type {scenario_type!r}",
                    details={"type": scenario_type})


def _add(items: list[dict], label: str, category: str, quantity: float, unit: str,
         factor_id: str, key: str, ratio: float) -> None:
    items.append({
        "key": key, "label": label, "category": category,
        "quantity": quantity, "unit": unit,
        "qty_per_fu": quantity * ratio, "factor_id": factor_id,
    })


def _collect_by_dimension(items: list[dict], dimension: str, db: FactorDatabase,
                          provenance: list[dict], analysis_year: int) -> dict:
    """Sum one impact dimension across inventory items, with breakdown.

    GWP collects every item whose factor is an impact factor in the relevant
    dimension (factor id prefix). Energy collects `en.*` factors (MJ per unit).
    """
    prefix = _DIMENSION_PREFIX[dimension]
    total = 0.0
    breakdown: list[dict] = []
    warnings: list[str] = []
    for it in items:
        factor_id = it["factor_id"]
        try:
            factor = db.get(factor_id)
        except ToolError:
            # Non-environmental items (labour, monitoring) carry no impact factor.
            continue
        matched = False
        if dimension == "water":
            matched = factor["category"] == "water"
        elif prefix and factor["id"].startswith(prefix):
            matched = True
        elif dimension == "energy" and factor_id in _EN_EQUIVALENT:
            # An item quantified with a gwp.* factor has a primary-energy twin.
            factor = db.get(_EN_EQUIVALENT[factor_id])
            matched = True
        if not matched:
            continue
        contrib = it["qty_per_fu"] * factor["value"]
        total += contrib
        warnings.extend(db.check_provenance(factor["id"], analysis_year))
        provenance.append({
            "factor_id": factor["id"], "version": factor["version"],
            "source": factor["provenance"], "region": factor["region"],
            "year": factor["year"],
        })
        breakdown.append({
            "item": it["label"], "category": factor["category"],
            "qty_per_fu": it["qty_per_fu"], "factor_id": factor["id"],
            "factor_value": factor["value"], "factor_unit": factor["unit"],
            "contribution": contrib,
        })
    unit = "kg CO2eq" if dimension == "gwp" else ("MJ" if dimension == "energy"
            else ("kg PO4eq" if dimension == "eutrophication" else dimension))
    return {"value": total, "unit": unit, "breakdown": breakdown, "warnings": warnings}


def _build_micp(scenario: dict, ratio: float, db: FactorDatabase, analysis_year: int) -> dict:
    provenance: list[dict] = []
    items: list[dict] = []

    mats = scenario.get("materials") or {}
    if not isinstance(mats, dict):
        raise ToolError(LcaErrorCode.INPUT_SCHEMA_VIOLATION.code,
                        "scenario.materials must be an object",
                        details={"scenario": scenario.get("id")})

    def add(label, category, quantity, unit, factor_id, key):
        _add(items, label, category, quantity, unit, factor_id, key, ratio)

    # --- materials ----------------------------------------------------------
    add("菌种培养", "materials", float(mats.get("culture_kg", 0.0)), "kg",
        "gwp.media_yeast", "culture")
    add("培养基", "materials", float(mats.get("media_kg", 0.0)), "kg",
        "gwp.media_yeast", "media")
    add("尿素", "materials", float(mats.get("urea_kg", 0.0)), "kg",
        "gwp.urea", "urea")
    add("钙源(CaCl2)", "materials", float(mats.get("cacl2_kg", 0.0)), "kg",
        "gwp.cacl2", "cacl2")
    add("水", "water", float(mats.get("water_m3", 0.0)), "m3",
        "gwp.water_industrial", "water")
    urea_kg = float(mats.get("urea_kg", 0.0))
    cacl2_kg = float(mats.get("cacl2_kg", 0.0))
    media_kg = float(mats.get("media_kg", 0.0))
    culture_kg = float(mats.get("culture_kg", 0.0))

    # --- energy -------------------------------------------------------------
    energy = scenario.get("energy") or {}
    add("电力(培养/泵送)", "energy", float(energy.get("electricity_kwh", 0.0)), "kWh",
        "gwp.electricity_cn_avg", "electricity")
    add("加热(燃气)", "energy", float(energy.get("natural_gas_kg", 0.0)), "kg",
        "gwp.natural_gas", "heating")
    add("柴油(现场机械)", "energy", float(energy.get("diesel_L", 0.0)), "L",
        "gwp.diesel", "diesel")

    # --- transport ----------------------------------------------------------
    tr = scenario.get("transport") or {}
    mat_km = float(tr.get("material_distance_km", 0.0))
    total_mass_kg = urea_kg + cacl2_kg + media_kg + culture_kg
    add("材料公路运输", "transport", total_mass_kg * mat_km / 1000.0, "t-km",
        "gwp.transport_road", "transport")

    # --- monitoring / test --------------------------------------------------
    monitor = scenario.get("monitoring") or {}
    add("监测设备能耗", "energy", float(monitor.get("electricity_kwh", 0.0)), "kWh",
        "gwp.electricity_cn_avg", "monitoring_energy")

    # --- waste: ammonium-rich effluent --------------------------------------
    waste = scenario.get("waste") or {}
    route = waste.get("route", "none")
    declared_n = float(waste.get("nh3_n_kg", 0.0))
    derive = bool(waste.get("derive_from_urea", True))
    nh3_n_kg = declared_n
    if nh3_n_kg == 0.0 and urea_kg > 0.0 and derive:
        nh3_n_kg = urea_kg * NH3_N_FRACTION
    if route != "none" and route != "direct_discharge":
        add("废液处理(氨氮)", "waste", nh3_n_kg, "kg NH3-N",
            _waste_factor_for(route), "waste_treatment")
        if route in ("landfill",):
            add("污泥/废渣处置", "waste", float(waste.get("sludge_t", 0.0)), "t",
                "gwp.sludge_landfill", "sludge")
    elif nh3_n_kg > 0:
        # direct discharge: no treatment burden, but the load is still reported
        pass

    # --- results ------------------------------------------------------------
    gwp = _collect_by_dimension(items, "gwp", db, provenance, analysis_year)
    energy_use = _collect_by_dimension(items, "energy", db, provenance, analysis_year)
    water_use = _collect_by_dimension(items, "water", db, provenance, analysis_year)
    eut = _eutrophication(nh3_n_kg, db, provenance)
    material_demand = (urea_kg + cacl2_kg + media_kg + culture_kg) * ratio

    if route in ("none", "direct_discharge") and nh3_n_kg > 0:
        gwp["warnings"].append(
            f"废液路线为 {route}: 氨氮 {nh3_n_kg:.2f} kg NH3-N 未经处理直接排放;"
            " 其环境负担被如实报告(氮负荷/富营养化),但未计入处理碳排 — 若实际需处理,请在 waste.route 中声明路线")

    return {
        "inventory": {
            "items": items,
            "per_fu_note": "All quantities scaled by reference_flow / analysis_size.",
            "scale_ratio": ratio,
            "mass_balance": {
                "urea_hydrolysed_kg": urea_kg,
                "nh3_n_released_kg": nh3_n_kg,
                "note": "NH3-N = 0.466 x urea_kg (stoichiometry) unless declared in waste.nh3_n_kg",
            },
        },
        "environmental_results": {
            "gwp": gwp,
            "energy": energy_use,
            "water": water_use,
            "eutrophication": eut,
            "nitrogen_load": {"value": nh3_n_kg, "unit": "kg NH3-N",
                              "source": "mass_balance"},
            "material_demand": {"value": material_demand, "unit": "kg"},
        },
        "mass_balance": {
            "urea_hydrolysed_kg": urea_kg,
            "nh3_n_released_kg": nh3_n_kg,
            "note": "NH3-N = 0.466 x urea_kg (stoichiometry) unless declared in waste.nh3_n_kg",
        },
        "provenance": _dedupe(provenance),
        "labour_hours_per_fu": float((scenario.get("labour") or {}).get("hours", 0.0)) * ratio,
        "scale_ratio": ratio,
    }


def _build_conventional(scenario: dict, ratio: float, db: FactorDatabase,
                        analysis_year: int) -> dict:
    """Cement / chemical-grouting baseline. Same envelope for fair comparison."""
    provenance: list[dict] = []
    items: list[dict] = []
    c = scenario.get("cement") or scenario.get("materials") or {}
    cement_kg = float(c.get("cement_kg", 0.0))
    water_m3 = float(c.get("water_m3", 0.0))

    def add(label, category, quantity, unit, factor_id, key):
        _add(items, label, category, quantity, unit, factor_id, key, ratio)

    add("水泥(P·O42.5)", "materials", cement_kg, "kg", "gwp.cement_pc425", "cement")
    add("水", "water", water_m3, "m3", "gwp.water_industrial", "water")
    energy = scenario.get("energy") or {}
    add("机械能耗", "energy", float(energy.get("electricity_kwh", 0.0)), "kWh",
        "gwp.electricity_cn_avg", "electricity")
    add("柴油", "energy", float(energy.get("diesel_L", 0.0)), "L", "gwp.diesel", "diesel")
    tr = scenario.get("transport") or {}
    add("材料公路运输", "transport", (cement_kg / 1000.0) * float(tr.get("material_distance_km", 0.0)),
        "t-km", "gwp.transport_road", "transport")
    waste = scenario.get("waste") or {}
    if float(waste.get("slurry_m3", 0.0)) > 0:
        add("施工废浆处置", "waste", float(waste.get("slurry_m3", 0.0)), "m3",
            "gwp.sludge_landfill", "waste")

    gwp = _collect_by_dimension(items, "gwp", db, provenance, analysis_year)
    energy_use = _collect_by_dimension(items, "energy", db, provenance, analysis_year)
    water_use = _collect_by_dimension(items, "water", db, provenance, analysis_year)
    return {
        "inventory": {"items": items, "per_fu_note": "scaled by reference_flow / analysis_size",
                      "scale_ratio": ratio, "mass_balance": {}},
        "environmental_results": {
            "gwp": gwp, "energy": energy_use, "water": water_use,
            "eutrophication": {"value": 0.0, "unit": "kg PO4eq",
                               "breakdown": [], "warnings": []},
            "nitrogen_load": {"value": 0.0, "unit": "kg NH3-N", "source": "mass_balance"},
            "material_demand": {"value": cement_kg * ratio, "unit": "kg"},
        },
        "mass_balance": {},
        "provenance": _dedupe(provenance),
        "labour_hours_per_fu": float((scenario.get("labour") or {}).get("hours", 0.0)) * ratio,
        "scale_ratio": ratio,
    }


def _eutrophication(nh3_n_kg: float, db: FactorDatabase, provenance: list[dict]) -> dict:
    f = db.get("eut.urea_n")
    value = nh3_n_kg * f["value"]
    provenance.append({"factor_id": f["id"], "version": f["version"],
                       "source": f["provenance"], "region": f["region"], "year": f["year"]})
    return {"value": value, "unit": "kg PO4eq", "breakdown": [
        {"item": "氨氮释放", "category": "waste", "qty_per_fu": nh3_n_kg,
         "factor_id": f["id"], "factor_value": f["value"],
         "factor_unit": f["unit"], "contribution": value}]}


def _waste_factor_for(route: str) -> str:
    if route == "nitrification":
        return "gwp.wastewater_nh3_n_removal"
    if route in ("stripping", "recovery"):
        return "gwp.wastewater_ammonia_stripping"
    if route == "anammox":
        return "gwp.wastewater_anammox"
    if route in ("none", "direct_discharge"):
        # handled by caller (no treatment line)
        return "gwp.wastewater_nh3_n_removal"
    raise ToolError(LcaErrorCode.INPUT_SCHEMA_VIOLATION.code,
                    f"unknown waste route {route!r}",
                    details={"route": route,
                             "allowed": ["none", "direct_discharge", "nitrification",
                                         "stripping", "recovery", "anammox"]})


def _dedupe(provenance: list[dict]) -> list[dict]:
    seen: dict[tuple, dict] = {}
    for p in provenance:
        key = (p["factor_id"], p["version"])
        seen.setdefault(key, p)
    return sorted(seen.values(), key=lambda x: x["factor_id"])
