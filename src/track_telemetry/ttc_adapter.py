"""Format dispatch through TTC, preserving its channel clocks and limitations."""

from __future__ import annotations

import contextlib
import csv
import io
from pathlib import Path

import numpy as np

from .models import ChannelSeries, Lap, TelemetrySession
from .motec_adapter import _channel_map, _motec_dependencies, load_all_rcz_stints

SUPPORTED_SUFFIXES = {".rcz", ".xrk", ".xrz", ".vbo", ".csv"}


def _csv_laps(lines: list[str]) -> tuple[list[Lap], dict]:
    """Use recorded contiguous lap labels, never TTC's whole-file timed fallback.

    CSV first/last samples are observed bounds, not beacon-quality boundaries.
    Both edge groups remain partial; only bounded interior groups are timed.
    """
    rows = list(csv.reader(lines))
    header_index = next((i for i, r in enumerate(rows) if len(r) > 2 and
                         r[0].strip().lower() in {"time", "time (s)", "timestamp"}), None)
    if header_index is None:
        raise ValueError("Not a supported RaceChrono CSV table")
    header = [h.strip().lower().replace("_", " ") for h in rows[header_index]]
    lap_col = next((i for i, h in enumerate(header) if h in {"lap", "lap number"}), None)
    if lap_col is None:
        return [], {"lap_timing_semantics": "No recorded lap labels; no timed laps inferred"}
    groups = []
    previous_time = -np.inf
    for row in rows[header_index + 1:]:
        try:
            t = float(row[0])
        except (ValueError, IndexError):
            continue
        if not np.isfinite(t) or t <= previous_time:
            raise ValueError("CSV clock must be finite and strictly increasing")
        previous_time = t
        label = row[lap_col].strip() if len(row) > lap_col else ""
        if not groups or groups[-1][0] != label:
            groups.append([label, t, t])
        else:
            groups[-1][2] = t
    laps = []
    for i, (label, start, end) in enumerate(groups):
        if not label:
            continue
        original = int(label) if label.lstrip("-").isdigit() else None
        complete = 0 < i < len(groups) - 1 and original is not None and original > 0
        # Transition timestamp is the observed next group's first sample.
        stop = groups[i + 1][1] if i + 1 < len(groups) else end
        laps.append(Lap(len(laps) + 1, label, "Timed" if complete else "Partial",
                        start, stop, stop - start, original_number=original))
    return laps, {"lap_timing_semantics": "CSV label transitions; edge groups partial; boundary uncertainty up to sample interval"}


def load_telemetry(path: str | Path) -> TelemetrySession:
    source = Path(path).expanduser().resolve()
    suffix = source.suffix.lower()
    if suffix not in SUPPORTED_SUFFIXES:
        raise ValueError(f"Unsupported telemetry format: {suffix}")
    if not source.is_file():
        raise FileNotFoundError(source)
    if suffix == ".rcz":
        return load_all_rcz_stints(source)
    mc, DataLog = _motec_dependencies()
    log = DataLog()
    log.log_file_path = str(source)
    lines = None
    # TTC prints parser diagnostics; stdout is reserved for the MCP protocol.
    diagnostics = io.StringIO()
    with contextlib.redirect_stdout(diagnostics):
        if suffix in {".xrk", ".xrz"}:
            try:
                import libxrk  # noqa: F401

                log.from_xrk_log(str(source))
            except ImportError as exc:
                raise RuntimeError("AiM XRK/XRZ requires libxrk>=0.13; install .[ttc]") from exc
        else:
            lines = source.read_text(encoding="utf-8-sig").splitlines(keepends=True)
            if suffix == ".vbo":
                log.from_vbo_log(lines)
            else:
                log.from_racechrono_log(lines)
    normalized = {}
    for raw, name in _channel_map(mc).items():
        channel = log.channels.get(raw)
        if channel is not None and len(channel.timestamps):
            normalized[name] = ChannelSeries(name, channel.units,
                                              channel.timestamps.copy(), channel.values.copy())
    if not normalized:
        raise ValueError("TTC decoded no supported telemetry channels")
    metadata = dict(log.metadata or {})
    metadata.update({
        "source_format": {".csv": "RaceChrono CSV", ".vbo": "VBOX VBO",
                          ".xrk": "AiM XRK", ".xrz": "AiM XRZ"}[suffix],
        "parser": "TrackTelemetryConverter",
        "source_channel_inventory": {name: {"units": ch.units, "samples": len(ch.timestamps)}
                                     for name, ch in log.channels.items()},
        "time_axis": "TTC seconds, preserved without per-channel rebasing",
        "recording_datetime": log.datetime.isoformat() if log.datetime else None,
        "recording_datetime_timezone": "unspecified" if log.datetime and log.datetime.tzinfo is None else "source",
        "time_origin_epoch_ms": log.time_origin_epoch_ms,
        "channel_sources": {name: "unknown" for name in normalized},
        "sampling_note": "Source file/export sampling; original device acquisition rate is unverified",
        "parser_diagnostics": diagnostics.getvalue().splitlines(),
    })
    # A CSV name alone is not proof of CAN/IMU origin. Preserve TTC's explicit
    # derived-yaw label, but do not upgrade unknown source to independent yaw.
    laps = [Lap(int(raw["lap_num"]), str(raw.get("lap_label", raw["lap_num"])),
                str(raw.get("type", "Unknown")), float(raw["start_time"]),
                float(raw["end_time"]), float(raw["duration"]),
                original_number=int(raw.get("orig_num", raw["lap_num"])),
                stint=raw.get("stint")) for raw in log.laps_info.get("laps", [])]
    if suffix == ".csv":
        laps, timing = _csv_laps(lines)
        metadata.update(timing)
        # TTC maps RaceChrono accelerator_pos/PPS to Throttle Pos. Correct
        # pedal semantics when no explicit throttle-body column exists.
        headers = [r for r in csv.reader(lines) if r and r[0].strip().lower() in {"time", "time (s)", "timestamp"}]
        if headers:
            names = {h.lower().strip().replace("_", " ") for h in headers[0]}
            if names & {"accelerator pos", "pps"}:
                if names & {"throttle pos", "throttle", "throttle position"}:
                    raise ValueError("Ambiguous mixed pedal/throttle CSV mapping in TTC; export channels separately")
                channel = normalized.pop("throttle_pct", None)
                if channel is not None:
                    channel.name = "accelerator_pct"
                    normalized[channel.name] = channel
                    metadata["channel_sources"][channel.name] = "unknown"
    elif suffix == ".vbo":
        metadata["lap_timing_semantics"] = "No lap boundaries provided by TTC VBO parser; no timed laps inferred"
    else:
        metadata["lap_timing_semantics"] = "AiM logger lap table on shared channel clock"
    return TelemetrySession(source.stem, str(source), metadata, laps, normalized)
