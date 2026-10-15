"""End-to-end test of the pinned converter using a miniature RCZ archive."""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

import numpy as np

from track_telemetry.channels import GPS_LATITUDE_DEG, SPEED_KMH
from track_telemetry.laps import fastest_timed_lap
from track_telemetry.motec_adapter import load_rcz


def test_rcz_archive_parses_into_normalized_timed_laps(tmp_path: Path) -> None:
    origin = 1_700_000_000_000
    timestamps = np.arange(origin, origin + 101_000, 1_000, dtype="<i8")
    speed_millimeters_per_second = np.full(len(timestamps), 20_000, dtype="<i4")
    latlon = np.column_stack(
        (
            222_000_000 + np.arange(len(timestamps), dtype="<i4"),
            -732_000_000 + np.arange(len(timestamps), dtype="<i4"),
        )
    )
    session = {
        "firstTimestamp": origin,
        "timeCreated": origin,
        "trackName": "Synthetic Integration Circuit",
        "laps": [
            {
                "number": 10,
                "sessionResume": 0,
                "startTimestamp": origin + 20_000,
                "finishTimestamp": origin + 50_000,
            },
            {
                "number": 11,
                "sessionResume": 0,
                "startTimestamp": origin + 50_000,
                "finishTimestamp": origin + 80_000,
            },
        ],
    }
    path = tmp_path / "integration.rcz"
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("session.json", json.dumps(session))
        archive.writestr("channel_1_300_0_1_1", timestamps.tobytes())
        archive.writestr("channel_1_300_0_4_0", speed_millimeters_per_second.tobytes())
        archive.writestr("channel_1_300_0_3_1", latlon.astype("<i4").tobytes())

    parsed = load_rcz(path)
    assert parsed.metadata["trackName"] == "Synthetic Integration Circuit"
    assert len(parsed.channel(SPEED_KMH).values) > 0
    assert len(parsed.channel(GPS_LATITUDE_DEG).values) > 0
    fastest = fastest_timed_lap(parsed)
    assert fastest is not None
    assert fastest.duration_s == 30.0
