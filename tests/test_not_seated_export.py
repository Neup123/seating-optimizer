"""Topic #65: the printed page is an exact projection of operator-selected overflow."""
from __future__ import annotations

from xml.etree import ElementTree as ET

import pytest
from fastapi.testclient import TestClient

from seating_optimizer import (
    Assignment, Guest, ManualInstruction, NotSeatedGroup, Plan, Problem,
    SolverConfig, Table, Zone, render, render_not_seated_list_html, solve,
)
from seating_optimizer.api.app import app


def meal(*, instructions: list[ManualInstruction] | None = None) -> Problem:
    groups = [
        ("family-four", "River & <Friends>", 4),
        ("family-three", "Green Family", 3),
        ("family-two", "Family to move", 2),
    ]
    guests = [
        Guest(id=f"{gid}-{i}", name=f"{registered} member {i}",
              group_id=gid, group_name=registered)
        for gid, registered, count in groups for i in range(count)
    ]
    return Problem(
        session_id="Another room & dinner",
        zones=[Zone(id="z", name="Room")],
        tables=[Table(id="A", zone_id="z", capacity=4),
                Table(id="B", zone_id="z", capacity=3)],
        guests=guests,
        manual_instructions=instructions or [],
        config=SolverConfig(time_limit_seconds=4, workers=2),
    )


def parsed(plan: Plan) -> ET.Element:
    result = render_not_seated_list_html(plan)
    assert result.startswith("<!DOCTYPE html>")
    assert "<script" not in result
    return ET.fromstring(result)


def test_capacity_alarm_never_prints_unselected_people_then_exact_operator_list():
    problem = meal()
    alarm = solve(problem)
    assert alarm.status == "infeasible"
    assert "short by 2" in alarm.message
    assert alarm.not_seated == []
    assert parsed(alarm).findall('.//tr[@data-group-id]') == []

    # The operator chooses the two-person family. The solver did not
    # determine who was excluded; the same recorded instruction is replayed.
    problem.manual_instructions = [
        ManualInstruction(id="owner-unseat", group_id="family-two", action="unseat")]
    decided = solve(problem)
    assert decided.status in {"optimal", "feasible"}
    assert [g.group_id for g in decided.not_seated] == ["family-two"]
    root = parsed(decided)
    assert root.find(".//h1").text == "Not seated in the main room"
    assert root.find(".//section/h2").text == "1 family · 2 people"
    rows = root.findall('.//tr[@data-group-id]')
    assert len(rows) == 1 and rows[0].attrib["data-group-id"] == "family-two"
    assert rows[0][0].text == "Family to move — 2"
    assert rows[0][1].text == "2"
    assert [(tag.attrib["data-guest-id"], tag.text)
            for tag in rows[0].findall(".//span[@data-guest-id]")] == [
        ("family-two-0", "Family to move member 0"),
        ("family-two-1", "Family to move member 1"),
    ]
    html = render_not_seated_list_html(decided)
    assert 'data-group-id="family-four"' not in html
    assert 'data-group-id="family-three"' not in html
    assert "River &amp; &lt;Friends&gt;" not in html  # Seated names never leak.
    assert sum(len(group.guest_ids) for group in decided.not_seated) == 2
    assert sum(int(row[1].text) for row in rows) == 2
    assert decided.model_dump() == Plan.model_validate(decided.model_dump()).model_dump()


def test_manual_move_to_unseated_then_restore_removes_every_print_entry():
    # Start with a full venue, then the operator removes a seated party.
    problem = meal(instructions=[
        ManualInstruction(id="owner-1", group_id="family-two", action="unseat")])
    first = solve(problem)
    assert first.not_seated and first.not_seated[0].group_id == "family-two"
    assert len(parsed(first).findall('.//tr[@data-group-id]')) == 1
    problem.manual_instructions = []
    restored = solve(problem)
    assert restored.status == "infeasible"  # Capacity alarm; no automatic choice.
    assert restored.not_seated == []
    assert not parsed(restored).findall('.//tr[@data-group-id]')
    assert "No one is currently marked not seated." in render_not_seated_list_html(restored)


