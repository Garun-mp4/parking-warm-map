import cv2
import numpy as np
import pytest
from backend.heatmap import color, composite, field, signature


def slot(value, x0=0.1, x1=0.4):
    return {"points": [[x0, 0.2], [x1, 0.2], [x1, 0.8], [x0, 0.8]], "occupancy": value}


def test_zero_is_visible_blue_unknown_is_hatched_and_driveway_is_unpainted():
    rgba = field(signature([slot(0), slot(None, 0.6, 0.9)]), 200, 120)
    assert tuple(rgba[60, 50, :3]) == color(0)
    assert rgba[60, 50, 3] > 200
    assert np.all(rgba[:, 95:105, 3] == 0)
    assert np.all(rgba[:20, :, 3] == 0)
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
    assert color(0) == (32, 79, 219)
    assert color(100) == (237, 35, 68)
    assert color(100, "warm") == (165, 29, 45)
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
