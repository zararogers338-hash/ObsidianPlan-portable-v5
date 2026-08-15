"""EDS / FTIR / Raman / TGA spectrum parsing and evidence extraction.

Each modality reports its own *evidence boundary* (spec §四.4): the parser
returns structured evidence with an explicit `modality` and `confidence` so
the fusion scorer never conflates what each technique can actually prove.

Evidence-boundary rules implemented here:
  * EDS — detects the presence of Ca (K-alpha ~3.69 keV) and optionally other
    cations. EDS proves *an element is present in the probed volume*, NOT that
    CaCO3 exists and NOT which polymorph. Output is always labeled
    `supporting` at most.
  * FTIR / Raman — identify carbonate functional-group bands. Bands are
    assigned against reference wavenumbers with an explicit tolerance. FTIR
    band positions are *informative* but matrix shifts mean identification
    needs corroboration.
  * TGA — a mass-loss curve. Only the stoichiometric CO2 loss (43.97 wt% for
    CaCO3 -> CaO) and decomposition temperature windows are compared. TGA
    cannot separate calcite/aragonite/vaterite on its own (their decompositions
    overlap once sample-dependent kinetics are considered); it *can* bound ACC
    / hydrated content via low-temperature loss steps.

All parsers are pure (list[float] in, dict out) and offline.
"""

from __future__ import annotations

from typing import Any

import numpy as np

from .errors import OmError, make_error
from .minerals import MINERAL_PHASES

CA_CO3_STOICHIOMETRIC_CO2_WT_PCT = 43.97


def _clean_channel(channels: list[float], intensities: list[float]) -> tuple[np.ndarray, np.ndarray]:
    if not channels or not intensities:
        raise make_error("OMM-E104", "光谱通道或强度为空", {})
    if len(channels) != len(intensities):
        raise make_error("OMM-E104", "光谱通道与强度长度不一致", {
            "len_channels": len(channels), "len_intensities": len(intensities)})
    c = np.asarray(channels, dtype=float)
    it = np.asarray(intensities, dtype=float)
    finite = np.isfinite(c) & np.isfinite(it)
    if not np.any(finite):
        raise make_error("OMM-E104", "光谱数据全部为非有限值", {})
    return c[finite], it[finite]


def _peaks_near(x: np.ndarray, y: np.ndarray, centers: list[float], tol: float) -> list[float]:
    """Return centers that have a local maximum within tol (x in same units).

    A peak requires: positive intensity, strict local maximum over both
    neighbors, and dominance within its tolerance window. Flat/zero baselines
    therefore never count (they would trivially satisfy a non-strict
    comparison on zero).
    """
    hits: list[float] = []
    for center in centers:
        within_idx = np.where(np.abs(x - center) <= tol)[0]
        if within_idx.size == 0:
            continue
        best = int(within_idx[np.argmax(y[within_idx])])
        if y[best] <= 0:
            continue
        if best > 0 and y[best] <= y[best - 1]:
            continue
        if best < x.size - 1 and y[best] <= y[best + 1]:
            continue
        hits.append(float(x[best]))
    return hits


def parse_eds(
    channels: list[float],
    intensities: list[float],
    *,
    ca_kev: float = 3.690,
    tol_kev: float = 0.15,
    other_peaks_kev: list[float] | None = None,
) -> dict[str, Any]:
    """EDS interpretation.

    Returns evidence that the probed volume contains Ca (and optionally other
    peaks), ALWAYS bounded to what EDS can prove (see module docstring).
    """
    c, it = _clean_channel(channels, intensities)
    ca_hit = bool(_peaks_near(c, it, [ca_kev], tol_kev))
    other_hits: list[float] = []
    if other_peaks_kev:
        other_hits = _peaks_near(c, it, other_peaks_kev, tol_kev)

    statements: list[str] = []
    if ca_hit:
        statements.append(f"EDS 检出 Ca K-alpha 峰(约 {ca_kev:.3f} keV±{tol_kev});"
                          "这只证明探测体积含钙,不证明 CaCO3 存在,更不证明晶型")
    else:
        statements.append(f"EDS 未在 {ca_kev:.3f}±{tol_kev} keV 检出 Ca 峰")
    if other_hits:
        statements.append(f"EDS 另检出峰: {', '.join(f'{v:.2f} keV' for v in other_hits)}"
                          "(可能对应其他元素,需按仪器峰表核验)")

    return {
        "modality": "eds",
        "ca_present": ca_hit,
        "ca_kev": ca_kev,
        "tol_kev": tol_kev,
        "other_peaks_kev": other_hits,
        "statements": statements,
        "max_evidence": "supporting",  # never exceeds supporting (see docstring)
        "note": "EDS 元素检出是 CaCO3 鉴定的必要非充分条件",
    }


def parse_ftir(
    channels: list[float],  # wavenumbers, cm-1
    intensities: list[float],
    *,
    tol_cm1: float = 8.0,
) -> dict[str, Any]:
    """FTIR interpretation.

    Matches carbonate v2/v3/v4 bands against reference positions; returns per-
    phase evidence. FTIR bands are informative; a single band pair is NOT
    enough for polymorph identification (matrix-dependent shifts).
    """
    c, it = _clean_channel(channels, intensities)
    out: dict[str, Any] = {
        "modality": "ftir",
        "phase_evidence": {},
        "notes": [],
    }
    for phase, data in MINERAL_PHASES.items():
        ftir = data.get("ftir", {})
        refs = ftir.get("transmittance", [])
        hits = _peaks_near(c, it, [w for (w, _a, _conf) in refs], tol_cm1)
        if not hits:
            continue
        out["phase_evidence"][phase] = {
            "matched_bands_cm1": [round(h, 1) for h in hits],
            "confidence": "supporting",
            "note": "FTIR 峰位受基质与结晶度影响,单靠 FTIR 不足以单独鉴定晶型",
        }
    if not out["phase_evidence"]:
        out["notes"].append("未匹配到参考碳酸盐 FTIR 谱带")
    return out


