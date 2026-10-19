import numpy as np

from track_telemetry.speed_minima import speed_minima_indices


def test_multiple_corners_preserve_measured_positions():
    speed = [120, 100, 80, 81, 80.5, 90, 110, 95, 70, 70, 80, 100]
    assert speed_minima_indices(speed) == [2, 8]


def test_noise_flat_and_boundary():
    assert speed_minima_indices([100, 99, 100, 99.5, 100]) == [1]
    assert speed_minima_indices([100, 90, 80]) == [2]
    assert speed_minima_indices([80, 80, 80]) == [0]
    assert speed_minima_indices([]) == []
    assert speed_minima_indices([90, np.nan, 80]) == []


def test_close_labels_are_separated_and_stay_inside_chart():
    from track_telemetry.speed_minima import place_label
    occupied = []
    for _ in range(6):
        place_label(580, 40, "Reference Vmin2 72.2", occupied)
    for i, a in enumerate(occupied):
        assert 0 <= a[0] < a[2] <= 600
        assert 0 <= a[1] < a[3] <= 600
        for b in occupied[:i]:
            assert a[2] < b[0] or a[0] > b[2] or a[3] < b[1] or a[1] > b[3]
