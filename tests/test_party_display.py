"""Regression coverage for imported party names, split portions and print surfaces."""
from __future__ import annotations

from io import BytesIO
from xml.etree import ElementTree

from pypdf import PdfReader

from seating_optimizer import (
    Assignment, FloorLayout, Guest, Plan, Problem, SolverConfig, Table,
    TableDrawing, TableUsage, VenueLayout, Zone, import_registrations, render,
    render_floor_svg, render_table_cards_pdf, render_people_list_html,
    render_table_list_html, solve,
)


def split_clan() -> Plan:
    imported = import_registrations(b"Name,Size\nHuge Clan,12\n", "clan.csv")
    assert not imported.has_errors
    assert all(g.group_name == "Huge Clan" for g in imported.guests)
    layout = VenueLayout(floors=[FloorLayout(
        zone_id="hall", width=360, height=150, tables=[
            TableDrawing(table_id="A", x=10, y=10, width=125, height=100),
            TableDrawing(table_id="B", x=155, y=10, width=125, height=100),
        ])])
    result = solve(Problem(
        session_id="dinner", zones=[Zone(id="hall", name="Hall")],
        tables=[Table(id="A", zone_id="hall", capacity=6),
                Table(id="B", zone_id="hall", capacity=6)],
        guests=imported.guests, layout=layout, config=SolverConfig(workers=1),
    ))
    assert result.status in ("feasible", "optimal"), result.conflicting_constraints
    assert {part.table_id for part in result.assignments} == {"A", "B"}
    assert all(len(part.guest_ids) == 6 for part in result.assignments)
    return result


def test_split_clan_human_surfaces_show_one_label_per_table_and_json_remains_lossless():
    plan = split_clan()
    table_text = render(plan, "table")
    assert table_text.count("Huge Clan — 6/12") == 2
    assert "registration:2" not in table_text
    assert "(7/12)" not in table_text
    assert "Group Huge Clan split across adjacent tables A, B" in table_text
    assert all(a.group_id == "registration:2" and a.group_name == "Huge Clan"
               for a in plan.assignments)
    people = render_people_list_html(plan)
    table_html = render_table_list_html(plan)
    for html in (people, table_html):
        assert html.count("Huge Clan — 6/12") == 2
        assert "Huge Clan (1/12)" not in html
        assert ">registration:2<" not in html
    root = ElementTree.fromstring(people)
    assert len(root.findall('.//tr[@data-group-id]')) == 2
    assert not root.findall('.//tr[@data-guest-id]')
    assert len(ElementTree.fromstring(table_html).findall('.//tr[@data-group-id]')) == 2
    for page in render_floor_svg(plan).pages:
        assert page.svg.count("Huge Clan — 6/12") == 2
        assert "registration:2" not in page.svg.replace('data-group-id="registration:2"', "")
    cards = PdfReader(BytesIO(render_table_cards_pdf(plan)))
    card_text = "\n".join(page.extract_text() for page in cards.pages)
    assert card_text.count("Huge Clan — 6/12") == 2
    assert "registration:2" not in card_text
    assert "(7/12)" not in card_text
    json_text = render(plan, "json")
    assert '"group_id": "registration:2"' in json_text
    assert '"group_name": "Huge Clan"' in json_text
    assert all(f"Huge Clan ({index}/12)" in json_text for index in range(1, 13))


def test_named_members_listed_once_beneath_one_party_header():
    plan = Plan(
        session_id="test", status="feasible",
        tables=[TableUsage(table_id="A", zone_id="hall", capacity=3, occupied=2, empty_seats=1)],
        assignments=[Assignment(group_id="registration:2", group_name="The Greens",
                                table_id="A", guest_ids=["a", "b"],
                                guest_names=["Alice Green", "Bob Green"])],
    )
    table_text = render(plan, "table")
    assert "The Greens — 2\n    Alice Green\n    Bob Green" in table_text
    assert "registration:2" not in table_text
    people = ElementTree.fromstring(render_people_list_html(plan))
    named_rows = people.findall('.//tr[@data-guest-id]')
    assert [r[0].text for r in named_rows] == ["Alice Green", "Bob Green"]
    assert [r[2].text for r in named_rows] == ["The Greens — 2", "—"]
    table_html = render_table_list_html(plan)
    assert table_html.count("The Greens — 2") == 1
    assert table_html.count("Alice Green") == 1
    assert table_html.count("Bob Green") == 1
    cards = PdfReader(BytesIO(render_table_cards_pdf(plan)))
    pdf_text = cards.pages[0].extract_text()
    assert "The Greens" in pdf_text
    assert pdf_text.count("Alice Green") == 1
    assert pdf_text.count("Bob Green") == 1


