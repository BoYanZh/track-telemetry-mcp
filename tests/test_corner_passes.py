"""Corner passages preserve real GPS, source gates and distinct controls."""
from test_plot_reports import _session

from track_telemetry.coaching_report import render_report
from track_telemetry.corner_passes import measure_passages
from track_telemetry.debrief import build_debrief
from track_telemetry.reference import compare_reference_laps


def test_all_passages_and_unverified_g_are_preserved(tmp_path):
    result = build_debrief([_session(21, warped=True), _session(20)], tmp_path,
                           same_layout_confirmed=True, plots=False)
    evidence = result["evidence"]
    observations = [o for o in evidence["observations"] if "sector" in o]
    assert observations
    for o in observations:
        context = o["corner_passages"]
        assert context["context_start_progress"] <= o["physical_section_profile"][0]["progress"]
        assert len(context["passages"]) == 2
        for p in context["passages"]:
            assert p["gps_paths"]
            assert p["gps_core_paths"]
            assert p["core_duration_s"] <= p["context_duration_s"]
            assert "brake_events" in p["input_analysis"]
            assert "unavailable_reason" in p["g_usage"]
            assert not p["g_samples"]
            assert p["start_s"] < p["end_s"]
            assert "accelerator_pct" in p["controls"]
            assert "throttle_pct" in p["controls"]
    coaching = {"language": "zh-CN", "summary": "检查最快圈与分段理论最佳。",
                "hypotheses": [], "experiments": []}
    _, report = render_report(evidence, coaching)
    assert "先看这两组圈速" not in report
    assert "最快圈与分段理论最佳" in report
    assert "每次过弯的真实路线" in report
    assert "缺少来源和质量合格的实测 G" in report
    assert "加速踏板" in report and "总 G · 平面合成" in report
    assert "节气门体 · %" not in report and "制动踏板 · %" not in report
    assert 'class="route-canvas"' in report and 'data-route-action="in"' in report
    assert 'data-route-action="context"' in report
    assert "查看踏板、节气门、制动与转向" not in report
    assert "横向 G</h3>" not in report and "纵向 G</h3>" not in report
    from track_telemetry.corner_report import render_corner

    corner = render_corner(observations[0], lambda i, lap: f"{i}:{lap}", True)
    assert corner.count('<figure><h3>') == 4
    assert "速度 · 公里/小时" not in corner
    assert "刹车 · 压力 bar" in corner
    for o in observations:
        context = o["corner_passages"]
        timing = context["timing_check"]
        assert abs(timing["core_difference_s"] - o["measured_difference_s"]) < 1e-6
        assert abs(timing["context_difference_s"] - timing["core_difference_s"]
                   - timing["adjacent_only_difference_s"]) < 1e-9


def test_corner_g_uses_bounded_measured_window_and_native_rate_gate(tmp_path):
    sessions = [_session(21, warped=True), _session(20)]
    for session in sessions:
        session.metadata["channel_sources"] = {"lat_g": "imu", "long_g": "imu"}
        session.metadata["native_sample_rate_hz"] = {"lat_g": 25., "long_g": 25.}
    # A resampled 1 Hz sensor must remain unavailable despite dense output.
    sessions[1].metadata["native_sample_rate_hz"]["lat_g"] = 1.
    evidence = build_debrief(sessions, tmp_path, same_layout_confirmed=True,
                             plots=False)["evidence"]
    qualified = 0
    for o in (o for o in evidence["observations"] if "sector" in o):
        good, bad = o["corner_passages"]["passages"]
        if good["g_samples"]:
            qualified += 1
            assert good["g_usage"]["quality"]["analysis_window_s"] == [good["start_s"], good["end_s"]]
            assert good["g_usage"]["quality"]["native_sample_rate_hz"]["lat_g"] == 25.
        assert "Native G rate" in bad["g_usage"]["unavailable_reason"]
        assert not bad["g_samples"]
    assert qualified > 0


def test_missing_longitude_splits_actual_route_instead_of_interpolating():
    import numpy as np

    session = _session(20, n=601)
    aligned = compare_reference_laps(session, 1, session, 1, same_layout_confirmed=True)
    longitude = session.channel("gps_longitude_deg")
    longitude.values[(longitude.timestamps > 8) & (longitude.timestamps < 9)] = np.nan
    observation = {"physical_section_profile": [{"progress": .4}, {"progress": .45}]}
    result = measure_passages([session], observation, [], aligned, 0)
    assert len(result["passages"][0]["gps_paths"]) == 2


def test_pedal_duration_does_not_bridge_missing_samples_or_clock_gaps():
    import numpy as np
    import pytest

    from track_telemetry.corner_inputs import summarize_inputs

    samples = [{"time_s": t, "progress": t / 20, "value": value}
               for t, value in [(0., 100.), (.1, 100.), (.2, None), (.3, 100.),
                                (.4, 100.), (.9, 100.), (1., 100.)]]
    speed = [{"time_s": 0., "progress": 0., "value": 50.}]
    def control(samples):
        return {"samples": samples, "source": "can", "native_sample_rate_hz": 25.}
    passage = {"start_s": 0., "end_s": 1., "core_start_s": .2, "core_end_s": .8,
               "controls": {"speed_kmh": control(speed), "accelerator_pct": control(samples)}}
    result = summarize_inputs(_session(20), 1, passage, np.array([0., 1.]), np.array([0., 20.]), 0.)
    stats = result["controls"]["accelerator_pct"]
    assert stats["at_least_90_duration_s"] == pytest.approx(.3)
    assert stats["valid_interval_duration_s"] == pytest.approx(.3)
    assert stats["at_least_90_after_minimum"]["time_s"] == 0.
    assert stats["core_samples"]["first"]["time_s"] == .3
