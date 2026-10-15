"""Synthetic multi-device RaceChrono fixtures: no private logger data committed."""

from __future__ import annotations

import asyncio
import json
import zipfile
from pathlib import Path

import numpy as np
import pytest
from mcp import Client

from track_telemetry import mcp_server
from track_telemetry.channels import LAT_G, LONG_G, VERT_G, YAW_RATE_DPS
from track_telemetry.motec_adapter import inspect_rcz_devices, load_all_rcz_stints


def _fixture(path: Path) -> None:
    start = 1_700_000_000_000
    laps = []
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        for stint in (0, 1):
            prefix = "" if stint == 0 else f"resume_{stint}/"
            base = start + stint * 120_000
            gps = (base + np.arange(501, dtype="<i8") * 40).astype("<i8")
            can = (base + np.arange(201, dtype="<i8") * 100).astype("<i8")
            laps.append({
                "number": stint + 1,
                "sessionResume": stint,
                "startTimestamp": int(base + 2000),
                "finishTimestamp": int(base + 18000),
            })
            z.writestr(
                prefix + "sessionfragment.json",
                json.dumps({
                    "primaryGpsDeviceIndex": 100,
                    "imuAccDevice": 101,
                    "imuGyroDevice": 102,
                    "devices2": [
                        {"selector": {"type": 1, "id": 100, "model": 121}},
                        {"selector": {"type": 2, "id": 101, "model": 121}},
                        {"selector": {"type": 3, "id": 102, "model": 121}},
                        {"selector": {"type": 12, "id": 200, "model": 405}},
                    ],
                }),
            )
            z.writestr(prefix + "channel_1_100_0_1_1", gps.tobytes())
            z.writestr(
                prefix + "channel_1_100_0_3_1",
                np.tile(np.array([222_000_000, -730_000_000], dtype="<i4"), (501, 1)).tobytes(),
            )
            z.writestr(
                prefix + "channel_1_100_0_4_0",
                np.full(501, 20_000, dtype="<i4").tobytes(),
            )
            z.writestr(prefix + "channel_2_101_0_1_1", gps.tobytes())
            z.writestr(prefix + "channel_3_102_0_1_1", gps.tobytes())
            for suffix, value in (("9", -2500), ("10", 7000), ("11", 9700)):
                z.writestr(
                    prefix + f"channel_2_101_0_{suffix}_0",
                    np.full(501, value, dtype="<i4").tobytes(),
                )
            z.writestr(
                prefix + "channel_3_102_0_14_0",
                np.full(501, -12000, dtype="<i4").tobytes(),
            )
            # CAN yaw only in stint 1 to exercise mixed-source provenance.
            if stint == 1:
                z.writestr(prefix + "channel_12_200_51_1_1", can.tobytes())
                z.writestr(
                    prefix + "channel2_12_200_51_51_3",
                    np.full(201, 12.0, dtype="<f8").tobytes(),
                )
            z.writestr(prefix + "channel_12_200_10024_1_1", can.tobytes())
            z.writestr(
                prefix + "channel2_12_200_10024_10024_3",
                np.full(201, 4500.0, dtype="<f8").tobytes(),
            )
        z.writestr(
            "session.json",
            json.dumps({"firstTimestamp": start, "timeCreated": start, "laps": laps}),
        )


def test_device_inventory_reports_native_clocks_and_roles(tmp_path: Path) -> None:
    source = tmp_path / "synthetic.rcz"
    _fixture(source)
    inventory = inspect_rcz_devices(source)
    assert [x["stint"] for x in inventory] == [0, 1]
    for stint in inventory:
        devices = {d["role"]: d for d in stint["devices"]}
        assert stint["primary_gps_device_id"] == 100
        assert devices["gps"]["is_primary_gps"]
        assert devices["gps"]["native_sample_rate_hz"] == pytest.approx(25)
        assert devices["accelerometer"]["native_sample_rate_hz"] == pytest.approx(25)
        assert devices["gyroscope"]["native_sample_rate_hz"] == pytest.approx(25)
        assert devices["can_obd"]["native_sample_rate_hz"] is None
        assert devices["can_obd"]["native_can_pid_rates"]["pid_10024"]["rate_hz"] == pytest.approx(10)


def test_multi_stint_provenance_and_imu_channels(tmp_path: Path) -> None:
    source = tmp_path / "synthetic.rcz"
    _fixture(source)
    session = load_all_rcz_stints(source)
    assert session.metadata["stint_count"] == 2
    assert session.metadata["yaw_rate_source"] == "mixed_or_unknown"
    assert session.metadata["yaw_rate_source_by_stint"] == {
        0: "rcz_gyro_3_102", 1: "rcz_can_12_200_pid_51",
    }
    assert session.metadata["longitudinal_accel_source_by_stint"] == {
        0: "rcz_accelerometer_2_101", 1: "rcz_accelerometer_2_101",
    }
    assert session.metadata["channel_provenance_by_stint"][0][VERT_G] == (
        "rcz_accelerometer_2_101"
    )
    for channel, expected in ((LAT_G, 0.7), (LONG_G, -0.25), (VERT_G, 0.97), (YAW_RATE_DPS, 12)):
        assert channel in session.channels
        assert np.nanmedian(session.channel(channel).values) == pytest.approx(expected, abs=1e-3)


def test_mcp_inspection_exposes_devices_and_conservative_yaw_gate(
    tmp_path: Path, monkeypatch
) -> None:
    root = tmp_path / "root"
    root.mkdir()
    source = root / "synthetic.rcz"
    _fixture(source)
    monkeypatch.setenv("TRACK_TELEMETRY_ROOT", str(root))
    monkeypatch.delenv("TRACK_TELEMETRY_UNSAFE_ALLOW_ANY_PATH", raising=False)
    mcp_server._load_cached.cache_clear()

    async def run() -> None:
        async with Client(mcp_server.mcp, raise_exceptions=True) as client:
            response = (await client.call_tool(
                "inspect_session", {"path": "synthetic.rcz"}
            )).structured_content
            assert response is not None
            assert len(response["device_summary_by_stint"]) == 2
            assert response["device_summary_by_stint"][1]["devices"][0]["native_sample_rate_hz"] == pytest.approx(25)
            assert "may be resampled" in response["native_sampling_note"]
            assert response["capabilities"]["channels"]["independent_yaw_rate"] is False

            solo = (await client.call_tool(
                "inspect_session", {"path": "synthetic.rcz", "stint": 0}
            )).structured_content
            assert solo is not None
            assert solo["capabilities"]["channels"]["independent_yaw_rate"] is True

    asyncio.run(run())
