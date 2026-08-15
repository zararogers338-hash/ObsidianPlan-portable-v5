"""CAPEX / OPEX cost model with price-tier discipline, scale-up factors, and
cost-database interface.

Price-tier discipline (spec §四):
- lab_catalogue prices are NEVER used as field costs (LCA-E204). A tier of
  "lab_catalogue" on any material flags the whole scenario.
- Default material prices are industrial / factory-gate (CNY/kg). Callers may
  declare a `price_tier` per scenario: industrial | small_batch |
  lab_catalogue. small_batch/lab tiers scale industrial prices with documented
  multipliers and carry a warning. Real quoted prices (price_quotes) override
  tier scaling.

Cost structure:
  CAPEX      (equipment, site setup, injection system, monitoring rig)
  fixed OPEX (labour base, monitoring, maintenance, insurance)
  variable OPEX (materials, energy, water, waste treatment, transport)
  plus risk reserve, downtime & failure cost (rework / re-injection).

All costs stay in the declared currency (default CNY); a display conversion to
USD is provided via units.convert_money.

Scale-up: a simple exponential scale factor (default exponent 0.7) scales the
CAPEX of a reference facility size to the target analysis size.
"""

from __future__ import annotations

from _common import ToolError, as_number
from errors import LcaErrorCode
from factors import FactorDatabase, tier_price, PRICE_TIERS
from inventory import build_inventory, NH3_N_FRACTION

MATERIAL_COST_FACTORS = {
    "urea": "cost.urea",
    "cacl2": "cost.cacl2",
    "calcium_lactate": "cost.calcium_lactate",
    "media_yeast": "cost.media_yeast",
    "molasses": "cost.molasses",
    "cement": "cost.cement_pc425",
}
WASTE_COST_FACTORS = {
    "nitrification": "cost.wastewater_nh3_n_removal",
    "stripping": "cost.wastewater_ammonia_stripping",
    "recovery": "cost.wastewater_ammonia_stripping",
    "anammox": None,  # no default operating-cost factor; caller must supply
}


def _get_material_cost(scenario_mats: dict, mats: dict, key: str, factor_id: str,
                       db: FactorDatabase, warnings: list[str]) -> tuple[float, dict]:
    """Return (unit cost CNY/unit, provenance). Price tier applied to the
    industrial factor; real price quotes override it; lab tier flags LCA-E204."""
    quotes = (scenario_mats.get("price_quotes") or {}) if isinstance(scenario_mats, dict) else {}
    quote = quotes.get(key)
    if quote is not None:
        return float(quote), {"source": "caller_price_quote", "tier": None}
    tier = scenario_mats.get("price_tier", "industrial") if isinstance(scenario_mats, dict) else "industrial"
    f = db.get(factor_id)
    price, lab_flag = tier_price(float(f["value"]), tier, f["category"])
    if lab_flag:
        warnings.append(
            f"材料 {key} 使用 lab_catalogue 目录价 {price:.2f} CNY/{f['unit']} 直接作为现场成本"
            " — 违反现场成本纪律(LCA-E204);已按 ×{lab_mult} 放大但仍不可代表现场价")
    return price, {"source": f["provenance"], "tier": tier, "year": f["year"], "factor_id": factor_id}


