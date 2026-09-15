"""Standalone HTML visualization for incident-analysis JSON."""

from __future__ import annotations

import json
from importlib.resources import files
from pathlib import Path
from typing import Any, Iterable


def build_incident_player_payload(
    incident: dict[str, Any],
    *,
    clean_reference_xy: Iterable[tuple[float, float]] | None = None,
) -> dict[str, Any]:
    """Build the compact payload expected by the bundled incident player.

    ``incident`` should come from ``analyze_incident(..., include_samples=True)``.
    ``clean_reference_xy`` is optional and is only a visual reference trajectory; it is
    not treated as a track boundary.
    """
    samples = incident.get("samples")
    if not samples:
        raise ValueError(
            "Incident visualization requires samples. Call analyze_incident with "
            "include_samples=True."
        )
    return {
        "window": incident.get("window", {}),
        "summary": incident.get("summary", {}),
        "timeline": incident.get("timeline", []),
        "caveats": incident.get("caveats", []),
        "samples": samples,
        "clean_reference_xy": (
            [[float(x), float(y)] for x, y in clean_reference_xy]
            if clean_reference_xy is not None
            else []
        ),
    }


def render_incident_html(
    incident: dict[str, Any],
    *,
    title: str = "Track Telemetry Incident Player",
    clean_reference_xy: Iterable[tuple[float, float]] | None = None,
) -> str:
    payload = build_incident_player_payload(
        incident,
        clean_reference_xy=clean_reference_xy,
    )
    template = (
        files("track_telemetry")
        .joinpath("templates")
        .joinpath("incident_player.html")
        .read_text(encoding="utf-8")
    )
    return template.replace("__TITLE_JSON__", json.dumps(title)).replace(
        "__PAYLOAD_JSON__",
        json.dumps(payload, separators=(",", ":"), allow_nan=False),
    )


def write_incident_html(
    incident: dict[str, Any],
    output_path: str | Path,
    *,
    title: str = "Track Telemetry Incident Player",
    clean_reference_xy: Iterable[tuple[float, float]] | None = None,
) -> Path:
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        render_incident_html(
            incident,
            title=title,
            clean_reference_xy=clean_reference_xy,
        ),
        encoding="utf-8",
    )
    return output
