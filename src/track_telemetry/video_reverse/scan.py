"""Sequential-decode scan + window search. Seeks cost ~2.7s each: always decode
forward and subsample, never seek per frame."""

from __future__ import annotations

import csv
import math


def iter_samples(video_path, sample_hz):
    """Yield (video_t, frame) at sample_hz by forward decode. Lazy cv2."""
    import cv2

    cap = cv2.VideoCapture(video_path)
    try:
        fps = cap.get(cv2.CAP_PROP_FPS)
        step = max(1, int(round(fps / sample_hz)))
        idx = 0
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            if idx % step == 0:
                yield idx / fps, frame
            idx += 1
    finally:
        cap.release()


def marker_track(video_path, map_roi, hsv_lower, hsv_upper, sample_hz,
                 progress_every=0, tag="scan"):
    """Full-video marker-only scan. Returns list of (video_t, (x, y) | None)."""
    from ..reference_video import OverlayConfig, Rect, detect_track_marker

    cfg = OverlayConfig(
        speedometer_roi=Rect(0, 0, 8, 8),
        needle_center_xy=(0.0, 0.0),
        calibration=None,
        track_map_roi=Rect(*map_roi),
        marker_hsv_lower=tuple(hsv_lower),
        marker_hsv_upper=tuple(hsv_upper),
    )
    pts = []
    for n, (vt, frame) in enumerate(iter_samples(video_path, sample_hz)):
        mk = detect_track_marker(frame, cfg)
        pts.append((vt, None if mk is None else (round(mk[0], 1), round(mk[1], 1))))
        if progress_every and (n + 1) % progress_every == 0:
            print(f"{tag}: {n + 1} samples @t={vt:.1f}", flush=True)
    return pts


def write_marker_csv(pts, out_path):
    with open(out_path, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["video_t", "map_x", "map_y"])
        for vt, m in pts:
            w.writerow([round(vt, 2), m[0] if m else "", m[1] if m else ""])


def find_windows(pts, target_s, tol=1.5, thresh_px=12.0):
    """Non-overlapping loop closures near target_s. Returns [(t0, t1, dur)]."""
    mk = [(t, x, y) for t, m in pts if m for x, y in [m]]
    laps, i = [], 0
    while i < len(mk):
        t0, x0, y0 = mk[i]
        found = None
        for j in range(i + 1, len(mk)):
            t1, x1, y1 = mk[j]
            if t1 - t0 > target_s + tol:
                break
            if t1 - t0 >= target_s - tol and math.hypot(x1 - x0, y1 - y0) < thresh_px:
                found = (t0, t1)
                i = j
                break
        if found:
            laps.append((round(found[0], 1), round(found[1], 1),
                         round(found[1] - found[0], 2)))
        else:
            i += 10
    return laps


def closure(pts, t0, t1):
    """Distance between marker near t0 and near t1 (loop-closure metric)."""
    mk = [(t, m[0], m[1]) for t, m in pts if m]
    a = min(mk, key=lambda p: abs(p[0] - t0))
    b = min(mk, key=lambda p: abs(p[0] - t1))
    return round(math.hypot(a[1] - b[1], a[2] - b[2]), 1)
