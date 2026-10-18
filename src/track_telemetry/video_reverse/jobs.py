"""Job specs: per-video calibration. Code implements templates; every video's
geometry lives here, never hard-coded (pivots differ even between same-model
cars, e.g. 25px between two GR86 videos).
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class AnchoredJob:
    """Analog-needle job: angle -> speed via driver-read anchors."""

    video_path: str
    out_path: str
    speed_roi: tuple[int, int, int, int]  # x0, y0, x1, y1 full-frame
    pivot_xy: tuple[float, float]
    anchors: tuple[tuple[float, float], ...]  # (needle_angle_deg, mph), any order
    needle_kind: str = "red"  # red | redsoft | cyan
    gate_dist: float = 25.0
    gate_pivot: float = 60.0
    drop_tail_below: float = -90.0  # needle-tail artifact guard (cyan dials)
    map_roi: tuple[int, int, int, int] = (0, 0, 0, 0)
    marker_hsv_lower: tuple[int, int, int] = (0, 0, 0)
    marker_hsv_upper: tuple[int, int, int] = (0, 0, 0)
    sample_hz: float = 10.0
    title_lap_s: float | None = None
    direction: str = ""  # CW | CCW


@dataclass(frozen=True)
class OcrJob:
    """Digital-readout job: tesseract speed + map-dot position."""

    video_path: str
    out_path: str
    digit_roi: tuple[int, int, int, int]  # x, y, w, h full-frame
    map_roi: tuple[int, int, int, int]
    marker_hsv_lower: tuple[int, int, int]
    marker_hsv_upper: tuple[int, int, int]
    psm: int = 8
    valid_range: tuple[int, int] = (15, 140)
    sample_hz: float = 10.0
    scan_hz: float = 2.0  # marker-only window search rate
    title_lap_s: float | None = None
    direction: str = ""
    extra: dict = field(default_factory=dict)
