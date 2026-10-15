"""Adapter from BoYanZh/TrackTelemetryConverter into the normalized session model."""

from __future__ import annotations

import json
import re
import zipfile
from collections import Counter
from pathlib import Path
from typing import Any

import numpy as np

from . import channels as out
from .models import ChannelSeries, Lap, TelemetrySession


def _motec_dependencies():
    try:
        from track_telemetry_converter import channels as mc
        from track_telemetry_converter.log import DataLog
    except ImportError as exc:
        raise RuntimeError(
            "RCZ support requires the track-telemetry-converter package. Install with: "
            "pip install -e '.[rcz]'"
        ) from exc
    return mc, DataLog


def _channel_map(mc: Any) -> dict[str, str]:
    return {
        mc.CH_GROUND_SPEED: out.SPEED_KMH,
        mc.CH_CG_ACCEL_LAT: out.LAT_G,
        mc.CH_CG_ACCEL_LON: out.LONG_G,
        mc.CH_CG_ACCEL_VERT: out.VERT_G,
        mc.CH_GPS_LATITUDE: out.GPS_LATITUDE_DEG,
        mc.CH_GPS_LONGITUDE: out.GPS_LONGITUDE_DEG,
        mc.CH_GPS_HEADING: out.GPS_HEADING_DEG,
        mc.CH_YAW_RATE: out.YAW_RATE_DPS,
        mc.CH_STEERING_ANGLE: out.STEERING_DEG,
        mc.CH_THROTTLE_POS: out.THROTTLE_PCT,
        mc.CH_ACCELERATOR_POS: out.ACCELERATOR_PCT,
        mc.CH_BRAKE_PRESS: out.BRAKE_PRESSURE_KPA,
        mc.CH_BRAKE_POS: out.BRAKE_POS_PCT,
        mc.CH_ENGINE_RPM: out.ENGINE_RPM,
        mc.CH_GEAR: out.GEAR,
        mc.CH_LAP_NUMBER: out.LAP_NUMBER,
        mc.CH_ENGINE_OIL_PRESS: out.ENGINE_OIL_PRESSURE_KPA,
        mc.CH_ENGINE_OIL_TEMP: out.ENGINE_OIL_TEMP_C,
        mc.CH_COOLANT_TEMP: out.COOLANT_TEMP_C,
        mc.CH_GEARBOX_TEMP: out.GEARBOX_TEMP_C,
    }


def load_rcz(
    path: str | Path,
    *,
    target_stint: int | None = None,
    target_session: str | None = None,
    mask_interp_gaps: bool = True,
) -> TelemetrySession:
    """Parse an RCZ archive using track_telemetry_converter and normalize its useful channels."""
    mc, DataLog = _motec_dependencies()
    source = Path(path).expanduser().resolve()
    if source.suffix.lower() != ".rcz":
        raise ValueError(f"Expected .rcz input, got {source.name!r}")
    if not source.is_file():
        raise FileNotFoundError(source)

    log = DataLog()
    log.from_rcz_log(
        str(source),
        target_stint=target_stint,
        target_session=target_session,
        mask_interp_gaps=mask_interp_gaps,
    )

    normalized: dict[str, ChannelSeries] = {}
    for source_name, target_name in _channel_map(mc).items():
        channel = log.channels.get(source_name)
        if channel is None or len(channel.timestamps) == 0:
            continue
        normalized[target_name] = ChannelSeries(
            target_name,
            channel.units,
            channel.timestamps.copy(),
            channel.values.copy(),
        )

    laps: list[Lap] = []
    for raw in getattr(log, "laps_info", {}).get("laps", []):
        laps.append(
            Lap(
                number=int(raw["lap_num"]),
                label=str(raw.get("lap_label", raw["lap_num"])),
                kind=str(raw.get("type", "Unknown")),
                start_s=float(raw["start_time"]),
                end_s=float(raw["end_time"]),
                duration_s=float(raw["duration"]),
                original_number=(
                    int(raw["orig_num"]) if raw.get("orig_num") is not None else None
                ),
            )
        )

    metadata = dict(getattr(log, "metadata", {}) or {})
    metadata.update({k: v for k, v in getattr(log, "rcz_metadata", {}).items() if v not in (None, "")})
    metadata["source_format"] = "RaceChrono RCZ"
    if target_stint is not None:
        metadata["target_stint"] = target_stint
    if target_session is not None:
        metadata["target_session"] = target_session

    return TelemetrySession(
        session_id=source.stem,
        source=str(source),
        metadata=metadata,
        laps=laps,
        channels=normalized,
    )



