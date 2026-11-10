"""Phase 2 core layout validation, round trips and annotated draft conversion."""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from seating_optimizer import (
    FloorLayout, Guest, Problem, Table, TableDrawing, VenueLayout, Zone,
    import_layout, import_layout_files, solve,
)


def sample():
    zones = [Zone(id="ground", name="Ground"), Zone(id="upper", name="Upper")]
    tables = [Table(id="G1", zone_id="ground", capacity=4),
              Table(id="G2", zone_id="ground", capacity=5),
              Table(id="U1", zone_id="upper", capacity=3)]
    layout = VenueLayout(floors=[
        FloorLayout(zone_id="ground", width=500, height=320, tables=[
            TableDrawing(table_id="G1", x=20, y=30, width=190, height=130, shape="rectangle"),
            TableDrawing(table_id="G2", x=250, y=40, width=160, height=160, shape="circle"),
        ]),
        FloorLayout(zone_id="upper", width=500, height=320, tables=[
            TableDrawing(table_id="U1", x=40, y=60, width=190, height=130, shape="ellipse"),
        ]),
    ])
    return zones, tables, layout


def test_layout_round_trip_geometry_and_optional_position():
    zones, tables, layout = sample()
    loaded = import_layout(layout.model_dump_json().encode(), "floors.json",
                           zones=zones, tables=tables)
    assert loaded == layout
    assert loaded.model_dump(mode="json") == layout.model_dump(mode="json")
    assert loaded.floors[0].tables[1].shape == "circle"
    problem = Problem(session_id="meal", zones=zones, tables=tables,
                      guests=[Guest(id="a", name="Alice")], layout=loaded)
    assert problem.model_dump_json() and problem.layout == layout
    # Layout is optional; existing Phase 1 programs and data remain valid.
    assert Problem(session_id="meal", zones=zones, tables=tables,
                   guests=[Guest(id="a", name="Alice")]).layout is None


def test_annotated_svg_draft_conversion_and_merge_two_floors():
    zones, tables, _ = sample()
    ground_svg = b'''<svg xmlns="http://www.w3.org/2000/svg" data-zone-id="ground"
      viewBox="0 0 500 320">
      <g data-table-id="G1"><rect x="20" y="30" width="190" height="130"/><text>G1</text></g>
      <g data-table-id="G2"><circle cx="330" cy="120" r="80"/><text>G2</text></g>
      </svg>'''
    upper_svg = b'''<svg data-zone-id="upper" viewBox="0 0 500 320">
      <g data-table-id="U1"><ellipse cx="135" cy="125" rx="95" ry="65"/>
        <text>U1</text></g></svg>'''
    single = import_layout(ground_svg, "ground.svg", zones=zones, tables=tables)
    assert len(single.floors) == 1
    assert single.floors[0].tables[1].shape == "circle"
    assert single.floors[0].tables[1].x == 250
    whole = import_layout_files([("ground.svg", ground_svg), ("upper.svg", upper_svg)],
                                zones=zones, tables=tables)
    assert len(whole.floors) == 2
    assert whole.floors[1].tables[0].shape == "ellipse"
    assert import_layout(whole.model_dump_json().encode(), "combined.json") == whole


@pytest.mark.parametrize("shape,dimensions", [
    ("circle", {"width": 40, "height": 50}),
    ("rectangle", {"width": -1, "height": 30}),
    ("rectangle", {"width": 30, "height": 0}),
])
def test_reject_invalid_geometry(shape, dimensions):
    with pytest.raises(ValidationError):
        TableDrawing(table_id="X", x=0, y=0, shape=shape, **dimensions)


def test_bounds_duplicates_and_reference_errors():
    zones, tables, layout = sample()
    with pytest.raises(ValidationError, match="exceeds floor bounds"):
        FloorLayout(zone_id="ground", width=100, height=100, tables=[
            TableDrawing(table_id="G1", x=90, y=0, width=20, height=50)
        ])
    with pytest.raises(ValidationError, match="Duplicate table drawing"):
        FloorLayout(zone_id="ground", width=400, height=300, tables=[
            TableDrawing(table_id="G1", x=5, y=5, width=60, height=50),
            TableDrawing(table_id="G1", x=100, y=5, width=60, height=50),
        ])
    with pytest.raises(ValidationError, match="across floors"):
        VenueLayout(floors=[
            FloorLayout(zone_id="ground", width=500, height=320,
                        tables=[TableDrawing(table_id="G1", x=1, y=1, width=80, height=70)]),
            FloorLayout(zone_id="upper", width=500, height=320,
                        tables=[TableDrawing(table_id="G1", x=1, y=1, width=80, height=70)]),
        ])
    wrong = VenueLayout(floors=[FloorLayout(zone_id="upper", width=500, height=320,
        tables=[TableDrawing(table_id="G1", x=10, y=10, width=100, height=100)])])
    with pytest.raises(ValueError, match="belongs to ground"):
        Problem(session_id="x", zones=zones, tables=tables,
                guests=[Guest(id="a", name="Alice")], layout=wrong)
    with pytest.raises(ValueError, match="unknown table"):
        import_layout(VenueLayout(floors=[FloorLayout(zone_id="ground", width=400, height=200,
             tables=[TableDrawing(table_id="no-such-table", x=0, y=0, width=80, height=80)])]
             ).model_dump_json().encode(), "layout.json", zones=zones, tables=tables)


def test_draft_rejects_untrusted_transform_mismatch_and_malicious_xml():
    with pytest.raises(ValueError, match="transforms"):
        import_layout(b'<svg data-zone-id="ground" viewBox="0 0 200 200">'
                      b'<g transform="translate(20)" data-table-id="G1">'
                      b'<rect width="50" height="50"/></g></svg>', "draft.svg")
    with pytest.raises(ValueError, match="text label"):
        import_layout(b'<svg data-zone-id="ground" viewBox="0 0 200 200">'
                      b'<g data-table-id="G1"><rect width="50" height="50"/>'
                      b'<text>G2</text></g></svg>', "draft.svg")
    with pytest.raises(ValueError, match="Invalid or unsafe"):
        import_layout(b'<!DOCTYPE svg [<!ENTITY a SYSTEM "file:///etc/passwd">]>'
                      b'<svg data-zone-id="ground" viewBox="0 0 200 200">'
                      b'<g data-table-id="G1"><rect width="50" height="50"/>'
                      b'<text>&a;</text></g></svg>', "draft.svg")
    with pytest.raises(ValueError, match="Supported venue layout"):
        import_layout(b"data", "draft.png")


def test_layout_survives_real_solve():
    zones, tables, layout = sample()
    plan = solve(Problem(session_id="meal", zones=zones, tables=tables,
        guests=[Guest(id="a", name="Alice")], layout=layout))
    assert plan.status in ("feasible", "optimal")
    assert plan.layout == layout


def test_layout_round_trip_carries_small_group_priority_metadata():
    _, _, original = sample()
    original.floors[0].tables[0].small_group_priority = True
    loaded = import_layout(original.model_dump_json().encode(), "layout.json")
    assert loaded.floors[0].tables[0].small_group_priority
    svg = (b'<svg data-zone-id="ground" viewBox="0 0 200 150">'
           b'<g data-table-id="T1" data-small-group-priority="true">'
           b'<rect x="10" y="10" width="80" height="60"/><text>T1</text></g></svg>')
    imported = import_layout(svg, "floor.svg")
    assert imported.floors[0].tables[0].small_group_priority
