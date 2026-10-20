from __future__ import annotations

import copy
import math

import numpy as np

from track_telemetry.channels import GPS_LATITUDE_DEG, GPS_LONGITUDE_DEG
from track_telemetry.corner_catalog import (
    _load_catalog,
    list_track_layouts,
    locate_section,
    match_lap,
)
from track_telemetry.models import ChannelSeries, Lap, TelemetrySession

_EARTH_RADIUS_M = 6_371_000.0


def _xy_to_latlon(
    points: np.ndarray, origin_lat: float, origin_lon: float
) -> tuple[np.ndarray, np.ndarray]:
    lat = origin_lat + np.rad2deg(points[:, 1] / _EARTH_RADIUS_M)
    lon = origin_lon + np.rad2deg(
        points[:, 0] / (_EARTH_RADIUS_M * math.cos(math.radians(origin_lat)))
    )
    return lat, lon


def _layout(layout_id: str = "test-ccw", *, duplicate: bool = False) -> dict:
    origin_lat, origin_lon = 37.0, -122.0
    radius = 100.0
    angles = np.linspace(0.0, 2.0 * math.pi, 241, endpoint=False)
    points = np.column_stack((radius * np.cos(angles), radius * np.sin(angles)))
    segment_lengths = np.linalg.norm(np.roll(points, -1, axis=0) - points, axis=1)
    length = float(np.sum(segment_lengths))
    corners = []
    for index in range(8):
        s = index * length / 8.0
        corners.append(
            {
                "id": f"{layout_id}:C{index + 1}",
                "official": f"C{index + 1}",
                "direction": "L" if index % 2 else "R",
                "reference_s_m": s,
                "identity_status": "owner_confirmed",
                "feature_type": "corner",
            }
        )
    return {
        "id": layout_id,
        "name": "Synthetic CCW Course" if not duplicate else "Duplicate Course",
        "direction": "CCW",
        "origin_latitude_deg": origin_lat,
        "origin_longitude_deg": origin_lon,
        "length_m": length,
        "reference_trace": points.tolist(),
        "corners": corners,
        "source": {"recording": "synthetic"},
    }


def _catalog(layouts: list[dict]) -> dict:
    return {
        "schema_version": 1,
        "approval": {"status": "owner_confirmed", "scope": "synthetic tests"},
        "identity_contract": "ordered GPS route identifies reviewed physical anchors",
        "layouts": layouts,
        "unobserved_features": [{"official": "not matched"}],
        "sources": [{"file": "synthetic"}],
    }


def _session(points: np.ndarray, *, offset=(0.0, 0.0), lap_number: int = 1) -> TelemetrySession:
    shifted = np.asarray(points, dtype=np.float64) + np.asarray(offset, dtype=np.float64)
    lat, lon = _xy_to_latlon(shifted, 37.0, -122.0)
    timestamps = np.linspace(0.0, 120.0, len(points))
    lap = Lap(lap_number, f"Lap {lap_number}", "timed", 0.0, 120.0, 120.0)
    channels = {
        GPS_LATITUDE_DEG: ChannelSeries(GPS_LATITUDE_DEG, "deg", timestamps, lat),
        GPS_LONGITUDE_DEG: ChannelSeries(GPS_LONGITUDE_DEG, "deg", timestamps, lon),
    }
    return TelemetrySession("synthetic", "synthetic.rcz", laps=[lap], channels=channels)


def _install_catalog(monkeypatch, catalog: dict) -> None:
    from track_telemetry import corner_catalog

    monkeypatch.setattr(corner_catalog, "_load_catalog", lambda: catalog)


def test_list_track_layouts_returns_only_gps_observed_physical_layouts() -> None:
    listed = list_track_layouts()

    assert listed["status"] == "available"
    assert len(listed["layouts"]) == 9
    assert {layout["id"] for layout in listed["layouts"]} == {
        "thill-east-bypass",
        "thill-east-cyclone",
        "thill-west",
        "sonoma",
        "laguna",
        "bw-13cw",
        "bw-1a-ccw",
        "bw-25ccw",
        "bw-circuit",
    }
    assert all("Drag Strip" not in layout["name"] for layout in listed["layouts"])
    assert listed["approval"]["status"] == "owner_confirmed"


def test_match_handles_cyclic_start_and_small_gps_translation(monkeypatch) -> None:
    layout = _layout()
    _install_catalog(monkeypatch, _catalog([layout]))
    points = np.asarray(layout["reference_trace"])
    start = 73
    lap_points = np.vstack((points[start:], points[:start], points[start]))

    result = match_lap(_session(lap_points, offset=(13.0, -7.0)), 1)

    assert result["status"] == "matched"
    assert result["layout_id"] == "test-ccw"
    assert result["name"] == "Synthetic CCW Course"
    assert len(result["corners"]) == 8
    assert np.linalg.norm(result["quality"]["registration_offset_m"]) <= 25.0
    assert result["quality"]["residual_p99_5_m"] < 2.0
    assert all(0.0 <= corner["lap_progress"] <= 1.0 for corner in result["corners"])


def test_opposite_direction_lap_is_refused(monkeypatch) -> None:
    layout = _layout()
    _install_catalog(monkeypatch, _catalog([layout]))
    points = np.asarray(layout["reference_trace"])
    lap_points = np.vstack((points[::-1], points[-1]))

    result = match_lap(_session(lap_points), 1)

    assert result["status"] == "unmatched"
    assert result["reason"] == "wrong_direction"
    assert result["corners"] == []