def test_legacy_synthetic_assignment_without_group_name_uses_same_party_header():
    plan = Plan(
        session_id="old", status="feasible",
        tables=[TableUsage(table_id="A", zone_id="hall", capacity=2, occupied=2, empty_seats=0)],
        assignments=[Assignment(group_id="registration:2", table_id="A",
                                guest_ids=["a", "b"],
                                guest_names=["Huge Clan (7/12)", "Huge Clan (8/12)"])],
    )
    assert "Huge Clan — 2" in render(plan, "table")
    assert "(7/12)" not in render(plan, "table")


def test_singular_generated_explanations_show_person_chair_and_point():
    from seating_optimizer import Rule
    plan = solve(Problem(
        session_id="solo", zones=[Zone(id="hall", name="Hall")],
        tables=[Table(id="A", zone_id="hall", capacity=2)],
        guests=[Guest(id="a", name="Alice", group_id="registration:2", group_name="Alice")],
        rules=[Rule(id="fill", shape="fill_efficiency", mode="soft", weight=1)],
        config=SolverConfig(workers=1),
    ))
    assert plan.status in ("feasible", "optimal")
    text = render(plan, "table")
    assert "Guest — 1" in text
    assert text.count("Alice") == 1
    assert "1 empty chair" in text
    assert "1 empty chairs" not in text
    assert "1 people" not in text
    assert "(-1 point)" in text
    assert "(lost 1 point)" in text
    assert any("1 empty chair" in reason.description
               for entry in plan.assignments for reason in entry.reasons)
    from seating_optimizer.display import counted
    assert counted(1, "group") == "1 group"
    assert counted(1, "empty seat") == "1 empty seat"
    assert counted(2, "group") == "2 groups"
    assert counted(2, "empty seat") == "2 empty seats"



def test_uneven_split_4_3_and_whole_party_use_correct_counts_across_exports():
    """Human outputs show local/whole for each portion, but JSON stays per-member."""
    from seating_optimizer import render_floor_pdf
    from seating_optimizer.display import party_totals

    layout = VenueLayout(floors=[FloorLayout(
        zone_id="hall", width=600, height=220, tables=[
            TableDrawing(table_id="A", x=10, y=10, width=160, height=150),
            TableDrawing(table_id="B", x=205, y=10, width=160, height=150),
            TableDrawing(table_id="C", x=400, y=10, width=160, height=150),
        ],
    )])
    plan = Plan(
        session_id="uneven-split", status="feasible", layout=layout,
        tables=[
            TableUsage(table_id="A", zone_id="hall", capacity=4, occupied=4, empty_seats=0),
            TableUsage(table_id="B", zone_id="hall", capacity=4, occupied=3, empty_seats=1),
            TableUsage(table_id="C", zone_id="hall", capacity=2, occupied=2, empty_seats=0),
        ],
        assignments=[
            Assignment(group_id="registration:2", group_name="Seven Family", table_id="A",
                       guest_ids=[f"s{i}" for i in range(1, 5)],
                       guest_names=[f"Seven Family ({i}/7)" for i in range(1, 5)]),
            Assignment(group_id="registration:2", group_name="Seven Family", table_id="B",
                       guest_ids=[f"s{i}" for i in range(5, 8)],
                       guest_names=[f"Seven Family ({i}/7)" for i in range(5, 8)]),
            Assignment(group_id="registration:3", group_name="Whole Family", table_id="C",
                       guest_ids=["w1", "w2"],
                       guest_names=["Whole Family (1/2)", "Whole Family (2/2)"]),
        ],
    )
    assert party_totals(plan) == {"registration:2": 7, "registration:3": 2}
    snippets = ("Seven Family — 4/7", "Seven Family — 3/7", "Whole Family — 2")

    classic = render(plan, "table")
    for snippet in snippets:
        assert classic.count(snippet) == 1
    assert "Whole Family — 2/2" not in classic
    assert "Seven Family (1/7)" not in classic

    for html in (
        render_people_list_html(plan),
        render_people_list_html(plan, group_by="floor"),
        render_table_list_html(plan),
        render_table_list_html(plan, group_by="table"),
    ):
        for snippet in snippets:
            assert html.count(snippet) == 1
        assert "Seven Family (1/7)" not in html
        assert ">registration:2<" not in html
    people = ElementTree.fromstring(render_people_list_html(plan))
    rows = people.findall('.//tr[@data-group-id]')
    assert len(rows) == 3
    assert [(r.attrib["data-group-id"], r.attrib["data-table-id"], r[2].text)
            for r in rows] == [
        ("registration:2", "A", "Seven Family — 4/7"),
        ("registration:2", "B", "Seven Family — 3/7"),
        ("registration:3", "C", "Whole Family — 2"),
    ]
    assert not people.findall('.//tr[@data-guest-id]')

    for page in render_floor_svg(plan).pages:
        for snippet in snippets:
            assert page.svg.count(snippet) == 1
    map_pdf = PdfReader(BytesIO(render_floor_pdf(plan)))
    map_text = "\n".join(page.extract_text() for page in map_pdf.pages)
    for snippet in snippets:
        assert map_text.count(snippet) == 1

    for density in (1, 2, 4):
        cards = PdfReader(BytesIO(render_table_cards_pdf(plan, cards_per_page=density)))
        text = "\n".join(page.extract_text() for page in cards.pages)
        for snippet in snippets:
            assert text.count(snippet) == 1
        assert "Seven Family (1/7)" not in text

    json_text = render(plan, "json")
    assert json_text.count('"group_id": "registration:2"') == 2
    for index in range(1, 8):
        assert f"Seven Family ({index}/7)" in json_text