def test_page_works_during_remaining_over_capacity_and_pending_review():
    p = meal(instructions=[
        ManualInstruction(id="owner-1", group_id="family-three", action="unseat")])
    decided = solve(p)
    assert decided.status in {"optimal", "feasible"}
    # The page is an independent projection: its status cannot cause it to
    # select/remove another family, and an alarm must not suppress printing.
    partial_alarm = decided.model_copy(deep=True)
    partial_alarm.status = "infeasible"
    partial_alarm.message = "Too many people — short by 1."
    assert parsed(partial_alarm).find(".//tr[@data-group-id]").attrib["data-group-id"] == "family-three"
    review = partial_alarm.model_copy(update={"status": "needs_review"})
    assert render_not_seated_list_html(review) == render_not_seated_list_html(
        partial_alarm).replace("infeasible", "needs_review")
    # Non-assignment sources remain irrelevant to page content.
    extra = review.model_copy(deep=True)
    extra.assignments = []
    assert render_not_seated_list_html(extra) == render_not_seated_list_html(review)


@pytest.mark.parametrize("status", ["optimal", "feasible", "infeasible", "needs_review", "unknown"])
def test_empty_set_has_explicit_message_and_no_phantom_rows(status):
    plan = Plan(session_id="Dinner", status=status)
    root = parsed(plan)
    assert root.find(".//h1").text == "Not seated in the main room"
    assert root.findall('.//tr[@data-group-id]') == []
    assert root.findall('.//span[@data-guest-id]') == []
    assert "No one is currently marked not seated." in "".join(root.itertext())


def test_registration_only_names_not_invented_and_markup_is_escaped():
    plan = Plan(
        session_id="Guests <&>",
        status="infeasible",
        not_seated=[
            NotSeatedGroup(
                group_id="registration:1",
                group_name="Green & <Family>",
                guest_ids=["anon-1", "anon-2"],
                guest_names=["Green & <Family> (1/2)", "Green & <Family> (2/2)"]),
            NotSeatedGroup(
                group_id="solo",
                group_name="Hannah & Family",
                guest_ids=["person-3"], guest_names=["Hannah & Family"]),
        ])
    html = render_not_seated_list_html(plan)
    assert "Green &amp; &lt;Family&gt; — 2" in html
    assert "Guests &lt;&amp;&gt;" in html
    assert "<Family>" not in html
    root = ET.fromstring(html)
    assert len(root.findall('.//tr[@data-group-id]')) == 2
    rows = root.findall('.//tr[@data-group-id]')
    assert rows[0][0].text == "Green & <Family> — 2"
    assert rows[0][2].text == "—"  # No synthetic person names.
    assert rows[1][0].text == "Hannah & Family — 1"
    assert rows[1][2].text == "—"  # Named single registration already in heading.
    assert root.find(".//section/h2").text == "2 families · 3 people"


def test_registry_and_http_endpoints_use_exact_same_plan_and_no_mutation():
    p = meal(instructions=[
        ManualInstruction(id="operator-choice", group_id="family-two", action="unseat")])
    plan = solve(p)
    before = plan.model_dump()
    html = render_not_seated_list_html(plan)
    assert render(plan, "not-seated-list-html") == html
    client = TestClient(app)
    response = client.post(
        "/v1/exports/not-seated-list/html", json=plan.model_dump(mode="json"))
    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("text/html")
    assert response.text == html
    assert plan.model_dump() == before


@pytest.mark.parametrize("broken", ["duplicate-group", "duplicate-person", "overlap", "names", "empty"])
def test_export_rejects_contradictory_records_instead_of_silently_dropping(broken):
    group = NotSeatedGroup(
        group_id="a", group_name="A family",
        guest_ids=["a1", "a2"], guest_names=["Alice", "Aaron"])
    plan = Plan(session_id="x", status="feasible", not_seated=[group])
    if broken == "duplicate-group":
        plan.not_seated.append(group.model_copy(deep=True))
    elif broken == "duplicate-person":
        plan.not_seated.append(NotSeatedGroup(
            group_id="b", group_name="B", guest_ids=["a1"], guest_names=["Alice"]))
    elif broken == "overlap":
        plan.assignments.append(Assignment(
            group_id="a", group_name="A family", table_id="T",
            guest_ids=["a1"], guest_names=["Alice"]))
    elif broken == "names":
        plan.not_seated[0].guest_names.pop()
    else:
        plan.not_seated[0].guest_ids = []
        plan.not_seated[0].guest_names = []
    with pytest.raises(ValueError):
        render_not_seated_list_html(plan)
    client = TestClient(app)
    result = client.post("/v1/exports/not-seated-list/html",
                         json=plan.model_dump(mode="json"))
    assert result.status_code == 422
