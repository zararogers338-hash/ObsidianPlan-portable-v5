"""XRD peak matching and polymorph quantification.

Pure numpy/scipy module. All functions take explicit arrays and return plain
python data (no I/O), so they are trivially unit-testable and offline.

Design principles (spec §四.2):
  * d-spacing is the fingerprint, 2theta is derived (computed from wavelength,
    never taken from input as truth).
  * Peak picking on the raw (2theta, I) profile is done with a prominence-based
    local maximum search; background is estimated via a rolling percentile,
    not a hard baseline subtraction that could remove real broad humps (ACC).
  * Matching tolerance is explicit (d-tolerance in Angstrom) and passed through
    every threshold, so a unit/scale mistake cannot silently pass.
  * No NaN/Inf/empty input survives: `clean_series` filters and raises a typed
    error when nothing usable remains.

The reference database is loaded from :mod:`mmpi.minerals` (the skill's single
source of truth for reference patterns) — this module never hardcodes peaks.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from .errors import OmError, make_error
from .minerals import CU_KALPHA1_A, MINERAL_PHASES

# numpy/scipy availability is a hard dependency for this module; raise a typed
# error the service can convert into OMM-E202 instead of an unhandled ImportError.
try:  # pragma: no cover - import guard
    import scipy.signal  # noqa: F401
    from scipy.signal import find_peaks
except Exception as exc:  # pragma: no cover
    raise make_error("OMM-E202", f"scipy 不可用: {exc}") from exc


@dataclass
class Peak:
    """A detected peak in an XRD profile."""

    two_theta: float
    d_A: float
    intensity: float
    prominence: float
    width_px: float = 0.0


@dataclass
class Match:
    """A single reference reflection matched against the observed profile."""

    ref_phase: str
    ref_d_A: float
    ref_hkl: tuple[int, int, int]
    ref_confidence: str
    obs_d_A: float
    obs_two_theta: float
    delta_d_A: float
    obs_intensity: float
    relative_intensity_pct: float  # intensity of this peak vs max observed peak


@dataclass
class PhaseMatchResult:
    phase: str
    matched_peaks: list[Match]
    score: float  # 0..1 fraction of required reference peaks matched, weighted
    verdict: str  # "identified" | "candidate" | "weak" | "absent"
    n_required_peaks: int
    max_intensity_obs: float
    notes: list[str] = field(default_factory=list)


def _clean_series(two_theta: np.ndarray, intensity: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    if two_theta.ndim != 1 or intensity.ndim != 1:
        raise make_error("OMM-E104", "XRD 序列必须是一维数组", {"shape_2theta": two_theta.shape})
    if two_theta.size != intensity.size:
        raise make_error("OMM-E104", "XRD 2theta 与强度长度不一致", {
            "len_2theta": two_theta.size, "len_intensity": intensity.size})
    finite = np.isfinite(two_theta) & np.isfinite(intensity)
    if not np.any(finite):
        raise make_error("OMM-E104", "XRD 数据全部为非有限值(NaN/Inf)", {})
    tt = two_theta[finite]
    it = intensity[finite]
    # strictly increasing 2theta (small duplicates tolerated then dropped)
    order = np.argsort(tt, kind="stable")
    tt, it = tt[order], it[order]
    keep = np.concatenate(([True], np.diff(tt) > 1e-9))
    tt, it = tt[keep], it[keep]
    if tt.size < 5:
        raise make_error("OMM-E104", "XRD 有效数据点过少(至少 5 点)", {"n": tt.size})
    if np.any(it < 0):
        # negative intensities: clamp to 0 (baseline overshoot), do not fabricate
        it = np.clip(it, 0, None)
    if np.all(it == 0):
        raise make_error("OMM-E104", "XRD 强度全部为零,无可分析信号", {})
    return tt, it


def _estimate_background(intensity: np.ndarray, window: int | None = None) -> np.ndarray:
    """Rolling-percentile background estimate (robust to broad amorphous humps)."""
    n = intensity.size
    if window is None:
        window = max(9, min(n, n // 20 + 1) | 1)
    # use a symmetric percentile filter
    order = window
    bg = np.empty_like(intensity, dtype=float)
    half = order // 2
    for i in range(n):
        lo = max(0, i - half)
        hi = min(n, i + half + 1)
        bg[i] = float(np.percentile(intensity[lo:hi], 15))
    return bg


def detect_peaks(
    two_theta: np.ndarray,
    intensity: np.ndarray,
    *,
    prominence_frac: float = 0.03,
    window_px: int | None = None,
) -> list[Peak]:
    """Detect peaks in a raw (2theta, I) profile.

    Background-removed prominence detection: a local maximum counts as a peak
    only if its prominence (over the rolling background) exceeds
    ``prominence_frac`` of the max prominence observed. Returns peaks sorted
    by 2theta. No peak is fabricated; a flat profile yields [].
    """
    tt, it = _clean_series(two_theta, intensity)
    bg = _estimate_background(it, window_px)
    sub = it - bg
    # find_peaks computes `prominences` only when the keyword is passed.
    peak_idxs, props = find_peaks(sub, prominence=1e-9)
    if peak_idxs.size == 0:
        return []
    prom = props["prominences"]
    max_prom = float(prom.max())
    if max_prom <= 0:
        return []
    keep = prom >= (prominence_frac * max_prom)
    result: list[Peak] = []
    for idx in peak_idxs[keep]:
        result.append(Peak(
            two_theta=float(tt[idx]),
            d_A=bragg_d(float(tt[idx]), CU_KALPHA1_A),
            intensity=float(it[idx]),
            prominence=float(prom[peak_idxs.tolist().index(idx)]),
            width_px=0.0,
        ))
    return sorted(result, key=lambda p: p.two_theta)


def bragg_d(two_theta_deg: float, wavelength_A: float = CU_KALPHA1_A) -> float:
    """2theta (deg) -> d-spacing (Angstrom), Bragg's law."""
    if wavelength_A <= 0:
        raise make_error("OMM-E103", "XRD 波长必须为正", {"wavelength_A": wavelength_A})
    theta_rad = math.radians(two_theta_deg) / 2.0
    if math.isclose(math.sin(theta_rad), 0.0):
        raise make_error("OMM-E104", "2theta=0 无法计算 d", {"two_theta_deg": two_theta_deg})
    return wavelength_A / (2.0 * math.sin(theta_rad))


