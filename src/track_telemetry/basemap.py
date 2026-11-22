"""Faint OSM track basemap for GPS-trajectory visualization only.

The basemap is a visual reference. It is never a surveyed track boundary and
must not be used for off-track, curb-apex or incident-boundary measurement.
All measurement stays on recorded GPS trajectories.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

import numpy as np

from .geometry import latlon_to_xy_m

OSM_ATTRIBUTION = "© OpenStreetMap contributors (ODbL)"
OVERPASS_URL = os.getenv(
    "TRACK_TELEMETRY_OVERPASS_URL", "https://overpass-api.de/api/interpreter"
)
CACHE_SCHEMA = 1
_EARTH_RADIUS_M = 6_371_000.0


def _osm_timeout_s(default: float = 20.0) -> float:
    """Allow slow networks to raise the Overpass read timeout without API changes."""
    try:
        value = float(os.getenv("TRACK_TELEMETRY_OSM_TIMEOUT_S", str(default)))
    except ValueError:
        return default
    return value if value > 0 else default


def xy_to_latlon(
    x: np.ndarray, y: np.ndarray, origin_lat_deg: float, origin_lon_deg: float
) -> tuple[np.ndarray, np.ndarray]:
    """Invert the equirectangular projection in geometry.latlon_to_xy_m."""
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    lat = np.asarray(origin_lat_deg, dtype=float) + np.degrees(y / _EARTH_RADIUS_M)
    lon = np.asarray(origin_lon_deg, dtype=float) + np.degrees(
        x / (_EARTH_RADIUS_M * np.cos(np.deg2rad(origin_lat_deg)))
    )
    return lat, lon


def load_catalog_trace(layout_id: str) -> list[dict[str, Any]]:
    """Load an owner-reviewed catalog layout trace as lat/lon centerline features."""
    from .corner_catalog import _load_catalog

    catalog = _load_catalog()
    layouts = catalog.get("layouts", []) if isinstance(catalog, dict) else []
    layout = next((item for item in layouts if item.get("id") == layout_id), None)
    if layout is None:
        raise ValueError(f"Unknown track layout: {layout_id!r}")
    points = np.asarray(layout["reference_trace"], dtype=float)
    if len(points) < 2:
        raise ValueError(f"Layout {layout_id!r} has no usable reference trace")
    lat, lon = xy_to_latlon(
        points[:, 0], points[:, 1],
        float(layout["origin_latitude_deg"]), float(layout["origin_longitude_deg"]),
    )
    return [{
        "kind": "centerline",
        "lat": [float(v) for v in lat],
        "lon": [float(v) for v in lon],
        "tags": {"name": layout.get("name", layout_id)},
    }]

_WIDTH_RE = re.compile(r"([-+]?\d+(?:\.\d+)?)")


def parse_width_m(raw: Any) -> float | None:
    """Parse an OSM width tag value to meters; None when unparseable."""
    if raw is None:
        return None
    if isinstance(raw, (int, float)):
        value = float(raw)
        return value if np.isfinite(value) and value > 0 else None
    match = _WIDTH_RE.search(str(raw))
    if not match:
        return None
    try:
        value = float(match.group(1))
    except ValueError:
        return None
    return value if np.isfinite(value) and 0 < value < 100 else None


def buffer_centerline_xy(
    x: np.ndarray, y: np.ndarray, half_width_m: float
) -> tuple[np.ndarray, np.ndarray]:
    """Offset a centerline to a faint full-width polygon without shapely.

    Uses per-point normals from central differences. Closed loops wrap;
    open lines clamp ends. This is a visualization aid, not a surveyed edge.
    """
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    n = len(x)
    if n < 2:
        raise ValueError("Centerline needs at least 2 points to buffer")
    closed = bool(np.hypot(x[0] - x[-1], y[0] - y[-1]) < 1.0)
    tx = np.empty(n)
    ty = np.empty(n)
    for i in range(n):
        if closed:
            prev_i, next_i = (i - 1) % n, (i + 1) % n
        else:
            prev_i, next_i = max(0, i - 1), min(n - 1, i + 1)
        dx, dy = x[next_i] - x[prev_i], y[next_i] - y[prev_i]
        length = float(np.hypot(dx, dy))
        if length <= 0:
            dx, dy, length = 1.0, 0.0, 1.0
        tx[i], ty[i] = dx / length, dy / length
    nx, ny = -ty, tx
    left = np.stack([x + nx * half_width_m, y + ny * half_width_m], axis=1)
    right = np.stack([x - nx * half_width_m, y - ny * half_width_m], axis=1)
    ring = np.vstack([left, right[::-1], left[:1]])
    return ring[:, 0], ring[:, 1]


def load_geojson_latlon(path: str | Path) -> list[dict[str, Any]]:
    """Load Polygon/LineString features from a GeoJSON file as lat/lon lists."""
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    features = raw.get("features", [raw]) if isinstance(raw, dict) else raw
    out: list[dict[str, Any]] = []
    for feature in features:
        if not isinstance(feature, dict):
            continue
        geometry = feature.get("geometry", feature)
        if not isinstance(geometry, dict):
            continue
        kind = geometry.get("type")
        coords = geometry.get("coordinates")
        props = feature.get("properties", {}) if isinstance(feature.get("properties"), dict) else {}
        if kind == "Polygon" and coords:
            ring = coords[0]
            lon = [float(p[0]) for p in ring]
            lat = [float(p[1]) for p in ring]
            out.append({"kind": "area", "lat": lat, "lon": lon, "tags": props})
        elif kind == "MultiPolygon" and coords:
            for polygon in coords:
                ring = polygon[0]
                lon = [float(p[0]) for p in ring]
                lat = [float(p[1]) for p in ring]
                out.append({"kind": "area", "lat": lat, "lon": lon, "tags": props})
        elif kind == "LineString" and coords:
            lon = [float(p[0]) for p in coords]
            lat = [float(p[1]) for p in coords]
            out.append({"kind": "centerline", "lat": lat, "lon": lon, "tags": props})
        elif kind == "MultiLineString" and coords:
            for line in coords:
                lon = [float(p[0]) for p in line]
                lat = [float(p[1]) for p in line]
                out.append({"kind": "centerline", "lat": lat, "lon": lon, "tags": props})
    if not out:
        raise ValueError(f"No Polygon/LineString features in {path}")
    return out


def _cache_path(cache_dir: Path, bbox: tuple[float, float, float, float]) -> Path:
    key = f"v{CACHE_SCHEMA}:" + ",".join(f"{v:.5f}" for v in bbox)
    name = hashlib.sha256(key.encode()).hexdigest()[:16] + ".json"
    return cache_dir / name


def fetch_osm_ways(
    south: float,
    west: float,
    north: float,
    east: float,
    *,
    cache_dir: Path | None = None,
    timeout_s: float | None = None,
) -> list[dict[str, Any]]:
    """Fetch track-like OSM ways inside a bbox via Overpass; file-cacheable."""
    if timeout_s is None:
        timeout_s = _osm_timeout_s()
    bbox = (south, west, north, east)
    if cache_dir is not None:
        cache_dir.mkdir(parents=True, exist_ok=True)
        cached = _cache_path(cache_dir, bbox)
        if cached.is_file():
            payload = json.loads(cached.read_text(encoding="utf-8"))
            if payload.get("schema_version") == CACHE_SCHEMA:
                return payload["ways"]
    query = (
        f"[out:json][timeout:25];(way[leisure=track]({south},{west},{north},{east});"
        f"way[highway=raceway]({south},{west},{north},{east}););out geom;"
    )
    request = urllib.request.Request(
        OVERPASS_URL,
        data=urllib.parse.urlencode({"data": query}).encode(),
        headers={"User-Agent": "track-telemetry-mcp basemap"},
    )
    with urllib.request.urlopen(request, timeout=timeout_s) as response:  # noqa: S310
        payload = json.loads(response.read().decode("utf-8"))
    ways: list[dict[str, Any]] = []
    for element in payload.get("elements", []):
        if element.get("type") != "way" or not element.get("geometry"):
            continue
        tags = element.get("tags", {})
        geometry = element["geometry"]
        lat = [float(p["lat"]) for p in geometry]
        lon = [float(p["lon"]) for p in geometry]
        if len(lat) < 2:
            continue
        closed = lat[0] == lat[-1] and lon[0] == lon[-1] and len(lat) >= 4
        kind = "area" if closed and tags.get("area") == "yes" else "centerline"
        ways.append({"kind": kind, "lat": lat, "lon": lon, "tags": tags})
    if cache_dir is not None:
        _cache_path(cache_dir, bbox).write_text(
            json.dumps({"schema_version": CACHE_SCHEMA, "ways": ways}, allow_nan=False),
            encoding="utf-8",
        )
    return ways


def _project_features(
    features: list[dict[str, Any]],
    lat0: float,
    lon0: float,
    width_override_m: float | None,
    default_width_m: float = 10.0,
) -> tuple[list[np.ndarray], list[np.ndarray], dict[str, Any]]:
    polygons: list[np.ndarray] = []
    lines: list[np.ndarray] = []
    assumed = 0
    tagged = 0
    for feature in features:
        lat = np.asarray(feature["lat"], dtype=float)
        lon = np.asarray(feature["lon"], dtype=float)
        x, y = latlon_to_xy_m(lat, lon, origin_lat_deg=lat0, origin_lon_deg=lon0)
        if feature["kind"] == "area" and len(x) >= 3:
            polygons.append(np.stack([x, y], axis=1))
        elif len(x) >= 2:
            width = width_override_m or parse_width_m(feature.get("tags", {}).get("width"))
            if width is None:
                width = default_width_m
                assumed += 1
            else:
                tagged += 1
            try:
                px, py = buffer_centerline_xy(x, y, width / 2)
            except ValueError:
                continue
            polygons.append(np.stack([px, py], axis=1))
            lines.append(np.stack([x, y], axis=1))
    provenance = {
        "feature_count": len(features),
        "polygon_count": len(polygons),
        "centerline_count": len(lines),
        "width_tagged": tagged,
        "width_assumed": assumed,
        "assumed_width_m": default_width_m if assumed else None,
        "width_override_m": width_override_m,
    }
    return polygons, lines, provenance


def resolve_basemap(
    basemap: str | Path | dict[str, Any] | None,
    lat0: float,
    lon0: float,
    lap_lat: np.ndarray,
    lap_lon: np.ndarray,
    *,
    width_override_m: float | None = None,
    cache_dir: Path | None = None,
) -> dict[str, Any]:
    """Resolve faint basemap polygons/lines in lap-local XY meters, fail-soft.

    basemap: None (disabled), "osm" (live Overpass fetch around the lap bbox),
    "catalog:<layout_id>" (owner-reviewed local trace), a path to a GeoJSON
    file, or an inline {"features": [...]} mapping.
    Never raises for fetch/parse issues; returns status ok/unavailable/disabled.
    """
    if basemap is None:
        return {
            "status": "disabled",
            "polygons_xy": [],
            "lines_xy": [],
            "label": "basemap",
            "attribution": None,
            "provenance": {},
        }
    try:
        if isinstance(basemap, dict):
            raw_features = basemap.get("features", [])
            features = [
                {"kind": f.get("kind", "centerline"), "lat": f["lat"], "lon": f["lon"],
                 "tags": f.get("tags", {})}
                for f in raw_features
            ]
            source = "inline"
            label, attribution = "basemap", None
        elif isinstance(basemap, str) and basemap.startswith("catalog:"):
            layout_id = basemap.split("catalog:", 1)[1]
            features = load_catalog_trace(layout_id)
            source = f"catalog:{layout_id}"
            label, attribution = "catalog track reference", None
        elif isinstance(basemap, (str, Path)) and str(basemap) != "osm":
            features = load_geojson_latlon(basemap)
            source = f"file:{Path(basemap).name}"
            label, attribution = "basemap", None
        elif str(basemap) == "osm":
            finite = np.isfinite(lap_lat) & np.isfinite(lap_lon)
            if np.count_nonzero(finite) < 3:
                raise ValueError("Insufficient lap GPS to locate OSM bbox")
            pad = 0.005
            south, north = float(np.min(lap_lat[finite])) - pad, float(np.max(lap_lat[finite])) + pad
            west, east = float(np.min(lap_lon[finite])) - pad, float(np.max(lap_lon[finite])) + pad
            features = fetch_osm_ways(south, west, north, east, cache_dir=cache_dir)
            source = "osm:overpass"
            label, attribution = "OSM basemap", OSM_ATTRIBUTION
            if not features:
                return {
                    "status": "unavailable",
                    "reason": "No OSM track ways in lap bbox",
                    "polygons_xy": [],
                    "lines_xy": [],
                    "label": label,
                    "attribution": attribution,
                    "provenance": {"source": source},
                }
        else:
            raise ValueError(f"Unknown basemap: {basemap!r}")
        polygons, lines, provenance = _project_features(
            features, lat0, lon0, width_override_m
        )
        provenance["source"] = source
        if not polygons and not lines:
            return {
                "status": "unavailable",
                "reason": "Basemap features did not project to any drawable shape",
                "polygons_xy": [],
                "lines_xy": [],
                "label": label,
                "attribution": attribution,
                "provenance": provenance,
            }
        return {
            "status": "ok",
            "polygons_xy": polygons,
            "lines_xy": lines,
            "label": label,
            "attribution": attribution,
            "provenance": provenance,
        }
    except Exception as exc:  # fail-soft: trajectories remain the measurement
        return {
            "status": "unavailable",
            "reason": f"{type(exc).__name__}: {exc}",
            "polygons_xy": [],
            "lines_xy": [],
            "label": "basemap",
            "attribution": OSM_ATTRIBUTION,
            "provenance": {},
        }
