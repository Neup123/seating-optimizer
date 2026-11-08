"""Vector PDF/SVG exports: per-floor page counts and exact table membership."""
from __future__ import annotations

from io import BytesIO
from xml.etree import ElementTree

import pytest
from pypdf import PdfReader

from seating_optimizer import (
    Assignment, FloorLayout, Plan, TableDrawing, TableUsage, VenueLayout,
    render, render_floor_pdf, render_floor_svg, render_table_cards_pdf,
)


def example_plan():
    layout = VenueLayout(floors=[
        FloorLayout(zone_id="ground", width=500, height=340, tables=[
            TableDrawing(table_id="G1", x=20, y=20, width=180, height=130, shape="rectangle"),
            TableDrawing(table_id="G2", x=240, y=20, width=180, height=130, shape="ellipse"),
        ]),
        FloorLayout(zone_id="upper", width=500, height=340, tables=[
            TableDrawing(table_id="U1", x=100, y=100, width=200, height=200, shape="circle"),
        ]),
    ])
    return Plan(
        session_id="example",
        status="feasible", total_score=0,
        tables=[TableUsage(table_id="G1", zone_id="ground", capacity=4,
                           occupied=2, empty_seats=2),
                TableUsage(table_id="G2", zone_id="ground", capacity=6,
                           occupied=0, empty_seats=6),
                TableUsage(table_id="U1", zone_id="upper", capacity=2,
                           occupied=2, empty_seats=0)],
        assignments=[
            Assignment(group_id="family-red", table_id="G1", guest_ids=["g1", "g2"],
                       guest_names=["Alice Red", "Bob Red"]),
            Assignment(group_id="family-blue", table_id="U1", guest_ids=["g3", "g4"],
                       guest_names=["Cara Blue", "Dan Blue"]),
        ], layout=layout,
    )


def read_pdf(pdf: bytes) -> PdfReader:
    assert pdf.startswith(b"%PDF-")
    return PdfReader(BytesIO(pdf))


def test_floor_svg_one_page_per_zone_with_correct_groups_on_drawings():
    plan = example_plan()
    result = render_floor_svg(plan)
    assert len(result.pages) == 2
    assert [page.zone_id for page in result.pages] == ["ground", "upper"]
    ns = {"svg": "http://www.w3.org/2000/svg"}
    expected = {"G1": "family-red", "G2": None, "U1": "family-blue"}
    for page in result.pages:
        root = ElementTree.fromstring(page.svg)
        assert root.attrib["data-zone-id"] == page.zone_id
        for drawing in root.findall(".//svg:g", ns):
            table_id = drawing.attrib["data-table-id"]
            group_ids = [node.attrib["data-group-id"] for node in
                         drawing.findall("svg:text[@data-group-id]", ns)]
            assert group_ids == ([expected[table_id]] if expected[table_id] else [])
            assert any(node.tag.rsplit("}", 1)[-1] in ("rect", "ellipse")
                       for node in drawing)
    assert "family-blue" not in result.pages[0].svg
    assert "family-red" not in result.pages[1].svg


def test_floor_pdf_exactly_one_vector_page_per_floor_and_right_members():
    reader = read_pdf(render_floor_pdf(example_plan()))
    assert len(reader.pages) == 2
    ground_text, upper_text = (page.extract_text() for page in reader.pages)
    assert "Table" not in ground_text  # Drawing labels use bare table IDs.
    assert all(item in ground_text for item in ("Floor: ground", "G1", "G2", "family-red"))
    assert "family-blue" not in ground_text
    assert all(item in upper_text for item in ("Floor: upper", "U1", "family-blue"))
    assert "family-red" not in upper_text


def test_card_pdf_exactly_one_card_per_table_and_no_other_families():
    reader = read_pdf(render_table_cards_pdf(example_plan()))
    assert len(reader.pages) == 3
    for page, table, member, unrelated in [
        (reader.pages[0], "G1", "family-red", "family-blue"),
        (reader.pages[1], "G2", "No assigned groups", "family-red"),
        (reader.pages[2], "U1", "family-blue", "family-red"),
    ]:
        text = page.extract_text()
        assert f"Table {table}" in text
        assert member in text
        assert unrelated not in text
    assert "Alice Red" in reader.pages[0].extract_text()
    assert "Bob Red" in reader.pages[0].extract_text()


def test_render_registry_exposes_all_phase2_formats_without_http():
    plan = example_plan()
    assert '"zone_id": "ground"' in render(plan, "floor-map-svg")
    assert render(plan, "floor-map-pdf").startswith(b"%PDF-")
    assert render(plan, "table-cards-pdf").startswith(b"%PDF-")
    assert render(plan, "json") == plan.model_dump_json(indent=2)


def test_incomplete_layout_never_silently_drops_tables_or_groups():
    plan = example_plan()
    plan.layout.floors[0].tables.pop()
    with pytest.raises(ValueError, match="Missing floor layout positions.*G2"):
        render_floor_svg(plan)
    with pytest.raises(ValueError, match="Missing floor layout positions"):
        render_floor_pdf(plan)
    plan.layout = None
    with pytest.raises(ValueError, match="requires plan.layout"):
        render_floor_svg(plan)
    plan.status = "infeasible"
    with pytest.raises(ValueError, match="feasible"):
        render_table_cards_pdf(plan)
