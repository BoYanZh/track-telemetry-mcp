"""Video-free unit tests for video_reverse (pure-stdlib paths only)."""

from track_telemetry.video_reverse import FourChecks, clean_speed_series, four_checks
from track_telemetry.video_reverse.clean import interp_gaps, reject_outliers
from track_telemetry.video_reverse.needle import anchors_sorted, angle_to_speed
from track_telemetry.video_reverse.scan import closure, find_windows


def test_angle_interp_and_clamp_flag():
    anchors = ((100.0, 40.0), (0.0, 90.0), (-30.0, 100.0))
    s, c = angle_to_speed(50.0, anchors)
    assert (s, c) == (65.0, False)
    s, c = angle_to_speed(200.0, anchors)
    assert c is True
    s, c = angle_to_speed(-50.0, anchors)
    assert c is True
    assert anchors_sorted(anchors)[0] == (-30.0, 100.0)


def test_cleaner_kills_isolated_and_burst_misreads():
    truth = [70.0] * 20
    series = list(truth)
    series[5] = 24.0  # isolated 7->2 style
    series[10:13] = [93.0, 93.0, 93.0]  # burst 7->9 style
    series[15] = None
    cleaned, rej, filled = clean_speed_series(series)
    assert rej >= 3
    assert all(abs(v - 70.0) <= 5 for v in cleaned)


def test_interp_edges():
    assert interp_gaps([None, None, 5.0]) == [5.0, 5.0, 5.0]
    assert interp_gaps([5.0, None, 9.0]) == [5.0, 7.0, 9.0]


def test_reject_outliers_passthrough():
    base, rej = reject_outliers([50.0, 51.0, 50.5])
    assert rej == 0 and base == [50.0, 51.0, 50.5]


def test_find_windows_and_closure():
    pts = [(t, (100.0 + (t % 10), 50.0)) for t in [i * 0.5 for i in range(60)]]
    laps = find_windows(pts, 10.0)
    assert laps and abs(laps[0][2] - 10.0) <= 1.5
    assert closure([(0.0, (1.0, 2.0)), (10.0, (1.5, 2.5))], 0.0, 10.0) < 1.0


def test_four_checks_pass_and_fail():
    rows = [{"video_t": i * 0.1, "map_x": 100 + i * 0.01, "map_y": 50.0,
             "speed_mph": 60 + i * 0.1} for i in range(20)]
    chk = four_checks(rows, anchors=[(0.5, 60.5)], title_lap_s=None,
                      vmax_band=(50.0, 70.0))
    assert isinstance(chk, FourChecks) and chk.passed
    bad = [dict(r) for r in rows]
    bad[10]["speed_mph"] = 5.0
    assert four_checks(bad).passed is False
