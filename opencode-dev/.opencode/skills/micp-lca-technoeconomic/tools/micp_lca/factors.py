"""Materials / energy / cost factor database with provenance, and the
factory-gate cost price-tier model.

Every factor carries:
  - id            stable machine id (e.g. `gwp.urea`)
  - category      materials | energy | transport | waste | water | lab
  - value         numeric mean
  - unit          explicit unit (LCA-E203 if absent)
  - provenance    reference id resolved against references/sources.md
  - region        geographic validity (CN, CN-north, global, ...)
  - year          reference year (LCA-E208 if absent and not overridden)
  - version       factor version (e.g. "1.0.0")
  - uncertainty   {type: coefficient-of-variation, value: 0.xx}
  - note          short explanation of what the factor covers

Default factors come from references/sources.md (which the research agent
verified online). They are the *factory-gate* / average values. Field cost
tiers (`lab_catalogue`, `small_batch`, `industrial`) are applied separately
by the cost model via `price_tier`, and only when the caller declares a tier;
a lab catalogue price is never a field cost (LCA-E204).

The database is offline and deterministic; callers may supply their own
factors in the input envelope, which override defaults by factor id.
"""

from __future__ import annotations

from _common import ToolError, as_number
from errors import LcaErrorCode

FACTOR_DB_VERSION = "1.0.0"


def _f(fid: str, category: str, value: float, unit: str, source: str,
       region: str, year: int, cv: float, note: str = "") -> dict:
    return {
        "id": fid,
        "category": category,
        "value": value,
        "unit": unit,
        "provenance": source,
        "region": region,
        "year": year,
        "version": FACTOR_DB_VERSION,
        "uncertainty": {"type": "coefficient-of-variation", "value": cv},
        "note": note,
    }


