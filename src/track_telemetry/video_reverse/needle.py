"""Analog needle extraction. Proven on 10 red/blue-needle videos (Fjy9, Gad,
5II, uFL, 15VN, JZN, rr2e, Zgdy + topbar family). cv2 is imported lazily."""

from __future__ import annotations

import math


def _cv2():
    import cv2

    return cv2


def color_mask(roi, kind: str):
    """Binary mask of needle pixels inside an ROI crop. ``roi`` is a BGR array."""
    np = __import__("numpy")
    cv2 = _cv2()
    b, g, r = cv2.split(roi.astype(np.int16))
    if kind in ("red", "redsoft"):
        return (((r - g > 50) & (r - b > 50) & (r > 100))).astype("uint8") * 255
    return (((b > 110) & (g > 110) & (r < 130))).astype("uint8") * 255


def needle_angle(frame, pivot_xy, roi, kind="red", gate_dist=25.0,
                 gate_pivot=60.0, drop_tail_below=-90.0):
    """Needle angle in degrees (atan2 convention, y up) or None.

    Picks the longest Hough segment passing near the pivot; the far endpoint
    is the tip. Segments pointing within ``drop_tail_below`` are needle-tail
    artifacts on the opposite side of the pivot and are skipped.
    """
    cv2 = _cv2()
    x0, y0, x1, y1 = roi
    px, py = pivot_xy
    crop = frame[y0:y1, x0:x1]
    mask = color_mask(crop, kind)
    lines = cv2.HoughLinesP(mask, 1, 3.14159 / 180.0, 12,
                            minLineLength=80, maxLineGap=12)
    if lines is None:
        return None
    best = None
    for a, b_, c, d in lines[:, 0, :]:
        fx1, fy1, fx2, fy2 = a + x0, b_ + y0, c + x0, d + y0
        dx, dy = fx2 - fx1, fy2 - fy1
        n = math.hypot(dx, dy)
        if n < 80:
            continue
        dist = abs(dy * px - dx * py + fx2 * fy1 - fy2 * fx1) / n
        if dist > gate_dist:
            continue
        d1 = math.hypot(fx1 - px, fy1 - py)
        d2 = math.hypot(fx2 - px, fy2 - py)
        if min(d1, d2) > gate_pivot:
            continue
        tip = (fx1, fy1) if d1 > d2 else (fx2, fy2)
        ang = math.degrees(math.atan2(-(tip[1] - py), tip[0] - px))
        if ang < drop_tail_below:
            continue
        if best is None or n > best[0]:
            best = (n, ang)
    return None if best is None else round(best[1], 2)


def angle_to_speed(angle, anchors):
    """Linear interp over (angle, mph) anchors. Returns (speed, clamped).

    ``clamped`` is True when the angle lies outside the anchor span: callers
    must extend anchors instead of shipping clamped stretches (lesson: 96
    samples once hid at a cold anchor).
    """
    xs = sorted(a for a, _ in anchors)
    if angle <= xs[0]:
        return anchors_sorted(anchors)[0][1], True
    if angle >= xs[-1]:
        return anchors_sorted(anchors)[-1][1], True
    ordered = anchors_sorted(anchors)
    for (x0, s0), (x1, s1) in zip(ordered, ordered[1:]):
        if x0 <= angle <= x1:
            t = (angle - x0) / (x1 - x0) if x1 > x0 else 0.0
            return round(s0 + t * (s1 - s0), 1), False
    last = ordered[-1][1]
    return last, True


def anchors_sorted(anchors):
    return sorted(anchors, key=lambda p: p[0])