def discover_rcz_stints(path: str | Path) -> list[dict[str, int]]:
    """Inspect archive metadata without decoding channels.

    A stint must have recording data. Lap metadata alone is not enough: a
    partially exported archive can mention stints with no recorded channels.
    Invalid archives raise an explicit exception rather than silently
    returning a fictitious stint 0.
    """
    source = Path(path).expanduser().resolve()
    with zipfile.ZipFile(source) as archive:
        names = archive.namelist()
        if "session.json" not in names:
            raise ValueError("Expected a session.json at the root of the RCZ archive")
        session = json.loads(archive.read("session.json"))
        if not isinstance(session, dict):
            raise ValueError("Invalid RaceChrono session.json object")
        raw_laps = session.get("laps") or []
        if not isinstance(raw_laps, list):
            raise ValueError("Invalid RaceChrono laps list")
        counts: Counter[int] = Counter()
        for lap in raw_laps:
            counts[int(lap.get("sessionResume", 0) or 0)] += 1
        # Use actual channel presence, not just sessionResume in session.json.
        # TrackTelemetryConverter expects channel streams under resume_N/.
        recorded: set[int] = set()
        for name in names:
            if name.startswith("channel_") and name.endswith("_1_1"):
                recorded.add(0)
                continue
            match = re.fullmatch(r"resume_(\d+)/channel_.*_1_1", name)
            if match:
                recorded.add(int(match.group(1)))
        return [
            {"stint": stint, "lap_count": counts[stint]}
            for stint in sorted(recorded)
        ]


