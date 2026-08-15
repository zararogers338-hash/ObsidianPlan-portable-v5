"""Model boundary checker (模型边界检查器).

Attacks model claims offline and deterministically:

  - missing boundary conditions (required but absent)
  - unidentifiable parameters (more fitted params than independent constraints)
  - same-data calibration AND validation (training on the same rows that
    validate) — a classic overfitting signal
  - domain overflow: conclusions drawn outside the calibrated/validated scale
    (e.g. small-column parameters used to predict field-scale behavior)

Input shape (`model`):
  {
    "name": "...",
    "equations": [...],
    "parameters": [{"name": "...", "role": "calibrated|given|free", "n": 3}],
    "boundary_conditions": [...],
    "required_boundary_conditions": [...],
    "data_split": {"calibration_rows": n, "validation_rows": n, "same_rows": bool},
    "validation_domain": {"scale": "column|field", "conditions": "..."},
    "claimed_domain": {"scale": "column|field", "conditions": "..."}
  }
"""

from __future__ import annotations

from typing import Any

from common import ToolError, emit_progress
from errors import OrtErrorCode, OrtError


def _audit_model(model: dict[str, Any]) -> dict[str, Any]:
    name = str(model.get("name", "model"))
    findings: list[dict] = []

    # 1) missing boundary conditions
    required = model.get("required_boundary_conditions") or []
    present = model.get("boundary_conditions") or []
    missing_bc = [b for b in required if b not in present]
    if missing_bc:
        findings.append({
            "id": name, "severity": "CRITICAL", "dimension": "model_boundary",
            "message": f"missing boundary conditions: {missing_bc}",
            "code": "MODEL_NO_BC",
        })

    # 2) unidentifiable parameters
    params = model.get("parameters") or []
    fitted = [p for p in params if p.get("role") == "calibrated"]
    n_fitted = sum(int(p.get("n", 1)) for p in fitted)
    n_observations = model.get("n_observations")
    if n_observations is not None and n_fitted > n_observations:
        findings.append({
            "id": name, "severity": "CRITICAL", "dimension": "model_boundary",
            "message": f"unidentifiable parameters: {n_fitted} fitted params > {n_observations} observations",
            "code": "MODEL_UNIDENTIFIABLE",
        })

    # 3) same-data calibration + validation
    split = model.get("data_split") or {}
    if split.get("same_rows"):
        findings.append({
            "id": name, "severity": "BLOCKING", "dimension": "model_boundary",
            "message": "same data used for calibration and validation: reported 'validation' is "
                       "in-sample fit, not generalization evidence",
            "code": "MODEL_SAME_DATA",
        })
    elif split.get("calibration_rows") and split.get("validation_rows") and \
            split.get("calibration_rows") and split.get("validation_rows") == 0:
        findings.append({
            "id": name, "severity": "CRITICAL", "dimension": "model_boundary",
            "message": "no held-out validation data: model never tested out-of-sample",
            "code": "MODEL_NO_VALIDATION",
        })

    # 4) domain overflow
    validation_scale = model.get("validation_domain", {}).get("scale")
    claimed_scale = model.get("claimed_domain", {}).get("scale")
    if validation_scale and claimed_scale and validation_scale != claimed_scale:
        findings.append({
            "id": name, "severity": "BLOCKING", "dimension": "model_boundary",
            "message": f"domain overflow: validated at {validation_scale} scale but claimed at "
                       f"{claimed_scale} scale; laboratory-to-field extrapolation unsupported",
            "code": "MODEL_SCALE_OVERFLOW",
        })
    elif not validation_scale and claimed_scale == "field":
        findings.append({
            "id": name, "severity": "CRITICAL", "dimension": "model_boundary",
            "message": "field-scale claim with no stated validation domain",
            "code": "MODEL_SCALE_UNVALIDATED",
        })

    return {"model_id": name, "findings": findings}


def main(payload: dict[str, Any]) -> dict[str, Any]:
    emit_progress("modelcheck: auditing model boundaries")
    models = payload.get("models")
    if not models:
        raise OrtError(OrtErrorCode.INPUT_SCHEMA_VIOLATION,
                       "modelcheck: models array is required",
                       detail={"how_to_fix": "attach the model specifications to audit"})
    results = [_audit_model(m) for m in models]
    all_findings = [f for r in results for f in r["findings"]]
    blocking = [f for f in all_findings if f["severity"] == "BLOCKING"]
    return {
        "models": results,
        "summary": {
            "models_checked": len(models),
            "findings": len(all_findings),
            "blocking": len(blocking),
            "codes": sorted({f["code"] for f in all_findings}),
        },
    }


if __name__ == "__main__":
    from common import read_stdin_envelope, run_tool
    run_tool("modelcheck", lambda: main(read_stdin_envelope()))