def _two_theta_for_d(d_A: float, wavelength_A: float) -> float:
    """d-spacing -> 2theta (deg), inverse of bragg_d. Pure arithmetic."""
    if d_A <= 0:
        raise make_error("OMM-E104", "d 间距必须为正", {"d_A": d_A})
    sin_theta = wavelength_A / (2.0 * d_A)
    sin_theta = max(-1.0, min(1.0, sin_theta))  # clamp floating-point overshoot
    return math.degrees(2.0 * math.asin(sin_theta))


def match_profile(
    two_theta: np.ndarray,
    intensity: np.ndarray,
    *,
    phases: list[str] | None = None,
    d_tol_A: float = 0.03,
    min_relative_intensity: float = 10.0,
    min_peaks: int = 2,
    wavelength_A: float = CU_KALPHA1_A,
) -> list[PhaseMatchResult]:
    """Match an observed profile against reference polymorph databases.

    For each requested reference phase, every detected peak is compared against
    the phase's primary+secondary reflections. A reflection is "matched" when
    |d_obs - d_ref| <= d_tol_A AND the observed peak's relative intensity is
    >= min_relative_intensity% of the max observed peak.

    Scoring (spec §四.5: "输出相鉴定置信度、候选相、冲突证据"):
      * each phase has `primary` and `secondary` reference reflections;
      * phase score = weighted matched fraction, where primary reflections
        count 2x secondary;
      * verdict thresholds are explicit and conservative (no peak-hunting to
        reach a conclusion):
          identified  if primary-peak match exists AND score >= 0.5
          candidate   if score >= 0.3
          weak        if 0 < score < 0.3
          absent      otherwise
    """
    tt, it = _clean_series(two_theta, intensity)
    peaks = detect_peaks(tt, it)
    if not peaks:
        return [
            PhaseMatchResult(
                phase=p, matched_peaks=[], score=0.0, verdict="absent",
                n_required_peaks=0, max_intensity_obs=0.0,
                notes=["profile 中未检测到明显衍射峰"],
            )
            for p in (phases or list(MINERAL_PHASES))
        ]
    max_intensity = float(max(p.intensity for p in peaks))
    candidates = phases if phases else list(MINERAL_PHASES)
    results: list[PhaseMatchResult] = []
    for phase in candidates:
        ref = MINERAL_PHASES[phase]
        xrd = ref.get("xrd", [])
        if not isinstance(xrd, list):
            results.append(PhaseMatchResult(
                phase=phase, matched_peaks=[], score=0.0, verdict="weak",
                n_required_peaks=0, max_intensity_obs=max_intensity,
                notes=["该相无 XRD 参考反射(如 ACC,按无衍射诊断)"]))
            continue
        required = [
            (float(d), tuple(map(int, hkl)), str(conf)) for (d, hkl, _int_pct, conf) in xrd
        ]
        # Only reference reflections whose 2theta falls within the observed scan
        # range are *evaluable* — a phase with many peaks outside the window
        # must not be penalized for them (the scan simply does not cover them).
        overrides = ref.get("xrd_interval_overrides", {}) or {}
        tmin, tmax = float(tt.min()), float(tt.max())
        evaluable = []
        for (d, hkl, conf) in required:
            lo = hi = d
            override = overrides.get((d, tuple(hkl)))
            if override:
                lo, hi = override
            t_ref = _two_theta_for_d(d, wavelength_A)
            t_lo = _two_theta_for_d(hi, wavelength_A)  # larger d -> smaller 2theta
            t_hi = _two_theta_for_d(lo, wavelength_A)
            if (min(t_ref, t_lo) - d_tol_A * 1.5 <= tmax and
                    max(t_ref, t_hi) + d_tol_A * 1.5 >= tmin):
                evaluable.append((d, hkl, conf))
        if not evaluable:
            results.append(PhaseMatchResult(
                phase=phase, matched_peaks=[], score=0.0, verdict="weak",
                n_required_peaks=0, max_intensity_obs=max_intensity,
                notes=["该相参考反射均不在观测扫描范围内,无法评估"]))
            continue
        primary_eval = [r for r in evaluable if r[2] == "primary"]
        secondary_eval = [r for r in evaluable if r[2] == "secondary"]
        matched: list[Match] = []
        # Per-reflection match window: default is the point-tolerance; phases may
        # declare an interval override (e.g. vaterite (110) drifts with
        # hydration/ordering) so the window widens for that reflection only.
        overrides = ref.get("xrd_interval_overrides", {}) or {}
        # greedily assign each observed peak to the closest unmatched reference
        # reflection of the phase (within its window), never double-using a peak.
        used_obs: set[int] = set()
        for d_ref, hkl, conf in evaluable:
            lo = hi = d_ref
            override = overrides.get((d_ref, tuple(hkl)))
            if override:
                lo, hi = override
            best_i: int | None = None
            best_delta = float("inf")
            for i, pk in enumerate(peaks):
                if i in used_obs:
                    continue
                if pk.intensity < (min_relative_intensity / 100.0) * max_intensity:
                    continue
                if lo - d_tol_A <= pk.d_A <= hi + d_tol_A:
                    delta = min(abs(pk.d_A - lo), abs(pk.d_A - hi), abs(pk.d_A - d_ref))
                    if delta < best_delta:
                        best_delta = delta
                        best_i = i
            if best_i is not None:
                pk = peaks[best_i]
                used_obs.add(best_i)
                matched.append(Match(
                    ref_phase=phase, ref_d_A=d_ref, ref_hkl=hkl, ref_confidence=conf,
                    obs_d_A=pk.d_A, obs_two_theta=pk.two_theta, delta_d_A=best_delta,
                    obs_intensity=pk.intensity,
                    relative_intensity_pct=pk.intensity / max_intensity * 100.0,
                ))
        n_primary = sum(1 for m in matched if m.ref_confidence == "primary")
        n_secondary = sum(1 for m in matched if m.ref_confidence == "secondary")
        n_required = len(primary_eval) * 2 + len(secondary_eval)
        if n_required == 0:
            score = 0.0
        else:
            score = (n_primary * 2 + n_secondary) / n_required
        notes: list[str] = []
        # Score-inflation guard (defect 6): when no primary reflection is
        # evaluable (outside scan window), the score cannot represent a full
        # match — annotate so the reader never reads 1.0 as "all reference
        # peaks present".
        if not primary_eval and score > 0.0:
            notes.append(f"主反射({len(primary_eval)} 条)不在扫描窗口内,score 仅基于支持反射,"
                         "不代表完整匹配")
        if len(matched) < min_peaks:
            notes.append(f"匹配峰数少于阈值 min_peaks={min_peaks}")
        if n_primary > 0 and n_secondary == 0 and score < 0.5:
            notes.append("主反射匹配但支持反射未匹配,置信度受限")
        if n_primary == 0 and n_secondary > 0:
            notes.append("仅匹配到支持反射,不足以单独鉴定晶型")
        # 单个峰(或峰数不足)永远不能升级到 identified——匹配峰数本身是
        # verdict 的硬性约束,不能只靠主峰权重分数。这是规格 §四.2
        # "不得仅凭单个峰武断识别矿物相"的代码级落实。
        if n_primary >= 1 and score >= 0.5 and len(matched) >= min_peaks:
            verdict = "identified"
        elif score >= 0.3:
            verdict = "candidate"
        elif score > 0.0:
            verdict = "weak"
        else:
            verdict = "absent"
        results.append(PhaseMatchResult(
            phase=phase, matched_peaks=matched, score=round(score, 4), verdict=verdict,
            n_required_peaks=n_required, max_intensity_obs=max_intensity, notes=notes,
        ))
    results.sort(key=lambda r: (r.score, len(r.matched_peaks)), reverse=True)
    return results


