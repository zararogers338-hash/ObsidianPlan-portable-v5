"""Spec §九 required tests — the 10 mandated cases mapped to real assertions.

    T1  XRD 峰重叠案例               -> tests/unit (eval-04 + vaterite 3.29/aragonite 3.273)
    T2  仅有单个候选峰的案例          -> test_single_candidate_peak (below)
    T3  方解石和球霰石混合相案例       -> test_calcite_vaterite_mixture (below)
    T4  SEM 只有一个局部视野的案例     -> tests/unit (eval-08 / test_sem_stats_basic)
    T5  图像缺失尺度尺的案例          -> test_missing_scale_bar (below)
    T6  XRD 与 FTIR 结论冲突案例       -> test_xrd_ftir_conflict (below)
    T7  CaCO3 总量高但接触沉淀少案例   -> test_high_caco3_low_contact (below)
    T8  原始图像和处理图像哈希检查     -> tests/unit/test_additions_v11.py (hashcheck)
    T9  不相关矿物数据输入             -> test_unrelated_mineral_input (below)
    T10 数据库不可用时的降级流程        -> test_database_unavailable_degrades (below)
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

SKILL_ROOT = Path(__file__).resolve().parent.parent.parent
CLI = SKILL_ROOT / "tools" / "mmpi_cli.py"


def invoke(payload: dict) -> dict:
    proc = subprocess.run([sys.executable, str(CLI)],
                          input=json.dumps(payload), capture_output=True, text=True, timeout=90)
    if proc.returncode != 0:
        raise RuntimeError(f"CLI crashed: {proc.stderr}")
    return json.loads(proc.stdout)


def base(action: str, **extra) -> dict:
    payload = {
        "contract_version": "1.0", "task_id": "spec9", "project_id": "spec9-proj",
        "request": "spec §九 required case", "action": action,
        "skill_version": "1.0.0", "timestamp": "2026-08-07T00:00:00Z",
    }
    payload.update(extra)
    return payload


def bragg_peak(d_A: float, rel: float, spread: float = 0.08) -> list[float]:
    """Build [x0,y0,x1,y1,...] around 2theta computed from d-spacing."""
    import math
    lam = 1.540598
    tth = math.degrees(2 * math.asin(lam / (2 * d_A)))
    out: list[float] = []
    for k in range(-4, 5):
        out.extend([tth + k * 0.05, rel * math.exp(-(k * 0.05 / spread) ** 2)])
    return out


# ---------------------------------------------------------------------------
# T2: 仅有单个候选峰的案例 —— 不得凭单个峰武断鉴定晶型
# ---------------------------------------------------------------------------

def test_single_candidate_peak_not_overclaimed():
    """Only one peak present. Several phases can share ~3.035 Å (calcite 104).
    The skill must list it as weak/candidate, NOT identified/confirmed."""
    # single strong peak at calcite's 3.035 Å
    values = bragg_peak(3.035, 100.0)
    out = invoke(base("tools.xrd_match", samples=[
        {"id": "x", "data_type": "xrd_twotheta_intensity", "values": values}]))
    assert out["status"] == "SUCCESS"
    matches = out["results"]["matches"]
    by_phase = {m["phase"]: m for m in matches}
    # calcite cannot be 'identified' from a single reflection (min_peaks=2 default)
    assert by_phase["calcite"]["verdict"] in ("weak", "candidate")
    assert by_phase["calcite"]["verdict"] != "identified"
    # no confirmed winner from a single peak
    assert "confirmed" not in json.dumps(out["findings"], ensure_ascii=False)


# ---------------------------------------------------------------------------
# T3: 方解石和球霰石混合相案例
# ---------------------------------------------------------------------------

def test_calcite_vaterite_mixture_detects_both():
    """Two-phase mixture: calcite (3.035/2.495/2.285/2.095) + vaterite
    (3.57-3.58/3.29/2.73) in one XRD profile. Both phases must appear in the
    candidate list with their primary reflections matched."""
    values: list[float] = []
    for d, rel in [(3.57, 60), (3.29, 40), (2.73, 45), (3.035, 100), (2.495, 30), (2.285, 35), (2.095, 30)]:
        values += bragg_peak(d, rel)
    out = invoke(base("tools.xrd_match", samples=[
        {"id": "x", "data_type": "xrd_twotheta_intensity", "values": values}]))
    assert out["status"] == "SUCCESS"
    matches = out["results"]["matches"]
    by_phase = {m["phase"]: m for m in matches}
    # both must have their primary reflection matched
    assert by_phase["calcite"]["primary_matched"] is True
    assert by_phase["vaterite"]["primary_matched"] is True
    assert by_phase["calcite"]["verdict"] in ("identified", "candidate")
    assert by_phase["vaterite"]["verdict"] in ("identified", "candidate")


# ---------------------------------------------------------------------------
# T5: 图像缺失尺度尺 —— 不得虚构像素到微米的换算
# ---------------------------------------------------------------------------

def test_missing_scale_bar_flagged_uncalibrated():
    """SEM particles in px without unit_scale must be flagged as uncalibrated;
    the skill must NOT invent an um conversion."""
    out = invoke(base("tools.sem_stats", samples=[
        {"id": "s", "data_type": "sem_particle_list", "particle_units": "px",
         "particles": [[10, 20, 100.0], [12, 22, 150.0], [15, 25, 120.0],
                       [18, 28, 200.0], [20, 30, 180.0], [22, 32, 160.0],
                       [25, 35, 140.0], [28, 38, 210.0], [30, 40, 190.0],
                       [32, 42, 170.0], [35, 45, 130.0], [38, 48, 155.0]]}]))
    assert out["status"] in ("SUCCESS", "PARTIAL")
    stats = out["results"]["stats"]
    assert stats["calibration"] == "px"
    assert stats["unit_scale_um_per_px"] is None
    # no fabricated um conversion: mean area must be reported in px scale only
    assert "uncalibrated" in json.dumps(stats["notes"], ensure_ascii=False) or \
           "像素" in json.dumps(stats["notes"], ensure_ascii=False)


# ---------------------------------------------------------------------------
# T6: XRD 与 FTIR 结论冲突案例
# ---------------------------------------------------------------------------

def test_xrd_ftir_conflict_surfaces_candidates_not_certainty():
    """XRD strongly calcite; FTIR bands are aragonite-typical (854 + 700/713).
    The conflict must be surfaced (multiple candidates, no confirmed winner
    from conflicting single modalities), never silently resolved to one phase."""
    xrd_values: list[float] = []
    for d, rel in [(3.035, 100), (2.495, 30), (2.285, 35), (2.095, 30), (1.875, 20)]:
        xrd_values += bragg_peak(d, rel)
    out = invoke(base("interpret.phases", samples=[
        {"id": "x", "data_type": "xrd_twotheta_intensity", "values": xrd_values},
        {"id": "f", "data_type": "ftir_spectrum",
         "channels": [700, 705, 710, 713, 715, 852, 854, 856, 1080, 1083, 1470, 1475],
         "intensities": [10, 20, 40, 100, 40, 15, 100, 15, 20, 40, 30, 60]},
    ]))
    # FTIR alone is never conclusive: aragonite may be candidate but not confirmed
    # unless XRD agrees. XRD says calcite. Result must be candid about the tension.
    blob = json.dumps(out, ensure_ascii=False)
    assert out["status"] in ("SUCCESS", "PARTIAL")
    # both phases must be candidates at most — no single-phase overclaim
    assert "confirmed" not in blob or "aragonite" not in out.get("confirmed_phases", [])
    assert "calcite" not in out.get("confirmed_phases", [])
    # uncertainty must mention the conflict/tension
    assert out["uncertainty"] or "候选" in blob or "无法确定" in out["summary"]


# ---------------------------------------------------------------------------
# T7: CaCO3 总量高但颗粒接触处沉淀很少
# ---------------------------------------------------------------------------

def test_high_caco3_low_contact_precipitation():
    """TGA says high total CaCO3; SEM shows few particles far apart -> the
    skill must NOT infer bridge formation / engineering contribution from the
    high total mass. Bridge evidence stays negative / requires mechanics."""
    out = invoke(base("interpret.phases", samples=[
        {"id": "t", "data_type": "tga_curve",
         "channels": [25.0, 200.0, 600.0, 800.0, 900.0],
         "intensities": [100.0, 98.0, 60.0, 50.0, 52.0]},
        {"id": "s", "data_type": "sem_particle_list", "particle_units": "um",
         "particles": [[0, 0, 1.0], [50, 0, 1.2], [100, 0, 0.9], [150, 0, 1.1],
                       [200, 0, 1.0], [250, 0, 1.3]]},
    ]))
    blob = json.dumps(out, ensure_ascii=False)
    # high total CaCO3 is level-2 only
    assert "CaCO3" in blob or "化学计量" in blob
    # no bridge engineering claim without contact evidence
    assert "晶桥" not in blob or "力学" in blob  # if mentioned, must reference mechanics
    assert "bridge_evidence" in out
    if out["bridge_evidence"]:
        assert out["bridge_evidence"].get("engineering_contribution_claimed") is not True


# ---------------------------------------------------------------------------
# T9: 不相关矿物数据输入
# ---------------------------------------------------------------------------

def test_unrelated_mineral_input_no_fabrication():
    """FeS2 (pyrite) peaks must NOT be forced into a carbonate phase. The skill
    either reports no match (weak/absent) or flags unexplained features."""
    # pyrite major reflections ~1.63, 2.71, 2.42, 1.91 Å — far from carbonate keys
    values: list[float] = []
    for d, rel in [(2.709, 100), (2.423, 65), (1.633, 85), (1.915, 40), (1.563, 30)]:
        values += bragg_peak(d, rel)
    out = invoke(base("interpret.phases", samples=[
        {"id": "x", "data_type": "xrd_twotheta_intensity", "values": values}]))
    blob = json.dumps(out, ensure_ascii=False)
    # no carbonate phase may be confirmed from pyrite data
    assert out.get("confirmed_phases", []) == []
    assert "unexplained_features" in out  # the mechanism exists
    winner = out["results"].get("fusion", {}).get("winner")
    assert winner is None  # no fabricated carbonate winner


# ---------------------------------------------------------------------------
# T10: 数据库不可用时的降级流程
# ---------------------------------------------------------------------------

def test_database_unavailable_degrades():
    """If a reference database cannot be resolved (path given, no data), the
    skill must return BLOCKED/FAILED with a typed dependency error — never a
    fabricated match. This is the required degradation path for 'no database
    available' (spec: 不得虚构匹配结果,应返回 BLOCKED 或请求用户提供参考数据库)."""
    out = invoke(base("tools.xrd_match", samples=[
        {"id": "x", "data_type": "xrd_twotheta_intensity", "path": "C:/nonexistent/icdd.db",
         "values": [25.3, 100, 27.1, 50]}]))
    assert out["status"] in ("BLOCKED", "FAILED")
    assert out["errors"][0]["code"] == "OMM-E204"
    assert out["results"] == {} or "matches" not in out["results"]  # no fabricated match
