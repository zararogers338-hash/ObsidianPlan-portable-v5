"""Figure digitization interface for micp-evidence-extractor.

This is a documented INTERFACE, not a full image-processing pipeline. The skill
must be able to mark a value as DIGITIZED_FROM_FIGURE with a reading error
estimate even in a pure-stdlib environment. To keep the whole toolchain offline,
deterministic, and dependency-free:

  - `estimate_reading_error(resolution_px_per_unit, axis_length_px)` computes a
    defensible absolute reading error from the figure resolution (a cursor
    readout is at best ~0.5–1 px; we use a conservative 2 px band).
  - `prepare_digitization(figure_id, ...)` returns the metadata stub an agent
    (or a bundled raster tool) fills in. When an image library is unavailable
    and no pixel resolution is known, the interface returns a
    digitization_unavailable marker so the caller can flag the value as
    INFERRED-with-error rather than pretending it read the figure.

Nothing here ever fabricates a number read from a figure: without an actual
image + axis calibration, the value stays None.
"""

from __future__ import annotations

import math
from typing import Any


def estimate_reading_error(resolution_px_per_unit: float, axis_length_px: float = 100.0,
                           cursor_band_px: float = 2.0) -> float | None:
    """Absolute reading error in data units.

    error = cursor_band_px / resolution_px_per_unit. Returns None when the
    resolution is not positive (unknown calibration -> cannot estimate).
    """
    if not isinstance(resolution_px_per_unit, (int, float)) \
            or isinstance(resolution_px_per_unit, bool) \
            or resolution_px_per_unit <= 0:
        return None
    return round(cursor_band_px / float(resolution_px_per_unit), 12)


def resolution_from_axis(axis_data_range: float, axis_px: float) -> float | None:
    """px per data-unit from a known axis length in pixels and its data range."""
    if not isinstance(axis_data_range, (int, float)) or isinstance(axis_data_range, bool) \
            or axis_data_range <= 0:
        return None
    if not isinstance(axis_px, (int, float)) or isinstance(axis_px, bool) or axis_px <= 0:
        return None
    return float(axis_px) / float(axis_data_range)


def prepare_digitization(figure_id: str, *, axis_px: float | None = None,
                         axis_data_range: float | None = None,
                         image_library_available: bool = False,
                         value: float | None = None) -> dict[str, Any]:
    """Build the digitization metadata block for a DIGITIZED_FROM_FIGURE value.

    When `value` is None the block is a placeholder: the caller must NOT write
    a DIGITIZED_FROM_FIGURE quantity without a value + error estimate.
    """
    error: float | None = None
    if axis_px is not None and axis_data_range is not None:
        res = resolution_from_axis(axis_data_range, axis_px)
        error = estimate_reading_error(res) if res is not None else None
    return {
        "method": ("manual cursor readout" if value is not None
                   else "not_performed"),
        "error_estimate": error,
        "figure_ref": figure_id,
        "image_library_available": bool(image_library_available),
        "note": (None if value is not None else
                 "no calibrated image readout performed; a DIGITIZED_FROM_FIGURE "
                 "value cannot be produced without an axis-calibrated raster"),
        "ready": value is not None and error is not None,
    }
