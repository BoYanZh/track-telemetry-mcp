"""Official corner labels should enrich report locations without replacing diagnoses."""
import sys
from types import ModuleType

from test_plot_reports import _session

from track_telemetry.coaching_report import render_report
from track_telemetry.debrief import build_debrief
from track_telemetry.external_report import render_external_scan
from track_telemetry.next_session_report import render_next_session


def _install_matcher(monkeypatch, *, match_status="matched", section_status="matched"):
    calls = []
    module = ModuleType("track_telemetry.corner_catalog")

    def match_lap(session, lap_number, layout_id=None):
        calls.append(("lap", session, lap_number, layout_id))
        if match_status == "matched":
            return {"status": "matched", "layout_id": "synthetic-east", "name": "Synthetic East",
                    "layout_name": "Synthetic East", "quality": {"confidence": "high"},
                    "provenance": {"source": "synthetic fixture"}}
        return {"status": match_status, "reason": "Insufficient identifying GPS shape",
                "candidates": [{"layout_id": "synthetic-east", "name": "Synthetic East"}]}

    def locate_section(match, start_progress, end_progress):
        calls.append(("section", start_progress, end_progress))
        return {"status": section_status, "label": "T14–T15", "corner_ids": ["east:T14", "east:T15"],
                "official_names": ["T14", "T15"], "role": "location_only"}

    module.match_lap = match_lap
    module.locate_section = locate_section
    monkeypatch.setitem(sys.modules, "track_telemetry.corner_catalog", module)
    return calls


def _coaching_for(observation_id):
    return {
        "summary": "Review the measured section before choosing a driving change.",
        "hypotheses": [{"observation_ids": [observation_id],
                        "explanation": "Driver-authored cause hypothesis remains unchanged.",
                        "confidence": "low", "confounders": ["Line and timing remain unresolved"]}],
        "sections": [{"observation_id": observation_id,
                      "title": "A · Driver-authored finding title",
                      "what_happened": "Driver-authored measured finding."}],
        "experiments": [],
        "validation_plan": "Repeat the same pace and compare the shared markers.",
        "language": "en",
    }


def test_reference_match_labels_profile_and_external_windows_in_reports(tmp_path, monkeypatch):
    calls = _install_matcher(monkeypatch)
    driver, faster = _session(21., warped=True, n=601), _session(20., n=601)
    evidence = build_debrief([driver, faster], tmp_path / "own", same_layout_confirmed=True,
                             plots=False)["evidence"]

    assert evidence["reference"]["session"] == 1
    assert evidence["track_location"]["status"] == "matched"
    assert evidence["track_location"]["layout_id"] == "synthetic-east"
    assert calls[0][0:1] == ("lap",)
    assert calls[0][1] is faster
    losses = [o for o in evidence["observations"] if "sector" in o]
    assert losses
    assert all(o["corner_location"]["label"] == "T14–T15" for o in losses)

    observation_id = losses[0]["id"]
    markdown, document = render_report(evidence, _coaching_for(observation_id))
    assert "Official corner: T14–T15" in document
    assert "Official corner: T14–T15" in markdown
    assert "Driver-authored finding title" in document and "Driver-authored finding title" in markdown
    assert "Driver-authored cause hypothesis remains unchanged." in document
    assert "S01 · T14–T15" not in document  # own-lap sections use A/B/C metadata, not external S labels

    plan = {key: "Keep this driver-authored plan text." for key in
            ("location", "why", "action", "keep_fixed", "success", "abort", "review_next")}
    plan.update(observation_ids=[observation_id], language="en")
    next_md, next_html = render_next_session(plan, evidence)
    assert "Keep this driver-authored plan text." in next_md
    assert "Keep this driver-authored plan text." in next_html
    assert "Official corner: T14–T15" in next_md
    assert "Official corner: T14–T15" in next_html

    external_calls = _install_matcher(monkeypatch)
    external_driver = _session(30., n=601)
    external_evidence = build_debrief(
        [external_driver], tmp_path / "external", reference_sessions=[_session(25., n=601)],
        plots=False)["evidence"]
    windows = external_evidence["external_reference_scan"]["windows"]
    assert any(w.get("corner_location", {}).get("status") == "matched" for w in windows)
    external_html, external_md = render_external_scan(
        external_evidence["external_reference_scan"], {}, external_evidence, False)
    import re
    external_markdown = "\n".join(external_md)
    assert re.search(r"S\d{2} · T14–T15", external_html)
    assert re.search(r"S\d{2} · T14–T15", external_markdown)
    assert external_calls[0][1] is external_driver


def test_ambiguous_or_unresolved_locations_never_publish_corner_names(tmp_path, monkeypatch):
    calls = _install_matcher(monkeypatch, match_status="ambiguous")
    ambiguous = build_debrief([_session(20., n=601)], tmp_path / "ambiguous",
                              same_layout_confirmed=True, plots=False)["evidence"]
    assert ambiguous["track_location"]["status"] == "ambiguous"
    assert not any(call[0] == "section" for call in calls)
    assert all("corner_location" not in o for o in ambiguous["observations"])

    _install_matcher(monkeypatch, section_status="unresolved")
    driver, faster = _session(21., warped=True, n=601), _session(20., n=601)
    unresolved = build_debrief([driver, faster], tmp_path / "unresolved", same_layout_confirmed=True,
                               plots=False)["evidence"]
    losses = [o for o in unresolved["observations"] if "sector" in o]
    assert losses and all(o["corner_location"]["status"] == "unresolved" for o in losses)
    assert all(o["corner_location"]["label"] == "T14–T15" for o in losses)
    markdown, document = render_report(unresolved, _coaching_for(losses[0]["id"]))
    assert "T14–T15" not in markdown and "T14–T15" not in document

