"""One-shot workflow safety gates and artifact contract."""
import asyncio
import json
import os
from pathlib import Path

import pytest
from mcp import Client
from test_plot_reports import _session
from test_rcz_integration import _build_multi_stint_archive

from track_telemetry import mcp_server
from track_telemetry.debrief import analyze_files, build_debrief, finalize_debrief
from track_telemetry.models import TelemetrySession


def _mixed_pace_session():
    import numpy as np

    from track_telemetry.models import ChannelSeries, Lap

    parts = [_session(duration, n=601) for duration in (20, 20.5, 23, 40)]
    channels = {}
    laps = []
    offset = 0.
    for number, part in enumerate(parts, 1):
        duration = part.laps[0].duration_s
        laps.append(Lap(number, str(number), "Timed", offset, offset + duration, duration, stint=0))
        for name, channel in part.channels.items():
            channels.setdefault(name, []).append((channel.timestamps + offset, channel.values))
        offset += duration + 5
    return TelemetrySession("mixed", "mixed", laps=laps, channels={
        name: ChannelSeries(name, parts[0].channels[name].units,
                            np.concatenate([t for t, _ in values]),
                            np.concatenate([v for _, v in values]))
        for name, values in channels.items()})


def test_slow_laps_preserved_but_not_ranked_as_driver_errors(tmp_path):
    evidence = build_debrief([_mixed_pace_session()], tmp_path, same_layout_confirmed=True,
                             plots=False)["evidence"]
    session = evidence["sessions"][0]
    assert session["consistency"]["count"] == 4
    assert session["candidate_push_consistency"]["count"] == 2
    audit = {lap["lap"]: lap for lap in session["lap_selection"]}
    assert audit[3]["classification"] == "unclassified_slow"
    assert audit[4]["classification"] == "unclassified_slow"
    assert not any(lap["intent_confirmed"] for lap in audit.values())
    assert {c["lap"] for c in evidence["comparisons"] if c["coaching_eligible"]} == {2}
    assert len(evidence["comparisons"]) == 3


def test_external_traffic_and_push_context_override_pace(tmp_path):
    session = _mixed_pace_session()
    evidence = build_debrief([session], tmp_path, plots=False, lap_context=[
        {"session": 0, "lap": 1, "classification": "traffic", "note": "Driver marked yielding"},
        {"session": 0, "lap": 3, "classification": "confirmed_push", "note": "Driver confirmed push"},
    ])["evidence"]
    assert evidence["reference"]["lap"] == 3
    audit = {lap["lap"]: lap for lap in evidence["sessions"][0]["lap_selection"]}
    assert not audit[1]["coaching_eligible"]
    assert audit[3]["coaching_eligible"] and audit[3]["intent_confirmed"]
    with pytest.raises(ValueError):
        build_debrief([session], tmp_path, lap_context=[
            {"session": 0, "lap": 99, "classification": "confirmed_push", "note": "wrong lap"}])


def test_concentrated_loss_is_flagged_not_called_traffic():
    from track_telemetry.debrief import _interruption_sectors

    flags = _interruption_sectors({"mini_sectors": [
        {"sector": i, "a_minus_b_s": 3. if i == 7 else .05} for i in range(1, 21)]})
    assert [flag["sector"] for flag in flags] == [7]
    assert "unresolved" in flags[0]["reason"]


def test_comparison_and_section_evidence(tmp_path):
    slow, fast = _session(21, warped=True), _session(20)
    result = build_debrief([slow, fast], tmp_path, same_layout_confirmed=True, plots=True)
    evidence = result["evidence"]
    assert evidence["reference"]["session"] == 1
    assert evidence["observations"]
    assert len(evidence["practice_plan"]) <= 3
    loss = next(o for o in evidence["observations"] if "sector" in o)
    assert loss["section_diagnostics"]["driver"]["control_source"]
    assert loss["loss_metric"] == "best_whole_lap_minus_sector_best"
    assert len(loss["physical_section_profile"]) == 11
    assert evidence["plots"][-1]["generated_plots"]
    for plot in evidence["plots"]:
        for path in plot.get("plot_files", {}).values():
            assert Path(path).read_bytes().startswith(b"\x89PNG")
    assert json.loads((tmp_path / "evidence.json").read_text())["status"] == "awaiting_agent_interpretation"
    assert "Next-session practice plan" in (tmp_path / "report.html").read_text()


