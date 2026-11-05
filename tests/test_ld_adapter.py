"""MoTeC LD dispatch through load_telemetry and session discovery."""

import datetime

import numpy as np
import pytest

from track_telemetry import mcp_server
from track_telemetry.models import ChannelSeries
from track_telemetry.ttc_adapter import SUPPORTED_SUFFIXES, load_telemetry


def test_ld_suffix_supported():
    assert ".ld" in SUPPORTED_SUFFIXES


def _stub_parse(log, source):
    assert source.endswith(".ld")
    log.channels["Ground Speed"] = ChannelSeries(
        "Ground Speed", "km/h", np.array([3.0, 4.0, 5.0]), np.array([70.0, 71.0, 72.0]))
    log.channels["GPS Latitude"] = ChannelSeries(
        "GPS Latitude", "deg", np.array([3.0, 4.0, 5.0]), np.array([39.5, 39.51, 39.52]))
    log.channels["GPS Longitude"] = ChannelSeries(
        "GPS Longitude", "deg", np.array([3.0, 4.0, 5.0]), np.array([-122.3, -122.31, -122.32]))
    log.channels["Chassis Yaw Rate"] = ChannelSeries(
        "Chassis Yaw Rate", "deg/s", np.array([3.0, 4.0, 5.0]), np.array([1.0, 2.0, 3.0]))
    log.laps_info = {"laps": [{"lap_num": 3, "start_time": 3, "end_time": 5,
                               "duration": 2, "type": "Timed"}]}
    log.datetime = datetime.datetime(2026, 10, 17, 8, 57, 55)
    log.metadata["lap_timing_semantics"] = "Recorded MoTeC LD lap-number transitions"
    log.metadata["yaw_rate_source"] = "motec_ld_recorded_Chassis Yaw Rate"
    log.metadata["native_sample_rate_hz"] = {"Ground Speed": 25.0, "GPS Latitude": 25.0}
    log.metadata["channel_provenance"] = {
        "Ground Speed": {"raw_name": "Ground Speed", "series_sample_rate_hz": 25.0}}
    print("diagnostic must not corrupt MCP stdout")


def test_ld_dispatch_preserves_lap_semantics_and_rates(tmp_path, monkeypatch, capsys):
    from track_telemetry_converter.log import DataLog

    monkeypatch.setattr(DataLog, "from_motec_ld_log", _stub_parse)
    path = tmp_path / "synthetic.ld"
    path.write_bytes(b"synthetic adapter contract")
    result = load_telemetry(path)
    assert capsys.readouterr().out == ""
    assert result.metadata["source_format"] == "MoTeC LD"
    assert result.channel("speed_kmh").timestamps[0] == 3.0
    assert result.metadata["lap_timing_semantics"] == "Recorded MoTeC LD lap-number transitions"
    assert result.laps[0].number == 3
    assert result.laps[0].original_number == 3
    assert result.metadata["native_sample_rate_hz"]["speed_kmh"] == 25.0
    assert result.metadata["normalized_channel_provenance"]["speed_kmh"]["raw_name"] == "Ground Speed"
    assert result.metadata["yaw_rate_source"] == "motec_ld_recorded_Chassis Yaw Rate"
    # Descriptive source labels must not open independent-yaw gates.
    assert result.metadata["channel_sources"]["yaw_rate_dps"] == "unknown"
    assert result.metadata["control_semantics"] == {}


def test_ld_discovery_and_loading_remain_root_confined(tmp_path, monkeypatch):
    from track_telemetry_converter.log import DataLog

    monkeypatch.setattr(DataLog, "from_motec_ld_log", _stub_parse)
    path = tmp_path / "synthetic.ld"
    path.write_bytes(b"synthetic adapter contract")
    monkeypatch.setenv("TRACK_TELEMETRY_ROOT", str(tmp_path))
    index = mcp_server._session_index()
    assert list(index.values()) == [path.resolve()]
    parsed = mcp_server._load(next(iter(index)))
    assert parsed.metadata["source_format"] == "MoTeC LD"
    assert not mcp_server._session_capabilities(parsed)["tool_support"]["analyze_slip_angle"]
    with pytest.raises(PermissionError):
        mcp_server._load(str(tmp_path.parent / "outside.ld"))


@pytest.mark.parametrize("pressure_unit,pressure_value", [("bar", 2.0), ("kPa", 200.0)])
def test_binary_ld_units_laps_and_source_gates(tmp_path, pressure_unit, pressure_value):
    from track_telemetry_converter._vendor.ldparser import ldData

    class Column:
        def __init__(self, values):
            self.values = np.asarray(values, dtype=np.float64)
            self.dtype = self.values.dtype

        def __len__(self):
            return len(self.values)

        def to_numpy(self, dtype=None):
            return self.values.astype(dtype) if dtype else self.values

    class Table:
        def __init__(self, values):
            self.values = {name: Column(value) for name, value in values.items()}
            self.columns = list(self.values)

        def __getitem__(self, name):
            return self.values[name]

    n = 600
    binary = ldData.frompd(Table({
        "Ground Speed": np.full(n, 100.0),
        "Brake Pressure": np.full(n, pressure_value),
        "Throttle Pos": np.full(n, 30.0),
        "Accelerator Pos": np.full(n, 40.0),
        "Lap Number": np.repeat([7.0, 8.0, 9.0], 200),
    }))
    for channel in binary.channs:
        channel.unit = {"Ground Speed": "km/h", "Brake Pressure": pressure_unit,
                        "Throttle Pos": "%", "Accelerator Pos": "%",
                        "Lap Number": ""}[channel.name]
    path = tmp_path / "binary.ld"
    binary.write(str(path))
    session = load_telemetry(path)
    assert session.channel("brake_pressure_kpa").units == "kPa"
    np.testing.assert_allclose(session.channel("brake_pressure_kpa").values, 200.0)
    np.testing.assert_allclose(session.channel("throttle_pct").values, 30.0)
    np.testing.assert_allclose(session.channel("accelerator_pct").values, 40.0)
    assert [(lap.number, lap.kind) for lap in session.laps] == [
        (7, "Out Lap"), (8, "Timed"), (9, "In Lap")]
    assert session.metadata["normalized_channel_provenance"]["brake_pressure_kpa"][
        "source_units"] == pressure_unit
    assert session.metadata["channel_sources"]["brake_pressure_kpa"] == "unknown"
    assert session.metadata["control_semantics"]["accelerator_pct"] == "unverified"