def build_cost_model(scenario: dict, functional_unit: dict, scope: dict,
                     db: FactorDatabase, analysis_year: int = 2026) -> dict:
    """Compute per-FU and absolute CAPEX/OPEX for one scenario.

    Returns { cost_results: {...}, per_fu: {...}, scale_up: {...},
              warnings, provenance, cap_ex_details, op_ex_details }.
    """
    ratio = _scale_ratio(functional_unit, scope)
    size_value, size_unit = _analysis_size(scope)
    warnings: list[str] = []

    # ---- CAPEX ------------------------------------------------------------
    capex_in = (scenario.get("capex") or {}) if isinstance(scenario, dict) else {}
    equipment = float(capex_in.get("equipment_cny", 0.0))
    injection_system = float(capex_in.get("injection_system_cny", 0.0))
    monitoring_rig = float(capex_in.get("monitoring_rig_cny", 0.0))
    site_setup = float(capex_in.get("site_setup_cny", 0.0))
    engineering = float(capex_in.get("engineering_cny", 0.0))
    lab_scaleup = float(capex_in.get("lab_scaleup_cny", 0.0))
    base_capex = equipment + injection_system + monitoring_rig + site_setup + engineering + lab_scaleup

    # ---- fixed OPEX ---------------------------------------------------------
    opex_in = (scenario.get("opex") or {}) if isinstance(scenario, dict) else {}
    labour = (scenario.get("labour") or {}) if isinstance(scenario, dict) else {}
    labour_hours = float(labour.get("hours", 0.0))
    labour_rate_cny_h = float(labour.get("rate_cny_h", 0.0))
    if labour_rate_cny_h == 0.0:
        f = db.get("cost.labor_technician_cn")
        labour_rate_cny_h = float(f["value"])
    labour_cost = labour_hours * labour_rate_cny_h
    fixed_opex = {
        "labour_cny": labour_cost,
        "monitoring_cny": float(opex_in.get("monitoring_cny", 0.0)),
        "maintenance_cny": float(opex_in.get("maintenance_cny", 0.0)),
        "insurance_cny": float(opex_in.get("insurance_cny", 0.0)),
        "total_cny": labour_cost + float(opex_in.get("monitoring_cny", 0.0))
                    + float(opex_in.get("maintenance_cny", 0.0))
                    + float(opex_in.get("insurance_cny", 0.0)),
    }

    # ---- variable OPEX (materials/energy/water/waste/transport) -------------
    var = {"materials_cny": 0.0, "energy_cny": 0.0, "water_cny": 0.0,
           "waste_cny": 0.0, "transport_cny": 0.0}
    var_breakdown: list[dict] = []
    mats = (scenario.get("materials") or {}) if isinstance(scenario, dict) else {}
    energy = (scenario.get("energy") or {}) if isinstance(scenario, dict) else {}
    tr = (scenario.get("transport") or {}) if isinstance(scenario, dict) else {}

    # materials
    mat_qty = {
        "urea": float(mats.get("urea_kg", 0.0)),
        "cacl2": float(mats.get("cacl2_kg", 0.0)),
        "calcium_lactate": float(mats.get("calcium_lactate_kg", 0.0)),
        "media_yeast": float(mats.get("media_kg", 0.0)),
        "molasses": float(mats.get("molasses_kg", 0.0)),
        "cement": float(mats.get("cement_kg", 0.0)),
    }
    for key, qty in mat_qty.items():
        if qty <= 0 or key not in MATERIAL_COST_FACTORS:
            continue
        price, prov = _get_material_cost(scenario_mats=mats, mats=mats, key=key,
                                         factor_id=MATERIAL_COST_FACTORS[key], db=db, warnings=warnings)
        cost = qty * price
        var["materials_cny"] += cost
        var_breakdown.append({"item": key, "qty": qty, "unit": "kg",
                              "price": price, "price_unit": "CNY/kg",
                              "cost_cny": cost, "provenance": prov})
    # water
    water_m3 = float(mats.get("water_m3", 0.0))
    if water_m3 > 0:
        try:
            wf = db.get("cost.water_industrial_cn")
        except ToolError:
            wf = db.get("cost.water_industrial")
        wprice = float(wf["value"])
        cost = water_m3 * wprice
        var["water_cny"] += cost
        var_breakdown.append({"item": "water", "qty": water_m3, "unit": "m3",
                              "price": wprice, "price_unit": "CNY/m3", "cost_cny": cost,
                              "provenance": {"source": wf["provenance"], "year": wf["year"]}})
    # energy
    elec_kwh = float(energy.get("electricity_kwh", 0.0))
    diesel_L = float(energy.get("diesel_L", 0.0))
    gas_kg = float(energy.get("natural_gas_kg", 0.0))
    if elec_kwh > 0:
        ef = db.get("cost.electricity_cn_industrial")
        cost = elec_kwh * float(ef["value"])
        var["energy_cny"] += cost
        var_breakdown.append({"item": "electricity", "qty": elec_kwh, "unit": "kWh",
                              "price": ef["value"], "price_unit": "CNY/kWh", "cost_cny": cost,
                              "provenance": {"source": ef["provenance"], "year": ef["year"]}})
    if diesel_L > 0:
        df = db.get("cost.diesel_cn")
        cost = diesel_L * float(df["value"])
        var["energy_cny"] += cost
        var_breakdown.append({"item": "diesel", "qty": diesel_L, "unit": "L",
                              "price": df["value"], "price_unit": "CNY/L", "cost_cny": cost,
                              "provenance": {"source": df["provenance"], "year": df["year"]}})
    if gas_kg > 0:
        gf = db.get("cost.natural_gas_cn")
        cost = gas_kg * float(gf["value"])
        var["energy_cny"] += cost
        var_breakdown.append({"item": "natural_gas", "qty": gas_kg, "unit": "kg",
                              "price": gf["value"], "price_unit": "CNY/kg", "cost_cny": cost,
                              "provenance": {"source": gf["provenance"], "year": gf["year"]}})
    # waste treatment
    waste = (scenario.get("waste") or {}) if isinstance(scenario, dict) else {}
    route = waste.get("route", "none")
    urea_kg = float(mats.get("urea_kg", 0.0))
    declared_n = float(waste.get("nh3_n_kg", 0.0))
    nh3_n = declared_n if declared_n > 0 else (urea_kg * NH3_N_FRACTION if urea_kg > 0 else 0.0)
    if route in WASTE_COST_FACTORS and nh3_n > 0:
        fid = WASTE_COST_FACTORS[route]
        if fid is None:
            warnings.append(f"废液路线 {route} 无默认运行成本因子,请提供 cost.waste_anammox 覆盖")
        else:
            wf = db.get(fid)
            cost = nh3_n * float(wf["value"])
            var["waste_cny"] += cost
            var_breakdown.append({"item": "waste_treatment", "qty": nh3_n, "unit": "kg NH3-N",
                                  "price": wf["value"], "price_unit": "CNY/kg NH3-N",
                                  "cost_cny": cost,
                                  "provenance": {"source": wf["provenance"], "year": wf["year"]}})
    elif route in ("none", "direct_discharge") and nh3_n > 0:
        warnings.append(f"废液 {nh3_n:.1f} kg NH3-N 直接排放:未计入处理成本,但排放负担已计入环境结果")

    # transport
    mat_km = float(tr.get("material_distance_km", 0.0))
    total_mass_t = (sum(float(mats.get(k, 0.0)) for k in
                        ("urea_kg", "cacl2_kg", "media_kg", "culture_kg", "cement_kg")) / 1000.0)
    truck_rate = float(db.get("cost.trucking_cn").get("value", 2.0))
    if total_mass_t > 0 and mat_km > 0:
        cost = total_mass_t * mat_km * truck_rate
        var["transport_cny"] += cost
        var_breakdown.append({"item": "road_freight", "qty": total_mass_t * mat_km,
                              "unit": "t-km", "price": truck_rate, "price_unit": "CNY/t-km",
                              "cost_cny": cost,
                              "provenance": {"source": db.get("cost.trucking_cn")["provenance"],
                                             "year": db.get("cost.trucking_cn")["year"]}})

    variable_opex_total = var["materials_cny"] + var["energy_cny"] + var["water_cny"] \
        + var["waste_cny"] + var["transport_cny"]

    # ---- risk reserve, downtime / failure -----------------------------------
    risk_pct = float((scenario.get("contingency") or {}).get("risk_reserve_pct", 0.0))
    failure_cost_cny = float((scenario.get("contingency") or {}).get("failure_cost_cny", 0.0))
    downtime_pct = float((scenario.get("contingency") or {}).get("downtime_pct", 0.0))
    risk_reserve = (base_capex + fixed_opex["total_cny"] + variable_opex_total) * risk_pct / 100.0
    downtime_cost = fixed_opex["total_cny"] * downtime_pct / 100.0
    failure_cost = failure_cost_cny  # rework / re-injection cost

    total_cost = base_capex + fixed_opex["total_cny"] + variable_opex_total \
        + risk_reserve + downtime_cost + failure_cost

    # ---- per-FU and scale-up -------------------------------------------------
    per_fu = {
        "capex_cny": base_capex * ratio,
        "fixed_opex_cny": fixed_opex["total_cny"] * ratio,
        "variable_opex_cny": variable_opex_total * ratio,
        "risk_reserve_cny": risk_reserve * ratio,
        "total_cost_cny": total_cost * ratio,
        "unit": "per functional unit",
        "per_m3_cny": total_cost * ratio / _fu_size_m3(functional_unit) if _fu_size_m3(functional_unit) else total_cost * ratio,
    }
    scale_up = scale_up_cost(base_capex, size_value, scope, exponent=None)

    return {
        "cost_results": {
            "capex_cny": base_capex,
            "fixed_opex_cny": fixed_opex["total_cny"],
            "variable_opex_cny": variable_opex_total,
            "risk_reserve_cny": risk_reserve,
            "downtime_cost_cny": downtime_cost,
            "failure_cost_cny": failure_cost,
            "total_cost_cny": total_cost,
            "currency": "CNY",
            "breakdown": var_breakdown,
        },
        "cost_components": {
            "capex": capex_in,
            "fixed_opex": fixed_opex,
            "variable_opex": var,
        },
        "per_fu": per_fu,
        "scale_up": scale_up,
        "warnings": warnings,
        "provenance": [{"source": p.get("source"), "tier": p.get("tier"),
                        "year": p.get("year"), "factor_id": p.get("factor_id")}
                       for p in var_breakdown],
    }