def parse_raman(
    channels: list[float],  # wavenumber shift, cm-1
    intensities: list[float],
    *,
    tol_cm1: float = 8.0,
) -> dict[str, Any]:
    """Raman interpretation (same evidence boundary as FTIR)."""
    c, it = _clean_channel(channels, intensities)
    out: dict[str, Any] = {"modality": "raman", "phase_evidence": {}, "notes": []}
    for phase, data in MINERAL_PHASES.items():
        refs = data.get("raman", [])
        hits = _peaks_near(c, it, [w for (w, _a, _conf) in refs], tol_cm1)
        if not hits:
            continue
        out["phase_evidence"][phase] = {
            "matched_bands_cm1": [round(h, 1) for h in hits],
            "confidence": "supporting",
            "note": "Raman 与 FTIR 同为振动谱,证据边界一致;v1 主带 1086-1090 需与晶型敏感带联用",
        }
    if not out["phase_evidence"]:
        out["notes"].append("未匹配到参考碳酸盐 Raman 谱带")
    return out


def parse_tga(
    temperature_c: list[float],
    mass_pct: list[float],
    *,
    co2_threshold_wt_pct: float = 40.0,
) -> dict[str, Any]:
    """TGA interpretation.

    Compares the total low/high-temperature mass loss against the CaCO3
    stoichiometric CO2 loss (43.97 wt%) and per-phase decomposition windows.
    Explicitly does NOT identify a polymorph: decomposition temperatures overlap
    once sample kinetics are considered. It CAN bound ACC/hydrate content.
    """
    c, it = _clean_channel(temperature_c, mass_pct)
    if np.any(it < 0) or np.any(it > 100):
        raise make_error("OMM-E104", "TGA 质量必须为 0-100 wt%", {"range": [float(it.min()), float(it.max())]})
    # total loss from start to end
    total_loss = float(it[0] - it[-1])
    # low-temperature loss (<250 C): structural water / organics / ACC dehydration
    low_mask = c < 250.0
    low_loss = float(it[0] - it[low_mask][-1]) if np.any(low_mask) and low_mask[-1] else 0.0
    # decomposition window (450-900 C): carbonates
    dec_mask = (c >= 450.0) & (c <= 900.0)
    dec_loss = 0.0
    if np.any(dec_mask):
        sub = it[dec_mask]
        dec_loss = float(sub[0] - sub[-1])

    ratio = total_loss / CA_CO3_STOICHIOMETRIC_CO2_WT_PCT if CA_CO3_STOICHIOMETRIC_CO2_WT_PCT else 0.0

    statements: list[str] = []
    if total_loss >= co2_threshold_wt_pct:
        statements.append(
            f"TGA 总失重 {total_loss:.1f} wt% 接近或超过 CaCO3 化学计量 CO2 失重"
            f"(43.97 wt%),与含 CaCO3 一致;定量占比需校准后判定")
    else:
        statements.append(
            f"TGA 总失重 {total_loss:.1f} wt% 明显低于 CaCO3 化学计量 CO2 失重(43.97 wt%),"
            f"可能指示部分非碳酸盐基体、残余 ACC 或低碳酸盐化")
    if low_loss > 3.0:
        statements.append(f"低温段(<250 C)失重 {low_loss:.1f} wt%,指示结构水/有机物/含水 ACC")

    return {
        "modality": "tga",
        "total_mass_loss_wt_pct": round(total_loss, 2),
        "low_temp_loss_wt_pct": round(low_loss, 2),
        "decarbonation_loss_wt_pct": round(dec_loss, 2),
        "co2_loss_ratio": round(ratio, 3),
        "stoichiometric_co2_wt_pct": CA_CO3_STOICHIOMETRIC_CO2_WT_PCT,
        "statements": statements,
        "max_evidence": "supporting",
        "note": "TGA 不能独立区分方解石/文石/球霰石(分解温窗相互重叠),仅能支撑 CaCO3 存在与含水/非晶含量边界",
    }


def parse_spectrum(sample: dict[str, Any]) -> dict[str, Any]:
    """Dispatch a spectrum-type sample to the right parser.

    `sample` is a SampleSpec dict (see models.py). Returns the parser's dict
    with `modality` and `data_type` attached.
    """
    dtype = sample.get("data_type")
    channels = sample.get("channels")
    intensities = sample.get("intensities")
    values = sample.get("values")
    if values and not channels:
        # flat [x0,y0,x1,y1,...] fallback
        if len(values) % 2 == 0:
            channels = values[0::2]
            intensities = values[1::2]
    if dtype in ("eds_spectrum", "ftir_spectrum", "raman_spectrum", "tga_curve"):
        if channels is None or intensities is None:
            raise make_error("OMM-E104", f"{dtype} 需要 channels 与 intensities(或 values)", {})
        if dtype == "eds_spectrum":
            res = parse_eds(channels, intensities,
                            ca_kev=sample.get("ed_kev_ca", 3.690),
                            tol_kev=sample.get("ed_kev_tolerance", 0.15))
        elif dtype == "ftir_spectrum":
            res = parse_ftir(channels, intensities)
        elif dtype == "raman_spectrum":
            res = parse_raman(channels, intensities)
        else:
            res = parse_tga(channels, intensities)
        res["data_type"] = dtype
        return res
    raise make_error("OMM-E104", f"不支持的样本 data_type: {dtype}", {})
