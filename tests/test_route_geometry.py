"""GPS shape estimates remain approximate and must not join missing samples."""
import numpy as np
import pytest

from track_telemetry.route_geometry import local_circle_fit, route_geometry_profile


def test_circle_fit_preserves_radius_under_translation():
    angle = np.linspace(-.4, .4, 51)
    x, y = 40*np.cos(angle), 40*np.sin(angle)
    for dx, dy in [(0, 0), (100000, -300000)]:
        fit = local_circle_fit(x+dx, y+dy)
        assert fit["radius_m"] == pytest.approx(40, abs=1e-6)
        assert fit["circle_model_adequate"]
    assert "unavailable_reason" in local_circle_fit(np.arange(20), np.zeros(20))


def test_spatial_fit_does_not_bridge_a_missing_gps_sample():
    angle = np.linspace(-1, 1, 201)
    samples = [{"time_s": i*.04, "progress": i/200, "x_m": float(40*np.cos(a)),
                "y_m": float(40*np.sin(a)), "segment_id": int(i >= 100)}
               for i, a in enumerate(angle)]
    result = route_geometry_profile(samples, [.5])
    assert all("unavailable_reason" in fit for fit in result[0]["fits_by_span_m"].values())
    for sample in samples:
        sample["segment_id"] = 0
    sparse_native = route_geometry_profile(samples, [.5], native_rate_hz=1)
    assert all("native GPS" in fit["unavailable_reason"] for fit in sparse_native[0]["fits_by_span_m"].values())