def scale_up_cost(reference_capex: float, target_size: float, scope: dict,
                  exponent: float | None = None) -> dict:
    """Exponential scale-up: capex = ref * (target / ref_size)^exponent.

    Default exponent 0.7 (process-plant convention). When scope lacks a
    reference size, scaling is reported as inapplicable rather than guessed.
    """
    ref_size = (scope.get("reference_scale") or {}).get("value") if isinstance(scope, dict) else None
    if ref_size is None or target_size <= 0:
        return {"applicable": False, "note": "no reference_scale declared; scale-up not computed"}
    exp = exponent if exponent is not None else 0.7
    scaled = reference_capex * (target_size / float(ref_size)) ** exp
    return {"applicable": True, "reference_capex_cny": reference_capex,
            "reference_size": float(ref_size), "target_size": target_size,
            "exponent": exp, "scaled_capex_cny": scaled}


def _scale_ratio(functional_unit: dict, scope: dict) -> float:
    from units import reference_flow_ratio
    return reference_flow_ratio(functional_unit, scope)


def _analysis_size(scope: dict) -> tuple[float, str]:
    size = (scope or {}).get("analysis_size") or {}
    v = size.get("value") if isinstance(size, dict) else None
    u = size.get("unit") if isinstance(size, dict) else "m3"
    if v is None:
        return 1.0, u
    return float(v), u


def _fu_size_m3(functional_unit: dict) -> float:
    ref = (functional_unit or {}).get("reference_flow") or {}
    if isinstance(ref, dict) and ref.get("unit") in ("m3",):
        return float(ref.get("value", 0.0))
    return 0.0
