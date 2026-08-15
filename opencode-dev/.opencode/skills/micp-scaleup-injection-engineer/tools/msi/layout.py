"""Injection layout (well array, zones) for MICP scale-up.

Builds a deterministic well array from the caller's `wells` spec (pattern,
spacing, injection radius) or a sensible default per scale level, plus zoned
volumes per layer for layer-selective treatment of heterogeneous profiles.

The layout is an engineering draft — field borehole positions must be finalized
by the geotechnical engineer under the approval gate (MSI-E502).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from .errors import OpError, OpErrorCode
from .material import material_balance
from .scenario import NormalizedScenario
from .units import check_finite


def _square_ring(n: int) -> list[tuple[float, float]]:
    """n points evenly spaced on a ring of radius 1 around the origin."""
    return [(math.cos(2 * math.pi * i / n), math.sin(2 * math.pi * i / n)) for i in range(n)]


def build_layout(s: NormalizedScenario) -> dict[str, Any]:
    wells_spec = {}  # filled below if caller provided
    # Note: raw wells spec is read via the service (which passes it here).
    wells_raw = getattr(s, "_wells_raw", None)
    if wells_raw:
        wells_spec = wells_raw

    pattern = (wells_spec.get("pattern") or
               (s.scale_level if s.scale_level in ("site", "field") else None) or
               "line_drive")
    radius = s.target_radius_m
    spacing = None
    if wells_spec.get("spacing") is not None:
        spacing = check_finite("wells.spacing", wells_spec["spacing"].get("value", wells_spec["spacing"])
                               if isinstance(wells_spec["spacing"], dict) else wells_spec["spacing"])

    # default injection/well radii by scale
    well_radius = 0.05
    if s.scale_level == "pilot_column":
        well_radius = 0.02
    elif s.scale_level == "metre":
        well_radius = 0.03

    # Build the array.
    wells: list[dict[str, Any]] = []
    if s.scale_level in ("site", "field"):
        # Triangular or 5-spot pattern of injection wells, plus extraction ring.
        if pattern == "triangular":
            positions = [(0.0, 0.0)] + _square_ring(3)  # centre + triangle ring
        elif pattern == "five_spot":
            positions = [(0.0, 0.0), (1.0, 0.0), (0.0, 1.0), (-1.0, 0.0), (0.0, -1.0)]
        else:  # square / line_drive
            positions = [(0.0, 0.0), (1.0, 0.0), (0.0, 1.0), (-1.0, 0.0), (0.0, -1.0)]
        n_inj = len(positions)
        for i, (dx, dy) in enumerate(positions):
            wells.append({
                "id": f"IW-{i + 1}",
                "type": "injection",
                "x": round(dx, 3),
                "y": round(dy, 3),
                "depth": s.target_depth_m,
                "radius": well_radius,
            })
        # extraction wells on the perimeter
        for i, (dx, dy) in enumerate(_square_ring(max(4, n_inj))):
            wells.append({
                "id": f"EW-{i + 1}",
                "type": "extraction",
                "x": round(dx * 1.8, 3),
                "y": round(dy * 1.8, 3),
                "depth": s.target_depth_m,
                "radius": well_radius,
            })
        # monitoring wells between injection and extraction
        for i, (dx, dy) in enumerate(_square_ring(max(3, n_inj - 1))):
            wells.append({
                "id": f"MW-{i + 1}",
                "type": "monitoring",
                "x": round(dx * 1.35, 3),
                "y": round(dy * 1.35, 3),
                "depth": s.target_depth_m,
                "radius": 0.025,
            })
    else:
        # pilot / metre: single injection point, monitoring points along path
        wells.append({"id": "IW-1", "type": "injection", "x": 0.0, "y": 0.0,
                      "depth": s.target_depth_m, "radius": well_radius})
        for i in range(1, 4):
            wells.append({"id": f"MW-{i}", "type": "monitoring",
                          "x": round(i * (radius / 3.0 if radius else 0.33), 3), "y": 0.0,
                          "depth": s.target_depth_m, "radius": 0.025})

    # zones: per-layer volumes for layer-selective injection
    zones: list[dict[str, Any]] = []
    if s.layers and s.target_volume_m3 is not None:
        total_h = sum(lyr.thickness_m for lyr in s.layers)
        if total_h > 0:
            for lyr in s.layers:
                frac = lyr.thickness_m / total_h
                zones.append({
                    "zone_id": f"Z-{lyr.name}",
                    "layer": lyr.name,
                    "thickness_m": lyr.thickness_m,
                    "volume_m3": round(s.target_volume_m3 * frac, 3),
                    "porosity": lyr.porosity,
                    "permeability_m2": lyr.permeability_m2,
                    "injection_points": [w["id"] for w in wells if w["type"] == "injection"],
                })

    # injection radius at each well (volume footprint) — simple subdivision
    layout = {
        "pattern": pattern,
        "wells": wells,
        "zones": zones,
        "injection_radius": radius,
        "spacing": spacing,
        "notes": [
            "Draft layout only — final borehole positions require geotechnical "
            "engineer sign-off (field gate).",
            "Extraction wells balance flow and pull treatment through low-k layers.",
            "Zone-based injection (packers / perforated intervals) is recommended "
            "for heterogeneous profiles (clogging_risk.preferential_flow_risk).",
        ],
    }
    return layout