def parse_twotheta_intensity(values: list[float]) -> tuple[np.ndarray, np.ndarray]:
    """Parse a flat [x0, y0, x1, y1, ...] or [[x,y], ...] series.

    The input `values` follows the sample contract (list of numbers or list of
    [x, y] pairs). Returns (2theta, intensity) arrays. Raises OMM-E104 on
    malformed data.
    """
    if not values:
        raise make_error("OMM-E104", "XRD values 为空", {})
    if all(isinstance(v, (int, float)) for v in values):
        if len(values) % 2 != 0:
            raise make_error("OMM-E104", "扁平序列长度必须为偶数([x,y,x,y,...])", {"n": len(values)})
        xs = values[0::2]
        ys = values[1::2]
    elif all(isinstance(v, (list, tuple)) and len(v) == 2 for v in values):
        xs = [v[0] for v in values]
        ys = [v[1] for v in values]
    else:
        raise make_error("OMM-E104", "XRD values 必须是 [x,y,...] 或 [[x,y],...]", {})
    return _clean_series(np.asarray(xs, dtype=float), np.asarray(ys, dtype=float))


def result_to_dict(result: PhaseMatchResult) -> dict[str, Any]:
    """Serialize a PhaseMatchResult, preserving per-peak confidence so the
    fusion scorer can detect primary reflections."""
    return {
        "phase": result.phase,
        "verdict": result.verdict,
        "score": result.score,
        "n_required_peaks": result.n_required_peaks,
        "matched_peak_count": len(result.matched_peaks),
        "primary_matched": any(m.ref_confidence == "primary" for m in result.matched_peaks),
        "peaks": [
            {
                "ref_d_A": round(m.ref_d_A, 4),
                "hkl": list(m.ref_hkl),
                "ref_confidence": m.ref_confidence,
                "obs_d_A": round(m.obs_d_A, 4),
                "obs_2theta": round(m.obs_two_theta, 3),
                "delta_d_A": round(m.delta_d_A, 5),
                "rel_intensity_pct": round(m.relative_intensity_pct, 1),
            }
            for m in result.matched_peaks[:3]
        ],
        "notes": result.notes,
    }
