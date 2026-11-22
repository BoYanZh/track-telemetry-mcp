"""Faint OSM basemap stays viz-only and fail-soft in gps_trace."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from track_telemetry.channels import GPS_LATITUDE_DEG, GPS_LONGITUDE_DEG, SPEED_KMH
from track_telemetry.models import ChannelSeries, Lap, TelemetrySession
from track_telemetry.report_plots import render_lap_comparison


def _session() -> TelemetrySession:
    t = np.linspace(0.0, 20.0, 301)
    angle = 2 * np.pi * t / 20.0
    latitude = 35.0 + 100.0 * np.cos(angle) / 111_195.0
    longitude = -119 + 100.0 * np.sin(angle) / (111_195.0 * np.cos(np.deg2rad(35.0)))
    fields = {
        GPS_LATITUDE_DEG: ChannelSeries(GPS_LATITUDE_DEG, "deg", t, latitude),
        GPS_LONGITUDE_DEG: ChannelSeries(GPS_LONGITUDE_DEG, "deg", t, longitude),
        SPEED_KMH: ChannelSeries(SPEED_KMH, "km/h", t, 100 + 8 * np.cos(angle)),
    }
    return TelemetrySession(
        session_id="synthetic",
        source="synthetic.rcz",
        metadata={},
        laps=[Lap(1, "1", "Timed", 0.0, 20.0, 20.0)],
        channels=fields,
    )


def _geojson(path: Path, session: TelemetrySession) -> Path:
    lat = session.channels[GPS_LATITUDE_DEG].values[::10]
    lon = session.channels[GPS_LONGITUDE_DEG].values[::10]
    payload = {
        "type": "FeatureCollection",
        "features": [{
            "type": "Feature",
            "properties": {"width": 12},
            "geometry": {
                "type": "LineString",
                "coordinates": [[float(lo), float(la)] for lo, la in zip(lon, lat)],
            },
        }],
    }
    target = path / "track.geojson"
    target.write_text(json.dumps(payload), encoding="utf-8")
    return target


def test_basemap_renders_faint_reference_only(tmp_path: Path) -> None:
    session = _session()
    result = render_lap_comparison(
        session, 1, session, 1, tmp_path / "c.html",
        same_layout_confirmed=True, plots=["gps_trace"],
        basemap=_geojson(tmp_path, session),
    )
    assert result["generated_plots"] == ["gps_trace"]
    assert result["basemap"]["status"] == "ok"
    assert any("visual reference only" in note for note in result["notes"])


def test_basemap_failure_downgrades_background_only(tmp_path: Path) -> None:
    session = _session()
    result = render_lap_comparison(
        session, 1, session, 1, tmp_path / "c.html",
        same_layout_confirmed=True, plots=["gps_trace"],
        basemap=tmp_path / "missing.geojson",
    )
    assert result["generated_plots"] == ["gps_trace"]
    assert result["basemap"]["status"] == "unavailable"
    assert any("trajectories remain measured" in note for note in result["notes"])


def test_basemap_defaults_to_disabled(tmp_path: Path) -> None:
    session = _session()
    result = render_lap_comparison(
        session, 1, session, 1, tmp_path / "c.html",
        same_layout_confirmed=True, plots=["gps_trace"],
    )
    assert result["basemap"]["status"] == "disabled"


def test_basemap_supports_catalog_layout(tmp_path: Path) -> None:
    session = _session()
    result = render_lap_comparison(
        session, 1, session, 1, tmp_path / "c.html",
        same_layout_confirmed=True, plots=["gps_trace"],
        basemap="catalog:thill-east-bypass", basemap_width_m=12.0,
    )
    assert result["basemap"]["status"] == "ok"
    assert result["basemap"]["provenance"]["source"] == "catalog:thill-east-bypass"
    assert any("catalog track reference" in note for note in result["notes"])


def test_basemap_rejects_unknown_catalog_layout(tmp_path: Path) -> None:
    session = _session()
    result = render_lap_comparison(
        session, 1, session, 1, tmp_path / "c.html",
        same_layout_confirmed=True, plots=["gps_trace"],
        basemap="catalog:no-such-track",
    )
    assert result["generated_plots"] == ["gps_trace"]
    assert result["basemap"]["status"] == "unavailable"
