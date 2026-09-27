"""Adapter from BoYanZh/TrackTelemetryConverter into the normalized session model."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from . import channels as out
from .models import ChannelSeries, Lap, TelemetrySession


def _motec_dependencies():
    try:
        from motec_log_generator import channels as mc
        from motec_log_generator.log import DataLog
    except ImportError as exc:
        raise RuntimeError(
            "RCZ support requires TrackTelemetryConverter (motec-log-generator package). Install with: "
            "pip install -e '.[rcz]'"
        ) from exc
    return mc, DataLog


def _channel_map(mc: Any) -> dict[str, str]:
    return {
        mc.CH_GROUND_SPEED: out.SPEED_KMH,
        mc.CH_CG_ACCEL_LAT: out.LAT_G,
        mc.CH_CG_ACCEL_LON: out.LONG_G,
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
    """Parse an RCZ archive using TrackTelemetryConverter and normalize its useful channels."""
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
