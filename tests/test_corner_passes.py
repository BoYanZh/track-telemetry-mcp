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
    assert "加速踏板" in report and "节气门体" in report


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
