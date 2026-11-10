"""Deterministic 120-guest golden event spanning two floors."""
from __future__ import annotations

from time import perf_counter
from io import BytesIO
from xml.etree import ElementTree
from pypdf import PdfReader

from seating_optimizer import (
    FloorLayout, Guest, Problem, Rule, SolverConfig, Table, TableDrawing,
    VenueLayout, Zone, render_floor_svg, render_floor_pdf, render_table_cards_pdf, solve,
)


def golden_problem() -> Problem:
    languages = ["English", "French", "Spanish"]
    guests = []
    for family in range(60):
        for member in range(2):
            mobility = "wheelchair" if family == 7 and member == 0 else "mobile"
            guests.append(Guest(
                id=f"guest-{family:02d}-{member}",
                name=f"Guest {family:02d} member {member}",
                group_id=f"family-{family:02d}", group_name=f"family-{family:02d}",
                attributes={
                    "language": languages[family % len(languages)],
                    "age_layer": "adult" if member == 0 or family % 4 else "child",
                    "mobility": mobility,
                },
            ))
    return Problem(
        session_id="golden-120-friday-meal",
        zones=[Zone(id="ground", name="Ground floor"),
               Zone(id="first", name="First floor")],
        tables=[
            Table(id=f"G-{i}", zone_id="ground", capacity=10) for i in range(6)
        ] + [
            Table(id=f"F-{i}", zone_id="first", capacity=10) for i in range(6)
        ],
        guests=guests,
        rules=[
            Rule(id="access", shape="zone_restriction", mode="hard",
                 parameters={"attribute": "mobility", "value": "wheelchair",
                             "zone": "ground"}),
            Rule(id="language", shape="attribute_grouping", mode="soft", weight=4,
                 parameters={"attribute": "language"}),
            Rule(id="age", shape="attribute_grouping", mode="soft", weight=1,
                 parameters={"attribute": "age_layer"}),
            Rule(id="fill", shape="fill_efficiency", mode="soft", weight=2),
        ],
        layout=VenueLayout(floors=[
            FloorLayout(zone_id=zone_id, width=700, height=380, tables=[
                TableDrawing(table_id=f"{prefix}-{index}", x=20 + 220 * (index % 3),
                             y=20 + 180 * (index // 3), width=200, height=160,
                             shape="ellipse" if index % 2 else "rectangle")
                for index in range(6)
            ])
            for zone_id, prefix in (("ground", "G"), ("first", "F"))
        ]),
        config=SolverConfig(time_limit_seconds=5, workers=8, random_seed=42),
    )


def test_golden_120_guests_two_floors_solve_in_seconds():
    problem = golden_problem()
    before = perf_counter()
    plan = solve(problem)
    elapsed = perf_counter() - before
    print(f"GOLDEN_120_SOLVE_SECONDS={plan.solve_seconds:.3f} "
          f"GOLDEN_120_WALL_SECONDS={elapsed:.3f} STATUS={plan.status} "
          f"SCORE={plan.total_score}", flush=True)
    assert plan.status in ("optimal", "feasible"), (
        plan.status, plan.message, plan.conflicting_constraints
    )
    assert len(problem.guests) == 120
    assert sum(t.occupied for t in plan.tables) == 120
    assert all(t.occupied <= t.capacity and t.empty_seats == 0 for t in plan.tables)
    assert elapsed < 9.0, f"Golden case exceeded a few seconds: {elapsed:.2f}s"
    assert plan.total_score == sum(row.points for row in plan.score_breakdown)
    assert all(a.reasons for a in plan.assignments)
    assigned = {guest_id: assignment.table_id
                for assignment in plan.assignments for guest_id in assignment.guest_ids}
    assert len(assigned) == 120
    assert assigned["guest-07-0"].startswith("G-")
    assert assigned["guest-07-0"] == assigned["guest-07-1"]
    for family in range(60):
        assert assigned[f"guest-{family:02d}-0"] == assigned[f"guest-{family:02d}-1"]


def test_golden_120_guests_floor_maps_and_family_cards():
    """Solve the same 120-guest golden case and print both Phase 2 formats."""
    problem = golden_problem()
    plan = solve(problem)
    assert plan.status in ("optimal", "feasible")
    assert len(plan.assignments) == 60
    assert sum(table.occupied for table in plan.tables) == 120
    assert all(table.occupied <= table.capacity for table in plan.tables)
    assert plan.layout == problem.layout
    svg_pages = render_floor_svg(plan).pages
    assert [page.zone_id for page in svg_pages] == ["ground", "first"]
    ns = {"s": "http://www.w3.org/2000/svg"}
    found = {}
    for page in svg_pages:
        root = ElementTree.fromstring(page.svg)
        drawings = root.findall(".//s:g", ns)
        assert len(drawings) == 6
        for drawing in drawings:
            table_id = drawing.attrib["data-table-id"]
            assert table_id.startswith("G-" if page.zone_id == "ground" else "F-")
            for label in drawing.findall("s:text[@data-group-id]", ns):
                group_id = label.attrib["data-group-id"]
                assert group_id not in found
                found[group_id] = table_id
    assert found == {item.group_id: item.table_id for item in plan.assignments}
    assert found["family-07"].startswith("G-")

    floor_pdf = PdfReader(BytesIO(render_floor_pdf(plan)))
    cards = PdfReader(BytesIO(render_table_cards_pdf(plan)))
    assert len(floor_pdf.pages) == 2
    assert len(cards.pages) == len(plan.tables) == 12
    for floor, page in zip(("ground", "first"), floor_pdf.pages):
        text = page.extract_text()
        assert f"Floor: {floor}" in text
        for group in plan.assignments:
            if found[group.group_id].startswith("G-" if floor == "ground" else "F-"):
                assert group.group_id in text
            else:
                assert group.group_id not in text
    for page, table in zip(cards.pages, plan.tables):
        text = page.extract_text()
        assert f"Table {table.table_id}" in text
        for group in plan.assignments:
            if group.table_id == table.table_id:
                assert group.group_id in text
                assert all(name in text for name in group.guest_names)
            else:
                assert group.group_id not in text
    print(f"GOLDEN_120_LAYOUT_FLOORS={len(svg_pages)} "
          f"FLOOR_PDF_PAGES={len(floor_pdf.pages)} "
          f"TABLE_CARDS={len(cards.pages)} STATUS={plan.status}", flush=True)
