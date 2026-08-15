"""MUC sens — one-at-a-time (OAT) sensitivity and uncertainty plumbing.

Sensitivity analysis over model inputs: for each parameter, perturb by ±delta
(relative or absolute), re-run the simulation, and report the fractional
change in selected response variables (final precipitated solid, final SI,
final pH). Deterministic, offline.

Also provides a simple parameter-uncertainty aggregation: given a response
sensitivity dR/R per parameter and an assumed relative uncertainty u_i for that
parameter, the propagated relative uncertainty is the RSS:
    U_R = sqrt( sum_i ( (dR/R / delta_i) * u_i )^2 )
where delta_i is the perturbation size used to estimate the sensitivity.
"""

from __future__ import annotations

import math

from .errors import MUCError
from .simulate import simulate_batch

_RESPONSES = ("caco3_solid", "ph_final", "si_final", "urea_conversion")


def sensitivity(
    *,
    base_input: dict,
    parameters: list[str],
    delta_relative: float = 0.01,
    responses: tuple[str, ...] = _RESPONSES,
) -> dict:
    """OAT sensitivity of the batch simulation to a set of parameter paths.

    parameters: dotted paths into the simulate_batch kwargs, e.g.
      "kinetics.vmax", "kinetics.km", "precipitation.k_precip",
      "precipitation.a_specific", "initial.urea", "initial.ca".
    """
    if delta_relative <= 0 or not math.isfinite(delta_relative):
        raise MUCError("MUC-E2004", f"sensitivity: delta_relative must be > 0, got {delta_relative!r}")

    def get(d: dict, path: str):
        cur = d
        for part in path.split("."):
            if isinstance(cur, dict) and part in cur:
                cur = cur[part]
            else:
                raise MUCError("MUC-E1001", f"sensitivity: unknown parameter path {path!r}")
        return cur

    def set_path(d: dict, path: str, value: float) -> dict:
        out = json_deepcopy(d)
        parts = path.split(".")
        node = out
        for p in parts[:-1]:
            node = node[p]
        node[parts[-1]] = value
        return out

    base = simulate_batch(**base_input)
    base_resp = {r: _response_value(base, r) for r in responses}

    rows = []
    for path in parameters:
        val0 = get(base_input, path)
        if not isinstance(val0, (int, float)) or not math.isfinite(float(val0)):
            continue
        delta = abs(val0) * delta_relative
        plus = set_path(base_input, path, float(val0) + delta)
        minus = set_path(base_input, path, float(val0) - delta)
        try:
            r_plus = simulate_batch(**plus)
            r_minus = simulate_batch(**minus)
        except MUCError:
            # Parameter perturbation may invalidate the system; record a failed row.
            rows.append({"parameter": path, "error": "perturbed simulation failed", "sensitivities": {}})
            continue
        row: dict = {"parameter": path, "base_value": val0, "sensitivities": {}}
        for r in responses:
            vp = _response_value(r_plus, r)
            vm = _response_value(r_minus, r)
            b = base_resp[r]
            if b is None or vp is None or vm is None or abs(b) < 1e-30:
                continue
            # normalized sensitivity: (dR/R)/(dP/P)
            dR = vp - vm
            sens = (dR / b) / (2.0 * delta_relative)
            row["sensitivities"][r] = sens
        rows.append(row)

    return {
        "delta_relative": delta_relative,
        "responses": list(responses),
        "base_response": base_resp,
        "rows": rows,
        "note": "OAT sensitivities are local and linearization-based; use for screening, not ranking across strong nonlinearities",
    }


def _response_value(result: dict, key: str):
    fin = result.get("final", {})
    if key == "caco3_solid":
        return fin.get("caco3_solid")
    if key == "ph_final":
        return fin.get("ph")
    if key == "si_final":
        return fin.get("si")
    if key == "urea_conversion":
        return fin.get("urea_conversion_frac")
    return None


def propagate_uncertainty(
    *,
    sensitivities: dict[str, float],  # response sensitivity dR/R per parameter
    parameter_rel_uncertainty: dict[str, float],  # u_i per parameter (fraction)
) -> dict:
    """RSS-propagate relative uncertainty from OAT sensitivities.

    U_R = sqrt( sum_i (sens_i * u_i)^2 )
    """
    total_sq = 0.0
    terms: list[dict] = []
    for p, s in sensitivities.items():
        u = parameter_rel_uncertainty.get(p)
        if u is None or u < 0 or not math.isfinite(u):
            raise MUCError("MUC-E1001", f"propagate_uncertainty: missing/invalid u for parameter {p!r}")
        term = s * u
        terms.append({"parameter": p, "sensitivity": s, "u": u, "term": term})
        total_sq += term * term
    u_total = math.sqrt(total_sq)
    return {
        "relative_uncertainty": u_total,
        "terms": terms,
        "note": "RSS under independence and linearized sensitivities; not valid for strong nonlinearity or correlations",
    }


def json_deepcopy(d: dict) -> dict:
    import json

    return json.loads(json.dumps(d))
