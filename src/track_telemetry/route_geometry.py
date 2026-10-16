"""Approximate local GPS geometry, with explicit spatial-window sensitivity."""
import numpy as np


def local_circle_fit(x, y):
    """Fit a circle to sampled XY points; this is not a track boundary or grip estimate."""
    x, y = np.asarray(x, dtype=float), np.asarray(y, dtype=float)
    if len(x) < 7 or len(x) != len(y) or not np.all(np.isfinite(x + y)):
        return {"unavailable_reason": "Insufficient finite GPS points"}
    x, y = x - x.mean(), y - y.mean()
    matrix = np.column_stack((2*x, 2*y, np.ones(len(x))))
    solution, _, rank, _ = np.linalg.lstsq(matrix, x*x + y*y, rcond=None)
    if rank < 3:
        return {"unavailable_reason": "Local GPS points do not constrain a circle"}
    cx, cy, constant = solution
    radius = float(np.sqrt(max(0., constant + cx*cx + cy*cy)))
    residual = float(np.sqrt(np.mean((np.hypot(x-cx, y-cy) - radius)**2)))
    return {"radius_m": radius, "radial_fit_rms_m": residual, "samples": len(x),
            "relative_fit_rms": residual / radius if radius > 0 else None,
            "circle_model_adequate": bool(radius > 0 and residual / radius <= .02)}


def route_geometry_profile(samples, positions, *, spans_m=(20., 30., 40.), native_rate_hz=None):
    """Use nearby recorded points over arc-distance spans; do not bridge GPS gaps."""
    if not samples:
        return []
    t = np.array([p["time_s"] for p in samples])
    p = np.array([p["progress"] for p in samples])
    x = np.array([p["x_m"] for p in samples])
    y = np.array([p["y_m"] for p in samples])
    segments = np.array([p.get("segment_id", 0) for p in samples])
    distance = np.r_[0., np.cumsum(np.hypot(np.diff(x), np.diff(y)))]
    result = []
    for position in positions:
        i = int(np.argmin(abs(p-position)))
        fits = {}
        for span in spans_m:
            lo, hi = np.searchsorted(distance, [distance[i]-span/2, distance[i]+span/2])
            if (lo == 0 or hi >= len(t) or np.any(np.diff(t[lo:hi]) > .25)
                    or len(np.unique(segments[lo:hi])) > 1):
                fits[str(span)] = {"unavailable_reason": "Spatial fit window truncated or contains GPS gap"}
            elif native_rate_hz is not None and (t[hi-1]-t[lo])*native_rate_hz < 6:
                fits[str(span)] = {"unavailable_reason": "Fewer than seven native GPS samples supported in fit window"}
            else:
                fits[str(span)] = local_circle_fit(x[lo:hi], y[lo:hi])
        result.append({"progress": float(p[i]), "time_s": float(t[i]), "x_m": float(x[i]),
                       "y_m": float(y[i]), "fits_by_span_m": fits})
    return result
