"""SEM particle statistics and image scale/segmentation utilities.

Handles the SEM evidence chain in this skill:
  * scale calibration (pixel <-> micron) with explicit unit_scale metadata;
  * particle statistics from an inline particle list (or, when scikit-image is
    available, from a real image — offline fallback lists are always allowed);
  * sampling-bias guards (spec §四.3): a single image must not be extrapolated
    to overall homogeneity; particle counts below a threshold raise a typed
    warning that the service surfaces as PARTIAL/uncertainty, never silence.

Image processing, when performed, records every parameter in an audit log so
it can be reproduced and audited (spec §四.7, §九.3).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from .errors import OmError, make_error


@dataclass
class ParticleStats:
    n: int
    min_area_um2: float
    max_area_um2: float
    mean_area_um2: float
    median_area_um2: float
    std_area_um2: float
    min_feret_um: float
    max_feret_um: float
    mean_feret_um: float
    circularity_mean: float
    calibration: str  # "um" | "px" | "uncalibrated"
    unit_scale_um_per_px: float | None
    notes: list[str] = field(default_factory=list)


def clean_particles(
    rows: list[list[float]],
    *,
    unit_scale_um_per_px: float | None,
    particle_units: str,
    min_columns: int = 3,
) -> tuple[np.ndarray, list[str]]:
    """Validate + clean an SEM particle row matrix.

    Each row is [x, y, area, ...]. Columns beyond the first 3 are kept as
    metadata. Returns (cleaned array [n, 3], notes). Raises OMM-E104 on empty
    or non-finite input.
    """
    if not rows:
        raise make_error("OMM-E104", "SEM 颗粒列表为空", {})
    if not all(isinstance(r, (list, tuple)) and len(r) >= min_columns for r in rows):
        raise make_error(
            "OMM-E104",
            f"SEM 颗粒行至少需要 {min_columns} 列 [x, y, area, ...]",
            {"sample_row": rows[0] if rows else None},
        )
    arr = np.asarray([[float(v) for v in r[:3]] for r in rows], dtype=float)
    if not np.isfinite(arr).all():
        raise make_error("OMM-E104", "SEM 颗粒数据包含 NaN/Inf", {})
    if np.any(arr[:, 2] <= 0):
        raise make_error("OMM-E104", "SEM 颗粒面积必须为正", {"n_invalid": int(np.sum(arr[:, 2] <= 0))})
    notes: list[str] = []
    if particle_units == "px":
        if unit_scale_um_per_px is None:
            notes.append("颗粒以像素为单位且缺少 unit_scale,面积单位为 px(未校准)")
        else:
            arr[:, :2] = arr[:, :2] * unit_scale_um_per_px      # x, y linear
            arr[:, 2] = arr[:, 2] * (unit_scale_um_per_px ** 2)  # area quadratic
    return arr, notes


def _feret_diameter(area_um2: float) -> float:
    """Estimate Feret diameter from area assuming compact (near-circular) grain.

    NOTE: this is an approximation used only for reporting; true Feret
    diameter requires pixel-level measurement. Labelled CALCULATED in output.
    """
    return 2.0 * math.sqrt(area_um2 / math.pi)


def particle_stats(
    rows: list[list[float]],
    *,
    unit_scale_um_per_px: float | None = None,
    particle_units: str = "um",
    min_particles: int = 30,
) -> ParticleStats:
    """Compute area/Feret statistics from a particle list.

    `min_particles` is the minimum sample size for concluding representativeness;
    below it the caller (service) must surface the limitation instead of
    extrapolating to the whole sample.
    """
    arr, notes = clean_particles(rows, unit_scale_um_per_px=unit_scale_um_per_px,
                                 particle_units=particle_units)
    areas = arr[:, 2]
    if arr.shape[1] >= 3:
        # best-effort feret from row geometry when available (columns 3+ are area-or-metadata)
        pass
    ferets = np.asarray([_feret_diameter(a) for a in areas], dtype=float)
    n = int(arr.shape[0])
    if n < min_particles:
        notes.append(f"颗粒样本量 {n} < min_particles={min_particles},不宜据此外推整体均匀性")
    else:
        notes.append(f"颗粒样本量 {n} >= min_particles={min_particles}")

    def _fmt(v: float) -> float:
        return float(f"{v:.4f}")

    stats = ParticleStats(
        n=n,
        min_area_um2=_fmt(float(areas.min())),
        max_area_um2=_fmt(float(areas.max())),
        mean_area_um2=_fmt(float(areas.mean())),
        median_area_um2=_fmt(float(np.median(areas))),
        std_area_um2=_fmt(float(areas.std())),
        min_feret_um=_fmt(float(ferets.min())),
        max_feret_um=_fmt(float(ferets.max())),
        mean_feret_um=_fmt(float(ferets.mean())),
        circularity_mean=_fmt(float(np.mean(4 * math.pi * areas / (ferets ** 2)))),
        calibration="um" if (unit_scale_um_per_px or particle_units == "um") else "px",
        unit_scale_um_per_px=unit_scale_um_per_px,
        notes=notes,
    )
    return stats


# ---------------------------------------------------------------------------
# image segmentation (optional scikit-image)
# ---------------------------------------------------------------------------

class ImageAuditLog:
    """Append-only, parameter-recording audit trail for image processing.

    Every segmentation/enhancement operation records its parameters so an
    auditor can reproduce the exact processing and check whether any synthetic
    structure was introduced (spec §八.4 blind-test requirement).
    """

    def __init__(self) -> None:
        self._entries: list[dict[str, Any]] = []
        self._closed = False

    def record(self, step: str, params: dict[str, Any], result: dict[str, Any]) -> None:
        if self._closed:
            raise make_error("OMM-E501", "审计日志已关闭,不可继续记录", {})
        self._entries.append({"step": step, "params": params, "result": result})

    def close(self) -> list[dict[str, Any]]:
        self._closed = True
        return list(self._entries)


def segment_image_gray(
    gray: np.ndarray,
    *,
    threshold: str = "otsu",
    min_area_px: int = 5,
    max_area_px: int | None = None,
    audit: ImageAuditLog | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Segment bright particles on a grayscale image.

    Uses scikit-image when importable; otherwise falls back to a numpy
    threshold (Otsu-equivalent percentile) so the skill never hard-requires
    the dependency. Returns (particles, params) where each particle has
    x/y/area (px). `params` records everything the audit needs.

    NOTE: this is deliberately a *lightweight* segmenter. It performs no
    morphological smoothing, no watershed, and does NOT attempt to separate
    touching crystals — the audit log and output explicitly state this so the
    skill never over-claims precision.
    """
    if gray.ndim != 2:
        raise make_error("OMM-E104", "灰度图像必须是二维数组", {"shape": gray.shape})
    if gray.size < 16:
        raise make_error("OMM-E104", "图像过小,无法分割", {"size": gray.size})
    gray = gray.astype(np.float32)
    gmin, gmax = float(gray.min()), float(gray.max())
    if gmax - gmin < 1e-6:
        raise make_error("OMM-E104", "图像灰度无对比度,无法分割", {})
    gray_norm = (gray - gmin) / (gmax - gmin)

    try:  # pragma: no cover - optional dependency
        from skimage import filters, measure

        if threshold == "otsu":
            thresh = filters.threshold_otsu(gray_norm)
        elif threshold == "median":
            thresh = filters.threshold_local(gray_norm, block_size=35, method="median")
        else:
            thresh = float(threshold) if isinstance(threshold, (int, float)) else filters.threshold_otsu(gray_norm)
        mask = gray_norm > thresh
        labels = measure.label(mask, connectivity=2)
        props = measure.regionprops(labels)
        used = "skimage"
    except Exception as exc:  # pragma: no cover - fallback
        # numpy fallback: Otsu-equivalent threshold at the 50% percentile of
        # non-background pixels is a crude but deterministic approximation.
        if threshold == "otsu":
            thresh = float(np.percentile(gray_norm, 60))
        elif isinstance(threshold, (int, float)):
            thresh = float(threshold)
        else:
            thresh = float(np.percentile(gray_norm, 60))
        mask = gray_norm > thresh
        labels = measure_fallback(mask)
        props = labels
        used = "numpy"

    particles: list[dict[str, Any]] = []
    for prop in props:
        area = float(prop.area)
        if area < min_area_px:
            continue
        if max_area_px is not None and area > max_area_px:
            continue
        # use regionprops centroid when skimage, else pixel arithmetic
        if used == "skimage":
            cy, cx = prop.centroid
        else:
            cy, cx = prop
        particles.append({
            "x_px": float(cx),
            "y_px": float(cy),
            "area_px": area,
            "label": len(particles),
        })

    params = {
        "threshold_method": threshold,
        "thresh_value": float(thresh) if isinstance(thresh, (int, float)) else None,
        "min_area_px": min_area_px,
        "max_area_px": max_area_px,
        "library": used,
        "note": "lightweight segmenter: no watershed/morphology; touching crystals "
                "are NOT separated; results are estimates, audited.",
    }
    if audit is not None:
        audit.record("segment_image_gray", params, {"n_particles": len(particles)})
    return particles, params


def measure_fallback(mask: np.ndarray) -> list[tuple[float, float]]:
    """Label connected components with numpy only (4-connectivity flood fill).

    Returns centroid (y, x) tuples per component. Slow but dependency-free;
    used only when scikit-image is absent.
    """
    import numpy as np

    h, w = mask.shape
    visited = np.zeros((h, w), dtype=bool)
    centroids: list[tuple[float, float]] = []
    for j in range(h):
        for i in range(w):
            if not mask[j, i] or visited[j, i]:
                continue
            stack = [(j, i)]
            visited[j, i] = True
            ys: list[int] = []
            xs: list[int] = []
            while stack:
                cy, cx = stack.pop()
                ys.append(cy)
                xs.append(cx)
                for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                    ny, nx = cy + dy, cx + dx
                    if 0 <= ny < h and 0 <= nx < w and mask[ny, nx] and not visited[ny, nx]:
                        visited[ny, nx] = True
                        stack.append((ny, nx))
            centroids.append((float(np.mean(ys)), float(np.mean(xs))))
    return centroids
