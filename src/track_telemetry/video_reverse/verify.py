"""Four-check validation for reversed record data. Pure stdlib.

Direction rule (2026-10-17 lesson): NEVER infer CW/CCW from shoelace winding
sign alone — screen y-down coordinates flip the sign, and overlay maps are not
guaranteed north-up. Ground direction in the official track direction (event
organizer / track reference); winding signs are only valid for comparing laps
on the SAME track against each other.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class FourChecks:
    anchor_errors: list  # [(t, expected, got)] incl. held-out frames
    vmax: float | None
    vmin: float | None
    closure_px: float | None
    speed_rate: float
    marker_rate: float
    jumps_over_8: int
    passed: bool


def four_checks(rows, anchors=(), title_lap_s=None, vmax_band=(90.0, 102.0),
                closure_limit=6.0, anchor_tol=2.0):
    """rows: list of dicts with video_t/map_x/map_y/speed_mph (str/None ok)."""
    ok = [(float(r["video_t"]), float(r["speed_mph"])) for r in rows if r.get("speed_mph")]
    mk = [(float(r["video_t"]), float(r["map_x"]), float(r["map_y"]))
          for r in rows if r.get("map_x")]
    errs = []
    for t, exp in anchors:
        s = min(ok, key=lambda p: abs(p[0] - t))[1]
        errs.append((t, exp, round(s, 1)))
    spd = [s for _, s in ok]
    jumps = sum(1 for a, b in zip(spd, spd[1:]) if abs(b - a) > 8)
    closure = None
    if mk and title_lap_s:
        import math

        t0 = mk[0][0]
        b = min(mk, key=lambda p: abs(p[0] - (t0 + title_lap_s)))
        closure = round(math.hypot(mk[0][1] - b[1], mk[0][2] - b[2]), 1)
    lo, hi = vmax_band
    passed = (
        bool(ok)
        and all(abs(g - e) <= anchor_tol for _, e, g in errs)
        and (min(spd) >= 20 if spd else False)
        and (lo <= max(spd) <= hi + 5 if spd else False)
        and jumps == 0
        and (closure is None or closure <= closure_limit)
    )
    return FourChecks(errs, max(spd) if spd else None, min(spd) if spd else None,
                      closure, len(ok) / len(rows) if rows else 0,
                      len(mk) / len(rows) if rows else 0, jumps, passed)
