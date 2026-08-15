"""Regression tests for defects found by the adversarial review (2026-08-07).

Each test guards a real defect the reviewer reproduced against the on-disk
code; each has a `# regression:` comment citing the defect. The review returned
`fail` with 4 blocking + 3 minor defects; this module locks in the fixes so
they cannot silently regress.
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
from mmpi import fuse, xrd  # noqa: E402


def invoke(payload: dict) -> dict:
    proc = subprocess.run([sys.executable, str(CLI)],
                          input=json.dumps(payload), capture_output=True, text=True, timeout=60)
    if proc.returncode != 0:
        raise RuntimeError(f"CLI crashed: {proc.stderr}")
    return json.loads(proc.stdout)


def base(action: str, **extra) -> dict:
    payload = {
        "contract_version": "1.0", "task_id": "advreg", "project_id": "advreg-proj",
        "request": "对抗审查回归", "action": action,
        "skill_version": "1.1.1", "timestamp": "2026-08-07T00:00:00Z",
    }
    payload.update(extra)
    return payload


def interleaved(peaks: list[tuple[float, float]], spread: float = 0.08) -> list[float]:
    out: list[float] = []
    for d, rel in peaks:
        c = math.degrees(2 * math.asin(CU_KALPHA1_A / (2 * d)))
        for k in range(-3, 4):
            out.extend([c + k * 0.05, rel * math.exp(-(k * 0.05 / spread) ** 2)])
    return [round(x, 3) for x in out]


# regression: blocking #1 — single primary peak must NOT be 'identified' nor win.
def test_single_primary_peak_not_identified():
    vals = interleaved([(3.035, 100)])
    tt, it = xrd.parse_twotheta_intensity(vals)
    res = xrd.match_profile(tt, it)
    cal = [r for r in res if r.phase == "calcite"][0]
    assert cal.verdict != "identified"
    # and the CLI must not emit a winner from a single peak
    out = invoke(base("interpret.phases", samples=[
        {"id": "x", "data_type": "xrd_twotheta_intensity", "values": vals}]))
    assert out["results"]["fusion"]["winner"] is None


# regression: blocking #2 — primary must not be double-counted as secondary;
# XRD primary + 2 secondary + SEM morphology must NOT reach 'confirmed'.
def test_no_primary_double_count():
    xrd_dict = [{"phase": "calcite", "verdict": "identified", "score": 1.0,
                 "primary_matched": True, "matched_peak_count": 3,
                 "peaks": [{"ref_confidence": "primary", "obs_d_A": 3.035},
                           {"ref_confidence": "secondary", "obs_d_A": 2.495},
                           {"ref_confidence": "secondary", "obs_d_A": 2.285}]}]
    f = fuse.fuse_all(xrd_results=xrd_dict, sem_morphology={"calcite": "rhombohedral"})
    c = [p for p in f["phases"] if p["phase"] == "calcite"][0]
    assert c["confidence"] != "confirmed"  # was confirmed (0.825), must be likely (0.7)
    assert "xrd_secondary" in c["weight_breakdown"]
    assert c["weight_breakdown"]["xrd_secondary"] == 2.0  # 2, not 3


# regression: blocking #3 — spectra_parse must pass its own self-check.
def test_spectra_parse_self_check_passes():
    out = invoke(base("tools.spectra_parse", samples=[
        {"id": "e", "data_type": "eds_spectrum",
         "channels": [1.0, 2.0, 3.0, 3.5, 3.69, 3.8, 4.0, 5.0],
         "intensities": [0, 0, 0, 50, 100, 50, 10, 0]}]))
    assert out["status"] == "SUCCESS"
    assert out["validation"]["self_check"] == "passed"
    assert out["errors"] == []


# regression: blocking #4 — observed-but-unmatched XRD peaks must surface.
def test_unmatched_peak_surfaced():
    out = invoke(base("interpret.phases", samples=[
        {"id": "x", "data_type": "xrd_twotheta_intensity",
         "values": [26.9, 10, 27.0, 18, 27.1, 25, 27.2, 18, 27.3, 10,
                    32.7, 20, 32.8, 30, 32.9, 20, 32.95, 12, 33.0, 18, 33.05, 12]}]))
    ux = out.get("unexplained_features", [])
    assert len(ux) > 0
    assert any(u.get("kind") == "xrd_unexplained_peak" for u in ux)


# regression: minor #5 — single_sem_image_used must be set so the hard rule fires.
def test_single_sem_signal_set():
    out = invoke(base("interpret.phases", samples=[
        {"id": "s", "data_type": "sem_particle_list", "particle_units": "um",
         "particles": [[10, 20, 4.5], [12, 24, 3.2]]}],
        thresholds={"sem_min_particles": 30}))
    assert out["results"].get("single_sem_image_used") is True


# regression: minor #7 — aragonite/vaterite overlap must be surfaced.
def test_reflection_overlap_surfaced():
    out = invoke(base("interpret.phases", samples=[
        {"id": "x", "data_type": "xrd_twotheta_intensity",
         "values": [26.9, 10, 27.0, 18, 27.1, 25, 27.2, 18, 27.3, 10,
                    32.7, 20, 32.8, 30, 32.9, 20]}]))
    ov = out.get("reflection_overlaps", [])
    assert len(ov) > 0
    assert any("aragonite" in o.get("phases", []) and "vaterite" in o.get("phases", [])
               for o in ov)


# regression: adversarial review secondary finding — aragonite FTIR diagnostic
# (854+700/713) must NOT corroborate calcite via the shared 712/713 v4 band.
def test_shared_v4_band_does_not_corroborate_calcite():
    from mmpi.minerals import DIAGNOSTIC_FTIR_BANDS
    assert DIAGNOSTIC_FTIR_BANDS["calcite"] == [[712.0, 874.0]]  # group requires 874
    # a lone 713 hit (aragonite doublet) must not produce calcite diagnostic hits
    diag = fuse._diagnostic_hits([713.0], DIAGNOSTIC_FTIR_BANDS["calcite"])
    assert diag == []
    # aragonite group [854, 700] with only 854 present must not fire either
    diag_ar = fuse._diagnostic_hits([854.0], DIAGNOSTIC_FTIR_BANDS["aragonite"])
    assert diag_ar == []
    # full aragonite group fires
    diag_ar_full = fuse._diagnostic_hits([854.0, 700.0], DIAGNOSTIC_FTIR_BANDS["aragonite"])
    assert len(diag_ar_full) == 2


# regression: minor #6 — score inflation annotated when primary outside window.
def test_primary_outside_window_annotated():
    vals = interleaved([(3.29, 25), (2.73, 30)])  # vaterite primary 3.57 not here
    tt, it = xrd.parse_twotheta_intensity(vals)
    res = xrd.match_profile(tt, it)
    v = [r for r in res if r.phase == "vaterite"][0]
    assert any("不在扫描窗口" in n for n in v.notes)


# regression: bridge_evidence stayed empty when particle count >= threshold
# (sem_stats was written then overwritten by the results block; found while
# closing the adversarial audit's bridge-evidence gap). Adequate particle counts
# must yield a geometric contact *candidate* with engineering claim=False.
def test_bridge_evidence_populated_with_adequate_particles():
    dense = [[0, 0, 1.0], [0, 1, 1.2], [0, 2, 0.9], [0, 3, 1.1], [0, 4, 1.0], [0, 5, 1.3],
             [1, 0, 1.1], [1, 1, 0.8], [1, 2, 1.2], [1, 3, 1.0], [1, 4, 1.4], [1, 5, 0.9],
             [2, 0, 1.0], [2, 1, 1.2], [2, 2, 0.9], [2, 3, 1.1], [2, 4, 1.0], [2, 5, 1.3],
             [3, 0, 1.1], [3, 1, 0.8], [3, 2, 1.2], [3, 3, 1.0], [3, 4, 1.4], [3, 5, 0.9],
             [4, 0, 1.0], [4, 1, 1.2], [4, 2, 0.9], [4, 3, 1.1], [4, 4, 1.0], [4, 5, 1.3]]
    out = invoke(base("interpret.phases", samples=[
        {"id": "s", "data_type": "sem_particle_list", "particle_units": "um", "particles": dense},
    ]))
    be = out.get("bridge_evidence", {})
    assert be, "bridge_evidence must be populated with adequate particle counts"
    assert "geometric_contacts_observed" in be
    assert be.get("engineering_contribution_claimed") is False
    # spatial distribution must also be present
    assert out.get("spatial_distribution", {}).get("n_particles") == 30


# regression: tools.self_check on a completed envelope disagreed with the live
# path's self-check (no_fabrication hard rule flagged inline-sample envelopes
# because the audit context was empty). The re-check must derive context from
# the candidate's results, so an inline-sample envelope passes BOTH paths.
def test_self_check_consistent_with_live_path():
    vals = interleaved([(3.035, 100), (2.495, 30), (2.285, 35), (2.095, 30)])
    live = invoke(base("interpret.phases", samples=[
        {"id": "x", "data_type": "xrd_twotheta_intensity", "values": vals},
    ]))
    assert live["validation"]["self_check"] == "passed"
    sc = invoke(base("tools.self_check", candidate_output=live))
    assert sc["status"] == "SUCCESS"
    assert sc["results"]["passed"] is True
    assert sc["results"].get("issues", []) == []
