"""Unit tests — pure domain modules, no subprocess, no disk beyond tmp fixtures."""

from __future__ import annotations

import math
import sys
from pathlib import Path

import numpy as np
import pytest

from mmpi.errors import ERROR_SPECS, OmError, make_error  # noqa: E402
from mmpi.minerals import CU_KALPHA1_A, HARD_RULES, MINERAL_PHASES, PHASE_DIAGNOSTICS  # noqa: E402
from mmpi import xrd, sem, spectra, fuse, audit, validate  # noqa: E402


def tth(d: float) -> float:
    return math.degrees(2 * math.asin(CU_KALPHA1_A / (2 * d)))


def interleaved(peaks: list[tuple[float, float]], spread: float = 0.08) -> list[float]:
    """Build a properly interleaved [x0,y0,x1,y1,...] XRD profile around peaks."""
    out: list[float] = []
    for d, rel in peaks:
        c = tth(d)
        for k in range(-3, 4):
            out.extend([c + k * 0.05, rel * math.exp(-(k * 0.05 / spread) ** 2)])
    return out


# ---------------------------------------------------------------------------
# minerals reference integrity
# ---------------------------------------------------------------------------

def test_reference_phases_complete():
    assert set(MINERAL_PHASES) == {"calcite", "aragonite", "vaterite", "acc"}


def test_xrd_refs_have_primary():
    for phase, data in MINERAL_PHASES.items():
        xrd_refs = data.get("xrd")
        if isinstance(xrd_refs, list):
            confs = [c for (_d, _h, _i, c) in xrd_refs]
            assert "primary" in confs, f"{phase} 缺少 primary 参考峰"


def test_hard_rules_count():
    assert len(HARD_RULES) >= 6


# ---------------------------------------------------------------------------
# error taxonomy
# ---------------------------------------------------------------------------

def test_all_error_codes_well_formed():
    for code, spec in ERROR_SPECS.items():
        assert spec.code.startswith("OMM-E")
        assert len(spec.code.split("-E")[1]) == 3
        assert isinstance(spec.retryable, bool)


def test_make_error_unknown_code_raises():
    with pytest.raises(ValueError):
        make_error("OMM-E999", "x")


def test_om_error_is_exception():
    err = make_error("OMM-E104", "bad data")
    assert isinstance(err, Exception)
    with pytest.raises(OmError):
        raise err


# ---------------------------------------------------------------------------
# xrd
# ---------------------------------------------------------------------------

def test_bragg_d_calcite_104():
    # calcite 3.035 A -> 2theta ~29.4 deg (Cu Ka1)
    assert math.isclose(xrd.bragg_d(29.4, CU_KALPHA1_A), 3.035, abs_tol=0.01)


def test_match_synthetic_calcite_identifies_calcite():
    tt, it = xrd.parse_twotheta_intensity(
        interleaved([(3.035, 100), (2.495, 14), (2.285, 18), (2.095, 18), (1.875, 17)]))
    results = xrd.match_profile(tt, it)
    calcite = [r for r in results if r.phase == "calcite"][0]
    assert calcite.verdict == "identified"
    assert any(m.ref_confidence == "primary" for m in calcite.matched_peaks)


def test_match_empty_profile_returns_absent_not_crash():
    results = xrd.match_profile(np.array([10.0, 11.0, 12.0, 13.0, 14.0]),
                                np.array([1.0, 1.0, 1.0, 1.0, 1.0]))
    assert all(r.verdict == "absent" for r in results)


def test_clean_series_rejects_nan():
    with pytest.raises(OmError) as ei:
        xrd.parse_twotheta_intensity([10.0, float("nan"), 20.0, 5.0])
    assert ei.value.code == "OMM-E104"


def test_flat_odd_length_rejected():
    with pytest.raises(OmError):
        xrd.parse_twotheta_intensity([1.0, 2.0, 3.0])


# ---------------------------------------------------------------------------
# spectra
# ---------------------------------------------------------------------------

def _ftir_with_bands(bands: list[float], lo: float = 600, hi: float = 1600, step: float = 5):
    ch = [float(i) for i in range(lo, hi, step)]
    it = [0.0] * len(ch)
    for band in bands:
        idx = min(range(len(ch)), key=lambda i: abs(ch[i] - band))
        it[idx] = 100.0
        if idx > 0:
            it[idx - 1] = 10.0
        if idx < len(ch) - 1:
            it[idx + 1] = 10.0
    return ch, it


def test_ftir_flat_baseline_no_false_peaks():
    # Flat zero baseline must NOT produce any matched band.
    ch = [float(i) for i in range(600, 1600, 5)]
    it = [0.0] * len(ch)
    res = spectra.parse_ftir(ch, it)
    assert res["phase_evidence"] == {}


def test_ftir_vaterite_bands_detected():
    ch, it = _ftir_with_bands([745, 1087, 1490])
    res = spectra.parse_ftir(ch, it)
    assert "vaterite" in res["phase_evidence"]
    assert res["phase_evidence"]["vaterite"]["confidence"] == "supporting"


def test_eds_ca_detected():
    ch = [1.0, 2.0, 3.0, 3.4, 3.5, 3.69, 3.8, 4.0, 5.0]
    it = [0, 0, 0, 20, 50, 100, 50, 10, 0]
    res = spectra.parse_eds(ch, it)
    assert res["ca_present"] is True
    assert res["max_evidence"] == "supporting"


