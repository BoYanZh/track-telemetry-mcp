"""Virtual sums must use all measured sectors without claiming a continuous lap."""
import pytest
from test_plot_reports import _session

from track_telemetry.debrief import build_debrief


def test_complementary_fast_sectors_make_a_virtual_not_an_actual_best(tmp_path):
    evidence = build_debrief([_session(20, n=601), _session(20, warped=True, n=601)],
                             tmp_path, same_layout_confirmed=True, plots=False)["evidence"]
    analysis = evidence["mini_sector_analysis"]
    result = analysis["combined"]
    assert len(analysis["rows"]) == 2
    assert all(len(row["sectors"]) == 20 for row in analysis["rows"])
    for row in analysis["rows"]:
        assert sum(s["duration_s"] for s in row["sectors"]) == pytest.approx(row["lap_time_s"])
    assert result["virtual_best_s"] == pytest.approx(sum(w["duration_s"] for w in result["winners"]))
    assert result["virtual_best_s"] < result["best_whole_lap_s"]
    assert {w["session"] for w in result["winners"]} == {0, 1}
    assert len(result["transitions"]) == 20
    assert any(t["changed_source"] for t in result["transitions"])
    assert result["second_fastest_composite_s"] >= result["virtual_best_s"]


def test_layout_gate_and_single_lap_do_not_invent_samples(tmp_path):
    missing = build_debrief([_session()], tmp_path / "no", plots=False)["evidence"]
    assert "mini_sector_analysis" not in missing
    evidence = build_debrief([_session()], tmp_path / "yes", plots=False,
                             same_layout_confirmed=True)["evidence"]
    result = evidence["mini_sector_analysis"]["combined"]
    assert result["virtual_best_s"] == pytest.approx(20)
    assert result["second_fastest_composite_s"] is None
    assert all(w["near_best_count"] == 1 for w in result["winners"])


def test_local_fast_sector_on_slow_whole_lap_remains_eligible(tmp_path):
    from test_debrief import _mixed_pace_session

    from track_telemetry.channels import GPS_LATITUDE_DEG, GPS_LONGITUDE_DEG

    session = _mixed_pace_session()
    lap = session.lap(3)
    warped = _session(23, warped=True, n=601)
    for name in (GPS_LATITUDE_DEG, GPS_LONGITUDE_DEG):
        channel = session.channels[name]
        mask = (channel.timestamps >= lap.start_s) & (channel.timestamps <= lap.end_s)
        channel.values[mask] = warped.channels[name].values
    evidence = build_debrief([session], tmp_path, same_layout_confirmed=True, plots=False)["evidence"]
    audit = next(lap for lap in evidence["sessions"][0]["lap_selection"] if lap["lap"] == 3)
    assert not audit["coaching_eligible"]
    assert any(w["lap"] == 3 for w in evidence["mini_sector_analysis"]["combined"]["winners"])


def test_boundary_speed_does_not_bridge_missing_values():
    from track_telemetry.mini_sectors import _speed

    profile = [{"progress": 0., "lap_a_speed_kmh": 100.},
               {"progress": .5, "lap_a_speed_kmh": None},
               {"progress": 1., "lap_a_speed_kmh": 120.}]
    assert _speed(profile, .5) is None
    assert _speed(profile, .75) is None


def test_ranked_deficits_cover_sectors_outside_gross_top_three():
    from track_telemetry.mini_sectors import _reduce

    def row(lap, slow_sector):
        sectors = [{"sector": i + 1, "duration_s": 4. if i == slow_sector else 5.,
                    "eligible": True, "entry_speed_kmh": None, "exit_speed_kmh": None}
                   for i in range(20)]
        return {"session": 0, "lap": lap, "stint": 0, "whole_lap_eligible": True,
                "lap_time_s": float(sum(s["duration_s"] for s in sectors)),
                "sectors": sectors, "alignment_quality": {}}
    baseline, donor = row(1, -1), row(2, 6)
    donor["sectors"][6]["duration_s"] = 4.
    for i in (0, 1, 2):
        donor["sectors"][i]["duration_s"] = 6.
    donor["lap_time_s"] = float(sum(s["duration_s"] for s in donor["sectors"]))
    combined = _reduce([baseline, donor])
    assert len(combined["ranked_best_lap_deficits"]) == 20
    assert [w["sector"] for w in combined["largest_best_lap_deficits"]] == [
        w["sector"] for w in combined["ranked_best_lap_deficits"][:3]]
    seventh = combined["ranked_best_lap_deficits"][6]
    assert seventh not in combined["largest_best_lap_deficits"]