def test_repeated_local_backtracking_cannot_inflate_corner_progress(monkeypatch) -> None:
    layout = _layout()
    _install_catalog(monkeypatch, _catalog([layout]))
    points = np.asarray(layout["reference_trace"])
    lap_points = []
    for index in range(len(points) - 1):
        lap_points.append(points[index])
        if 20 <= index <= 180 and index % 20 == 0:
            lap_points.extend(points[index - 1 : index - 5 : -1])
            lap_points.extend(points[index - 3 : index])
    lap_points.append(points[0])

    result = match_lap(_session(np.asarray(lap_points)), 1)

    assert result["status"] == "unmatched"
    assert all(candidate["status"] == "unmatched" for candidate in result["candidates"])
    assert any(
        candidate["reason"] == "route_order_mismatch" for candidate in result["candidates"]
    ), result["candidates"]


def test_geographically_unrelated_lap_does_not_rotate_into_match(monkeypatch) -> None:
    layout = _layout()
    _install_catalog(monkeypatch, _catalog([layout]))
    points = np.asarray(layout["reference_trace"])
    session = _session(np.vstack((points, points[0])))
    session.channels[GPS_LATITUDE_DEG].values += 0.1

    result = match_lap(session, 1)

    assert result["status"] == "unmatched"
    assert result["reason"] == "geographic_mismatch"


def test_short_alternative_branch_is_rejected_by_top_and_symmetric_residual(monkeypatch) -> None:
    base = _layout("route-base")
    branch = copy.deepcopy(base)
    branch["id"] = "route-branch"
    branch["name"] = "Nearby Alternative Branch"
    branch_points = np.asarray(branch["reference_trace"], dtype=np.float64)
    # One short but distinct route branch; most of the lap remains identical.
    branch_points[72:98] *= 1.8
    branch["reference_trace"] = branch_points.tolist()
    lengths = np.linalg.norm(np.roll(branch_points, -1, axis=0) - branch_points, axis=1)
    branch["length_m"] = float(lengths.sum())
    for corner in branch["corners"]:
        corner["id"] = corner["id"].replace("route-base", "route-branch")
    _install_catalog(monkeypatch, _catalog([base, branch]))
    points = np.asarray(base["reference_trace"])

    result = match_lap(_session(np.vstack((points, points[0]))), 1)

    assert result["status"] == "matched"
    assert result["layout_id"] == "route-base"
    branch_candidate = next(c for c in result["candidates"] if c["layout_id"] == "route-branch")
    assert branch_candidate["reason"] == "route_residual_or_branch_mismatch"
    assert branch_candidate["quality"]["symmetric_reference_coverage_fraction_within_30m"] < 0.9


def test_close_duplicate_layouts_remain_ambiguous_even_with_hint(monkeypatch) -> None:
    first = _layout("layout-a")
    second = copy.deepcopy(first)
    second["id"] = "layout-b"
    second["name"] = "Duplicate Course"
    for corner in second["corners"]:
        corner["id"] = corner["id"].replace("layout-a", "layout-b")
    _install_catalog(monkeypatch, _catalog([first, second]))
    points = np.asarray(first["reference_trace"])

    result = match_lap(_session(np.vstack((points, points[0]))), 1, layout_id="layout-a")

    assert result["status"] == "ambiguous"
    assert result["layout_id"] is None
    assert {candidate["layout_id"] for candidate in result["candidates"]} == {
        "layout-a",
        "layout-b",
    }


def test_locate_section_handles_wrapped_and_multi_corner_intervals(monkeypatch) -> None:
    layout = _layout()
    _install_catalog(monkeypatch, _catalog([layout]))
    points = np.asarray(layout["reference_trace"])
    match = match_lap(_session(np.vstack((points, points[0]))), 1)

    wrapped = locate_section(match, 0.95, 0.05)
    broad = locate_section(match, 0.10, 0.40)

    assert wrapped["status"] == "matched"
    assert wrapped["wraps_lap"] is True
    assert set(wrapped["official_names"]) == {"C1", "C8"}
    assert wrapped["role"] == "location_only"
    assert broad["status"] == "matched"
    assert broad["official_names"][0] == "C1"
    assert broad["official_names"][-1] == "C4"
    assert len(broad["intervals"]) >= 3


def test_missing_gps_is_unavailable_and_unmatched_location_stays_unresolved(monkeypatch) -> None:
    layout = _layout()
    _install_catalog(monkeypatch, _catalog([layout]))
    points = np.asarray(layout["reference_trace"])
    session = _session(np.vstack((points, points[0])))
    del session.channels[GPS_LONGITUDE_DEG]

    result = match_lap(session, 1)
    section = locate_section(result, 0.95, 0.05)

    assert result["status"] == "unavailable"
    assert section["status"] == "unresolved"
    assert section["corner_ids"] == []


def test_real_catalog_trace_smoke_matches_its_reviewed_layout() -> None:
    catalog = _load_catalog()
    layout = catalog["layouts"][0]
    reference = np.asarray(layout["reference_trace"], dtype=np.float64)
    points = np.vstack((reference, reference[0]))
    lat, lon = _xy_to_latlon(
        points,
        float(layout["origin_latitude_deg"]),
        float(layout["origin_longitude_deg"]),
    )
    timestamps = np.arange(len(points), dtype=np.float64)
    lap = Lap(1, "Lap 1", "timed", 0.0, float(timestamps[-1]), float(timestamps[-1]))
    session = TelemetrySession(
        "catalog-smoke",
        "synthetic-from-catalog.rcz",
        laps=[lap],
        channels={
            GPS_LATITUDE_DEG: ChannelSeries(GPS_LATITUDE_DEG, "deg", timestamps, lat),
            GPS_LONGITUDE_DEG: ChannelSeries(GPS_LONGITUDE_DEG, "deg", timestamps, lon),
        },
    )

    result = match_lap(session, 1)

    assert result["status"] == "matched"
    assert result["layout_id"] == layout["id"]
    assert len(result["corners"]) == len(layout["corners"])