def test_genuine_named_members_of_a_split_party_keep_one_fractional_header_per_table():
    plan = Plan(
        session_id="named-split", status="feasible",
        tables=[
            TableUsage(table_id="A", zone_id="hall", capacity=4, occupied=4, empty_seats=0),
            TableUsage(table_id="B", zone_id="hall", capacity=4, occupied=3, empty_seats=1),
        ],
        assignments=[
            Assignment(group_id="party", group_name="Family Smith", table_id="A",
                       guest_ids=["1", "2", "3", "4"],
                       guest_names=["Ada", "Ben", "Cara", "Dan"]),
            Assignment(group_id="party", group_name="Family Smith", table_id="B",
                       guest_ids=["5", "6", "7"],
                       guest_names=["Elle", "Finn", "Grace"]),
        ],
    )
    classic = render(plan, "table")
    assert "Family Smith — 4/7\n    Ada\n    Ben\n    Cara\n    Dan" in classic
    assert "Family Smith — 3/7\n    Elle\n    Finn\n    Grace" in classic
    people = ElementTree.fromstring(render_people_list_html(plan))
    rows = people.findall('.//tr[@data-guest-id]')
    assert len(rows) == 7
    assert [row[2].text for row in rows] == [
        "Family Smith — 4/7", "—", "—", "—",
        "Family Smith — 3/7", "—", "—",
    ]
    table_html = render_table_list_html(plan)
    assert table_html.count("Family Smith — 4/7") == 1
    assert table_html.count("Family Smith — 3/7") == 1
    for member in ("Ada", "Ben", "Cara", "Dan", "Elle", "Finn", "Grace"):
        assert table_html.count(f">{member}</span>") == 1


def _solve_greens(guests: list[Guest]) -> Plan:
    """The same simple venue for imported and API-shaped identity cases."""
    layout = VenueLayout(floors=[FloorLayout(
        zone_id="hall", width=250, height=150, tables=[
            TableDrawing(table_id="A", x=20, y=20, width=180, height=110),
        ])])
    plan = solve(Problem(
        session_id="greens", zones=[Zone(id="hall", name="Hall")],
        tables=[Table(id="A", zone_id="hall", capacity=2)],
        guests=guests, layout=layout, config=SolverConfig(workers=1),
    ))
    assert plan.status in ("feasible", "optimal"), plan.conflicting_constraints
    return plan


