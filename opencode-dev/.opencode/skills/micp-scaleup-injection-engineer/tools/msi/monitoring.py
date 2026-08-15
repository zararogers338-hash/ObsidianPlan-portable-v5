"""Monitoring plan and real-time alarm module for MICP scale-up.

The monitoring plan maps every required parameter to location, frequency,
equipment, thresholds (alarm/stop), alarm action, stop rule and data
retention. The `evaluate_monitoring` function consumes real-time readings
(`monitoring` block in the input) and fires alerts / stop signals against the
plan thresholds.

Threshold design notes:
  - NH4-N stop threshold: from site ammonia limit (constraints.ammonia_limit_mg_L)
  - injection pressure alarm/stop: from pressure check (allowable limit)
  - pH: ureolysis raises pH toward 9; alarm if > 9.5 or drift fast
  - EC: tracks ionic strength; alarm on sudden jump (precipitation front)
  - Ca2+ depletion downstream of the front indicates precipitation progress
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from .errors import OpError, OpErrorCode
from .scenario import NormalizedScenario
from .units import check_finite


def _loc(id_: str, kind: str) -> dict[str, Any]:
    return {"id": id_, "type": kind}


def build_monitoring_plan(s: NormalizedScenario, pressure_limit_pa: float | None,
                          ammonia_limit_mg_L: float | None) -> dict[str, Any]:
    # A missing ammonia limit must NOT be silently replaced by a fabricated
    # 50 mg/L (environment auditor blocker). A limit of 0 (no-discharge) is a
    # legitimate value and must be honored.
    ammonia_stop = ammonia_limit_mg_L
    ammonia_alarm = None
    if ammonia_stop is not None:
        ammonia_alarm = 0.8 * ammonia_stop
    p_alarm = 0.7 * pressure_limit_pa if pressure_limit_pa else None
    p_stop = pressure_limit_pa

    params: list[dict[str, Any]] = [
        {
            "name": "injection_pressure",
            "locations": [_loc("IW-1", "injection_line")],
            "frequency": "continuous (1 Hz log)",
            "equipment": "pressure transducer + datalogger",
            "thresholds": {
                "alarm_low": None, "alarm_high": p_alarm, "stop_low": None, "stop_high": p_stop,
                "units": "Pa",
            },
            "alarm": "reduce rate / pause phase",
            "stop_rule": "STOP if pressure > allowable (or >80% fracture pressure)",
            "data_save": "raw + 1 min rolling mean to datalogger; CSV + cloud backup",
        },
        {
            "name": "flow_rate",
            "locations": [_loc("IW-1", "injection_line"), _loc("EW-1", "extraction_line")],
            "frequency": "continuous (1 Hz)",
            "equipment": "magnetic flow meter",
            "thresholds": {
                "alarm_low": None, "alarm_high": None, "stop_low": None, "stop_high": None,
                "units": "m3/s",
            },
            "alarm": "flow imbalance between inject/extract -> possible surface breakout",
            "stop_rule": "STOP if injection/extraction imbalance > 20% sustained",
            "data_save": "raw + cumulative volume integrator",
        },
        {
            "name": "cumulative_volume",
            "locations": [_loc("IW-1", "injection_line")],
            "frequency": "continuous (totalizer)",
            "equipment": "totalizer / flow integrator",
            "thresholds": {"alarm_low": None, "alarm_high": None, "stop_low": None,
                           "stop_high": None, "units": "m3"},
            "alarm": "compare against planned phase volume",
            "stop_rule": "STOP phase at planned volume (volume-limited rounds)",
            "data_save": "phase log with timestamps",
        },
        {
            "name": "pH",
            "locations": [_loc("IW-1", "injection_line"), _loc("MW-1", "monitoring_well")],
            "frequency": "every 15 min during injection",
            "equipment": "inline pH probe (calibrated)",
            "thresholds": {"alarm_low": 6.5, "alarm_high": 9.5, "stop_low": 6.0,
                           "stop_high": 10.0, "units": "-"},
            "alarm": "pH rise >9.5 indicates active ureolysis; drop <6.5 probe fault",
            "stop_rule": "STOP if pH < 6.0 or > 10.0 (probe check / dosing fault)",
            "data_save": "pH log + calibration records",
        },
        {
            "name": "EC",
            "locations": [_loc("IW-1", "injection_line"), _loc("EW-1", "extraction_line")],
            "frequency": "every 15 min",
            "equipment": "conductivity probe",
            "thresholds": {"alarm_low": None, "alarm_high": None, "stop_low": None,
                           "stop_high": None, "units": "mS/cm"},
            "alarm": "sudden EC jump = precipitation front; steady decline = reagent exhaustion",
            "stop_rule": "no hard stop; trend-based advisory",
            "data_save": "EC log + correlation with Ca/urea samples",
        },
        {
            "name": "temperature",
            "locations": [_loc("IW-1", "injection_line")],
            "frequency": "every 15 min",
            "equipment": "thermocouple / RTD",
            "thresholds": {"alarm_low": 5.0, "alarm_high": 40.0, "stop_low": 2.0,
                           "stop_high": 45.0, "units": "degC"},
            "alarm": "out of ureolysis-active window slows kinetics",
            "stop_rule": "STOP if <2 C or >45 C (kinetics/equipment)",
            "data_save": "temperature log",
        },
        {
            "name": "ca_conc",
            "locations": [_loc("MW-1", "monitoring_well"), _loc("EW-1", "extraction_line")],
            "frequency": "per round (grab sample, lab)",
            "equipment": "EDTA titration / ICP / colorimetric kit",
            "thresholds": {"alarm_low": None, "alarm_high": None, "stop_low": None,
                           "stop_high": None, "units": "mol/m3"},
            "alarm": "Ca breakthrough at monitoring well = front arrival",
            "stop_rule": "advisory: adjust rounds based on Ca depletion profile",
            "data_save": "sample log with lab results",
        },
        {
            "name": "nh4_conc",
            "locations": [_loc("EW-1", "extraction_line")],
            "frequency": "per round (grab sample, lab)",
            "equipment": "Nessler / ion-selective / colorimetric",
            "thresholds": {"alarm_low": None, "alarm_high": ammonia_alarm, "stop_low": None,
                           "stop_high": ammonia_stop, "units": "mg/L NH4-N"},
            "alarm": ("near discharge limit -> route to treatment"
                      if ammonia_alarm is not None else
                      "no discharge limit provided — set constraints.ammonia_limit_mg_L"),
            "stop_rule": ("STOP injection if effluent NH4-N > site limit (ammonia gate)"
                          if ammonia_stop is not None else
                          "discharge limit not set — effluent must NOT be discharged until "
                          "a limit is established"),
            "data_save": "effluent sample log + mass balance of NH4-N",
        },
        {
            "name": "urea_conc",
            "locations": [_loc("EW-1", "extraction_line")],
            "frequency": "per round (grab sample, lab)",
            "equipment": "urease/colorimetric assay",
            "thresholds": {"alarm_low": None, "alarm_high": None, "stop_low": None,
                           "stop_high": None, "units": "mol/m3"},
            "alarm": "unreacted urea in effluent = low conversion",
            "stop_rule": "advisory: increase retention time",
            "data_save": "effluent sample log",
        },
        {
            "name": "tracer",
            "locations": [_loc("MW-1", "monitoring_well")],
            "frequency": "one pulse at start + breakthrough sampling",
            "equipment": "fluorometer / conductivity for NaCl tracer",
            "thresholds": {"alarm_low": None, "alarm_high": None, "stop_low": None,
                           "stop_high": None, "units": "-"},
            "alarm": "early breakthrough / low recovery = preferential flow",
            "stop_rule": "advisory: re-zone treatment if recovery < 70%",
            "data_save": "breakthrough curve file",
        },
        {
            "name": "shear_wave_velocity",
            "locations": [_loc("MW-1", "monitoring_well"), _loc("surface", "surface")],
            "frequency": "after each round (MASW/bender)",
            "equipment": "MASW / bender elements / geophones",
            "thresholds": {"alarm_low": None, "alarm_high": None, "stop_low": None,
                           "stop_high": None, "units": "m/s"},
            "alarm": "Vs gain < expected = poor cementation progress",
            "stop_rule": "advisory: additional rounds if Vs gain lags plan",
            "data_save": "Vs profile per monitoring line",
        },
        {
            "name": "groundwater_indicators",
            "locations": [_loc("MW-1", "monitoring_well"), _loc("MW-2", "monitoring_well")],
            "frequency": "daily during treatment + weekly after",
            "equipment": "downhole sampler + lab analysis",
            "thresholds": {"alarm_low": None, "alarm_high": None, "stop_low": None,
                           "stop_high": None, "units": "-"},
            "alarm": "off-site plume detection",
            "stop_rule": "STOP and contain if groundwater indicator exceeds baseline",
            "data_save": "groundwater monitoring record",
        },
    ]

    plan = {
        "parameters": params,
        "sampling_schedule": {
            "baseline": "2-4 weeks before injection (soil + groundwater + geophysics)",
            "during_injection": "pressure/flow continuous; pH/EC/温度 every 15 min; "
                                "chemistry grab per round",
            "post_treatment": "core sampling + Vs + CPT at 7/28/90 days; groundwater "
                              "recovery monitoring until NH4-N < limit",
        },
        "data_management": {
            "storage": "datalogger CSV + cloud backup; immutable append-only (SHA-256 "
                       "chain per project convention)",
            "retention": "project lifetime + 5 years (environmental records)",
            "audit": "calibration log per instrument; chain-of-custody for samples",
        },
    }
    return plan


def evaluate_monitoring(s: NormalizedScenario, plan: dict[str, Any], readings: dict[str, Any]) -> dict[str, Any]:
    """Evaluate real-time readings against the plan thresholds.

    Returns {alerts: [...], stop_signals: [...], pass: bool}. Stop signals
    correspond to the plan's stop rules; any stop -> the caller must emit
    stop_conditions + fallback in the output.
    """
    alerts: list[str] = []
    stops: list[str] = []
    pressure_limit = None
    ammonia_stop = None
    if s.allowed_injection_pressure_pa is not None:
        pressure_limit = s.allowed_injection_pressure_pa
    if s.ammonia_limit_mg_L is not None:
        ammonia_stop = s.ammonia_limit_mg_L

    if not readings:
        return {"alerts": alerts, "stop_signals": stops, "pass": True}

    def num(key: str) -> float | None:
        v = readings.get(key)
        if v is None:
            return None
        return check_finite(f"monitoring.{key}", float(v))

    p = num("injection_pressure_pa")
    if p is not None and pressure_limit:
        if p > pressure_limit:
            stops.append(f"injection_pressure {p / 1e5:.2f} bar > allowable "
                         f"{pressure_limit / 1e5:.2f} bar — STOP (pressure gate)")
        elif p > 0.7 * pressure_limit:
            alerts.append(f"injection_pressure {p / 1e5:.2f} bar > 70% of allowable — reduce rate")

    q = num("flow_rate_m3_s")
    qe = num("extraction_flow_rate_m3_s") if "extraction_flow_rate_m3_s" in readings else None
    if q is not None and qe is not None and q > 0:
        imbalance = abs(q - qe) / q
        if imbalance > 0.2:
            alerts.append(f"injection/extraction imbalance {imbalance * 100:.0f}% — check breakout")

    nh4 = num("nh4_conc_mol_m3")
    if nh4 is not None:
        nh4_mgL = nh4 * 14.007  # mol/m3 NH4-N -> mg/L NH4-N
        if ammonia_stop and nh4_mgL > ammonia_stop:
            stops.append(f"effluent NH4-N {nh4_mgL:.0f} mg/L > site limit "
                         f"{ammonia_stop:.0f} mg/L — STOP (ammonia gate)")
        elif ammonia_stop and nh4_mgL > 0.8 * ammonia_stop:
            alerts.append(f"effluent NH4-N {nh4_mgL:.0f} mg/L near limit "
                          f"{ammonia_stop:.0f} mg/L — route to treatment")

    ph = num("ph")
    if ph is not None:
        if ph < 6.0 or ph > 10.0:
            stops.append(f"pH {ph:.1f} out of [6,10] — STOP (probe/dosing fault)")
        elif ph > 9.5:
            alerts.append(f"pH {ph:.1f} high — active ureolysis; check dosing")

    t = num("temperature_c")
    if t is not None and (t < 2.0 or t > 45.0):
        stops.append(f"temperature {t:.1f} C out of [2,45] — STOP (kinetics/equipment)")

    v = num("cumulative_volume_m3")
    planned = readings.get("_planned_volume_m3")
    if v is not None and planned is not None and v >= planned:
        alerts.append(f"cumulative volume {v:.2f} m3 reached planned {planned:.2f} m3 "
                      "- volume-limited round complete")

    # Groundwater / off-site plume detection (environment auditor): a reading
    # in a monitoring well beyond the site baseline is a hard stop+containment.
    gw_nh4 = num("groundwater_nh4_mol_m3")
    gw_ec = num("groundwater_ec_ms_cm")
    gw_baseline_nh4 = readings.get("groundwater_baseline_nh4_mol_m3")
    if gw_nh4 is not None:
        baseline = gw_baseline_nh4 if gw_baseline_nh4 is not None else 0.0
        if gw_nh4 > baseline + 1e-9:
            stops.append(f"groundwater monitoring well NH4-N {gw_nh4:.2f} mol/m3 exceeds "
                         f"baseline {baseline:.2f} — STOP and contain (off-site plume risk)")
    if gw_ec is not None:
        gw_ec_base = readings.get("groundwater_baseline_ec_ms_cm")
        if gw_ec_base is not None and gw_ec > gw_ec_base * 1.5:
            stops.append(f"groundwater EC {gw_ec:.1f} mS/cm > 1.5x baseline "
                         f"{gw_ec_base:.1f} — STOP and contain (plume detection)")

    return {"alerts": alerts, "stop_signals": stops, "pass": len(stops) == 0}