def test_unconfirmed_layout_never_compares(tmp_path):
    result = build_debrief([_session(), _session(22)], tmp_path, plots=False)["evidence"]
    assert result["comparisons"] == []
    assert not result["time_loss_ranking"]
    assert result["unavailable_data"]


def test_diagnostics_target_best_lap_against_fastest_sector_source(tmp_path):
    evidence = build_debrief([_session(21, warped=True, n=601), _session(22, n=601),
                             _session(40, n=601), _session(20, n=601)],
                             tmp_path, same_layout_confirmed=True, plots=False)["evidence"]
    losses = [o for o in evidence["observations"] if "sector" in o]
    assert losses
    assert all(o["example_session"] == 3 for o in losses)
    assert any(o["section_reference"]["session"] == 0 for o in losses)


def test_missing_gps_and_no_laps(tmp_path):
    evidence = build_debrief([TelemetrySession("empty", "unknown")], tmp_path)["evidence"]
    assert evidence["reference"] is None
    assert evidence["sessions"][0]["consistency"]["count"] == 0
    with pytest.raises(ValueError):
        build_debrief([], tmp_path)


def test_recorded_stint_without_timed_laps_is_preserved(tmp_path):
    session = _session()
    session.metadata["stints"] = [{"stint": 0}, {"stint": 1}]
    evidence = build_debrief([session], tmp_path, plots=False)["evidence"]
    empty = next(s for s in evidence["sessions"][0]["stints"] if s["stint"] == 1)
    assert empty["consistency"]["count"] == 0


def test_divergent_layout_and_missing_sensors(tmp_path):
    first, second = _session(20, controls=False), _session(22, controls=False)
    from track_telemetry.channels import GPS_LATITUDE_DEG
    second.channels[GPS_LATITUDE_DEG].values += .1
    evidence = build_debrief([first, second], tmp_path, same_layout_confirmed=True,
                             plots=False)["evidence"]
    assert "unavailable_reason" in evidence["comparisons"][0]["result"]
    assert not evidence["time_loss_ranking"]
    assert "unavailable_reason" in evidence["diagnostics"][0]["wheel_speeds"]


def test_finalization_validates_before_publishing(tmp_path):
    build_debrief([_session()], tmp_path, plots=False)
    path = tmp_path / "evidence.json"
    original = path.read_bytes()
    coaching = {"summary": "Prioritize repeatability before pace.", "hypotheses": [],
                "experiments": [{"observation_ids": ["session-0"], "location": "Whole lap",
                                 "change": "Use consistent visual markers",
                                 "baseline": "Recorded session timing",
                                 "success_measure": "Lower per-stint MAD over three clear laps",
                                 "abort_condition": "Traffic or instructor concern",
                                 "re_test": "Next session with comparable conditions"}]}
    invalid = {**coaching, "experiments": coaching["experiments"] * 4}
    with pytest.raises(ValueError):
        finalize_debrief(path, invalid)
    assert path.read_bytes() == original
    finalize_debrief(path, coaching)
    assert json.loads(path.read_text())["status"] == "coaching_complete"
    assert "Use consistent visual markers" in (tmp_path / "report.md").read_text()
    assert "Use consistent visual markers" in (tmp_path / "report.html").read_text()
    assert "<table>" in (tmp_path / "report.html").read_text()
    assert "<pre>" not in (tmp_path / "report.html").read_text()