def _assert_greens_surfaces(plan: Plan, header: str) -> None:
    """One header and exactly one appearance of each member per human export."""
    text = render(plan, "table")
    for output in (text, render_people_list_html(plan), render_table_list_html(plan)):
        assert output.count(header) == 1
        assert output.count("Alice Green") == 1
        assert output.count("Bob Green") == 1
        assert "Alice Green — 2" not in output
        assert "Bob Green — 2" not in output
        assert "registration:" not in output
    assert f"{header}\n    Alice Green\n    Bob Green" in text
    people = ElementTree.fromstring(render_people_list_html(plan))
    rows = people.findall('.//tr[@data-guest-id]')
    assert [row[0].text for row in rows] == ["Alice Green", "Bob Green"]
    assert [row[2].text for row in rows] == [header, "—"]
    svg = render_floor_svg(plan).pages[0].svg
    assert svg.count(header) == 1
    assert "Alice Green — 2" not in svg
    cards = PdfReader(BytesIO(render_table_cards_pdf(plan)))
    card_text = "\n".join(page.extract_text() for page in cards.pages)
    assert card_text.count(header) == 1
    assert card_text.count("Alice Green") == 1
    assert card_text.count("Bob Green") == 1


def test_import_shared_group_without_group_name_uses_neutral_header():
    """Alice and Bob have individual row names, not a party name."""
    imported = import_registrations(
        b"Guest Name,Party Size,Group ID\n"
        b"Alice Green,1,greens\nBob Green,1,greens\n",
        "greens.csv",
    )
    assert not imported.has_errors, imported.issues
    assert imported.mapping["Group ID"] == "group_id"
    assert len(imported.guests) == 2
    assert [guest.name for guest in imported.guests] == ["Alice Green", "Bob Green"]
    assert all(guest.group_name is None for guest in imported.guests)
    plan = _solve_greens(imported.guests)
    assert len(plan.assignments) == 1
    assert plan.assignments[0].group_name is None
    _assert_greens_surfaces(plan, "Party — 2")
    machine = render(plan, "json")
    assert '"group_id": "greens"' in machine
    assert '"group_name": null' in machine


def test_import_mapped_group_name_uses_the_greens_on_every_surface():
    """The field picker feeds a distinct party label through import and solve."""
    from seating_optimizer import preview_registrations

    csv = (b"Guest Name,Party Size,Group ID,Household Title\n"
           b"Alice Green,1,greens,The Greens\n"
           b"Bob Green,1,greens,The Greens\n")
    mapping = {"Household Title": "group_name"}
    preview = preview_registrations(csv, "greens.csv", mapping=mapping)
    assert "group_name" in preview.targets
    assert preview.mapping["Household Title"] == "group_name"
    imported = import_registrations(csv, "greens.csv", mapping=mapping)
    assert not imported.has_errors, imported.issues
    assert all(guest.group_name == "The Greens" for guest in imported.guests)
    assert all("Household Title" not in guest.attributes for guest in imported.guests)
    plan = _solve_greens(imported.guests)
    assert plan.assignments[0].group_name == "The Greens"
    _assert_greens_surfaces(plan, "The Greens — 2")
    assert '"group_name": "The Greens"' in render(plan, "json")


def test_explicit_api_group_name_remains_distinct_through_solve_and_exports():
    """Existing API callers supplying The Greens remain fully supported."""
    plan = _solve_greens([
        Guest(id="a", name="Alice Green", group_id="greens", group_name="The Greens"),
        Guest(id="b", name="Bob Green", group_id="greens", group_name="The Greens"),
    ])
    assert plan.assignments[0].group_name == "The Greens"
    _assert_greens_surfaces(plan, "The Greens — 2")
    assert '"group_name": "The Greens"' in render(plan, "json")


def test_api_member_name_as_group_name_is_rejected_at_source():
    """Even directly submitted API guest data cannot promote Alice to party name."""
    plan = _solve_greens([
        Guest(id="a", name="Alice Green", group_id="greens", group_name="Alice Green"),
        Guest(id="b", name="Bob Green", group_id="greens", group_name="Alice Green"),
    ])
    assert plan.assignments[0].group_name is None
    _assert_greens_surfaces(plan, "Party — 2")


def test_neutral_party_header_does_not_equal_a_member_named_party():
    """Even a literal 'Party' member name cannot become the fallback header."""
    plan = _solve_greens([
        Guest(id="a", name="Party", group_id="greens"),
        Guest(id="b", name="Bob Green", group_id="greens"),
    ])
    assert plan.assignments[0].group_name is None
    text = render(plan, "table")
    assert "Unnamed Party — 2\n    Party\n    Bob Green" in text
    assert "  Party — 2" not in text
    assert "Unnamed Party — 2" in render_table_list_html(plan)
    assert "Unnamed Party — 2" in render_people_list_html(plan)
