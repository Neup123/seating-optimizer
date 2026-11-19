"""The irregular room outline is a validated, portable floor constraint."""
import pytest
from pydantic import ValidationError

from seating_optimizer.models import FloorLayout, TableDrawing, VenueLayout
from seating_optimizer.room_geometry import point_inside, rectangle_inside


def floor(outline=None, *drawings):
    fields = dict(zone_id="hall", width=100, height=100, tables=list(drawings))
    if outline is not None:
        fields["room_outline"] = outline
    return FloorLayout(**fields)


def drawing(x, y, width=10, height=10):
    return TableDrawing(table_id="T1", x=x, y=y, width=width, height=height)


def test_legacy_rectangle_roundtrip_without_polygon():
    legacy = floor(None, drawing(90, 90))
    assert legacy.room_outline is None
    assert VenueLayout.model_validate(VenueLayout(floors=[legacy]).model_dump()).floors[0].room_outline is None


def test_l_shaped_room_validates_full_footprint_not_only_center():
    outline = [(0, 0), (100, 0), (100, 40), (40, 40), (40, 100), (0, 100)]
    assert floor(outline, drawing(10, 70)).room_outline == outline
    assert floor(outline, drawing(70, 10)).room_outline == outline
    assert point_inside((25, 50), outline)
    assert not point_inside((65, 65), outline)
    assert not rectangle_inside(outline, 35, 35, 10, 10)
    with pytest.raises(ValidationError, match="outside room outline"):
        floor(outline, drawing(35, 35, 10, 10))
    with pytest.raises(ValidationError, match="outside room outline"):
        floor(outline, drawing(55, 55))
    assert floor(outline, drawing(0, 0, 40, 40))


@pytest.mark.parametrize("outline,reason", [
    ([(0, 0), (100, 100)], "between 3 and 100"),
    ([(0, 0), (50, 50), (100, 100)], "nonzero area"),
    ([(0, 0), (100, 0), (100, 100), (0, 100), (10, -1)], "outside floor"),
    ([(0, 0), (100, 100), (0, 100), (100, 0)], "nonzero area|cross"),
    ([(0, 0), (100, 0), (100, 0), (0, 100)], "repeated"),
    ([(0, 0), (100, 0), (90, 90), (0, 100), (50, 0)], "cross or touch"),
])
def test_invalid_outlines_rejected(outline, reason):
    with pytest.raises(ValidationError, match=reason):
        floor(outline)


def test_polygon_and_tables_survive_layout_json_roundtrip():
    outline = [(0, 0), (95, 0), (95, 80), (0, 80)]
    portable = VenueLayout(floors=[floor(outline, drawing(20, 20))]).model_dump_json()
    restored = VenueLayout.model_validate_json(portable)
    assert restored.floors[0].room_outline == outline
    assert restored.floors[0].tables[0].x == 20


def test_self_crossing_nonzero_area_polygon_is_rejected():
    polygon = [(0, 0), (100, 0), (20, 80), (80, 80), (0, 40)]
    with pytest.raises(ValidationError, match="cross or touch"):
        floor(polygon)
