"""Known synthetic dynamics and adversarial source/quality boundaries."""

import asyncio
import json

import numpy as np
import pytest
from mcp import Client

from track_telemetry import mcp_server
from track_telemetry.gg import analyze_gg_usage
from track_telemetry.models import ChannelSeries, Lap, TelemetrySession
from track_telemetry.quality import native_rate
from track_telemetry.vehicle_response import (
    WHEELS,
    analyze_braking_efficiency,
    analyze_steering_response,
    analyze_wheel_speeds,
)


def vehicle_session():
    t = np.arange(0, 10.001, 0.02)
    speed = 100 - t * 3.6  # exactly 1 m/s2 deceleration
    values = {"speed_kmh": speed, "long_g": np.full_like(t, -1 / 9.80665),
              "lat_g": np.zeros_like(t), "brake_pressure_kpa": np.full_like(t, 500),
              "steering_deg": 10 * (np.sin(t * 1.3) + 0.4 * np.sin(t * 4.7)),
              "yaw_rate_dps": np.zeros_like(t)}
    values.update({name: speed.copy() for name in WHEELS})
    units = {"speed_kmh": "km/h", "long_g": "G", "lat_g": "G", "brake_pressure_kpa": "kPa",
             "steering_deg": "deg", "yaw_rate_dps": "deg/s", **dict.fromkeys(WHEELS, "km/h")}
    return TelemetrySession("synthetic", "synthetic", metadata={
        "channel_sources": dict.fromkeys(values, "can"),
        "yaw_rate_source": "can", "native_sample_rate_hz": dict.fromkeys(values, 50)},
        laps=[Lap(1, "1", "Timed", 0, 10, 10)],
        channels={name: ChannelSeries(name, units[name], t.copy(), v) for name, v in values.items()})


def test_constant_deceleration_energy_distance_and_control_integral():
    result = analyze_braking_efficiency(vehicle_session(), 1)
    assert result["event_count"] == 1
    event = result["events"][0]
    assert event["speed_loss_kmh"] == pytest.approx(36)
    assert event["distance_m"] == pytest.approx((100 / 3.6 + 64 / 3.6) / 2 * 10)
    assert event["speed_energy_deceleration_g"] == pytest.approx(1 / 9.80665)
    assert event["mean_measured_deceleration_g"] == pytest.approx(1 / 9.80665)
    assert event["control_integral_unit_s"] == pytest.approx(5000)
    json.dumps(result, allow_nan=False)


def test_missing_brake_samples_split_events_without_filling():
    s = vehicle_session()
    s.channel("brake_pressure_kpa").values[200:210] = np.nan
    result = analyze_braking_efficiency(s, 1)
    assert result["event_count"] == 2
    assert sum(e["duration_s"] for e in result["events"]) < 10


@pytest.mark.parametrize("case", ["source", "native", "units", "coverage"])
def test_braking_rejects_unreliable_evidence(case):
    s = vehicle_session()
    if case == "source":
        s.metadata["channel_sources"]["long_g"] = "unknown"
    elif case == "native":
        s.metadata["native_sample_rate_hz"]["brake_pressure_kpa"] = 1
    elif case == "units":
        s.channel("speed_kmh").units = "mph"
    else:
        s.channel("brake_pressure_kpa").values[100:400] = np.nan
    with pytest.raises(ValueError):
        analyze_braking_efficiency(s, 1)


def test_wheel_deficit_is_indication_not_abs_confirmation():
    s = vehicle_session()
    s.channel(WHEELS[0]).values[100:151] *= 0.8
    result = analyze_wheel_speeds(s, 1)
    assert result["wheel_deficit_indications"][WHEELS[0]]["sustained_deficit_event_count"] == 1
    assert result["wheel_deficit_indications"][WHEELS[0]]["sustained_deficit_duration_s"] == pytest.approx(1)
    assert result["wheel_deficit_indications"][WHEELS[1]]["sustained_deficit_event_count"] == 0
    assert result["abs_activation"] == "not_confirmed"
    json.dumps(result, allow_nan=False)


def test_wheel_turning_or_no_braking_is_not_an_abs_opportunity():
    s = vehicle_session()
    s.channel("lat_g").values[:] = 0.5
    result = analyze_wheel_speeds(s, 1)
    assert result["eligible_straight_braking_s"] == 0
    assert result["abs_activation"] == "not_confirmed"


@pytest.mark.parametrize("case", ["unknown_native", "slow_native", "unknown_source", "missing_wheel", "units"])
def test_wheel_gates(case):
    s = vehicle_session()
    if case == "unknown_native":
        s.metadata["native_sample_rate_hz"] = {}
    elif case == "slow_native":
        s.metadata["native_sample_rate_hz"][WHEELS[0]] = 2
    elif case == "unknown_source":
        s.metadata["channel_sources"][WHEELS[0]] = "unknown"
    elif case == "missing_wheel":
        del s.channels[WHEELS[0]]
    else:
        s.channel(WHEELS[0]).units = "m/s"
    with pytest.raises((ValueError, KeyError)):
        analyze_wheel_speeds(s, 1)


