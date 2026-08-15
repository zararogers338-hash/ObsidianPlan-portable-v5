"""Injection schedule: sequence, phases, pulse strategy, retention time, rounds.

Builds a deterministic schedule from the normalized scenario:
  phases: bacteria -> fixation (optional) -> cementation rounds -> flushing
  pulse strategy: continuous | pulsed | alternating | sequential
  retention time between phases
  rounds from material balance (conversion-limited)
  flushing PV at end

The schedule is engineering design output; durations are estimates that must
be confirmed at pilot.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from .errors import OpError, OpErrorCode
from .material import material_balance
from .scenario import NormalizedScenario
from .units import check_finite


def build_schedule(s: NormalizedScenario, mb: Any) -> dict[str, Any]:
    rounds = mb.rounds
    if rounds is None:
        # estimate rounds from target content vs per-round deposition
        if (mb.caco3_mol and s.lab_urea_conc_mol_m3 and mb.pore_volume_m3
                and mb.pore_volume_m3 > 0 and mb.conversion_efficiency):
            per_round_mol = s.lab_urea_conc_mol_m3 * mb.pore_volume_m3 * mb.conversion_efficiency
            rounds = max(1, math.ceil(mb.caco3_mol / per_round_mol))
        else:
            rounds = 3  # conservative default; flagged as estimate

    pulse = s.pulse_strategy or "continuous"
    retention = s.retention_time_s
    flushing_pv = s.flushing_pv or 2.0

    # per-phase volumes
    cementation_vol = mb.cementation_volume_m3 or 0.0
    bacteria_vol = mb.bacteria_volume_m3 or 0.0
    per_round_vol = cementation_vol / max(rounds, 1)
    flushing_vol = mb.pore_volume_m3 * flushing_pv if mb.pore_volume_m3 else 0.0

    phases: list[dict[str, Any]] = []
    order = 0
    if bacteria_vol > 0:
        phases.append({
            "phase": "bacteria",
            "order": order,
            "duration_days": _duration(bacteria_vol, mb.injection_flow_m3_s),
            "volumes_m3": bacteria_vol,
            "flow_mode": "constant_flux",
            "flow_rate_m3_s": mb.injection_flow_m3_s,
            "retention_time_s": retention,
        })
        order += 1
    # cementation rounds
    for r in range(1, rounds + 1):
        phases.append({
            "phase": "cementation",
            "order": order,
            "duration_days": _duration(per_round_vol, mb.injection_flow_m3_s),
            "volumes_m3": per_round_vol,
            "round": r,
            "flow_mode": s.lab_flow_mode or "constant_flux",
            "flow_rate_m3_s": mb.injection_flow_m3_s,
            "retention_time_s": retention,
            "pulse": pulse,
        })
        order += 1
    if flushing_vol > 0:
        phases.append({
            "phase": "flushing",
            "order": order,
            "duration_days": _duration(flushing_vol, mb.injection_flow_m3_s),
            "volumes_m3": flushing_vol,
            "flow_mode": "constant_flux",
            "flow_rate_m3_s": mb.injection_flow_m3_s,
            "note": "flush to recover residual ammonium and unreacted reagents",
        })
        order += 1

    total_days = sum(p.get("duration_days", 0.0) or 0.0 for p in phases)
    if retention is not None and len(phases) >= 2:
        # A retention pause sits between consecutive phases (len(phases)-1
        # gaps) — never len(phases)+1, and never a phantom pause.
        total_days += retention * (len(phases) - 1) / 86400.0

    sequence = [p["phase"] for p in phases]

    return {
        "phases": phases,
        "sequence": sequence,
        "pulse_strategy": pulse,
        "retention_time_s": retention,
        "rounds": rounds,
        "flushing_pv": flushing_pv,
        "total_duration_days": round(total_days, 2),
        "notes": [
            "durations are estimates from total volume / design flow; confirm at pilot",
            "sequential bacteria -> cementation prevents mixed-flocculation clogging (VP2010)",
        ],
    }


def _duration(volume_m3: float, flow_m3_s: float | None) -> float:
    if not flow_m3_s or flow_m3_s <= 0 or volume_m3 <= 0:
        return 0.0
    return round(volume_m3 / flow_m3_s / 86400.0, 3)