# ids referenced from references/sources.md. Keep in sync when editing there.
# Values updated 2026-08-07 against verified sources (research agent); see
# references/sources.md for the DOI/URL behind every factor.
DEFAULT_FACTORS: dict[str, dict] = {
    # --- materials (per kg unless noted) -----------------------------------
    "gwp.cement_pc425": _f("gwp.cement_pc425", "materials", 0.62, "kg CO2eq/kg",
                           "IEA_2023_Cement", "global", 2020, 0.15,
                           "OPC cradle-to-gate GWP; IEA 2023 global avg ~0.60, China 2020 0.62 t/t"),
    "gwp.cement_dsm_cemi": _f("gwp.cement_dsm_cemi", "materials", 0.913, "kg CO2eq/kg",
                              "DSM_CEMI_EPD", "global", 2023, 0.10,
                              "CEM I A1-A3 for deep soil mixing (OneTunnel/EPD)"),
    "gwp.urea": _f("gwp.urea", "materials", 3.0, "kg CO2eq/kg",
                   "Urea_Coal_China", "CN", 2022, 0.20,
                   "Urea GWP coal-route (China mainstream) 2.7-3.43 kgCO2eq/kg"),
    "gwp.cacl2": _f("gwp.cacl2", "materials", 0.87, "kg CO2eq/kg",
                    "Ecoinvent2_CaCl2", "global", 2015, 0.25,
                    "CaCl2 industrial synthesis (Ecoinvent 2.2, Thai carbon-label)"),
    "gwp.calcium_lactate": _f("gwp.calcium_lactate", "materials", 1.5, "kg CO2eq/kg",
                              "LCA_CalciumLactate", "global", 2021, 0.35,
                              "Ca lactate GWP: DATA GAP — value is a placeholder, must verify before formal use"),
    "gwp.media_yeast": _f("gwp.media_yeast", "materials", 2.0, "kg CO2eq/kg",
                          "LCA_YeastExtract", "global", 2021, 0.35,
                          "Yeast extract / nutrient media, approximate"),
    "gwp.molasses": _f("gwp.molasses", "materials", 0.4, "kg CO2eq/kg",
                       "LCA_Molasses", "global", 2021, 0.30,
                       "Molasses (agro-byproduct) approximate"),
    "gwp.water_industrial": _f("gwp.water_industrial", "water", 0.00013, "kg CO2eq/L",
                               "WaterSupply_LCA", "CN", 2021, 0.30,
                               "Water supply GWP 0.12-0.14 kgCO2eq/m3 (Shanghai plant, verified)"),
    # --- energy ------------------------------------------------------------
    "gwp.electricity_cn_avg": _f("gwp.electricity_cn_avg", "energy", 0.5366, "kg CO2eq/kWh",
                                 "MEE_2022_grid", "CN", 2022, 0.10,
                                 "China 2022 national avg grid emission factor (MEE/NBS 2024-12公告)"),
    "gwp.electricity_cn_north": _f("gwp.electricity_cn_north", "energy", 0.6776, "kg CO2eq/kWh",
                                   "MEE_2022_grid_north", "CN-north", 2022, 0.12,
                                   "North-China regional grid factor 2022 (MEE)"),
    "gwp.electricity_cn_south": _f("gwp.electricity_cn_south", "energy", 0.3869, "kg CO2eq/kWh",
                                   "MEE_2022_grid_south", "CN-south", 2022, 0.12,
                                   "South-China regional grid factor 2022 (MEE)"),
    "gwp.electricity_global_avg": _f("gwp.electricity_global_avg", "energy", 0.475, "kg CO2eq/kWh",
                                     "IEA_2019_electricity", "global", 2019, 0.20,
                                     "IEA global average electricity emission factor (CodeCarbon default)"),
    "gwp.diesel": _f("gwp.diesel", "energy", 3.03, "kg CO2eq/L",
                     "GEMIS_v5", "global", 2023, 0.10,
                     "Diesel full life-cycle 3.015-3.055 kgCO2e/L (GEMIS v5); combustion-only 2.68"),
    "gwp.natural_gas": _f("gwp.natural_gas", "energy", 2.05, "kg CO2eq/kg",
                          "DEFRA_2023", "global", 2023, 0.10,
                          "Natural gas combustion factor"),
    "eut.urea_n": _f("eut.urea_n", "materials", 0.0010, "kg PO4eq/kg",
                     "CML2001_Nutrient", "global", 2015, 0.40,
                     "Eutrophication potential of urea-N release (approx)"),
    # --- transport ---------------------------------------------------------
    "gwp.transport_road": _f("gwp.transport_road", "transport", 0.10, "kg CO2eq/t-km",
                             "Truck_Freight_WTW", "CN", 2024, 0.25,
                             "Heavy-truck road freight WTW 0.09-0.12 kgCO2e/t-km"),
    "gwp.transport_shipping": _f("gwp.transport_shipping", "transport", 0.015, "kg CO2eq/t-km",
                                 "DEFRA_2023", "global", 2023, 0.30,
                                 "Ocean freight per t-km"),
    # --- waste treatment ---------------------------------------------------
    "gwp.wastewater_nh3_n_removal": _f("gwp.wastewater_nh3_n_removal", "waste", 5.0, "kg CO2eq/kg NH3-N",
                                       "WWTP_N", "global", 2020, 0.40,
                                       "N-removal via nitrification-denitrification energy+emissions"),
    "gwp.wastewater_ammonia_stripping": _f("gwp.wastewater_ammonia_stripping", "waste", 2.5, "kg CO2eq/kg NH3-N",
                                           "WWTP_Stripping", "global", 2020, 0.45,
                                           "Ammonia stripping (energy-intensive but N-recovered)"),
    "gwp.wastewater_anammox": _f("gwp.wastewater_anammox", "waste", 1.2, "kg CO2eq/kg NH3-N",
                                 "WWTP_Anammox", "global", 2020, 0.40,
                                 "Anammox deammonification, low-carbon route"),
    "gwp.sludge_landfill": _f("gwp.sludge_landfill", "waste", 60.0, "kg CO2eq/t wet",
                              "DEFRA_2023", "global", 2023, 0.40,
                              "Landfill disposal of dewatered sludge (wet)"),
    # --- primary energy content (MJ per unit; LHV basis where applicable) ---
    "en.electricity_cn": _f("en.electricity_cn", "energy", 8.5, "MJ/kWh",
                            "IEA_PrimaryEnergy", "CN", 2022, 0.20,
                            "primary-energy per kWh delivered (coal-heavy CN grid)"),
    "en.natural_gas": _f("en.natural_gas", "energy", 46.0, "MJ/kg",
                         "IPCC_2006", "global", 2015, 0.10,
                         "natural gas lower heating value"),
    "en.diesel": _f("en.diesel", "energy", 36.0, "MJ/L",
                    "IPCC_2006", "global", 2015, 0.05,
                    "diesel lower heating value"),
    "en.urea": _f("en.urea", "energy", 18.4, "MJ/kg",
                  "Porter2021_UreaEnergy", "global", 2021, 0.20,
                  "urea cradle-to-gate primary energy (gas-based ~18.4; coal higher)"),
    "en.cacl2": _f("en.cacl2", "energy", 11.76, "MJ/kg",
                   "Porter2021_CaCl2Energy", "global", 2021, 0.20,
                   "CaCl2 cradle-to-gate primary energy (Porter 2021)"),
    "en.cement": _f("en.cement", "energy", 6.21, "MJ/kg",
                    "Porter2021_CementEnergy", "global", 2021, 0.15,
                    "OPC cradle-to-gate primary energy (Porter 2021)"),
    "en.water_industrial": _f("en.water_industrial", "water", 0.015, "MJ/L",
                              "LCA_Water", "CN", 2021, 0.30,
                              "primary energy for industrial water supply"),
    "en.transport_road": _f("en.transport_road", "transport", 0.85, "MJ/t-km",
                            "GB_T22051_2015", "CN", 2015, 0.30,
                            "primary energy per t-km road freight"),
    # --- cost price tiers (factory gate; CNY per kg / per m3 / per kWh) ----
    "cost.urea": _f("cost.urea", "materials", 2.49, "CNY/kg",
                    "Cost_Urea_2023", "CN", 2023, 0.15,
                    "China urea avg 2023 ~2489 CNY/t (range 2070-2785); 2024 forecast 1900-2600"),
    "cost.cacl2": _f("cost.cacl2", "materials", 0.83, "CNY/kg",
                     "Cost_CaCl2_2024", "CN", 2024, 0.15,
                     "Industrial CaCl2 600-950 CNY/t (anhydrous ~950)"),
    "cost.calcium_lactate": _f("cost.calcium_lactate", "materials", 15.0, "CNY/kg",
                               "Cost_CalciumLactate", "CN", 2024, 0.30,
                               "industrial Ca-lactate price: DATA GAP, placeholder"),
    "cost.media_yeast": _f("cost.media_yeast", "materials", 25.0, "CNY/kg",
                           "Cost_YeastExtract", "CN", 2024, 0.30,
                           "yeast extract price"),
    "cost.molasses": _f("cost.molasses", "materials", 1.5, "CNY/kg",
                        "Cost_Molasses", "CN", 2024, 0.20, "molasses price"),
    "cost.water_industrial": _f("cost.water_industrial", "water", 4.0, "CNY/m3",
                                "Cost_Water", "CN", 2024, 0.15, "industrial water price"),
    "cost.electricity_cn_industrial": _f("cost.electricity_cn_industrial", "energy", 0.65, "CNY/kWh",
                                         "Cost_Electricity", "CN", 2024, 0.10,
                                         "industrial electricity tariff"),
    "cost.diesel_cn": _f("cost.diesel_cn", "energy", 7.0, "CNY/L",
                         "Cost_Diesel", "CN", 2024, 0.20, "diesel retail price"),
    "cost.natural_gas_cn": _f("cost.natural_gas_cn", "energy", 3.8, "CNY/kg",
                              "Cost_NaturalGas", "CN", 2024, 0.20, "natural gas industrial price"),
    "cost.trucking_cn": _f("cost.trucking_cn", "transport", 2.0, "CNY/t-km",
                           "Cost_Trucking", "CN", 2024, 0.25, "road freight rate per t-km"),
    "cost.cement_pc425": _f("cost.cement_pc425", "materials", 0.45, "CNY/kg",
                            "Cost_Cement", "CN", 2024, 0.12, "OPC 42.5 ex-factory price"),
    "cost.water_industrial_cn": _f("cost.water_industrial_cn", "water", 4.0, "CNY/m3",
                                   "Cost_Water", "CN", 2024, 0.15, "industrial water price"),
    "cost.wastewater_nh3_n_removal": _f("cost.wastewater_nh3_n_removal", "waste", 5.0, "CNY/kg NH3-N",
                                        "Cost_WWTP_N", "CN", 2024, 0.35,
                                        "N-removal (nitrification-denitrif) op cost 2-5 EUR/kg N"),
    "cost.wastewater_ammonia_stripping": _f("cost.wastewater_ammonia_stripping", "waste", 3.0, "CNY/kg NH3-N",
                                            "Cost_WWTP_Stripping", "CN", 2024, 0.35,
                                            "stripping op cost 1.8-10 CNY/kg NH4-N"),
    "cost.wastewater_anammox": _f("cost.wastewater_anammox", "waste", 15.6, "CNY/kg NH3-N",
                                  "Cost_WWTP_Anammox", "CN", 2024, 0.30,
                                  "anammox op cost 15.6 CNY/kg NH4-N (China full-scale 2024)"),
    "cost.labor_technician_cn": _f("cost.labor_technician_cn", "labor", 40.0, "CNY/h",
                                   "Cost_Labor", "CN", 2024, 0.25,
                                   "field technician labour (incl. overhead)"),
    "cost.labor_engineer_cn": _f("cost.labor_engineer_cn", "labor", 80.0, "CNY/h",
                                 "Cost_Labor", "CN", 2024, 0.25,
                                 "site engineer labour"),
    # --- lab catalogue prices (test/reagent scale; NEVER field costs) ------
    "lab.urea_reagent": _f("lab.urea_reagent", "lab", 0.15, "CNY/g",
                           "Cost_Lab_Urea", "CN", 2024, 0.40,
                           "lab reagent urea catalogue price (purity-grade)"),
    "lab.cacl2_reagent": _f("lab.cacl2_reagent", "lab", 0.08, "CNY/g",
                            "Cost_Lab_CaCl2", "CN", 2024, 0.40,
                            "lab reagent CaCl2 catalogue price"),
    "lab.media_reagent": _f("lab.media_reagent", "lab", 0.30, "CNY/g",
                            "Cost_Lab_Media", "CN", 2024, 0.40,
                            "lab reagent media catalogue price"),
}


