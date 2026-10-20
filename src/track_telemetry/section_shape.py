"""Derive a driver-facing shape description for one reference section.

Deterministic geometry only: net heading change over the sampled reference
trajectory. No corner database and no official corner numbering.
"""
from __future__ import annotations

import math


def _heading_deg(a: dict, b: dict) -> float:
    return math.degrees(math.atan2(b["y_m"] - a["y_m"], b["x_m"] - a["x_m"]))


def _unwrap(degrees: list[float]) -> list[float]:
    out, previous = [], degrees[0]
    out.append(previous)
    for value in degrees[1:]:
        delta = (value - previous + 180.0) % 360.0 - 180.0
        previous = previous + delta
        out.append(previous)
    return out


def _local_max_turn(headings: list[float], span: int) -> float:
    """Largest absolute turn over any `span`-sample window."""
    if len(headings) <= span:
        return abs(headings[-1] - headings[0]) if headings else 0.0
    return max(abs(headings[i + span] - headings[i]) for i in range(len(headings) - span))


def section_shape(points: list[dict], lo: float, hi: float) -> dict:
    """Return net turn angle and a left/right/straight label for a progress span.

    `points` must be ordered along the lap with `progress` in [0, 1].
    Positive net angle (counter-clockwise) reads as a left turn.
    """
    selected = [p for p in points if lo - 1e-9 <= p["progress"] <= hi + 1e-9]
    if len(selected) < 3:
        return {"available": False, "reason": "too few sampled points in section"}
    headings = _unwrap([_heading_deg(selected[i], selected[i + 1]) for i in range(len(selected) - 1)])
    net = headings[-1] - headings[0]
    magnitude = abs(net)
    span = max(2, len(headings) // 5)
    local = _local_max_turn(headings, span)
    corner_near_bounds = local >= 40.0 and magnitude < 25.0
    if magnitude < 25.0:
        label_zh, label_en = ("区段内或边界附近有弯，整体走向近直",
                              "corner inside or near the bounds") if corner_near_bounds else (
            "基本直道或缓弯", "near-straight")
    elif magnitude < 100.0:
        label_zh, label_en = ("左弯", "left") if net > 0 else ("右弯", "right")
    else:
        label_zh, label_en = ("左急弯或连续左弯", "sharp or linked left") if net > 0 else (
            "右急弯或连续右弯", "sharp or linked right")
    return {"available": True, "net_angle_deg": round(net, 1), "local_max_turn_deg": round(local, 1),
            "label_zh": label_zh, "label_en": label_en, "samples": len(selected)}


def shape_sentence(points: list[dict], lo: float, hi: float, min_speed_kmh, zh: bool) -> str:
    """One short driver-facing sentence, or an empty string when geometry is unusable."""
    shape = section_shape(points, lo, hi)
    if not shape.get("available"):
        return ""
    angle = abs(shape["net_angle_deg"])
    near_bounds = shape["label_zh"].startswith("区段内")
    if near_bounds:
        head = (f"区段内或边界附近有弯（净转角{angle:.0f}°，局部最大转角{shape['local_max_turn_deg']:.0f}°）"
                if zh else f"corner inside or near the bounds (~{angle:.0f}° net)")
    else:
        head = (f"{shape['label_zh']}（净转角约{angle:.0f}°）" if zh
                else f"{shape['label_en']} (~{angle:.0f}° net)")
    parts = [head]
    if isinstance(min_speed_kmh, (int, float)) and math.isfinite(min_speed_kmh):
        parts.append(f"最低速度约{min_speed_kmh:.0f}km/h" if zh
                     else f"min speed ~{min_speed_kmh:.0f} km/h")
    return "，".join(parts) + ("。" if zh else ".")
