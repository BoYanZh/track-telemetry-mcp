from __future__ import annotations

from track_telemetry.reference_video import NeedleCalibration
from track_telemetry.visualization import render_incident_html


def test_reference_speedometer_calibration_is_piecewise_linear() -> None:
    calibration = NeedleCalibration(((-100.0, 55.0), (-50.0, 80.0), (0.0, 105.0)))
    assert calibration.speed_from_angle(-75.0) == 67.5
    assert calibration.speed_from_angle(-25.0) == 92.5


def test_incident_html_embeds_samples_without_case_specific_data() -> None:
    incident = {
        "window": {"start_s": 1.0, "end_s": 2.0, "anchor_s": 1.0},
        "summary": {"peak_abs_yaw_rate_dps": 25.0, "max_abs_sideslip_proxy_deg": 12.0},
        "timeline": [{"type": "snap_back", "time_s": 1.5}],
        "caveats": ["Synthetic fixture."],
        "samples": [
            {
                "time_s": 1.0,
                "x_m": 0.0,
                "y_m": 0.0,
                "speed_kmh": 100.0,
                "yaw_rate_dps": 5.0,
                "steering_deg": 2.0,
                "throttle_pct": 80.0,
                "body_heading_estimate_deg": 0.0,
                "travel_heading_deg": 0.0,
                "sideslip_proxy_deg": 0.0,
            },
            {
                "time_s": 1.5,
                "x_m": 10.0,
                "y_m": 2.0,
                "speed_kmh": 90.0,
                "yaw_rate_dps": -25.0,
                "steering_deg": -20.0,
                "throttle_pct": 0.0,
                "body_heading_estimate_deg": 15.0,
                "travel_heading_deg": 4.0,
                "sideslip_proxy_deg": -11.0,
            },
        ],
    }
    html = render_incident_html(
        incident,
        title="Synthetic incident",
        clean_reference_xy=[(0.0, 0.0), (10.0, 0.0)],
    )
    assert "Synthetic incident" in html
    assert "snap_back" in html
    assert "__PAYLOAD_JSON__" not in html
    assert "body_heading_estimate_deg" in html
