"""Internal normalized telemetry data models."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np


@dataclass(frozen=True)
class Lap:
    number: int
    label: str
    kind: str
    start_s: float
    end_s: float
    duration_s: float
    original_number: int | None = None

    @property
    def is_timed(self) -> bool:
        return self.kind.lower() == "timed"

    def to_dict(self) -> dict[str, Any]:
        return {
            "number": self.number,
            "label": self.label,
            "kind": self.kind,
            "start_s": self.start_s,
            "end_s": self.end_s,
            "duration_s": self.duration_s,
            "original_number": self.original_number,
        }


@dataclass
class ChannelSeries:
    name: str
    units: str
    timestamps: np.ndarray
    values: np.ndarray

    def __post_init__(self) -> None:
        self.timestamps = np.asarray(self.timestamps, dtype=np.float64)
        self.values = np.asarray(self.values, dtype=np.float64)
        if self.timestamps.ndim != 1 or self.values.ndim != 1:
            raise ValueError(f"Channel {self.name!r} must be one-dimensional")
        if len(self.timestamps) != len(self.values):
            raise ValueError(f"Channel {self.name!r} timestamp/value lengths differ")
        if len(self.timestamps) > 1 and np.any(np.diff(self.timestamps) < 0):
            raise ValueError(f"Channel {self.name!r} timestamps must be sorted")

    @property
    def sample_rate_hz(self) -> float | None:
        if len(self.timestamps) < 2:
            return None
        dt = np.diff(self.timestamps)
        dt = dt[np.isfinite(dt) & (dt > 0)]
        if len(dt) == 0:
            return None
        return float(1.0 / np.median(dt))

    def slice(self, start_s: float, end_s: float) -> "ChannelSeries":
        mask = (self.timestamps >= start_s) & (self.timestamps <= end_s)
        return ChannelSeries(self.name, self.units, self.timestamps[mask], self.values[mask])

    def interp(self, timestamps: np.ndarray) -> np.ndarray:
        target = np.asarray(timestamps, dtype=np.float64)
        valid = np.isfinite(self.timestamps) & np.isfinite(self.values)
        if np.count_nonzero(valid) == 0:
            return np.full_like(target, np.nan, dtype=np.float64)
        src_t = self.timestamps[valid]
        src_v = self.values[valid]
        if len(src_t) == 1:
            return np.full_like(target, src_v[0], dtype=np.float64)
        return np.interp(target, src_t, src_v, left=np.nan, right=np.nan)


@dataclass
class TelemetrySession:
    session_id: str
    source: str
    metadata: dict[str, Any] = field(default_factory=dict)
    laps: list[Lap] = field(default_factory=list)
    channels: dict[str, ChannelSeries] = field(default_factory=dict)

    def channel(self, name: str) -> ChannelSeries:
        try:
            return self.channels[name]
        except KeyError as exc:
            available = ", ".join(sorted(self.channels))
            raise KeyError(f"Missing channel {name!r}; available: {available}") from exc

    def optional_channel(self, name: str) -> ChannelSeries | None:
        return self.channels.get(name)

    def lap(self, number: int) -> Lap:
        for lap in self.laps:
            if lap.number == number:
                return lap
        raise KeyError(f"Lap {number} not found")

    def to_summary(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "source_name": self.source.rsplit("/", 1)[-1].rsplit("\\", 1)[-1],
            "metadata": self.metadata,
            "laps": [lap.to_dict() for lap in self.laps],
            "channels": {
                name: {
                    "units": ch.units,
                    "samples": int(len(ch.timestamps)),
                    "sample_rate_hz": ch.sample_rate_hz,
                    "start_s": float(ch.timestamps[0]) if len(ch.timestamps) else None,
                    "end_s": float(ch.timestamps[-1]) if len(ch.timestamps) else None,
                }
                for name, ch in sorted(self.channels.items())
            },
        }