def test_chinese_report_has_spatial_figures_and_no_raw_field_dump(tmp_path):
    from track_telemetry.coaching_report import render_report

    evidence = build_debrief([_session(21, warped=True), _session(20)], tmp_path,
                             same_layout_confirmed=True, plots=False)["evidence"]
    assert len(evidence["reference_geometry"]["points"]) > 10
    loss = next(o for o in evidence["observations"] if "sector" in o)
    coaching = {"summary": "先复现快圈，再逐项练习。", "language": "zh-CN", "hypotheses": [
                    {"observation_ids": ["session-0"], "explanation": "未记录机油压力，不能验证油压安全。",
                     "confidence": "low", "confounders": ["缺少数据"]}],
                "sections": [{"observation_id": loss["id"], "title": "看图定位这个区段",
                              "interpretation": "<script>not executable</script>"}],
                "experiments": [{"observation_ids": [loss["id"]], "location": "distance 1234 m",
                                 "change": "固定一个参照", "baseline": "已记录的速度",
                                 "success_measure": "三个可比样本", "abort_condition": "有交通就停止",
                                 "re_test": "下一节复测"}]}
    markdown, document = render_report(evidence, coaching)
    assert 'lang="zh-CN"' in document
    assert document.count('<svg ') >= 3
    assert 'href="#zone-A"' in document
    assert "只改这一项" in document and "候选快圈" in document
    assert "median_loss_s" not in document
    assert "Session and stint timing" not in document
    assert "distance 1234 m" not in document
    assert "<script>not executable</script>" not in document and "&lt;script&gt;" in document
    assert document.count("<script") == 1 and '<script id="route-controls">' in document
    assert "固定一个参照" in markdown
    assert "未记录机油压力" in document and "未记录机油压力" in markdown
    assert '<details class="calculations">' in document
    assert '<details class="calculations" open' not in document
    assert document.index('id="zone-A"') < document.index('<details class="calculations">')
    assert document.index('class="sector-matrix"') > document.index('<details class="calculations">')


def test_all_stints_and_mcp(tmp_path, monkeypatch):
    path = tmp_path / "multi.rcz"
    _build_multi_stint_archive(path)
    result = analyze_files([path], tmp_path / "cli", plots=False)
    assert len(result["evidence"]["sessions"][0]["stints"]) == 3
    monkeypatch.setenv("TRACK_TELEMETRY_ROOT", str(tmp_path))

    async def run():
        async with Client(mcp_server.mcp) as client:
            result = await client.call_tool("analyze_session_debrief", {
                "paths": [str(path)], "output_dir": "mcp-report", "plots": False})
            assert not result.is_error
            denied = await client.call_tool("analyze_session_debrief", {
                "paths": [str(path)], "output_dir": str(tmp_path.parent / "escape")})
            assert denied.is_error
            finalized = await client.call_tool("finalize_session_debrief", {
                "evidence_path": "mcp-report/evidence.json",
                "coaching": {"summary": "Measure repeatability first.", "hypotheses": [],
                             "experiments": [{"observation_ids": ["session-0"],
                                              "location": "Whole lap", "change": "Consistent markers",
                                              "baseline": "Recorded lap-time MAD",
                                              "success_measure": "Reduced spread on three clear laps",
                                              "abort_condition": "Traffic or instructor concern",
                                              "re_test": "Next comparable stint"}]}})
            assert not finalized.is_error
    asyncio.run(run())
    assert (tmp_path / "mcp-report" / "report.md").is_file()
    assert json.loads((tmp_path / "mcp-report" / "evidence.json").read_text())["status"] == "coaching_complete"


@pytest.mark.skipif(not os.getenv("TRACK_TELEMETRY_REAL_RCZ"), reason="Set local real RCZ path")
def test_local_real_rcz(tmp_path):
    result = analyze_files([Path(os.environ["TRACK_TELEMETRY_REAL_RCZ"])], tmp_path, plots=True)
    assert result["evidence"]["sessions"][0]["summary"]["channels"]
    assert (tmp_path / "report.html").stat().st_size > 100
    assert result["evidence"]["sessions"][0]["consistency"]["count"] > 0
    assert result["evidence"]["comparisons"] == []
