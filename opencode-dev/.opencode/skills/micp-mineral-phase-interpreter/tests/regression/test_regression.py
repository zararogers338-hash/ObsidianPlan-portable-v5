"""Regression tests — guard against re-introducing fixed bugs and verify
deterministic, consistent behavior across repeated runs.

Includes:
  * the three real bugs fixed during development (prominence KeyError,
    OmError not an Exception, evaluable-peak scoring);
  * repeat-run consistency (same input, same output);
  * contract stability (output shape never changes).
"""

from __future__ import annotations

import json
import math
import subprocess
import sys
from pathlib import Path

import pytest

SKILL_ROOT = Path(__file__).resolve().parent.parent.parent
CLI = SKILL_ROOT / "tools" / "mmpi_cli.py"

sys.path.insert(0, str(SKILL_ROOT / "tools"))
from mmpi.minerals import CU_KALPHA1_A  # noqa: E402
from mmpi import xrd  # noqa: E402


def invoke(payload: dict) -> dict:
    proc = subprocess.run([sys.executable, str(CLI)],
                          input=json.dumps(payload), capture_output=True, text=True, timeout=60)
    if proc.returncode != 0:
        raise RuntimeError(f"CLI crashed: {proc.stderr}")
    return json.loads(proc.stdout)


def interleaved(peaks: list[tuple[float, float]], spread: float = 0.08) -> list[float]:
    out: list[float] = []
    for d, rel in peaks:
        c = math.degrees(2 * math.asin(CU_KALPHA1_A / (2 * d)))
        for k in range(-3, 4):
            out.extend([c + k * 0.05, rel * math.exp(-(k * 0.05 / spread) ** 2)])
    return [round(x, 3) for x in out]


def base(action: str, **extra) -> dict:
    payload = {
        "contract_version": "1.0", "task_id": "rg", "project_id": "rg-proj",
        "request": "回归测试", "action": action,
        "skill_version": "1.0.0", "timestamp": "2026-08-06T00:00:00Z",
    }
    payload.update(extra)
    return payload


# ---------------------------------------------------------------------------
# regression of fixed bugs
# ---------------------------------------------------------------------------

def test_prominence_keyerror_regression():
    """find_peaks with prominence must never raise KeyError (bug fixed)."""
    vals = interleaved([(3.035, 100)])
    tt, it = xrd.parse_twotheta_intensity(vals)
    peaks = xrd.detect_peaks(tt, it)
    assert len(peaks) == 1


def test_om_error_is_exception_regression():
    """OmError must subclass Exception (bug fixed) so `raise` works."""
    from mmpi.errors import OmError, make_error
    err = make_error("OMM-E104", "x")
    assert isinstance(err, Exception)
    with pytest.raises(OmError):
        raise err


def test_evaluable_peak_scoring_regression():
    """Score must be computed only over reflections inside the scan window
    (bug fixed) — a calcite scan covering 3 peaks should be `identified`."""
    vals = interleaved([(3.035, 100), (2.495, 14), (2.285, 18)])
    tt, it = xrd.parse_twotheta_intensity(vals)
    results = xrd.match_profile(tt, it)
    calcite = [r for r in results if r.phase == "calcite"][0]
    assert calcite.verdict == "identified"
    assert calcite.score >= 0.5


# ---------------------------------------------------------------------------
# repeat-run consistency (spec §十一: M6 repeated-run consistency)
# ---------------------------------------------------------------------------

def test_repeat_run_identical_output():
    payload = base("interpret.phases", samples=[
        {"id": "x", "data_type": "xrd_twotheta_intensity",
         "values": interleaved([(3.035, 100), (2.495, 14)])},
    ])
    o1 = invoke(payload)
    o2 = invoke(payload)
    # strip timestamps (legitimately differ), compare everything else
    for o in (o1, o2):
        o["provenance"].pop("started_at", None)
        o["provenance"].pop("completed_at", None)
    assert o1 == o2


def test_output_shape_stable():
    payload = base("tools.sem_stats", samples=[
        {"id": "s", "data_type": "sem_particle_list", "particle_units": "um",
         "particles": [[10, 20, 4.0], [12, 22, 5.0]]},
    ])
    out = invoke(payload)
    required_keys = {"contract_version", "skill", "skill_version", "status", "summary",
                     "action", "project_id", "task_id", "findings", "assumptions",
                     "evidence_used", "uncertainty", "risks", "artifacts",
                     "requested_next_skills", "results", "validation", "provenance", "errors"}
    assert required_keys <= set(out.keys())


def test_deterministic_fusion_ordering():
    """Fusion ordering must be deterministic (score desc, then confidence)."""
    payload = base("interpret.phases", samples=[
        {"id": "x", "data_type": "xrd_twotheta_intensity",
         "values": interleaved([(3.57, 100), (3.29, 25)])},
    ])
    o1 = invoke(payload)
    o2 = invoke(payload)
    p1 = [p["phase"] for p in o1["results"]["fusion"]["phases"]]
    p2 = [p["phase"] for p in o2["results"]["fusion"]["phases"]]
    assert p1 == p2
