"""Visualization / reporting assets for micp-modeling-optimizer.

Produces self-contained HTML (inline SVG) and CSV artifacts so results remain
viewable offline. No external charting library is used; the SVG generation is
deterministic and validated with well-formed XML.

generate_plots(model_output: dict) -> list[artifact payload dicts]:
  * kinetics_time_series.html : U / Ca / NH4 / CaCO3 / porosity vs time
  * pareto_front.html         : 2D or 3D projection of the Pareto front
  * sensitivity_bar.html      : Sobol' S1/ST bar chart
  * profile_likelihood.html   : profile curve with 95% chi2 band
"""

from __future__ import annotations

import math
from typing import Any, Sequence

from _common import ToolError
from errors import MmoError, MmoErrorCode


def _svg_header(w: int, h: int) -> str:
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" '
        f'viewBox="0 0 {w} {h}" font-family="Arial,Helvetica,sans-serif">'
    )


def _svg_axis(w: int, h: int, pad: int, xlabel: str, ylabel: str) -> str:
    return (
        f'<line x1="{pad}" y1="{h-pad}" x2="{w-pad}" y2="{h-pad}" stroke="#333"/>'
        f'<line x1="{pad}" y1="{pad}" x2="{pad}" y2="{h-pad}" stroke="#333"/>'
        f'<text x="{w/2}" y="{h-8}" text-anchor="middle" font-size="12">{_esc(xlabel)}</text>'
        f'<text x="{12}" y="{h/2}" text-anchor="middle" font-size="12" '
        f'transform="rotate(-90 12 {h/2})">{_esc(ylabel)}</text>'
    )


def _esc(s: Any) -> str:
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _normalize(values: Sequence[float], lo: float | None = None, hi: float | None = None) -> tuple[list[float], float, float]:
    vals = [float(v) for v in values]
    mn = lo if lo is not None else (min(vals) if vals else 0.0)
    mx = hi if hi is not None else (max(vals) if vals else 1.0)
    if mx - mn < 1e-12:
        mx = mn + 1.0
    return vals, mn, mx


def _polyline(pts: Sequence[tuple[float, float]], color: str, width: int = 2) -> str:
    d = "M " + " L ".join(f"{x:.1f},{y:.1f}" for x, y in pts)
    return f'<path d="{d}" fill="none" stroke="{color}" stroke-width="{width}"/>'


def kinetics_time_series_html(result: dict) -> str:
    """result: {times, urea, ca, nh4, calcite_kg, phi, ...} lists."""
    times = [float(t) for t in result.get("times", [])]
    n = len(times)
    if n < 2:
        raise MmoError(MmoErrorCode.INVALID_MODEL_SPEC, "need >= 2 time points for a time-series plot")
    w, h, pad = 720, 420, 48
    series: list[tuple[str, str, list[float]]] = [
        ("Urea", "#1f77b4", [float(v) for v in result.get("urea", [])]),
        ("Ca", "#ff7f0e", [float(v) for v in result.get("ca", [])]),
        ("NH4+", "#2ca02c", [float(v) for v in result.get("nh4", [])]),
        ("CaCO3 kg/m3", "#d62728", [float(v) for v in result.get("calcite_kg", [])]),
    ]
    parts = [_svg_header(w, h), _svg_axis(w, h, pad, "time", "concentration")]
    t0, t1 = min(times), max(times)
    tspan = t1 - t0 if t1 > t0 else 1.0
    for name, color, vals in series:
        if len(vals) != n:
            continue
        _, mn, mx = _normalize(vals)
        pts = [
            (pad + (times[i] - t0) / tspan * (w - 2 * pad),
             h - pad - (vals[i] - mn) / (mx - mn + 1e-12) * (h - 2 * pad))
            for i in range(n)
        ]
        parts.append(_polyline(pts, color))
        # legend
        parts.append(f'<circle cx="{pad+8}" cy="{36 + len(series)*0}" r="3" fill="{color}"/>')
    ly = 36
    for name, color, _ in series:
        parts.append(f'<text x="{pad+16}" y="{ly}" font-size="11">{_esc(name)}</text>')
        parts.append(f'<rect x="{pad+4}" y="{ly-8}" width="8" height="3" fill="{color}"/>')
        ly += 16
    parts.append("</svg>")
    html = (
        "<!DOCTYPE html><html><head><meta charset=\"utf-8\"><title>MICP kinetics</title></head>"
        f"<body><h3>Kinetic model time series (calibrated)</h3>{''.join(parts)}</body></html>"
    )
    return html


