"""Recover approximate telemetry from a reference onboard video overlay.

This module intentionally treats video-derived values as approximate evidence. It is
useful when a reference driver publishes speedometer/track-map overlays but no raw log.
The extractor is calibration-driven: no video layout, ROI, color, or dial geometry is
hard-coded for one driver.
"""

from __future__ import annotations

import csv
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np


@dataclass(frozen=True)
class Rect:
    x: int
    y: int
    width: int
    height: int

    @classmethod
    def from_mapping(cls, value: dict[str, Any]) -> "Rect":
        return cls(int(value["x"]), int(value["y"]), int(value["width"]), int(value["height"]))


@dataclass(frozen=True)
class NeedleCalibration:
    """Piecewise-linear mapping from an *unwrapped* dial angle to speed.

    Use at least two manually verified anchor points from the same overlay. Angles are
    degrees in mathematical coordinates: 0=right, 90=up. If the needle crosses +/-180,
    unwrap the anchors before putting them in the config.
    """

    angle_speed_points: tuple[tuple[float, float], ...]

    def __post_init__(self) -> None:
        if len(self.angle_speed_points) < 2:
            raise ValueError("Needle calibration requires at least two angle/speed anchors")
        angles = [p[0] for p in self.angle_speed_points]
        if any(b <= a for a, b in zip(angles, angles[1:])):
            raise ValueError("Needle calibration angles must be strictly increasing")

    @classmethod
    def from_mapping(cls, value: list[list[float]] | list[tuple[float, float]]) -> "NeedleCalibration":
        return cls(tuple((float(angle), float(speed)) for angle, speed in value))

    def speed_from_angle(self, angle_deg: float) -> float:
        x = np.asarray([p[0] for p in self.angle_speed_points], dtype=np.float64)
        y = np.asarray([p[1] for p in self.angle_speed_points], dtype=np.float64)
        return float(np.interp(float(angle_deg), x, y))


@dataclass(frozen=True)
class OverlayConfig:
    speedometer_roi: Rect
    needle_center_xy: tuple[float, float]
    calibration: NeedleCalibration
    track_map_roi: Rect | None = None
    marker_hsv_lower: tuple[int, int, int] | None = None
    marker_hsv_upper: tuple[int, int, int] | None = None
    canny_low: int = 60
    canny_high: int = 160
    center_tolerance_px: float = 18.0
    min_needle_length_px: float = 18.0
    max_needle_length_px: float = 180.0

    @classmethod
    def from_mapping(cls, value: dict[str, Any]) -> "OverlayConfig":
        marker = value.get("track_map_marker") or {}
        return cls(
            speedometer_roi=Rect.from_mapping(value["speedometer_roi"]),
            needle_center_xy=tuple(float(v) for v in value["needle_center_xy"]),
            calibration=NeedleCalibration.from_mapping(value["angle_speed_points"]),
            track_map_roi=(Rect.from_mapping(value["track_map_roi"]) if value.get("track_map_roi") else None),
            marker_hsv_lower=(tuple(int(v) for v in marker["hsv_lower"]) if marker.get("hsv_lower") else None),
            marker_hsv_upper=(tuple(int(v) for v in marker["hsv_upper"]) if marker.get("hsv_upper") else None),
            canny_low=int(value.get("canny_low", 60)),
            canny_high=int(value.get("canny_high", 160)),
            center_tolerance_px=float(value.get("center_tolerance_px", 18.0)),
            min_needle_length_px=float(value.get("min_needle_length_px", 18.0)),
            max_needle_length_px=float(value.get("max_needle_length_px", 180.0)),
        )


def load_overlay_config(path: str | Path) -> OverlayConfig:
    return OverlayConfig.from_mapping(json.loads(Path(path).read_text(encoding="utf-8")))


def _cv2():
    try:
        import cv2
    except ImportError as exc:
        raise RuntimeError(
            "Reference-video extraction requires OpenCV. Install with: "
            "pip install -e '.[video]'"
        ) from exc
    return cv2


def _crop(frame: np.ndarray, rect: Rect) -> np.ndarray:
    return frame[rect.y : rect.y + rect.height, rect.x : rect.x + rect.width]


def _line_angle_from_center(
    line: np.ndarray,
    center_xy: tuple[float, float],
    center_tolerance_px: float,
) -> tuple[float, float] | None:
    x1, y1, x2, y2 = [float(v) for v in line]
    cx, cy = center_xy
    d1 = math.hypot(x1 - cx, y1 - cy)
    d2 = math.hypot(x2 - cx, y2 - cy)
    near = min(d1, d2)
    if near > center_tolerance_px:
        return None
    fx, fy = (x1, y1) if d1 > d2 else (x2, y2)
    length = math.hypot(fx - cx, fy - cy)
    # Image Y grows downward, so negate dy for mathematical coordinates.
    angle = math.degrees(math.atan2(-(fy - cy), fx - cx))
    return angle, length


