"""Time-weighted use of the observed acceleration envelope."""

from __future__ import annotations

import numpy as np

from .channels import LAT_G, LONG_G
from .models import TelemetrySession
from .quality import matched_window, measured_source


def analyze_gg_usage(session: TelemetrySession, lap_number: int) -> dict:
    """Measure recorded G occupancy, not available tire grip or a friction coefficient."""
    _, values, weights, quality = matched_window(session, lap_number, (LAT_G, LONG_G))
    if not all(measured_source(s) for s in quality["sources"].values()):
        raise ValueError("G usage requires verified measured acceleration sources")
    if any(rate is not None and rate < 5 for rate in quality["native_sample_rate_hz"].values()):
        raise ValueError("Native G rate below 5 Hz; output resampling cannot qualify the source")
    if session.channel(LAT_G).units.lower() != "g" or session.channel(LONG_G).units.lower() != "g":
        raise ValueError("Acceleration channels must use G units")
    lat, lon = values[:-1].T
    valid = weights > 0
    radius = np.hypot(lat, lon)
    total = float(weights.sum())

    def fraction(mask):
        return float(weights[mask & valid].sum() / total)

    # Duration-weighted quantiles avoid over-weighting densely sampled intervals.
    order = np.argsort(radius[valid])
    r = radius[valid][order]
    cumulative = np.cumsum(weights[valid][order])
    p95 = float(r[min(np.searchsorted(cumulative, total * 0.95), len(r) - 1)])
    return {
        "lap": session.lap(lap_number).to_dict(), "quality": quality,
        "observed_combined_g_p95": p95,
        "observed_combined_g_peak": float(np.max(radius[valid])),
        "time_above_g_fraction": {str(g): fraction(radius >= g) for g in (0.5, 1.0, 1.5)},
        "occupancy_fraction": {
            "braking": fraction(lon < -0.1), "acceleration": fraction(lon > 0.1),
            "combined_braking_cornering": fraction((lon < -0.1) & (abs(lat) > 0.2)),
            "low_load": fraction(radius < 0.2),
        },
        "limitations": ["Observed envelope is not available tire grip or a utilization percentage.",
                        "Vehicle-axis signs and sensor mounting must be calibrated; grade/banking affect G."],
    }
