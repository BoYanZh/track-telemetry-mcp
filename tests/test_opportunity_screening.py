"""Single-sector bests must not hide losses in real adjoining intervals."""
from track_telemetry.opportunity_screening import screen_training_opportunities


def test_best_first_sector_still_has_adjoining_opportunity():
    def row(lap, times):
        return {"session": 0, "lap": lap, "whole_lap_eligible": True, "classification": "candidate_push",
                "sectors": [{"eligible": True, "duration_s": t} for t in times]}
    analysis = {"rows": [row(1, [5., 7., 7.]), row(2, [5.1, 6.5, 6.5])], "sector_count": 3,
                "combined": {"best_whole_lap_source": {"session": 0, "lap": 1}}, "near_best_tolerance_s": .1}
    scan = screen_training_opportunities(analysis)
    assert len(scan["sectors"]) == 3
    assert scan["sectors"][0]["observed_deficit_s"] == 0
    group = next(g for g in scan["contiguous_real_intervals"] if g["start_sector"] == 1 and g["end_sector"] == 3)
    assert abs(group["observed_deficit_s"] - .9) < 1e-9
    assert group["source"]["lap"] == 2
    assert scan["sectors"][0]["candidate_execution_by_session"]["0"]["count"] == 2


def test_flagged_local_interval_is_excluded_from_contiguous_donors():
    rows = [{"session": 0, "lap": number, "whole_lap_eligible": True, "classification": "unclassified_slow",
             "sectors": [{"eligible": number == 1 or index != 1, "duration_s": duration}
                         for index in range(3)]} for number, duration in [(1, 5.), (2, 1.)]]
    analysis = {"rows": rows, "sector_count": 3, "combined": {"best_whole_lap_source": {"session": 0, "lap": 1}},
                "near_best_tolerance_s": .1}
    scan = screen_training_opportunities(analysis)
    group = next(g for g in scan["contiguous_real_intervals"] if g["start_sector"] == 1 and g["end_sector"] == 3)
    assert group["source"]["lap"] == 1 and group["observed_deficit_s"] == 0
    assert scan["sectors"][0]["candidate_execution_by_session"] == {}


def test_linked_net_flags_reversed_single_sector_advantage():
    def row(lap, times):
        return {"session": 0, "lap": lap, "whole_lap_eligible": True, "classification": "candidate_push",
                "sectors": [{"eligible": True, "duration_s": t} for t in times]}
    analysis = {"rows": [row(1, [5., 5., 9.]), row(2, [5., 4., 12.])], "sector_count": 3,
                "combined": {"best_whole_lap_source": {"session": 0, "lap": 1}}, "near_best_tolerance_s": .1}
    scan = screen_training_opportunities(analysis)
    target = scan["sectors"][1]
    assert target["observed_deficit_s"] == 1.
    assert target["linked_window_reversed"]
    assert target["linked_net_s"] < 0
    assert all(entry["sector"] != 2 or entry["linked_window_reversed"]
               for entry in scan["ranked_shortlist"])


def test_wrap_intervals_cover_finish_line_boundary():
    def row(lap, times):
        return {"session": 0, "lap": lap, "whole_lap_eligible": True, "classification": "candidate_push",
                "sectors": [{"eligible": True, "duration_s": t} for t in times]}
    analysis = {"rows": [row(1, [5., 7., 7.]), row(2, [5.1, 6.5, 6.5])], "sector_count": 3,
                "combined": {"best_whole_lap_source": {"session": 0, "lap": 1}}, "near_best_tolerance_s": .1}
    scan = screen_training_opportunities(analysis)
    wraps = [g for g in scan["contiguous_real_intervals"] if g["wraps_finish_line"]]
    assert wraps
    assert all("unavailable_reason" not in g or g["start_sector"] > g["end_sector"] for g in wraps)


def test_wrap_intervals_cover_length_four_boundary():
    def row(lap, times):
        return {"session": 0, "lap": lap, "whole_lap_eligible": True, "classification": "candidate_push",
                "sectors": [{"eligible": True, "duration_s": t} for t in times]}
    analysis = {"rows": [row(1, [5., 7., 7., 7., 7.]), row(2, [5.1, 6.5, 6.5, 6.5, 6.5])], "sector_count": 5,
                "combined": {"best_whole_lap_source": {"session": 0, "lap": 1}}, "near_best_tolerance_s": .1}
    scan = screen_training_opportunities(analysis)
    fours = {(g["start_sector"], g["end_sector"]) for g in scan["contiguous_real_intervals"]
             if g["wraps_finish_line"]}
    assert {(3, 1), (4, 2), (5, 3)} <= fours
    group = next(g for g in scan["contiguous_real_intervals"]
                 if g["start_sector"] == 5 and g["end_sector"] == 3)
    assert "unavailable_reason" in group
    assert "observed_deficit_s" not in group


def test_sector_without_linked_net_is_retained_behind_netted():
    def row(lap, times, eligible):
        sectors = [{"eligible": e, "duration_s": t} for e, t in zip(eligible, times)]
        return {"session": 0, "lap": lap, "whole_lap_eligible": True, "classification": "candidate_push",
                "sectors": sectors}
    rows = [row(1, [5., 5., 5., 5.], [True, True, True, False]),
            row(2, [4., 9., 9., 9.], [True, True, True, True])]
    analysis = {"rows": rows, "sector_count": 4,
                "combined": {"best_whole_lap_source": {"session": 0, "lap": 1}}, "near_best_tolerance_s": .1}
    scan = screen_training_opportunities(analysis)
    short = scan["ranked_shortlist"]
    assert short[0]["linked_net_s"] is not None
    retained = [entry for entry in short if entry["linked_net_s"] is None]
    assert retained and retained[0]["sector"] == 1
