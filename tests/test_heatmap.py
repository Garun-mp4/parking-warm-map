import cv2
import numpy as np
import pytest
from backend.heatmap import color, composite, field, parking_rows, signature


def slot(value, x0=0.1, x1=0.4):
    return {"points": [[x0, 0.2], [x1, 0.2], [x1, 0.8], [x0, 0.8]], "occupancy": value}


def test_zero_is_visible_blue_unknown_is_hatched_and_outside_rows_is_transparent():
    rgba = field(signature([slot(0), slot(None, 0.6, 0.9)]), 200, 120)
    assert tuple(rgba[60, 50, :3]) == color(0)
    assert rgba[60, 50, 3] > 200
    assert np.all(rgba[:10, :, 3] == 0)
    assert rgba[60, 150, 3] > 100
    assert len(set(rgba[55:65, 140:160, 0].ravel())) == 2
    assert np.all(rgba[55:65, 140:160, 0] == rgba[55:65, 140:160, 1])
    assert not rgba.flags.writeable


def test_normalized_blending_does_not_invent_a_hotspot_by_summing_neighbors():
    a, b = slot(73, 0.1, 0.6), slot(73, 0.4, 0.9)
    rgba = field(signature([a, b]), 200, 120)
    known = rgba[..., 3] > 150
    assert np.max(np.abs(rgba[..., :3][known].astype(int) - color(73))) <= 1
    # A single 100% place stays red at its feathered edge, never a fabricated blue rim.
    hot = field(signature([slot(100)]), 200, 120)
    assert np.all(hot[..., :3][hot[..., 3] > 0] == color(100))


def test_palette_scale_empty_support_and_composite_alpha():
    assert color(0) == (24, 83, 235)
    assert color(100) == (240, 35, 35)
    assert color(100, "warm") == (196, 28, 28)
    empty = field((), 200, 120)
    assert not empty[..., 3].any()
    source = np.full((120, 200, 3), 90, np.uint8)
    rgba = field(signature([slot(100)]), 200, 120)
    assert np.array_equal(composite(source, rgba, 0), source)
    assert np.array_equal(composite(source, rgba)[0, 0], source[0, 0])
    assert composite(source, rgba)[60, 50, 2] > 90
    with pytest.raises(ValueError):
        field((), 200, 120, "invalid")
    with pytest.raises(ValueError):
        composite(source, rgba, 2)


def test_layer_png_keeps_alpha_channel():
    from backend.heatmap import png_layer

    encoded = png_layer([slot(100)], 200, 120)
    decoded = cv2.imdecode(np.frombuffer(encoded, np.uint8), cv2.IMREAD_UNCHANGED)
    assert decoded.shape == (120, 200, 4)
    assert decoded[0, 0, 3] == 0
    assert tuple(decoded[60, 50, :3]) == color(100)[::-1]


def test_broad_core_has_uniform_strength_independent_of_neighbor_count():
    single = field(signature([slot(73)]), 200, 120)
    duplicate = field(signature([slot(73), slot(73)]), 200, 120)
    support = single[..., 3] > 0
    assert np.mean(single[..., 3][support] >= 230) > 0.35
    assert np.array_equal(single, duplicate)
    # Corners of the expanded envelope remain clear: its caps are rounded.
    assert single[20, 5, 3] == 0
    assert single[60, 50, 3] == 255


def test_ramp_preserves_chroma_and_default_overlay_stays_clear_on_white_cars():
    # The cyan/yellow midpoint must remain saturated rather than become gray-green.
    midpoint = color(37.5)
    assert max(midpoint) - min(midpoint) >= 230
    white_car = np.full((120, 200, 3), 255, np.uint8)
    for value in (0, 50, 100):
        rgba = field(signature([slot(value)]), 200, 120)
        output = composite(white_car, rgba)
        hsv = cv2.cvtColor(output, cv2.COLOR_BGR2HSV)
        assert hsv[60, 50, 1] / 255 > 0.55
        expected = cv2.cvtColor(
            np.array([[color(value)[::-1]]], np.uint8), cv2.COLOR_BGR2HSV
        )[0, 0, 0]
        hue_error = abs(int(hsv[60, 50, 0]) - int(expected))
        assert min(hue_error, 180 - hue_error) <= 2


def test_resizing_never_blends_transparent_rgb_into_the_visible_color():
    # Blue RGB in a fully transparent pixel must not contaminate its red neighbor.
    rgba = np.array([[[240, 35, 35, 255], [0, 0, 255, 0]]], np.uint8)
    background = np.zeros((1, 9, 3), np.uint8)
    result = composite(background, rgba, 1)
    assert np.max(np.abs(result[..., 0].astype(int) - result[..., 1])) <= 1
    assert result[0, 4, 2] > result[0, 4, 0]


def test_adjacent_places_form_a_continuous_ribbon_with_exact_center_values():
    places = [slot(0, 0.1, 0.3), slot(50, 0.4, 0.6), slot(100, 0.7, 0.9)]
    rgba = field(signature(places), 300, 180)
    # The gap between ROIs belongs to this row's interpolated visualization.
    assert rgba[90, 105, 3] >= 150
    assert tuple(rgba[90, 105, :3]) == color(25)
    for x, value in ((60, 0), (150, 50), (240, 100)):
        assert tuple(rgba[90, x, :3]) == color(value)


def test_parallel_rows_keep_the_driveway_clear_and_unknown_cells_are_hatched():
    places = []
    for value, x0, x1 in ((0, 0.1, 0.3), (None, 0.4, 0.6), (100, 0.7, 0.9)):
        for y0, y1 in ((0.15, 0.35), (0.65, 0.85)):
            places.append(
                {"points": [[x0, y0], [x1, y0], [x1, y1], [x0, y1]], "occupancy": value}
            )
    rgba = field(signature(places), 300, 300)
    assert np.all(rgba[130:170, :, 3] == 0)
    assert rgba[75, 150, 3] > 100
    assert np.all(rgba[70:80, 145:155, 0] == rgba[70:80, 145:155, 1])


def test_tilted_camera_rows_and_distant_groups():
    angle = np.deg2rad(20)
    rotate = np.array([[np.cos(angle), -np.sin(angle)], [np.sin(angle), np.cos(angle)]])
    places = []
    for y in (100, 300):
        for x in (100, 200, 300):
            points = np.array(
                [[x - 25, y - 32], [x + 25, y - 32], [x + 25, y + 32], [x - 25, y + 32]]
            )
            points = ((points - 200) @ rotate.T + 200) / 400
            places.append({"points": points.tolist(), "occupancy": 73})
    axis, rows = parking_rows(signature(places), 400, 400)
    assert sorted(map(len, rows)) == [3, 3]
    assert abs(axis @ rotate[:, 0]) > 0.99
    rgba = field(signature(places), 400, 400)
    assert rgba[200, 200, 3] == 0
    midpoint = np.rint((np.array([150, 100]) - 200) @ rotate.T + 200).astype(int)
    assert rgba[midpoint[1], midpoint[0], 3] > 80
    distant = field(signature([slot(0, 0.05, 0.15), slot(100, 0.85, 0.95)]), 400, 400)
    assert not distant[:, 190:210, 3].any()
