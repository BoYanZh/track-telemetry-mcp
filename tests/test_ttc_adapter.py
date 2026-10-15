"""Synthetic end-to-end text-format decoding and binary adapter contract."""

import datetime

import numpy as np
import pytest

from track_telemetry import mcp_server
from track_telemetry.models import ChannelSeries
from track_telemetry.ttc_adapter import load_telemetry


def test_csv_preserves_clock_labels_and_pedal_semantics(tmp_path, capsys):
    path = tmp_path / "synthetic.csv"
    path.write_text("Time,lap_number,speed,accelerator_pos,wheelspeedfl\n"
                    "s,,m/s,%,km/h\n" + "".join(
                        f"{100 + i * 0.1},{17 + i // 100},20,50,72\n" for i in range(301)))
    result = load_telemetry(path)
    assert capsys.readouterr().out == ""
    assert result.metadata["source_format"] == "RaceChrono CSV"
    assert result.channel("speed_kmh").values[0] == pytest.approx(72)
    assert result.channel("speed_kmh").timestamps[0] == 100
    assert "accelerator_pct" in result.channels
    assert "throttle_pct" not in result.channels
    assert result.channel("wheel_fl_kmh").values[0] == 72
    assert [lap.original_number for lap in result.laps] == [17, 18, 19, 20]
    assert [lap.kind for lap in result.laps] == ["Partial", "Timed", "Timed", "Partial"]
    assert result.laps[1].start_s == 110
    assert result.laps[1].end_s == 120


def test_csv_without_lap_metadata_has_no_fake_timed_lap(tmp_path):
    path = tmp_path / "unlapped.csv"
    path.write_text("Time,speed,bearing\ns,m/s,deg\n0,10,0\n1,10,2\n2,10,4\n")
    result = load_telemetry(path)
    assert result.laps == []
    assert result.metadata["yaw_rate_source"] == "gps_heading_derivative"


def test_vbo_midnight_clock_and_no_inferred_laps(tmp_path):
    path = tmp_path / "synthetic.VBO"
    path.write_text("File created on 14/10/2026 at 23:59:59\n[column names]\n"
                    "time lat long velocity\n[data]\n235959.9 2100 -7140 72\n"
                    "000000.1 2100.001 -7139.999 73\n")
    result = load_telemetry(path)
    assert result.channel("speed_kmh").timestamps == pytest.approx([0, 0.2])
    assert result.channel("gps_latitude_deg").values[0] == pytest.approx(35)
    assert result.laps == []
    assert result.metadata["recording_datetime"] == "2026-10-14T23:59:59"
    assert result.metadata["recording_datetime_timezone"] == "unspecified"


@pytest.mark.parametrize("suffix", [".xrk", ".xrz"])
def test_aim_dispatch_preserves_common_clock_and_laps(tmp_path, monkeypatch, suffix):
    import sys
    import types

    from track_telemetry_converter.log import DataLog

    def parse(log, source):
        assert source.endswith(suffix)
        log.channels["Ground Speed"] = ChannelSeries("Ground Speed", "km/h",
                                                       np.array([3., 4., 5.]), np.array([70., 71., 72.]))
        log.channels["Steering Angle"] = ChannelSeries("Steering Angle", "deg",
                                                        np.array([3.5, 4.5]), np.array([1., 2.]))
        log.laps_info = {"laps": [{"lap_num": 42, "start_time": 3, "end_time": 5,
                                   "duration": 2, "type": "Timed"}]}
        log.datetime = datetime.datetime(2026, 10, 14, 12)
        print("diagnostic must not corrupt MCP stdout")

    monkeypatch.setitem(sys.modules, "libxrk", types.ModuleType("libxrk"))
    monkeypatch.setattr(DataLog, "from_xrk_log", parse)
    path = tmp_path / f"synthetic{suffix}"
    path.write_bytes(b"synthetic adapter contract")
    result = load_telemetry(path)
    assert result.channel("steering_deg").timestamps[0] == 3.5
    assert result.laps[0].original_number == 42
    assert result.laps[0].start_s == 3
    assert result.metadata["channel_sources"]["steering_deg"] == "unknown"
    assert result.metadata["parser_diagnostics"]


def test_discovery_and_loading_non_rcz_remain_root_confined(tmp_path, monkeypatch):
    path = tmp_path / "synthetic.csv"
    path.write_text("Time,speed,bearing\ns,m/s,deg\n0,10,0\n1,10,2\n")
    monkeypatch.setenv("TRACK_TELEMETRY_ROOT", str(tmp_path))
    index = mcp_server._session_index()
    assert list(index.values()) == [path.resolve()]
    parsed = mcp_server._load(next(iter(index)))
    assert parsed.metadata["source_format"] == "RaceChrono CSV"
    assert not mcp_server._session_capabilities(parsed)["tool_support"]["compare_laps"]
    with pytest.raises(PermissionError):
        mcp_server._load(str(tmp_path.parent / "outside.csv"))


def test_invalid_text_fails_without_protocol_output(tmp_path, capsys):
    path = tmp_path / "broken.csv"
    path.write_text("not a telemetry file\n")
    with pytest.raises(ValueError, match="no supported"):
        load_telemetry(path)
    assert capsys.readouterr().out == ""