def detect_needle_angle(frame: np.ndarray, config: OverlayConfig) -> float | None:
    """Estimate analog speedometer needle angle with Hough line segments."""
    cv2 = _cv2()
    roi = _crop(frame, config.speedometer_roi)
    gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
    gray = cv2.GaussianBlur(gray, (3, 3), 0)
    edges = cv2.Canny(gray, config.canny_low, config.canny_high)
    lines = cv2.HoughLinesP(
        edges,
        rho=1,
        theta=np.pi / 180.0,
        threshold=18,
        minLineLength=max(8, int(config.min_needle_length_px * 0.55)),
        maxLineGap=8,
    )
    if lines is None:
        return None

    cx = config.needle_center_xy[0] - config.speedometer_roi.x
    cy = config.needle_center_xy[1] - config.speedometer_roi.y
    candidates: list[tuple[float, float]] = []
    for raw in lines[:, 0, :]:
        result = _line_angle_from_center(raw, (cx, cy), config.center_tolerance_px)
        if result is None:
            continue
        angle, length = result
        if config.min_needle_length_px <= length <= config.max_needle_length_px:
            candidates.append((length, angle))
    if not candidates:
        return None
    candidates.sort(reverse=True)
    return float(candidates[0][1])


def detect_track_marker(frame: np.ndarray, config: OverlayConfig) -> tuple[float, float] | None:
    """Return the overlay track-map marker centroid in full-frame pixel coordinates."""
    if (
        config.track_map_roi is None
        or config.marker_hsv_lower is None
        or config.marker_hsv_upper is None
    ):
        return None
    cv2 = _cv2()
    rect = config.track_map_roi
    roi = _crop(frame, rect)
    hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(
        hsv,
        np.asarray(config.marker_hsv_lower, dtype=np.uint8),
        np.asarray(config.marker_hsv_upper, dtype=np.uint8),
    )
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    moments = cv2.moments(mask)
    if moments["m00"] <= 0:
        return None
    x = float(moments["m10"] / moments["m00"] + rect.x)
    y = float(moments["m01"] / moments["m00"] + rect.y)
    return x, y


def _unwrap_angle_near_calibration(angle_deg: float, calibration: NeedleCalibration) -> float:
    anchors = np.asarray([p[0] for p in calibration.angle_speed_points], dtype=np.float64)
    center = float((anchors[0] + anchors[-1]) * 0.5)
    candidates = np.asarray([angle_deg - 360.0, angle_deg, angle_deg + 360.0])
    return float(candidates[np.argmin(np.abs(candidates - center))])


def extract_reference_telemetry(
    video_path: str | Path,
    config: OverlayConfig,
    *,
    start_s: float = 0.0,
    end_s: float | None = None,
    sample_hz: float = 10.0,
) -> list[dict[str, float | None]]:
    """Sample a video overlay and recover approximate speed + track-map position.

    The returned schema mirrors the useful output from the reference-video
    prototype: ``video_t``, ``map_x``, ``map_y``, ``speed_mph``, ``needle_angle``.
    Missing detections remain ``None`` rather than being silently invented.
    """
    if sample_hz <= 0:
        raise ValueError("sample_hz must be positive")
    cv2 = _cv2()
    source = str(Path(video_path).expanduser().resolve())
    cap = cv2.VideoCapture(source)
    if not cap.isOpened():
        raise FileNotFoundError(f"Could not open video: {source}")
    try:
        fps = float(cap.get(cv2.CAP_PROP_FPS))
        frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        if not np.isfinite(fps) or fps <= 0:
            raise ValueError("Video FPS is unavailable")
        duration = frame_count / fps if frame_count > 0 else math.inf
        stop = min(duration, end_s) if end_s is not None else duration
        if stop <= start_s:
            raise ValueError("end_s must be greater than start_s")

        rows: list[dict[str, float | None]] = []
        step = 1.0 / sample_hz
        t = float(start_s)
        while t <= stop + 1e-9:
            cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000.0)
            ok, frame = cap.read()
            if not ok:
                break
            angle = detect_needle_angle(frame, config)
            marker = detect_track_marker(frame, config)
            speed = None
            if angle is not None:
                calibrated_angle = _unwrap_angle_near_calibration(angle, config.calibration)
                speed = config.calibration.speed_from_angle(calibrated_angle)
                angle = calibrated_angle
            rows.append(
                {
                    "video_t": t,
                    "map_x": marker[0] if marker is not None else None,
                    "map_y": marker[1] if marker is not None else None,
                    "speed_mph": speed,
                    "needle_angle": angle,
                }
            )
            t += step
        return rows
    finally:
        cap.release()


def write_reference_csv(rows: list[dict[str, float | None]], output_path: str | Path) -> Path:
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    fields = ["video_t", "map_x", "map_y", "speed_mph", "needle_angle"]
    with output.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    return output