def inspect_rcz_devices(path: str | Path) -> list[dict[str, Any]]:
    """Inventory logger devices and native acquisition clocks for each stint.

    Only metadata and timestamp channels are decoded. Model IDs are RaceChrono
    codes, not evidence of a particular hardware brand. Rates refer to the
    source files, not to the Converter's resampled GPS-aligned output.
    """
    source = Path(path).expanduser().resolve()
    roles = {1: "gps", 2: "accelerometer", 3: "gyroscope", 12: "can_obd"}
    known = {
        1: {"gps_latitude_deg": "3_1", "gps_speed_kmh": "4_0"},
        2: {"lat_g": "10_0", "long_g": "9_0", "vert_g": "11_0"},
        3: {"yaw_rate_dps": "14_0"},
    }

    def rate_and_count(archive: zipfile.ZipFile, name: str) -> tuple[int, float | None]:
        timestamps = np.frombuffer(archive.read(name), dtype="<i8")
        if len(timestamps) < 2:
            return len(timestamps), None
        positive = np.diff(timestamps)
        positive = positive[positive > 0]
        return (
            len(timestamps),
            float(1000 / np.median(positive)) if len(positive) else None,
        )

    inventories: list[dict[str, Any]] = []
    with zipfile.ZipFile(source) as archive:
        names = set(archive.namelist())
        for desc in discover_rcz_stints(source):
            stint = desc["stint"]
            prefix = "" if stint == 0 else f"resume_{stint}/"
            key = prefix + "sessionfragment.json"
            if key not in names:
                inventories.append({
                    "stint": stint,
                    "primary_gps_device_id": None,
                    "devices": [],
                    "warning": "Missing sessionfragment.json device metadata",
                })
                continue
            fragment = json.loads(archive.read(key))
            primary = fragment.get("primaryGpsDeviceIndex")
            devices: list[dict[str, Any]] = []
            for raw in fragment.get("devices2", []):
                selector = raw.get("selector", {})
                device_type = selector.get("type")
                device_id = selector.get("id")
                if not isinstance(device_type, int) or not isinstance(device_id, int):
                    continue
                is_primary = device_type == 1 and device_id == primary
                basename = f"channel_{device_type}_{device_id}_0_"
                channels = known.get(device_type, {})
                native_rates: dict[str, Any] = {}
                ts_name = prefix + basename + "1_1"
                if device_type == 12:
                    # CAN PIDs have independent rates, not one device Hz.
                    pid_prefix = prefix + f"channel_12_{device_id}_"
                    for item in sorted(names):
                        if not (item.startswith(pid_prefix) and item.endswith("_1_1")):
                            continue
                        pid = item[len(pid_prefix):-4]
                        count, hz = rate_and_count(archive, item)
                        native_rates[f"pid_{pid}"] = {"samples": count, "rate_hz": hz}
                    sample_count, rate = 0, None
                elif ts_name in names:
                    sample_count, rate = rate_and_count(archive, ts_name)
                else:
                    sample_count, rate = 0, None
                devices.append({
                    "type": device_type,
                    "device_id": device_id,
                    "model_code": selector.get("model"),
                    "role": roles.get(device_type, "other"),
                    "is_primary_gps": is_primary,
                    "timestamp_samples": sample_count,
                    "native_sample_rate_hz": rate,
                    "recorded_channels": [
                        name for name, suffix in channels.items()
                        if prefix + basename + suffix in names
                    ],
                    "native_can_pid_rates": native_rates if device_type == 12 else {},
                })
            inventories.append({
                "stint": stint,
                "primary_gps_device_id": primary,
                "imu_accel_device_id": fragment.get("imuAccDevice"),
                "imu_gyro_device_id": fragment.get("imuGyroDevice"),
                "devices": devices,
            })
    return inventories


