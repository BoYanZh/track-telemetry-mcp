import math

from track_telemetry.section_shape import section_shape, shape_sentence


def _circle(cx, cy, radius, start_deg, sweep_deg, n=60):
    """Points along a circular arc; progress increases with sample order."""
    pts = []
    for i in range(n):
        angle = math.radians(start_deg + sweep_deg * i / (n - 1))
        pts.append({"x_m": cx + radius * math.cos(angle), "y_m": cy + radius * math.sin(angle),
                    "progress": i / (n - 1)})
    return pts


def test_left_turn_is_positive_net_angle():
    shape = section_shape(_circle(0, 0, 50, 0, 90), 0.0, 1.0)
    assert shape["available"]
    assert shape["net_angle_deg"] > 0
    assert shape["label_zh"] == "左弯"


def test_right_turn_is_negative_net_angle():
    shape = section_shape(_circle(0, 0, 50, 0, -90), 0.0, 1.0)
    assert shape["net_angle_deg"] < 0
    assert shape["label_zh"] == "右弯"


def test_sharp_turn_label():
    shape = section_shape(_circle(0, 0, 20, 0, 150), 0.0, 1.0)
    assert "急弯" in shape["label_zh"]


def test_straight_section():
    pts = [{"x_m": float(i), "y_m": 0.0, "progress": i / 50} for i in range(51)]
    shape = section_shape(pts, 0.0, 1.0)
    assert shape["label_zh"] == "基本直道或缓弯"


def test_section_slice_uses_progress_bounds():
    pts = _circle(0, 0, 50, 0, 90)
    half = section_shape(pts, 0.0, 0.5)
    full = section_shape(pts, 0.0, 1.0)
    assert abs(half["net_angle_deg"]) < abs(full["net_angle_deg"])


def test_too_few_points_is_unavailable():
    assert section_shape([{"x_m": 0, "y_m": 0, "progress": 0.0}], 0.0, 1.0)["available"] is False


def test_sentence_includes_speed():
    text = shape_sentence(_circle(0, 0, 50, 0, 90), 0.0, 1.0, 88.457, True)
    assert "左弯" in text and "88km/h" in text


def test_sentence_omits_speed_when_missing():
    text = shape_sentence(_circle(0, 0, 50, 0, 90), 0.0, 1.0, None, True)
    assert "km/h" not in text


def test_sentence_is_empty_without_geometry():
    assert shape_sentence([], 0.0, 1.0, 90.0, True) == ""


def test_corner_near_bounds_is_flagged():
    """A near-straight net window that contains a sharp S-bend must say so."""
    pts, x, y, heading, progress = [], 0.0, 0.0, 0.0, 0.0

    def step(distance, turn_deg, n=12):
        nonlocal x, y, heading, progress
        for _ in range(n):
            heading += math.radians(turn_deg) / n
            x += distance / n * math.cos(heading)
            y += distance / n * math.sin(heading)
            progress += 0.001
            pts.append({"x_m": x, "y_m": y, "progress": progress})

    step(60.0, 0.0)      # straight in
    step(12.0, 80.0)     # sharp left
    step(12.0, -80.0)    # sharp right back to original heading
    step(60.0, 0.0)      # straight out
    shape = section_shape(pts, 0.0, 1.0)
    assert shape["available"]
    assert shape["local_max_turn_deg"] >= 40.0
    text = shape_sentence(pts, 0.0, 1.0, 68.0, True)
    assert "边界附近有弯" in text or "区段内" in text
