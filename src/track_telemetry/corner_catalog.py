"""Conservative GPS-to-track-layout and physical-corner matching.

The catalog identifies a layout from its ordered GPS route. Corner names are
then located by their reviewed reference distances; telemetry minima or turn
shape never create corner identities.
"""

from __future__ import annotations

import json
import math
from importlib import resources
from typing import Any

import numpy as np

from .channels import GPS_LATITUDE_DEG, GPS_LONGITUDE_DEG
from .geometry import cumulative_distance_m, latlon_to_xy_m
from .models import Lap, TelemetrySession

_EARTH_RADIUS_M = 6_371_000.0
_MAX_GEO_DISTANCE_M = 5_000.0
_MAX_REGISTRATION_M = 25.0
_MAX_LAP_GAP_S = 3.0
_MAX_MEDIAN_GAP_S = 2.0
_MAX_CLOSURE_GAP_M = 120.0
_MIN_SAMPLES = 24
_RESIDUAL_COVERAGE_M = 30.0
_MAX_P95_RESIDUAL_M = 25.0
_MAX_P995_RESIDUAL_M = 45.0
_MAX_RESIDUAL_RUN = 2
_AMBIGUITY_SCORE_MARGIN_M = 2.0


def _load_catalog() -> dict[str, Any]:
    """Read the package resource each time so edits and test injection stay visible."""
    raw = (
        resources.files("track_telemetry")
        .joinpath("data", "corner_catalog.json")
        .read_text(encoding="utf-8")
    )
    return json.loads(raw)


def _catalog_or_error() -> tuple[dict[str, Any] | None, str | None]:
    try:
        catalog = _load_catalog()
    except (OSError, ModuleNotFoundError, json.JSONDecodeError) as exc:
        return None, f"Corner catalog is unavailable: {exc}"
    if not isinstance(catalog, dict) or catalog.get("schema_version") != 1:
        return None, "Corner catalog is unavailable: unsupported or invalid schema"
    layouts = catalog.get("layouts")
    if not isinstance(layouts, list):
        return None, "Corner catalog is unavailable: layouts must be a list"
    for layout in layouts:
        if not _valid_layout(layout):
            return None, "Corner catalog is unavailable: a layout is malformed"
    return catalog, None


def _valid_layout(layout: Any) -> bool:
    if not isinstance(layout, dict):
        return False
    required = (
        "id",
        "name",
        "direction",
        "origin_latitude_deg",
        "origin_longitude_deg",
        "length_m",
        "reference_trace",
        "corners",
    )
    if any(key not in layout for key in required):
        return False
    if layout["direction"] not in {"CW", "CCW"}:
        return False
    try:
        length = float(layout["length_m"])
        origin = [float(layout["origin_latitude_deg"]), float(layout["origin_longitude_deg"])]
        trace = np.asarray(layout["reference_trace"], dtype=np.float64)
        corners = layout["corners"]
    except (TypeError, ValueError):
        return False
    if (
        not np.isfinite(length)
        or length <= 0
        or not np.all(np.isfinite(origin))
        or trace.ndim != 2
        or trace.shape[1] != 2
        or len(trace) < 8
        or not np.all(np.isfinite(trace))
        or not isinstance(corners, list)
        or not corners
    ):
        return False
    try:
        for corner in corners:
            if (
                not isinstance(corner, dict)
                or not corner.get("id")
                or not corner.get("official")
                or not np.isfinite(float(corner["reference_s_m"]))
            ):
                return False
    except (KeyError, TypeError, ValueError):
        return False
    return True


def list_track_layouts() -> dict[str, Any]:
    """List reviewed, GPS-observed layouts without exposing unobserved features as matches."""
    catalog, error = _catalog_or_error()
    if error:
        return {"status": "unavailable", "layouts": [], "reason": error}
    assert catalog is not None
    return {
        "status": "available",
        "schema_version": catalog["schema_version"],
        "approval": catalog.get("approval"),
        "identity_contract": catalog.get("identity_contract"),
        "layouts": [
            {
                "id": layout["id"],
                "name": layout["name"],
                "direction": layout["direction"],
                "length_m": float(layout["length_m"]),
                "corner_count": len(layout["corners"]),
                "provenance": layout.get("source"),
            }
            for layout in catalog["layouts"]
        ],
        "provenance": {"approval": catalog.get("approval"), "sources": catalog.get("sources")},
    }