def test_tga_ratio():
    res = spectra.parse_tga([25, 100, 200, 600, 900], [100, 99, 95, 60, 56])
    assert res["total_mass_loss_wt_pct"] > 40


def test_tga_unit_check():
    with pytest.raises(OmError):
        spectra.parse_tga([25, 100], [100, 150])  # >100 wt%


# ---------------------------------------------------------------------------
# sem
# ---------------------------------------------------------------------------

def test_sem_stats_basic():
    rows = [[10, 20, 4.0], [12, 22, 5.0], [14, 24, 6.0]]
    st = sem.particle_stats(rows, particle_units="um", min_particles=30)
    assert st.n == 3
    assert st.min_area_um2 == 4.0
    assert st.max_area_um2 == 6.0
    assert any("样本量" in n for n in st.notes)


def test_sem_px_to_um_conversion():
    rows = [[10, 20, 100.0]]
    st = sem.particle_stats(rows, unit_scale_um_per_px=0.1, particle_units="px",
                            min_particles=1)
    # area: 100 px^2 * (0.1)^2 = 1.0 um^2
    assert math.isclose(st.max_area_um2, 1.0, abs_tol=1e-3)


def test_sem_empty_rows_rejected():
    with pytest.raises(OmError) as ei:
        sem.particle_stats([], particle_units="um")
    assert ei.value.code == "OMM-E104"


def test_audit_log_append_and_close():
    alog = sem.ImageAuditLog()
    alog.record("seg", {"t": "otsu"}, {"n": 5})
    entries = alog.close()
    assert len(entries) == 1
    with pytest.raises(OmError):
        alog.record("late", {}, {})


# ---------------------------------------------------------------------------
# fuse
# ---------------------------------------------------------------------------

def test_xrd_alone_capped_likely():
    # XRD identified with zero corroboration must never be 'confirmed'.
    f = fuse.fuse_phase("calcite", xrd_verdict="identified", xrd_primary_matched=True,
                        xrd_secondary_count=2)
    assert f.confidence == "likely"
    assert f.score >= fuse.LIKELY_THRESHOLD


def test_multi_modal_confirmed():
    f = fuse.fuse_phase("vaterite", xrd_verdict="identified", xrd_primary_matched=True,
                        xrd_secondary_count=2, ftir_bands=[745.0], eds_ca=True,
                        tga_co2_likely=True)
    assert f.confidence == "confirmed"
    assert f.score >= fuse.CONFIRM_THRESHOLD


def test_fuse_all_no_evidence_empty():
    res = fuse.fuse_all(xrd_results=[], eds_ca=False)
    assert res["winner"] is None
    assert all(p["score"] == 0.0 for p in res["phases"])


# ---------------------------------------------------------------------------
# audit
# ---------------------------------------------------------------------------

def _minimal_envelope(status: str = "SUCCESS") -> dict:
    return {
        "contract_version": "1.0", "skill": "micp-mineral-phase-interpreter",
        "skill_version": "1.0.0", "status": status, "summary": "x", "action": "interpret.phases",
        "project_id": "p", "task_id": "t", "findings": [], "assumptions": [], "evidence_used": [],
        "uncertainty": [], "risks": [], "artifacts": [], "requested_next_skills": [],
        "results": {}, "validation": {}, "provenance": {}, "errors": [],
    }


def test_label_inflation_detected():
    env = _minimal_envelope()
    env["findings"] = [{"label": "OBSERVED", "statement": "无来源的观测断言"}]
    res = audit.check_epistemology(env)
    assert len(res) == 1


def test_observed_with_source_ok():
    env = _minimal_envelope()
    env["findings"] = [{"label": "OBSERVED", "statement": "有来源", "source": "SEM 图像 s1"}]
    res = audit.check_epistemology(env)
    assert res == []


def test_hard_rule_single_sem_homogeneity():
    env = _minimal_envelope()
    env["summary"] = "整体均匀一致"
    issues = audit.check_hard_rules(env, context={"single_sem_image_used": True})
    assert any("single_sem_no_homogeneity" in i for i in issues)


def test_no_fabrication_flags_empty_evidence():
    env = _minimal_envelope()
    env["findings"] = [{"label": "CALCULATED", "statement": "主导相为 calcite"}]
    issues = audit.check_hard_rules(env, context={"has_inline_samples": False})
    assert any("no_fabrication" in i for i in issues)


# ---------------------------------------------------------------------------
# validate (JSON schema subset)
# ---------------------------------------------------------------------------

def test_validator_basic():
    schema = {"type": "object", "required": ["a"],
              "properties": {"a": {"type": "integer", "minimum": 1}},
              "additionalProperties": False}
    assert validate.validate({"a": 2}, schema) == []
    assert len(validate.validate({"b": 1}, schema)) == 2  # missing a + additional b


def test_validator_enum_and_ref():
    schema = {"$defs": {"e": {"enum": ["x", "y"]}},
              "type": "object", "properties": {"v": {"$ref": "#/$defs/e"}}}
    assert validate.validate({"v": "x"}, schema) == []
    assert len(validate.validate({"v": "z"}, schema)) == 1
