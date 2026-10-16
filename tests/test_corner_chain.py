"""A mini-sector is a locator; action windows use matched physical boundaries."""
import numpy as np
import pytest
from test_plot_reports import _session

from track_telemetry.corner_chain import select_chain_window


def test_upstream_brake_to_common_next_brake(monkeypatch):
    sessions = [_session(20), _session(20)]
    for session in sessions:
        session.metadata["channel_sources"] = {"brake_pressure_kpa": "can"}
    def braking(session, number):
        offset = 0 if session is sessions[0] else -.2
        return {"events": [{"start_s": start + offset, "end_s": end,
                            "control_channel": "brake_pressure_kpa"} for start, end in [(7, 9), (15, 17)]]}
    monkeypatch.setattr("track_telemetry.corner_chain.analyze_braking", braking)
    profile = [{"progress": float(p), "lap_a_elapsed_s": float(p * 20)} for p in np.linspace(0, 1, 201)]
    results = {(i, 1): {"profile": profile} for i in range(2)}
    observation = {"example_session": 0, "example_lap": 1, "section_reference": {"session": 1, "lap": 1},
                   "physical_section_profile": [{"progress": .5}, {"progress": .55}]}
    window = select_chain_window(sessions, observation, results)
    assert window["start_progress"] == pytest.approx(6.3 / 20)
    assert window["end_progress"] == pytest.approx(14.8 / 20)
    assert window["upstream_events_overlap_on_reference"]
    assert window["method"] == "braking_to_next_braking"
    for session in sessions:
        session.metadata["channel_sources"] = {}
    fallback = select_chain_window(sessions, observation, results)
    assert fallback["method"] == "fixed_context_fallback"
    assert fallback["start_progress"] == pytest.approx(.45)
    assert fallback["end_progress"] == pytest.approx(.6)