def _trace_geometry(layout: dict[str, Any]) -> tuple[np.ndarray, np.ndarray, float, float]:
    points = np.asarray(layout["reference_trace"], dtype=np.float64)
    if np.linalg.norm(points[-1] - points[0]) < 1e-6:
        points = points[:-1]
    following = np.roll(points, -1, axis=0)
    lengths = np.linalg.norm(following - points, axis=1)
    keep = lengths > 1e-6
    points = points[keep]
    following = following[keep]
    lengths = lengths[keep]
    if len(points) < 8:
        raise ValueError("Reference trace has too few distinct segments")
    starts = np.concatenate(([0.0], np.cumsum(lengths[:-1])))
    total = float(np.sum(lengths))
    area = _signed_area(points)
    return points, starts, total, area


def _signed_area(points: np.ndarray) -> float:
    following = np.roll(points, -1, axis=0)
    return float(0.5 * np.sum(points[:, 0] * following[:, 1] - following[:, 0] * points[:, 1]))


def _nearest_polyline(
    queries: np.ndarray,
    vertices: np.ndarray,
    starts: np.ndarray | None = None,
    segment_lengths: np.ndarray | None = None,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Return nearest feet, circular route distances, and distances to a closed polyline."""
    points = np.asarray(vertices, dtype=np.float64)
    following = np.roll(points, -1, axis=0)
    vectors = following - points
    lengths = (
        np.linalg.norm(vectors, axis=1)
        if segment_lengths is None
        else np.asarray(segment_lengths, dtype=np.float64)
    )
    if starts is None:
        starts = np.concatenate(([0.0], np.cumsum(lengths[:-1])))
    q = np.asarray(queries, dtype=np.float64)
    feet = np.empty((len(q), 2), dtype=np.float64)
    route_s = np.empty(len(q), dtype=np.float64)
    distances = np.empty(len(q), dtype=np.float64)
    denom = np.maximum(lengths * lengths, 1e-12)
    # Keep intermediate arrays bounded when a high-rate lap has many samples.
    chunk_size = max(1, min(64, 1_000_000 // max(len(points), 1)))
    for begin in range(0, len(q), chunk_size):
        end = min(begin + chunk_size, len(q))
        delta = q[begin:end, None, :] - points[None, :, :]
        fraction = np.clip(np.sum(delta * vectors[None, :, :], axis=2) / denom[None, :], 0.0, 1.0)
        projected = points[None, :, :] + fraction[:, :, None] * vectors[None, :, :]
        error = q[begin:end, None, :] - projected
        dist2 = np.sum(error * error, axis=2)
        index = np.argmin(dist2, axis=1)
        row = np.arange(end - begin)
        feet[begin:end] = projected[row, index]
        route_s[begin:end] = starts[index] + fraction[row, index] * lengths[index]
        distances[begin:end] = np.sqrt(dist2[row, index])
    return feet, route_s, distances


def _channel_window_quality(session: TelemetrySession, lap: Lap, name: str) -> dict[str, Any]:
    channel = session.optional_channel(name)
    if channel is None:
        raise ValueError(f"Missing GPS channel {name!r}")
    mask = (channel.timestamps >= lap.start_s) & (channel.timestamps <= lap.end_s)
    times = channel.timestamps[mask]
    values = channel.values[mask]
    if len(times) < _MIN_SAMPLES or not np.all(np.isfinite(times)):
        raise ValueError(f"Insufficient {name} samples within the timed lap")
    gaps = np.diff(times)
    if np.any(gaps <= 0):
        raise ValueError(f"{name} timestamps are not strictly increasing")
    median_gap = float(np.median(gaps))
    max_gap = float(np.max(gaps))
    permitted_gap = min(_MAX_LAP_GAP_S, max(1.0, 3.0 * median_gap))
    if median_gap > _MAX_MEDIAN_GAP_S or max_gap > permitted_gap:
        raise ValueError(f"{name} timestamp gap quality is insufficient")
    duration = lap.end_s - lap.start_s
    coverage = (times[-1] - times[0]) / duration if duration > 0 else 0.0
    edge_allowance = max(2.0, 0.03 * duration)
    if (
        coverage < 0.92
        or times[0] - lap.start_s > edge_allowance
        or lap.end_s - times[-1] > edge_allowance
    ):
        raise ValueError(f"{name} does not cover the full timed lap")
    return {
        "samples": int(len(times)),
        "median_rate_hz": float(1.0 / median_gap) if median_gap > 0 else None,
        "max_gap_s": max_gap,
        "median_gap_s": median_gap,
        "time_coverage_fraction": float(coverage),
        "values": values,
        "timestamps": times,
    }


def _session_trace(
    session: TelemetrySession, lap_number: int
) -> tuple[dict[str, Any] | None, str | None]:
    try:
        lap = session.lap(lap_number)
    except KeyError:
        return None, f"Lap {lap_number} is unavailable"
    if not lap.is_timed or not np.isfinite(lap.duration_s) or lap.duration_s <= 0:
        return None, "A finite positive timed lap is required"
    if not (np.isfinite(lap.start_s) and np.isfinite(lap.end_s) and lap.end_s > lap.start_s):
        return None, "The lap has invalid start/end timestamps"
    try:
        lat_q = _channel_window_quality(session, lap, GPS_LATITUDE_DEG)
        lon_q = _channel_window_quality(session, lap, GPS_LONGITUDE_DEG)
    except (KeyError, ValueError) as exc:
        return None, str(exc)
    t = lat_q["timestamps"]
    lat = lat_q["values"]
    try:
        lon = session.channel(GPS_LONGITUDE_DEG).interp(t)
    except KeyError as exc:
        return None, str(exc)
    valid = np.isfinite(lat) & np.isfinite(lon)
    if np.count_nonzero(valid) < _MIN_SAMPLES or np.mean(valid) < 0.98:
        return None, "Latitude/longitude samples do not align across the full timed lap"
    t, lat, lon = t[valid], lat[valid], lon[valid]
    if np.any(np.diff(t) <= 0):
        return None, "GPS timestamps are not strictly increasing after channel alignment"
    if np.any(np.abs(lat) > 90.0) or np.any(np.abs(lon) > 180.0):
        return None, "GPS contains out-of-range latitude or longitude"
    return {
        "lap": lap,
        "timestamps": t,
        "latitude_deg": lat,
        "longitude_deg": lon,
        "lat_quality": {k: v for k, v in lat_q.items() if k not in {"values", "timestamps"}},
        "lon_quality": {k: v for k, v in lon_q.items() if k not in {"values", "timestamps"}},
    }, None


def _longest_run(mask: np.ndarray) -> int:
    longest = current = 0
    for value in np.asarray(mask, dtype=bool):
        current = current + 1 if value else 0
        longest = max(longest, current)
    return longest


def _prepare_candidate(trace: dict[str, Any], layout: dict[str, Any]) -> dict[str, Any]:
    ref, starts, ref_length, ref_area = _trace_geometry(layout)
    declared_direction = layout["direction"]
    if abs(ref_area) < 1_000 or (ref_area > 0) != (declared_direction == "CCW"):
        return {
            "layout_id": layout["id"],
            "status": "unmatched",
            "reason": "invalid_catalog_direction",
            "score": math.inf,
        }

    lat = trace["latitude_deg"]
    lon = trace["longitude_deg"]
    x, y = latlon_to_xy_m(
        lat,
        lon,
        origin_lat_deg=float(layout["origin_latitude_deg"]),
        origin_lon_deg=float(layout["origin_longitude_deg"]),
    )
    actual = np.column_stack((x, y))
    geo_distance = float(np.median(np.hypot(x, y)))
    quality: dict[str, Any] = {
        "geodetic_median_distance_m": geo_distance,
        "gps": {"latitude": trace["lat_quality"], "longitude": trace["lon_quality"]},
    }
    if geo_distance > _MAX_GEO_DISTANCE_M:
        return {
            "layout_id": layout["id"],
            "status": "unmatched",
            "reason": "geographic_mismatch",
            "score": math.inf,
            "quality": quality,
        }

    area = _signed_area(actual)
    area_direction = "CCW" if area > 0 else "CW"
    quality["observed_direction"] = area_direction
    quality["reference_direction"] = declared_direction
    if abs(area) < 1_000 or area_direction != declared_direction:
        return {
            "layout_id": layout["id"],
            "status": "unmatched",
            "reason": "wrong_direction",
            "score": math.inf,
            "quality": quality,
        }

    distance = cumulative_distance_m(actual[:, 0], actual[:, 1])
    lap_length = float(distance[-1])
    closure_gap = float(np.linalg.norm(actual[-1] - actual[0]))
    median_step = float(np.median(np.diff(distance))) if len(distance) > 1 else 0.0
    quality.update(
        {
            "lap_spatial_distance_m": lap_length,
            "closure_gap_m": closure_gap,
            "reference_trace_distance_m": ref_length,
            "catalog_length_m": float(layout["length_m"]),
        }
    )
    if closure_gap > min(_MAX_CLOSURE_GAP_M, max(60.0, 3.0 * median_step)):
        return {
            "layout_id": layout["id"],
            "status": "unmatched",
            "reason": "lap_not_closed",
            "score": math.inf,
            "quality": quality,
        }
    length_ratio = lap_length / float(layout["length_m"])
    quality["lap_to_catalog_length_ratio"] = float(length_ratio)
    if not 0.70 <= length_ratio <= 1.35:
        return {
            "layout_id": layout["id"],
            "status": "unmatched",
            "reason": "lap_length_mismatch",
            "score": math.inf,
            "quality": quality,
        }

    # Estimate only a small robust translation. This corrects map/GPS origin offsets,
    # not scale, rotation, or unrelated geometry.
    shift = np.zeros(2, dtype=np.float64)
    for _ in range(3):
        feet, _, _ = _nearest_polyline(
            actual + shift, ref, starts, np.linalg.norm(np.roll(ref, -1, axis=0) - ref, axis=1)
        )
        correction = np.median(feet - (actual + shift), axis=0)
        if np.linalg.norm(shift + correction) > _MAX_REGISTRATION_M:
            quality["registration_offset_m"] = [float(v) for v in shift + correction]
            return {
                "layout_id": layout["id"],
                "status": "unmatched",
                "reason": "registration_exceeds_limit",
                "score": math.inf,
                "quality": quality,
            }
        shift += correction
        if np.linalg.norm(correction) < 0.05:
            break
    aligned = actual + shift
    nearest, route_s, residual = _nearest_polyline(
        aligned, ref, starts, np.linalg.norm(np.roll(ref, -1, axis=0) - ref, axis=1)
    )
    quality["registration_offset_m"] = [float(v) for v in shift]

    signed_steps = (np.diff(route_s) + ref_length / 2.0) % ref_length - ref_length / 2.0
    spatial_steps = np.linalg.norm(np.diff(aligned, axis=0), axis=1)
    allowed_jump = np.maximum(50.0, 3.0 * spatial_steps + 15.0)
    large_jumps = np.abs(signed_steps) > allowed_jump
    backtrack_limit = np.maximum(8.0, 0.75 * spatial_steps)
    meaningful_backtracks = signed_steps < -backtrack_limit
    positive = np.maximum(signed_steps, 0.0)
    negative = np.maximum(-signed_steps, 0.0)
    direction_consistency = float(np.sum(positive) / max(np.sum(positive + negative), 1e-9))
    backtrack_distance = float(np.sum(negative))
    # Keep signed increments when unwrapping. Summing only positive deltas
    # inflates progress whenever the nearest projection moves backward.
    unwrapped_s = np.concatenate(([route_s[0]], route_s[0] + np.cumsum(signed_steps)))
    projection_span = float(unwrapped_s[-1] - unwrapped_s[0])
    quality.update(
        {
            "monotonic_direction_fraction": direction_consistency,
            "projection_backtrack_distance_m": backtrack_distance,
            "projection_span_m": projection_span,
            "projection_span_ratio": projection_span / ref_length,
            "projection_large_jumps": int(np.count_nonzero(large_jumps)),
            "projection_meaningful_backtracks": int(np.count_nonzero(meaningful_backtracks)),
        }
    )
    if (
        np.count_nonzero(large_jumps) > max(2, int(0.005 * len(signed_steps)))
        or _longest_run(large_jumps) > 2
    ):
        return {
            "layout_id": layout["id"],
            "status": "unmatched",
            "reason": "projection_discontinuity",
            "score": math.inf,
            "quality": quality,
        }
    if direction_consistency < 0.92 or backtrack_distance > max(20.0, 0.05 * ref_length):
        return {
            "layout_id": layout["id"],
            "status": "unmatched",
            "reason": "route_order_mismatch",
            "score": math.inf,
            "quality": quality,
        }
    if not 0.78 <= projection_span / ref_length <= 1.22:
        return {
            "layout_id": layout["id"],
            "status": "unmatched",
            "reason": "incomplete_route_coverage",
            "score": math.inf,
            "quality": quality,
        }

    # Minor local reversals are held at their previous route coordinate after the
    # signed unwrap. Larger or persistent backtracking was rejected above.
    directed_s = np.maximum.accumulate(unwrapped_s)
    keep_last = np.concatenate((directed_s[1:] != directed_s[:-1], [True]))
    unique_s = directed_s[keep_last]
    unique_indices = np.flatnonzero(keep_last)
    unique_distance = distance[unique_indices]
    if len(unique_s) < 3:
        return {
            "layout_id": layout["id"],
            "status": "unmatched",
            "reason": "projection_unusable",
            "score": math.inf,
            "quality": quality,
        }

    # Bidirectional line coverage catches short missing branches that percentile-only
    # gates can hide. Point-to-segment distance also tolerates different GPS rates.
    _, _, reverse_residual = _nearest_polyline(ref, np.vstack((aligned, aligned[0])))
    p50, p95, p995 = [float(np.percentile(residual, p)) for p in (50, 95, 99.5)]
    reverse_coverage = float(np.mean(reverse_residual <= _RESIDUAL_COVERAGE_M))
    forward_coverage = float(np.mean(residual <= _RESIDUAL_COVERAGE_M))
    high_run = _longest_run(residual > _RESIDUAL_COVERAGE_M)
    quality.update(
        {
            "residual_median_m": p50,
            "residual_p95_m": p95,
            "residual_p99_5_m": p995,
            "residual_max_m": float(np.max(residual)),
            "residual_over_30m_fraction": float(np.mean(residual > _RESIDUAL_COVERAGE_M)),
            "residual_over_30m_longest_run_samples": high_run,
            "forward_coverage_fraction_within_30m": forward_coverage,
            "symmetric_reference_coverage_fraction_within_30m": reverse_coverage,
        }
    )
    if (
        p95 > _MAX_P95_RESIDUAL_M
        or p995 > _MAX_P995_RESIDUAL_M
        or reverse_coverage < 0.90
        or forward_coverage < 0.90
        or high_run > _MAX_RESIDUAL_RUN
    ):
        return {
            "layout_id": layout["id"],
            "status": "unmatched",
            "reason": "route_residual_or_branch_mismatch",
            "score": math.inf,
            "quality": quality,
        }

    score = p95 + 0.25 * p995 + 20.0 * (1.0 - reverse_coverage)
    confidence = float(np.clip(math.exp(-score / 45.0), 0.0, 1.0))
    quality["geometry_score_m"] = float(score)
    quality["confidence"] = confidence
    candidate = {
        "layout_id": layout["id"],
        "status": "matched_candidate",
        "score": float(score),
        "quality": quality,
        "layout": layout,
        "reference_points": ref,
        "reference_starts": starts,
        "reference_length_m": ref_length,
        "aligned_points": aligned,
        "actual_points": actual,
        "actual_distance_m": distance,
        "directed_reference_s_m": directed_s,
        "unique_reference_s_m": unique_s,
        "unique_actual_distance_m": unique_distance,
        "nearest_reference_points": nearest,
        "residual_distance_m": residual,
        "registration_offset_m": shift,
        "lap": trace["lap"],
        "timestamps": trace["timestamps"],
        "latitude_deg": lat,
        "longitude_deg": lon,
    }
    corner_records = _corner_records(candidate)
    max_anchor_offset = max((corner["distance_m"] for corner in corner_records), default=0.0)
    quality["max_corner_anchor_offset_m"] = float(max_anchor_offset)
    if max_anchor_offset > 45.0:
        return {
            "layout_id": layout["id"],
            "status": "unmatched",
            "reason": "corner_anchor_projection_mismatch",
            "score": math.inf,
            "quality": quality,
        }
    candidate["corners"] = corner_records
    return candidate


def _reference_point_at_s(candidate: dict[str, Any], distance_m: float) -> np.ndarray:
    points = candidate["reference_points"]
    starts = candidate["reference_starts"]
    lengths = np.linalg.norm(np.roll(points, -1, axis=0) - points, axis=1)
    total = candidate["reference_length_m"]
    s = float(distance_m % total)
    index = int(np.searchsorted(starts, s, side="right") - 1)
    index = max(0, min(index, len(points) - 1))
    fraction = (s - starts[index]) / max(lengths[index], 1e-9)
    return points[index] + fraction * (points[(index + 1) % len(points)] - points[index])


def _lap_values_at_reference_s(
    candidate: dict[str, Any], reference_s_m: float
) -> tuple[float, np.ndarray]:
    total = candidate["reference_length_m"]
    route_s = candidate["unique_reference_s_m"]
    start = float(route_s[0])
    target = float(reference_s_m) % total
    target += math.ceil((start - target) / total) * total
    if target > route_s[-1] + 1e-6:
        target -= total
    target = float(np.clip(target, route_s[0], route_s[-1]))
    lap_distance = float(np.interp(target, route_s, candidate["unique_actual_distance_m"]))
    point = np.array(
        [
            np.interp(
                lap_distance, candidate["actual_distance_m"], candidate["aligned_points"][:, 0]
            ),
            np.interp(
                lap_distance, candidate["actual_distance_m"], candidate["aligned_points"][:, 1]
            ),
        ],
        dtype=np.float64,
    )
    return lap_distance, point


def _lap_progress_for_reference_s(candidate: dict[str, Any], reference_s_m: float) -> float:
    distance, _ = _lap_values_at_reference_s(candidate, reference_s_m)
    total_distance = float(candidate["actual_distance_m"][-1])
    return float(distance / total_distance) if total_distance > 0 else 0.0


def _corner_records(candidate: dict[str, Any]) -> list[dict[str, Any]]:
    layout = candidate["layout"]
    total_ref = candidate["reference_length_m"]
    total_lap = float(candidate["actual_distance_m"][-1])
    corners = []
    for source in layout["corners"]:
        s = float(source["reference_s_m"]) % total_ref
        lap_distance, observed = _lap_values_at_reference_s(candidate, s)
        reference = _reference_point_at_s(candidate, s)
        offset = reference - observed
        residual = float(np.linalg.norm(offset))
        coordinates = {
            "latitude_deg": float(
                np.interp(lap_distance, candidate["actual_distance_m"], candidate["latitude_deg"])
            ),
            "longitude_deg": float(
                np.interp(lap_distance, candidate["actual_distance_m"], candidate["longitude_deg"])
            ),
            "reference_x_m": float(reference[0]),
            "reference_y_m": float(reference[1]),
        }
        corners.append(
            {
                "id": str(source["id"]),
                "official": str(source["official"]),
                "direction": source.get("direction"),
                "feature_type": source.get("feature_type", "corner"),
                "lap_progress": float(lap_distance / total_lap) if total_lap > 0 else 0.0,
                "lap_distance_m": float(lap_distance),
                "reference_distance_m": s,
                "distance_m": residual,
                "offset_m": [float(offset[0]), float(offset[1])],
                "confidence": float(
                    np.clip(
                        math.exp(-residual / 30.0) * candidate["quality"]["confidence"], 0.0, 1.0
                    )
                ),
                "coordinates": coordinates,
            }
        )
    corners.sort(key=lambda value: value["lap_progress"])
    return corners


def _section_intervals(corners: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if len(corners) < 2:
        return []
    intervals = []
    for index, current in enumerate(corners):
        previous = corners[index - 1]
        following = corners[(index + 1) % len(corners)]
        current_progress = float(current["lap_progress"])
        previous_progress = float(previous["lap_progress"])
        following_progress = float(following["lap_progress"])
        if index == 0:
            current_progress += 1.0
        if previous_progress > current_progress:
            previous_progress -= 1.0
        if following_progress <= current_progress:
            following_progress += 1.0
        start = 0.5 * (previous_progress + current_progress)
        end = 0.5 * (current_progress + following_progress)
        intervals.append(
            {
                "label": f"{previous['official']}–{current['official']}",
                "corner_ids": [previous["id"], current["id"]],
                "official_names": [previous["official"], current["official"]],
                "start_progress": float(start % 1.0),
                "end_progress": float(end % 1.0) if end > 1.0 else end,
                "wraps_lap": bool(end > 1.0 or start < 0.0),
            }
        )
    return intervals


def _matched_result(candidate: dict[str, Any]) -> dict[str, Any]:
    layout = candidate["layout"]
    corners = candidate.get("corners") or _corner_records(candidate)
    return {
        "status": "matched",
        "lap_number": int(candidate["lap"].number),
        "layout_id": str(layout["id"]),
        "name": str(layout["name"]),
        "layout_name": str(layout["name"]),
        "direction": layout["direction"],
        "corners": corners,
        "section_intervals": _section_intervals(corners),
        "quality": candidate["quality"],
        "provenance": {
            "approval": candidate.get("catalog_approval"),
            "layout_source": layout.get("source"),
            "identity_contract": candidate.get("identity_contract"),
        },
        "interpretation": "Matched GPS locates reviewed physical corners; it does not identify cause.",
    }


def match_lap(
    session: TelemetrySession,
    lap_number: int,
    layout_id: str | None = None,
) -> dict[str, Any]:
    """Match a full timed lap to one reviewed physical layout using GPS geometry."""
    catalog, error = _catalog_or_error()
    if error:
        return {
            "status": "unavailable",
            "layout_id": None,
            "name": None,
            "reason": "catalog_unavailable",
            "message": error,
            "corners": [],
            "section_intervals": [],
            "quality": {},
            "provenance": None,
        }
    assert catalog is not None
    layouts = catalog["layouts"]
    known_ids = {str(layout["id"]) for layout in layouts}
    if layout_id is not None and layout_id not in known_ids:
        return {
            "status": "unmatched",
            "layout_id": None,
            "name": None,
            "reason": "unknown_layout_id",
            "message": f"Unknown layout id {layout_id!r}",
            "requested_layout_id": layout_id,
            "corners": [],
            "section_intervals": [],
            "quality": {},
            "provenance": None,
        }
    trace, error = _session_trace(session, lap_number)
    if error:
        return {
            "status": "unavailable",
            "layout_id": None,
            "name": None,
            "reason": "lap_gps_unavailable",
            "message": error,
            "corners": [],
            "section_intervals": [],
            "quality": {},
            "provenance": None,
        }
    assert trace is not None
    order = {str(layout["id"]): index for index, layout in enumerate(layouts)}
    candidates = list(layouts)
    if layout_id is not None:
        candidates.sort(
            key=lambda layout: (str(layout["id"]) != layout_id, order[str(layout["id"])])
        )
    results = [_prepare_candidate(trace, layout) for layout in candidates]
    for result in results:
        result["catalog_approval"] = catalog.get("approval")
        result["identity_contract"] = catalog.get("identity_contract")
    good = sorted(
        (result for result in results if result["status"] == "matched_candidate"),
        key=lambda item: item["score"],
    )
    candidate_summaries = [
        {
            "layout_id": result["layout_id"],
            "status": result["status"],
            "reason": result.get("reason"),
            "score_m": result.get("score") if np.isfinite(result.get("score", math.inf)) else None,
            "quality": result.get("quality", {}),
        }
        for result in results
    ]
    if not good:
        reasons = [result.get("reason") for result in results if result.get("reason")]
        common = (
            "wrong_direction"
            if "wrong_direction" in reasons
            else "geographic_mismatch"
            if reasons and all(r == "geographic_mismatch" for r in reasons)
            else "no_layout_match"
        )
        return {
            "status": "unmatched",
            "layout_id": None,
            "name": None,
            "lap_number": int(lap_number),
            "reason": common,
            "message": "No reviewed layout passed geographic, direction, route-order, and residual gates.",
            "requested_layout_id": layout_id,
            "candidates": candidate_summaries,
            "quality": {
                "gps": {"latitude": trace["lat_quality"], "longitude": trace["lon_quality"]}
            },
            "provenance": {"approval": catalog.get("approval"), "sources": catalog.get("sources")},
            "corners": [],
            "section_intervals": [],
        }
    best = good[0]
    if len(good) > 1 and good[1]["score"] - best["score"] <= _AMBIGUITY_SCORE_MARGIN_M:
        return {
            "status": "ambiguous",
            "layout_id": None,
            "name": None,
            "lap_number": int(lap_number),
            "reason": "close_layout_matches",
            "message": "Multiple reviewed layouts fit the GPS trace within the ambiguity margin.",
            "requested_layout_id": layout_id,
            "candidates": [
                {
                    "layout_id": result["layout_id"],
                    "name": result["layout"]["name"],
                    "score_m": result["score"],
                    "quality": result["quality"],
                }
                for result in good
            ],
            "quality": best["quality"],
            "provenance": {"approval": catalog.get("approval"), "sources": catalog.get("sources")},
            "corners": [],
            "section_intervals": [],
        }
    if layout_id is not None and best["layout_id"] != layout_id:
        return {
            "status": "unmatched",
            "layout_id": None,
            "name": None,
            "lap_number": int(lap_number),
            "reason": "requested_layout_mismatch",
            "message": "The requested layout did not rank as the GPS match.",
            "requested_layout_id": layout_id,
            "candidates": [
                {
                    "layout_id": result["layout_id"],
                    "name": result["layout"]["name"],
                    "score_m": result["score"],
                    "quality": result["quality"],
                }
                for result in good
            ],
            "quality": best["quality"],
            "provenance": {"approval": catalog.get("approval"), "sources": catalog.get("sources")},
            "corners": [],
            "section_intervals": [],
        }
    result = _matched_result(best)
    result["candidates"] = candidate_summaries
    return result


def locate_section(
    match: dict[str, Any],
    start_progress: float,
    end_progress: float,
) -> dict[str, Any]:
    """Map a lap-progress interval to adjacent reviewed corner anchors, without causal claims."""
    base = {
        "status": "unresolved",
        "label": None,
        "corner_ids": [],
        "official_names": [],
        "role": "location_only",
        "interpretation": "GPS location context does not establish a performance cause.",
    }
    if not isinstance(match, dict) or match.get("status") != "matched":
        base["reason"] = "a uniquely matched lap layout is required"
        return base
    try:
        start = float(start_progress)
        end = float(end_progress)
    except (TypeError, ValueError):
        base["reason"] = "start_progress and end_progress must be finite numbers"
        return base
    if not (np.isfinite(start) and np.isfinite(end) and 0.0 <= start <= 1.0 and 0.0 <= end <= 1.0):
        base["reason"] = "progress values must be finite and lie in [0, 1]"
        return base
    corners = match.get("corners")
    if not isinstance(corners, list) or len(corners) < 2:
        base["reason"] = "the matched layout has insufficient corner anchors"
        return base
    try:
        ordered = sorted(corners, key=lambda value: float(value["lap_progress"]))
        if any(not np.isfinite(float(corner["lap_progress"])) for corner in ordered):
            raise ValueError
    except (KeyError, TypeError, ValueError):
        base["reason"] = "corner anchor progress is malformed"
        return base

    query_start = start % 1.0
    query_end = end if end == 1.0 and start == 0.0 else end % 1.0
    query_span = (query_end - query_start) % 1.0
    if start == 0.0 and end == 1.0:
        query_span = 1.0
    query_stop = query_start + query_span
    pairs: list[tuple[float, dict[str, Any]]] = []
    # Wide windows only name intervals with a meaningful share of the window, so a
    # ~25 m sliver at the edge (e.g. T10–T11 touching sector 15) does not pull an
    # extra corner into the label. Narrow/point queries keep any intersection.
    min_overlap = 0.01 if 0.02 <= query_span < 1.0 - 1e-9 else 1e-10
    for interval in _section_intervals(ordered):
        left = float(interval["start_progress"])
        right = float(interval["end_progress"])
        if interval["wraps_lap"] or right <= left:
            right += 1.0
        for shift in (-1.0, 0.0, 1.0, 2.0):
            a, b = left + shift, right + shift
            overlap_start = max(query_start, a)
            overlap = min(query_stop, b) - overlap_start
            contains_point = query_span == 0.0 and a <= query_start <= b
            if overlap > min_overlap or contains_point or query_span == 1.0:
                pairs.append((overlap_start - query_start, interval))
                break
    if not pairs:
        base["reason"] = "interval did not intersect a reviewed corner anchor pair"
        return base

    pairs.sort(key=lambda item: item[0])
    selected_intervals = [interval for _, interval in pairs]
    # Preserve route order and remove repeated shared endpoints across adjacent intervals.
    names: list[str] = []
    corner_ids: list[str] = []
    seen_ids: set[str] = set()
    for interval in selected_intervals:
        for corner_id, name in zip(interval["corner_ids"], interval["official_names"]):
            if corner_id not in seen_ids:
                seen_ids.add(corner_id)
                corner_ids.append(corner_id)
                names.append(name)
    label = f"{names[0]}–{names[-1]}" if len(names) > 1 else names[0]
    if query_span >= 1.0 - 1e-9:
        label = f"Full lap ({names[0]}–{names[-1]})"
    return {
        "status": "matched",
        "layout_id": match.get("layout_id"),
        "name": match.get("name", match.get("layout_name")),
        "label": label,
        "corner_ids": corner_ids,
        "official_names": names,
        "intervals": selected_intervals,
        "start_progress": start,
        "end_progress": end,
        "wraps_lap": bool(start > end),
        "role": "location_only",
        "interpretation": "GPS location context does not establish a performance cause.",
    }
