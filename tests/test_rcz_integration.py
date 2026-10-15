"""End-to-end test of the pinned converter using a miniature RCZ archive."""

from __future__ import annotations

import asyncio
import json
import zipfile
from pathlib import Path

import numpy as np
from mcp import Client

from track_telemetry import mcp_server
from track_telemetry.channels import GPS_LATITUDE_DEG, LAP_NUMBER, SPEED_KMH
from track_telemetry.laps import fastest_timed_lap
from track_telemetry.motec_adapter import discover_rcz_stints, load_all_rcz_stints, load_rcz


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



def _build_multi_stint_archive(path: Path, *, duplicate_lap_number: bool = False) -> None:
    """RaceChrono uses root session.json and resume_N/ for later stints."""
    origin = 1_700_000_000_000
    periods = [
        (0, origin, (7, 8), (20, 60, 100)),
        (1, origin + 3_600_000, (20, 21), (20, 60, 100)),
        (2, origin + 7_200_000, (22 if not duplicate_lap_number else 7, 23), (20, 55, 100)),
    ]
    laps = []
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        for stint, start, numbers, markers in periods:
            for number, begin, end in zip(numbers, markers[:-1], markers[1:]):
                laps.append(
                    {
                        "number": number,
                        "sessionResume": stint,
                        "startTimestamp": start + begin * 1000,
                        "finishTimestamp": start + end * 1000,
                    }
                )
            seconds = np.arange(121, dtype=np.float64)
            timestamps = (start + seconds.astype("<i8") * 1000).astype("<i8")
            angles = np.zeros_like(seconds)
            for begin, end in zip(markers[:-1], markers[1:]):
                mask = (seconds >= begin) & (seconds <= end)
                angles[mask] = 2 * np.pi * (seconds[mask] - begin) / (end - begin)
            lat = 35 + 100 * np.cos(angles) / 111_195
            lon = -119 + 100 * np.sin(angles) / (111_195 * np.cos(np.deg2rad(35)))
            coords = np.column_stack(
                (np.rint(lat * 6_000_000), np.rint(lon * 6_000_000))
            ).astype("<i4")
            speed = np.full(len(seconds), 20_000, dtype="<i4")
            prefix = "" if stint == 0 else f"resume_{stint}/"
            archive.writestr(prefix + "channel_1_300_0_1_1", timestamps.tobytes())
            archive.writestr(prefix + "channel_1_300_0_4_0", speed.tobytes())
            archive.writestr(prefix + "channel_1_300_0_3_1", coords.tobytes())
        archive.writestr(
            "session.json",
            json.dumps(
                {
                    "firstTimestamp": origin,
                    "timeCreated": origin,
                    "trackName": "Synthetic Multi-Stint Circuit",
                    "laps": laps,
                }
            ),
        )


def test_multi_stint_archive_discovers_and_preserves_original_lap_numbers(tmp_path: Path) -> None:
    source = tmp_path / "all-day.rcz"
    _build_multi_stint_archive(source)
    assert [item["stint"] for item in discover_rcz_stints(source)] == [0, 1, 2]

    # Keep the old single-stint adapter for callers that explicitly need it.
    single = load_rcz(source, target_stint=2)
    assert [lap.original_number for lap in single.laps if lap.is_timed] == [22, 23]
    assert [lap.number for lap in single.laps if lap.is_timed] != [22, 23]

    merged = load_all_rcz_stints(source)
    assert merged.metadata["stint_count"] == 3
    assert [lap.number for lap in merged.laps if lap.is_timed] == [7, 8, 20, 21, 22, 23]
    assert [lap.stint for lap in merged.laps if lap.is_timed] == [0, 0, 1, 1, 2, 2]
    assert merged.lap(22).original_number == 22
    assert merged.lap(22).duration_s == 35.0
    assert merged.lap(22).start_s == 7220.0
    number_channel = merged.channel(LAP_NUMBER)
    at_l22 = np.argmin(np.abs(number_channel.timestamps - 7230.0))
    assert number_channel.values[at_l22] == 22
    assert merged.channel(SPEED_KMH).sample_rate_hz == 1.0
    assert fastest_timed_lap(merged).number == 22
    assert len({lap.number for lap in merged.laps}) == len(merged.laps)


def test_multi_stint_duplicate_original_numbers_do_not_collide(tmp_path: Path) -> None:
    source = tmp_path / "restarted-numbering.rcz"
    _build_multi_stint_archive(source, duplicate_lap_number=True)
    merged = load_all_rcz_stints(source)
    repeated = [lap for lap in merged.laps if lap.original_number == 7]
    assert len(repeated) == 2
    assert len({lap.number for lap in repeated}) == 2
    assert {lap.stint for lap in repeated} == {0, 2}


def test_mcp_exposes_all_stints_and_can_compare_laps_across_stints(
    tmp_path: Path, monkeypatch
) -> None:
    root = tmp_path / "telemetry"
    root.mkdir()
    _build_multi_stint_archive(root / "all-day.rcz")
    monkeypatch.setenv("TRACK_TELEMETRY_ROOT", str(root))
    monkeypatch.delenv("TRACK_TELEMETRY_UNSAFE_ALLOW_ANY_PATH", raising=False)
    mcp_server._load_cached.cache_clear()

    async def run() -> None:
        async with Client(mcp_server.mcp, raise_exceptions=True) as client:
            listing = (await client.call_tool("list_sessions", {})).structured_content
            assert listing is not None
            assert [item["stint"] for item in listing["sessions"][0]["stints"]] == [0, 1, 2]
            source_id = listing["sessions"][0]["session_id"]

            prepared = (await client.call_tool("prepare_session", {"path": source_id})).structured_content
            assert prepared is not None
            assert prepared["fastest_timed_lap_number"] == 22
            assert prepared["fastest_timed_lap_stint"] == 2
            assert prepared["timed_lap_numbers"] == [7, 8, 20, 21, 22, 23]

            all_laps = (await client.call_tool("list_laps", {"path": source_id})).structured_content
            assert all_laps is not None
            assert len([lap for lap in all_laps["laps"] if lap["kind"] == "Timed"]) == 6
            assert next(lap for lap in all_laps["laps"] if lap["number"] == 22)["stint"] == 2

            lap = (await client.call_tool(
                "analyze_lap", {"path": source_id, "lap_number": 22}
            )).structured_content
            assert lap is not None
            assert lap["lap"]["original_number"] == 22

            comparison = (await client.call_tool(
                "compare_laps",
                {
                    "path_a": source_id,
                    "lap_a": 7,
                    "path_b": source_id,
                    "lap_b": 22,
                    "same_layout_confirmed": True,
                    "mini_sectors": 5,
                },
            )).structured_content
            assert comparison is not None
            assert comparison["lap_a_minus_b_total_s"] == 5.0
            assert comparison["lap_b"]["stint"] == 2

    asyncio.run(run())
