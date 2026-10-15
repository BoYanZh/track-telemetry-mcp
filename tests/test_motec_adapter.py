"""Regression tests for RCZ adapter normalization (synthetic only, no binary fixtures)."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from track_telemetry import motec_adapter


class _FakeChannel:
    def __init__(self, units: str, timestamps, values) -> None:
        self.units = units
        self.timestamps = np.asarray(timestamps, dtype=np.float64)
        self.values = np.asarray(values, dtype=np.float64)


def _install_fake(monkeypatch: pytest.MonkeyPatch, *, capture: dict, channels: dict,
                  laps: list, metadata: dict, rcz_metadata: dict):
    mc = SimpleNamespace(
        CH_GROUND_SPEED="MC_GROUND_SPEED",
        CH_CG_ACCEL_LAT="MC_CG_ACCEL_LAT",
        CH_CG_ACCEL_LON="MC_CG_ACCEL_LON",
        CH_CG_ACCEL_VERT="MC_CG_ACCEL_VERT",
        CH_GPS_LATITUDE="MC_GPS_LATITUDE",
        CH_GPS_LONGITUDE="MC_GPS_LONGITUDE",
        CH_GPS_HEADING="MC_GPS_HEADING",
        CH_YAW_RATE="MC_YAW_RATE",
        CH_STEERING_ANGLE="MC_STEERING_ANGLE",
        CH_THROTTLE_POS="MC_THROTTLE_POS",
        CH_ACCELERATOR_POS="MC_ACCELERATOR_POS",
        CH_BRAKE_PRESS="MC_BRAKE_PRESS",
        CH_BRAKE_POS="MC_BRAKE_POS",
        CH_ENGINE_RPM="MC_ENGINE_RPM",
        CH_GEAR="MC_GEAR",
        CH_LAP_NUMBER="MC_LAP_NUMBER",
        CH_ENGINE_OIL_PRESS="MC_ENGINE_OIL_PRESS",
        CH_ENGINE_OIL_TEMP="MC_ENGINE_OIL_TEMP",
        CH_COOLANT_TEMP="MC_COOLANT_TEMP",
        CH_GEARBOX_TEMP="MC_GEARBOX_TEMP",
        CH_WHEEL_SPEED_FL="MC_WHEEL_SPEED_FL",
        CH_WHEEL_SPEED_FR="MC_WHEEL_SPEED_FR",
        CH_WHEEL_SPEED_RL="MC_WHEEL_SPEED_RL",
        CH_WHEEL_SPEED_RR="MC_WHEEL_SPEED_RR",
    )

    class _FakeDataLog:
        def __init__(self) -> None:
            self.channels = dict(channels)
            self.laps_info = {"laps": list(laps)}
            self.metadata = dict(metadata)
            self.rcz_metadata = dict(rcz_metadata)

        def from_rcz_log(self, path, *, target_stint=None,
                         target_session=None, mask_interp_gaps=True) -> None:
            capture["path"] = path
            capture["target_stint"] = target_stint
            capture["target_session"] = target_session
            capture["mask_interp_gaps"] = mask_interp_gaps

    monkeypatch.setattr(motec_adapter, "_motec_dependencies", lambda: (mc, _FakeDataLog))
    return mc


def _rcz_file(tmp_path: Path, name: str = "session.rcz") -> Path:
    path = tmp_path / name
    path.write_bytes(b"")
    return path


def test_preserves_timestamps_values_units_and_rates(tmp_path, monkeypatch) -> None:
    capture: dict = {}
    t_gps = np.arange(0.0, 4.0, 0.04)  # 25 Hz GPS
    t_rpm = np.arange(0.0, 4.0, 0.10)  # 10 Hz ECU
    gps_values = np.full_like(t_gps, 100.0)
    rpm_values = np.full_like(t_rpm, 5000.0)
    channels = {
        "MC_GROUND_SPEED": _FakeChannel("km/h", t_gps, gps_values),
        "MC_ENGINE_RPM": _FakeChannel("rpm", t_rpm, rpm_values),
    }
    _install_fake(monkeypatch, capture=capture, channels=channels,
                  laps=[], metadata={}, rcz_metadata={})

    session = motec_adapter.load_rcz(_rcz_file(tmp_path))

    speed = session.channel("speed_kmh")
    rpm = session.channel("engine_rpm")
    np.testing.assert_array_equal(speed.timestamps, t_gps)
    np.testing.assert_array_equal(speed.values, gps_values)
    np.testing.assert_array_equal(rpm.timestamps, t_rpm)
    np.testing.assert_array_equal(rpm.values, rpm_values)
    assert speed.units == "km/h"
    assert rpm.units == "rpm"
    # Distinct native rates must survive without silent resampling.
    assert speed.sample_rate_hz == pytest.approx(25.0, rel=0.02)
    assert rpm.sample_rate_hz == pytest.approx(10.0, rel=0.02)
    # Normalized arrays must be copies, not aliases of converter buffers.
    channels["MC_GROUND_SPEED"].timestamps[0] = -999.0
    channels["MC_GROUND_SPEED"].values[0] = -999.0
    assert session.channel("speed_kmh").timestamps[0] != -999.0
    assert session.channel("speed_kmh").values[0] != -999.0


def test_skips_empty_channels_without_inventing_data(tmp_path, monkeypatch) -> None:
    capture: dict = {}
    channels = {
        "MC_GROUND_SPEED": _FakeChannel("km/h", [], []),
        "MC_THROTTLE_POS": _FakeChannel("%", [0.0, 1.0], [10.0, 90.0]),
    }
    _install_fake(monkeypatch, capture=capture, channels=channels,
                  laps=[], metadata={}, rcz_metadata={})

    session = motec_adapter.load_rcz(_rcz_file(tmp_path))

    assert "speed_kmh" not in session.channels
    assert session.channel("throttle_pct").units == "%"
    # Unmapped converter output must not appear under a normalized name.
    assert "brake_pos_pct" not in session.channels


def test_maps_laps_with_original_numbers(tmp_path, monkeypatch) -> None:
    capture: dict = {}
    _install_fake(
        monkeypatch, capture=capture, channels={}, metadata={}, rcz_metadata={},
        laps=[
            {"lap_num": 1, "lap_label": "1", "type": "Timed",
             "start_time": 0.0, "end_time": 90.0, "duration": 90.0, "orig_num": 3},
            {"lap_num": 2, "lap_label": "In Lap", "type": "In Lap",
             "start_time": 90.0, "end_time": 120.0, "duration": 30.0},
        ],
    )

    session = motec_adapter.load_rcz(_rcz_file(tmp_path))

    assert [lap.number for lap in session.laps] == [1, 2]
    assert session.laps[0].original_number == 3
    assert session.laps[1].original_number is None
    assert session.laps[0].is_timed is True
    assert session.laps[1].is_timed is False


def test_merges_metadata_and_records_source_format(tmp_path, monkeypatch) -> None:
    capture: dict = {}
    _install_fake(
        monkeypatch, capture=capture, channels={}, laps=[],
        metadata={"venue_name": "Thunderhill", "gps_source": "rcz_gps_1_200",
                  "yaw_rate_source": "rcz_can_12_100_pid_51"},
        rcz_metadata={"title": "Evening", "trackName": "Thunderhill",
                      "empty": "", "missing": None, "timeCreated": 123},
    )

    session = motec_adapter.load_rcz(
        _rcz_file(tmp_path), target_stint=2, target_session="abc123")

    assert session.metadata["source_format"] == "RaceChrono RCZ"
    assert session.metadata["target_stint"] == 2
    assert session.metadata["target_session"] == "abc123"
    assert session.metadata["venue_name"] == "Thunderhill"
    # GPS/yaw provenance from the converter must survive normalization.
    assert session.metadata["gps_source"] == "rcz_gps_1_200"
    assert session.metadata["yaw_rate_source"] == "rcz_can_12_100_pid_51"
    assert session.metadata["title"] == "Evening"
    assert "empty" not in session.metadata
    assert "missing" not in session.metadata
    assert session.session_id == "session"


def test_forwards_stint_session_and_gap_masking(tmp_path, monkeypatch) -> None:
    capture: dict = {}
    _install_fake(monkeypatch, capture=capture, channels={},
                  laps=[], metadata={}, rcz_metadata={})

    motec_adapter.load_rcz(_rcz_file(tmp_path))
    assert capture["target_stint"] is None
    assert capture["target_session"] is None
    assert capture["mask_interp_gaps"] is True

    motec_adapter.load_rcz(
        _rcz_file(tmp_path, "other.rcz"),
        target_stint=1, target_session="sess-9", mask_interp_gaps=False,
    )
    assert capture["target_stint"] == 1
    assert capture["target_session"] == "sess-9"
    assert capture["mask_interp_gaps"] is False


def test_rejects_non_rcz_suffix(tmp_path, monkeypatch) -> None:
    capture: dict = {}
    _install_fake(monkeypatch, capture=capture, channels={},
                  laps=[], metadata={}, rcz_metadata={})
    other = tmp_path / "session.csv"
    other.write_bytes(b"")

    with pytest.raises(ValueError, match=r"Expected \.rcz input"):
        motec_adapter.load_rcz(other)


def test_missing_file_raises(tmp_path, monkeypatch) -> None:
    capture: dict = {}
    _install_fake(monkeypatch, capture=capture, channels={},
                  laps=[], metadata={}, rcz_metadata={})

    with pytest.raises(FileNotFoundError):
        motec_adapter.load_rcz(tmp_path / "absent.rcz")


def test_distinct_stints_yield_distinct_lap_structures(tmp_path, monkeypatch) -> None:
    """Each requested stint must surface its own lap list, not a cached blend."""
    mc = SimpleNamespace(
        CH_GROUND_SPEED="MC_GROUND_SPEED",
        CH_CG_ACCEL_LAT="MC_CG_ACCEL_LAT",
        CH_CG_ACCEL_LON="MC_CG_ACCEL_LON",
        CH_CG_ACCEL_VERT="MC_CG_ACCEL_VERT",
        CH_GPS_LATITUDE="MC_GPS_LATITUDE",
        CH_GPS_LONGITUDE="MC_GPS_LONGITUDE",
        CH_GPS_HEADING="MC_GPS_HEADING",
        CH_YAW_RATE="MC_YAW_RATE",
        CH_STEERING_ANGLE="MC_STEERING_ANGLE",
        CH_THROTTLE_POS="MC_THROTTLE_POS",
        CH_ACCELERATOR_POS="MC_ACCELERATOR_POS",
        CH_BRAKE_PRESS="MC_BRAKE_PRESS",
        CH_BRAKE_POS="MC_BRAKE_POS",
        CH_ENGINE_RPM="MC_ENGINE_RPM",
        CH_GEAR="MC_GEAR",
        CH_LAP_NUMBER="MC_LAP_NUMBER",
        CH_ENGINE_OIL_PRESS="MC_ENGINE_OIL_PRESS",
        CH_ENGINE_OIL_TEMP="MC_ENGINE_OIL_TEMP",
        CH_COOLANT_TEMP="MC_COOLANT_TEMP",
        CH_GEARBOX_TEMP="MC_GEARBOX_TEMP",
        CH_WHEEL_SPEED_FL="MC_WHEEL_SPEED_FL",
        CH_WHEEL_SPEED_FR="MC_WHEEL_SPEED_FR",
        CH_WHEEL_SPEED_RL="MC_WHEEL_SPEED_RL",
        CH_WHEEL_SPEED_RR="MC_WHEEL_SPEED_RR",
    )
    stint_laps = {
        None: [{"lap_num": 1, "lap_label": "1", "type": "Timed",
                "start_time": 0.0, "end_time": 95.0, "duration": 95.0,
                "orig_num": 1}],
        1: [{"lap_num": 1, "lap_label": "1", "type": "Timed",
             "start_time": 0.0, "end_time": 95.0, "duration": 95.0,
             "orig_num": 1}],
        2: [{"lap_num": 1, "lap_label": "1", "type": "Timed",
             "start_time": 0.0, "end_time": 88.5, "duration": 88.5,
             "orig_num": 7},
            {"lap_num": 2, "lap_label": "In Lap", "type": "In Lap",
             "start_time": 88.5, "end_time": 110.0, "duration": 21.5}],
    }

    class _StintDataLog:
        def __init__(self) -> None:
            self.channels = {}
            self.laps_info = {"laps": []}
            self.metadata = {}
            self.rcz_metadata = {}

        def from_rcz_log(self, path, *, target_stint=None,
                         target_session=None, mask_interp_gaps=True) -> None:
            self.laps_info = {"laps": list(stint_laps[target_stint])}

    monkeypatch.setattr(motec_adapter, "_motec_dependencies", lambda: (mc, _StintDataLog))
    path = _rcz_file(tmp_path)

    default = motec_adapter.load_rcz(path)
    first = motec_adapter.load_rcz(path, target_stint=1)
    second = motec_adapter.load_rcz(path, target_stint=2)

    assert [(lap.number, lap.duration_s) for lap in default.laps] == [(1, 95.0)]
    assert [(lap.number, lap.duration_s) for lap in first.laps] == [(1, 95.0)]
    assert [(lap.number, lap.duration_s) for lap in second.laps] == [(1, 88.5), (2, 21.5)]
    assert second.laps[0].original_number == 7
    assert "target_stint" not in default.metadata
    assert first.metadata["target_stint"] == 1
    assert second.metadata["target_stint"] == 2