class FactorDatabase:
    def __init__(self, overrides: list[dict] | None = None) -> None:
        self._db: dict[str, dict] = dict(DEFAULT_FACTORS)
        if overrides:
            for f in overrides:
                self._check_factor(f)
                self._db[f["id"]] = f

    @staticmethod
    def _check_factor(f: dict) -> None:
        fid = f.get("id")
        if not isinstance(fid, str) or not fid:
            raise ToolError(LcaErrorCode.FACTOR_UNKNOWN.code,
                            "custom factor must carry a non-empty string `id`",
                            details={"factor": f})
        if "value" not in f:
            raise ToolError(LcaErrorCode.FACTOR_REQUIRES_UNIT.code,
                            f"factor {fid!r} has no `value`",
                            details={"id": fid})
        as_number(f["value"], f"factors[{fid}].value")
        if not isinstance(f.get("unit"), str) or not f["unit"]:
            raise ToolError(LcaErrorCode.FACTOR_REQUIRES_UNIT.code,
                            f"factor {fid!r} must declare an explicit `unit`",
                            details={"id": fid})
        for key in ("provenance", "region"):
            if not isinstance(f.get(key), str) or not f[key]:
                raise ToolError(LcaErrorCode.FACTOR_UNVERIFIABLE.code,
                                f"factor {fid!r} must declare {key}",
                                details={"id": fid, "missing": key})
        f.setdefault("version", FACTOR_DB_VERSION)
        f.setdefault("uncertainty", {"type": "coefficient-of-variation", "value": 0.0})
        f.setdefault("category", _default_category(fid))
        if f.get("year") is None:
            raise ToolError(LcaErrorCode.DATA_YEAR_MISSING.code,
                            f"factor {fid!r} must declare a reference `year`",
                            details={"id": fid})

    def get(self, fid: str) -> dict:
        f = self._db.get(fid)
        if f is None:
            raise ToolError(LcaErrorCode.FACTOR_UNKNOWN.code,
                            f"factor {fid!r} is not in the factor database",
                            details={"known": sorted(self._db)})
        return dict(f)

    def has(self, fid: str) -> bool:
        return fid in self._db

    def all(self) -> dict[str, dict]:
        return {k: dict(v) for k, v in self._db.items()}

    def check_provenance(self, fid: str, analysis_year: int, max_stale_years: int = 5) -> list[str]:
        """Return non-fatal warnings when a factor is stale or provenance is weak.

        Expired factors raise LCA-E202 only when enforced by the caller;
        here we return a list of human-readable findings.
        """
        f = self.get(fid)
        warnings: list[str] = []
        if not f.get("provenance"):
            warnings.append(f"factor {fid}: missing provenance (unverifiable)")
        if not f.get("year"):
            warnings.append(f"factor {fid}: missing reference year")
        else:
            if analysis_year - int(f["year"]) > max_stale_years:
                warnings.append(
                    f"factor {fid}: reference year {f['year']} is stale/expired — "
                    f">{max_stale_years} years older than analysis year {analysis_year}")
        if not f.get("region"):
            warnings.append(f"factor {fid}: missing region")
        return warnings