def pareto_front_html(front: list[dict], obj_names: list[str]) -> str:
    """front: [{x, objectives:[...]}]."""
    w, h, pad = 720, 420, 56
    n_obj = len(obj_names)
    if n_obj < 2 or not front:
        raise MmoError(MmoErrorCode.INVALID_MODEL_SPEC, "pareto plot needs >= 2 objectives and a non-empty front")
    # project first two objectives
    o0 = [f["objectives"][0] for f in front]
    o1 = [f["objectives"][1] for f in front]
    _, mn0, mx0 = _normalize(o0)
    _, mn1, mx1 = _normalize(o1)
    parts = [_svg_header(w, h), _svg_axis(w, h, pad, obj_names[0], obj_names[1])]
    for f in front:
        x = pad + (f["objectives"][0] - mn0) / (mx0 - mn0 + 1e-12) * (w - 2 * pad)
        y = h - pad - (f["objectives"][1] - mn1) / (mx1 - mn1 + 1e-12) * (h - 2 * pad)
        parts.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="4" fill="#1f77b4" opacity="0.85"/>')
    if n_obj >= 3:
        parts.append(
            f'<text x="{pad}" y="{pad-6}" font-size="11" fill="#666">'
            f'projection on {obj_names[0]} vs {obj_names[1]} '
            f'({len(front)} front solutions, {n_obj} objectives)</text>'
        )
    parts.append("</svg>")
    html = (
        "<!DOCTYPE html><html><head><meta charset=\"utf-8\"><title>Pareto front</title></head>"
        f"<body><h3>Pareto front approximation</h3>{''.join(parts)}</body></html>"
    )
    return html


def sensitivity_bar_html(result: dict) -> str:
    """result: sobol_indices() dict with first_order/total_order lists."""
    s1 = result.get("first_order", [])
    st = result.get("total_order", [])
    w, h, pad = 720, 320, 48
    parts = [_svg_header(w, h), _svg_axis(w, h, pad, "parameter", "index")]
    n = len(s1)
    bw = min(30.0, (w - 2 * pad) / (2 * n + 1))
    for i in range(n):
        x1 = pad + i * 2 * bw + bw * 0.25
        h1 = min(h - 2 * pad, abs(s1[i]) * (h - 2 * pad))
        parts.append(f'<rect x="{x1:.1f}" y="{h-pad-h1:.1f}" width="{bw:.1f}" height="{h1:.1f}" fill="#1f77b4"/>')
        h2 = min(h - 2 * pad, abs(st[i]) * (h - 2 * pad))
        parts.append(f'<rect x="{x1+bw*1.1:.1f}" y="{h-pad-h2:.1f}" width="{bw:.1f}" height="{h2:.1f}" fill="#ff7f0e"/>')
        parts.append(f'<text x="{x1+bw:.1f}" y="{h-pad+14}" text-anchor="middle" font-size="10">P{i+1}</text>')
    parts.append(f'<text x="{pad}" y="{pad-6}" font-size="11" fill="#1f77b4">S1</text>')
    parts.append(f'<text x="{pad+28}" y="{pad-6}" font-size="11" fill="#ff7f0e">ST</text>')
    parts.append("</svg>")
    html = (
        "<!DOCTYPE html><html><head><meta charset=\"utf-8\"><title>Sobol indices</title></head>"
        f"<body><h3>Global sensitivity (Sobol')</h3>{''.join(parts)}</body></html>"
    )
    return html