def load_all_rcz_stints(path: str | Path) -> TelemetrySession:
    """Load all RCZ stints onto one monotonic wall-clock-relative time axis.

    The per-stint converter uses a local time origin and renumbers laps. We
    shift channels and lap boundaries by the real recorder epoch and prefer
    RaceChrono's original lap numbers for stable all-day selection. Non-timed
    synthetic out laps receive negative IDs to avoid collisions.
    """
    source = Path(path).expanduser().resolve()
    stints = discover_rcz_stints(source)
    if not stints:
        raise ValueError(f"RCZ file contains no recorded stints: {source.name}")

    parts: list[tuple[int, int, TelemetrySession]] = []
    for description in stints:
        stint = description["stint"]
        session = load_rcz(source, target_stint=stint)
        origin_ms = session.metadata.get("timeOriginEpochMs")
        if origin_ms is None:
            raise ValueError(f"Missing recorder epoch for stint {stint}")
        parts.append((stint, int(origin_ms), session))

    first_origin_ms = min(origin for _, origin, _ in parts)
    original_counts: Counter[int] = Counter(
        lap.original_number
        for _, _, session in parts
        for lap in session.laps
        if lap.original_number is not None
    )
    used_numbers: set[int] = set()
    laps: list[Lap] = []
    series: dict[str, list[ChannelSeries]] = {}
    stint_info: list[dict[str, Any]] = []

    for stint, origin_ms, session in parts:
        offset_s = (origin_ms - first_origin_ms) / 1000.0
        active_channels = [
            channel for channel in session.channels.values() if len(channel.timestamps)
        ]
        if not active_channels:
            raise ValueError(f"RCZ stint {stint} has no usable channel samples")
        stint_info.append(
            {
                "stint": stint,
                "time_origin_epoch_ms": origin_ms,
                "start_s": offset_s + min(ch.timestamps[0] for ch in active_channels),
                "end_s": offset_s + max(ch.timestamps[-1] for ch in active_channels),
                "lap_count": len(session.laps),
                "timed_lap_count": sum(lap.is_timed for lap in session.laps),
            }
        )
        lap_id_map: dict[int, int] = {}
        for lap in session.laps:
            original = lap.original_number
            if original is not None and original > 0 and original_counts[original] == 1:
                number = original
            elif original is not None:
                # A stitched or imported archive can restart numbering per stint.
                # In that case, preserve the source number separately and expose
                # an unambiguous composite selector instead.
                number = (stint + 1) * 1_000_000 + original
            else:
                number = -((stint + 1) * 1_000_000 + lap.number)
            if number in used_numbers:
                raise ValueError(f"Duplicate normalized lap ID {number}")
            used_numbers.add(number)
            lap_id_map[lap.number] = number
            laps.append(
                Lap(
                    number=number,
                    label=str(original) if original is not None else lap.label,
                    kind=lap.kind,
                    start_s=lap.start_s + offset_s,
                    end_s=lap.end_s + offset_s,
                    duration_s=lap.duration_s,
                    original_number=original,
                    stint=stint,
                )
            )
        for name, channel in session.channels.items():
            values = channel.values.copy()
            if name == out.LAP_NUMBER:
                # The converter's Lap Number channel contains local stint
                # indices. Map it to the same public IDs as session.laps.
                for local_number, global_number in lap_id_map.items():
                    values[channel.values == float(local_number)] = float(global_number)
            series.setdefault(name, []).append(
                ChannelSeries(
                    name,
                    channel.units,
                    channel.timestamps + offset_s,
                    values,
                )
            )

    channels: dict[str, ChannelSeries] = {}
    for name, components in series.items():
        timestamps = np.concatenate([component.timestamps for component in components])
        values = np.concatenate([component.values for component in components])
        order = np.argsort(timestamps, kind="stable")
        channels[name] = ChannelSeries(
            name, components[0].units, timestamps[order], values[order]
        )

    metadata = dict(parts[0][2].metadata)
    metadata.update(
        {
            "timeOriginEpochMs": first_origin_ms,
            "stint_count": len(stint_info),
            "stints": stint_info,
        }
    )
    metadata["device_summary_by_stint"] = inspect_rcz_devices(source)
    for source_key in (
        "gps_source",
        "lateral_accel_source",
        "longitudinal_accel_source",
        "vertical_accel_source",
        "yaw_rate_source",
    ):
        sources = {
            stint: str(session.metadata.get(source_key, "unknown"))
            for stint, _, session in parts
        }
        metadata[f"{source_key}_by_stint"] = sources
        if len(set(sources.values())) != 1:
            # Do not claim a single sensor/provenance for a mixed day.
            metadata[source_key] = "mixed_or_unknown"
    metadata["channel_provenance_by_stint"] = {
        stint: {
            name: (
                session.metadata.get("gps_source", "unknown")
                if name in {
                    out.GPS_LATITUDE_DEG,
                    out.GPS_LONGITUDE_DEG,
                    out.GPS_HEADING_DEG,
                    out.SPEED_KMH,
                }
                else session.metadata.get("lateral_accel_source", "unknown")
                if name == out.LAT_G
                else session.metadata.get("longitudinal_accel_source", "unknown")
                if name == out.LONG_G
                else session.metadata.get("yaw_rate_source", "unknown")
                if name == out.YAW_RATE_DPS
                else "rcz_can_obd_or_derived"
            )
            for name in session.channels
        }
        for stint, _, session in parts
    }

    laps.sort(key=lambda lap: (lap.start_s, lap.end_s))
    return TelemetrySession(
        session_id=source.stem,
        source=str(source),
        metadata=metadata,
        laps=laps,
        channels=channels,
    )