# ---------------------------------------------------------------------------
# Price-tier scaling (factory gate -> small batch -> lab reagent)
# ---------------------------------------------------------------------------

PRICE_TIERS = ("industrial", "small_batch", "lab_catalogue")


def _default_category(fid: str) -> str:
    """Infer a factor category from its id prefix for custom overrides."""
    for prefix, cat in (("gwp.water", "water"), ("cost.water", "water"),
                        ("en.water", "water"), ("gwp.", "materials"),
                        ("en.", "energy"), ("cost.", "materials"),
                        ("eut.", "waste"), ("lab.", "lab")):
        if fid.startswith(prefix):
            return cat
    return "materials"

# Approximate catalogue-to-industrial multipliers per category, used ONLY to
# derive a small-batch / lab tier when the caller chooses that tier and no
# real quoted price is supplied. Lab tier is always flagged (LCA-E204
# warning) so it is never silently treated as a field cost.
_TIER_MULT: dict[str, float] = {
    "industrial": 1.0,
    "small_batch": 2.0,
    "lab_catalogue": 8.0,
}


def tier_price(industrial_price: float, tier: str, category: str = "materials") -> tuple[float, bool]:
    """Scale an industrial (factory-gate) unit price to a tier.

    Returns (price, lab_flag) where lab_flag=True only for lab_catalogue.
    """
    if tier not in PRICE_TIERS:
        raise ToolError(LcaErrorCode.INPUT_SCHEMA_VIOLATION.code,
                        f"price tier must be one of {list(PRICE_TIERS)}",
                        details={"tier": tier})
    mult = _TIER_MULT[tier]
    return industrial_price * mult, (tier == "lab_catalogue")