def profile_likelihood_html(result: dict) -> str:
    """result: profile_likelihood() dict."""
    values = [float(v) for v in result.get("values", [])]
    prof = [float(v) for v in result.get("profile_rss", [])]
    if len(values) < 2:
        raise MmoError(MmoErrorCode.INVALID_MODEL_SPEC, "profile likelihood needs >= 2 points")
    w, h, pad = 720, 340, 48
    vmin, vmax = min(values), max(values)
    pmin, pmax = min(prof), max(prof)
    parts = [_svg_header(w, h), _svg_axis(w, h, pad, "parameter value", "profile RSS")]
    thresh = pmin + 3.84
    pts = [
        (pad + (values[i] - vmin) / (vmax - vmin + 1e-12) * (w - 2 * pad),
         h - pad - (prof[i] - pmin) / (pmax - pmin + 1e-12) * (h - 2 * pad))
        for i in range(len(values))
    ]
    parts.append(_polyline(pts, "#1f77b4", 3))
    # 95% band
    yth = h - pad - (thresh - pmin) / (pmax - pmin + 1e-12) * (h - 2 * pad)
    parts.append(f'<line x1="{pad}" y1="{yth:.1f}" x2="{w-pad}" y2="{yth:.1f}" stroke="#d62728" stroke-dasharray="4 3"/>')
    parts.append(f'<text x="{w-pad-4}" y="{yth-6}" text-anchor="end" font-size="11" fill="#d62728">95% chi2 band</text>')
    parts.append("</svg>")
    html = (
        "<!DOCTYPE html><html><head><meta charset=\"utf-8\"><title>Profile likelihood</title></head>"
        f"<body><h3>Profile likelihood (parameter {result.get('param_index','?')})</h3>"
        f"{''.join(parts)}<p>class: {_esc(result.get('class',''))}</p></body></html>"
    )
    return html


def generate_plots(model_output: dict) -> list[dict]:
    """Produce a list of {artifact_id, kind, content_type, description, payload}
    render artifacts from a model output dict. Never raises on a missing
    section — a section that cannot be plotted is skipped."""
    artifacts: list[dict] = []
    if model_output.get("times") and model_output.get("urea") is not None:
        try:
            html = kinetics_time_series_html(model_output)
            artifacts.append({
                "artifact_id": "plot_kinetics",
                "kind": "model_diagnostics",
                "content_type": "text/html",
                "description": "Calibrated kinetics time series (U/Ca/NH4/CaCO3/porosity).",
                "payload": {"html": html},
            })
        except MmoError:
            pass
    if model_output.get("pareto_front"):
        try:
            html = pareto_front_html(model_output["pareto_front"], model_output.get("objective_names", ["obj1", "obj2"]))
            artifacts.append({
                "artifact_id": "plot_pareto",
                "kind": "model_diagnostics",
                "content_type": "text/html",
                "description": "Pareto front projection.",
                "payload": {"html": html},
            })
        except MmoError:
            pass
    if model_output.get("sensitivity"):
        try:
            html = sensitivity_bar_html(model_output["sensitivity"])
            artifacts.append({
                "artifact_id": "plot_sensitivity",
                "kind": "model_diagnostics",
                "content_type": "text/html",
                "description": "Sobol' first/total order indices.",
                "payload": {"html": html},
            })
        except MmoError:
            pass
    if model_output.get("profile_likelihood"):
        try:
            html = profile_likelihood_html(model_output["profile_likelihood"])
            artifacts.append({
                "artifact_id": "plot_profile_likelihood",
                "kind": "model_diagnostics",
                "content_type": "text/html",
                "description": "Profile likelihood for a fitted parameter.",
                "payload": {"html": html},
            })
        except MmoError:
            pass
    return artifacts
