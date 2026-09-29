import pytest

from warhammer_agent.ingestion.handlers.visibility import top_left_bbox


def test_bottom_left_conversion_preserves_image_extent():
    assert top_left_bbox(
        {"l": 10, "t": 700, "r": 200, "b": 500, "coord_origin": "BOTTOMLEFT"}, 800
    ) == [10, 100, 200, 300]


def test_top_left_coordinates_are_unchanged():
    assert top_left_bbox(
        {"l": 10, "t": 100, "r": 200, "b": 300, "coord_origin": "TOPLEFT"}, 800
    ) == [10, 100, 200, 300]


def test_unknown_coordinates_fail():
    with pytest.raises(ValueError, match="Unknown"):
        top_left_bbox({"coord_origin": "UNKNOWN"}, 800)