def response_session():
    s = vehicle_session()
    s.channel("speed_kmh").values[:] = 80
    t = s.channel("steering_deg").timestamps
    delayed = 10 * (np.sin((t - 0.2) * 1.3) + 0.4 * np.sin((t - 0.2) * 4.7))
    s.channel("yaw_rate_dps").values[:] = delayed * 0.4
    return s


def test_known_response_delay_and_signed_gain():
    result = analyze_steering_response(response_session(), 1)
    assert result["observed_delay_s"] == pytest.approx(0.2)
    assert result["yaw_gain_dps_per_steering_deg"] == pytest.approx(0.4)
    assert result["change_correlation"] == pytest.approx(1)
    json.dumps(result, allow_nan=False)


def test_reversed_yaw_sign_is_reported_without_inventing_understeer():
    s = response_session()
    s.channel("yaw_rate_dps").values *= -1
    result = analyze_steering_response(s, 1)
    assert result["observed_delay_s"] == pytest.approx(0.2)
    assert result["change_correlation"] == pytest.approx(-1)
    assert result["yaw_gain_dps_per_steering_deg"] == pytest.approx(-0.4)


@pytest.mark.parametrize("case", ["gps_yaw", "slow_native", "nan", "frozen", "speed"])
def test_response_rejects_unreliable_evidence(case):
    s = response_session()
    if case == "gps_yaw":
        s.metadata["channel_sources"]["yaw_rate_dps"] = "gps_heading_derivative"
    elif case == "slow_native":
        s.metadata["native_sample_rate_hz"]["yaw_rate_dps"] = 1
    elif case == "nan":
        s.channel("yaw_rate_dps").values[100] = np.nan
    elif case == "frozen":
        s.channel("steering_deg").values[:] = 0
    else:
        s.channel("speed_kmh").values[:] = 10
    with pytest.raises(ValueError):
        analyze_steering_response(s, 1)


def test_native_rcz_inventory_resolves_selected_stint_and_device_role():
    s = vehicle_session()
    s.metadata["native_sample_rate_hz"] = {}
    s.laps = [Lap(1, "1", "Timed", 0, 10, 10, stint=1)]
    s.metadata["channel_provenance_by_stint"] = {1: {WHEELS[0]: "rcz_can_12_200_pid_197623"}}
    s.metadata["device_summary_by_stint"] = [
        {"stint": 0, "devices": [{"device_id": 200, "role": "can_obd",
            "native_can_pid_rates": {"pid_197623": {"rate_hz": 2}}}]},
        {"stint": 1, "devices": [{"device_id": 200, "role": "can_obd",
            "native_can_pid_rates": {"pid_197623": {"rate_hz": 50}}}]},
    ]
    assert native_rate(s, WHEELS[0], 1) == 50


def test_gg_rejects_known_slow_native_despite_fast_output():
    s = vehicle_session()
    s.metadata["native_sample_rate_hz"]["lat_g"] = 1
    with pytest.raises(ValueError, match="Native G"):
        analyze_gg_usage(s, 1)


def test_new_mcp_tools_roundtrip_and_capability_gates(monkeypatch):
    s = vehicle_session()
    monkeypatch.setattr(mcp_server, "_load", lambda path: s)

    async def run():
        async with Client(mcp_server.mcp, raise_exceptions=True) as client:
            names = {t.name for t in (await client.list_tools()).tools}
            assert {"compare_reference_laps", "analyze_gg_usage", "analyze_braking_efficiency",
                    "analyze_wheel_speeds", "analyze_steering_response"} <= names
            result = await client.call_tool("analyze_braking_efficiency", {"path": "synthetic", "lap_number": 1})
            assert result.structured_content["event_count"] == 1
            gg = await client.call_tool("analyze_gg_usage", {"path": "synthetic", "lap_number": 1})
            assert gg.structured_content["quality"]["coverage_fraction"] == pytest.approx(1)
            wheels = await client.call_tool("analyze_wheel_speeds", {"path": "synthetic", "lap_number": 1})
            assert wheels.structured_content["abs_activation"] == "not_confirmed"
            response = response_session()
            s.channels.update(response.channels)
            result = await client.call_tool("analyze_steering_response", {"path": "synthetic", "lap_number": 1})
            assert result.structured_content["observed_delay_s"] == pytest.approx(0.2)
    asyncio.run(run())
    assert mcp_server._session_capabilities(s)["tool_support"]["analyze_wheel_speeds"]
    s.metadata["native_sample_rate_hz"][WHEELS[0]] = 1
    assert not mcp_server._session_capabilities(s)["tool_support"]["analyze_wheel_speeds"]
