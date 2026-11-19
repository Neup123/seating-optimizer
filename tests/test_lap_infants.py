"""An explicitly marked lap infant is registered but does not occupy a chair."""
from __future__ import annotations

import pytest

from seating_optimizer import Guest, Problem, Table, Zone, SolverConfig, solve, import_registrations
from seating_optimizer.generic_solver import GenericProblem, solve_generic
from seating_optimizer.generic_evaluator import hard_violations
from seating_optimizer.models import chairs_needed


def baby_problem():
    return Problem(
        session_id="lap-infant", zones=[Zone(id="hall", name="Hall")],
        tables=[Table(id="T", zone_id="hall", capacity=2)],
        guests=[
            Guest(id="mother", name="Mother", group_id="family"),
            Guest(id="father", name="Father", group_id="family"),
            Guest(id="baby", name="Baby", group_id="family", requires_chair=False,
                  attributes={"age_layer": "Baby"}),
        ],
        rules=[], config=SolverConfig(workers=1, time_limit_seconds=3),
    )


@pytest.mark.parametrize("engine", ["v1", "v2"])
def test_infant_present_but_does_not_consume_chair(engine):
    problem = baby_problem()
    plan = solve(problem) if engine == "v1" else solve_generic(GenericProblem.from_v1(problem))
    assert plan.status in ("optimal", "feasible"), plan.message
    assert len(plan.assignments) == 1
    assert set(plan.assignments[0].guest_ids) == {"mother", "father", "baby"}
    assert plan.tables[0].capacity == 2
    assert plan.tables[0].occupied == 2
    assert plan.tables[0].empty_seats == 0
    assert chairs_needed(problem.guests) == 2
    mapping = {id: entry.table_id for entry in plan.assignments for id in entry.guest_ids}
    if engine == "v2":
        assert hard_violations(problem.guests, problem.tables, mapping, []) == []


@pytest.mark.parametrize("engine", ["v1", "v2"])
def test_baby_label_alone_never_waives_a_chair(engine):
    problem = baby_problem()
    problem.guests[2].requires_chair = True
    plan = solve(problem) if engine == "v1" else solve_generic(GenericProblem.from_v1(problem))
    assert plan.status == "infeasible"


def test_import_explicit_lap_infants_and_validation():
    good = import_registrations(
        b"Name,Size,Lap infants\nFamily,3,1\n", "family.csv")
    assert not good.has_errors, good.issues
    assert len(good.guests) == 3
    assert sum(not g.requires_chair for g in good.guests) == 1
    assert sum(g.requires_chair for g in good.guests) == 2
    assert all(g.group_name == "Family" for g in good.guests)

    bad = import_registrations(
        b"Name,Size,Lap infants\nFamily,3,4\n", "family.csv")
    assert bad.has_errors
    assert not bad.guests
    assert any("Lap infants" in issue.message for issue in bad.issues)


def test_legacy_payload_defaults_to_one_chair_per_guest():
    guest = Guest.model_validate({"id": "a", "name": "Alice"})
    assert guest.requires_chair is True
    with pytest.raises(Exception):
        Guest.model_validate({"id": "a", "name": "Alice", "requires_chair": "false"})


@pytest.mark.parametrize("engine", ["v1", "v2"])
def test_lap_infant_appears_on_both_printable_lists(engine):
    from seating_optimizer import render_people_list_html, render_table_list_html
    problem = baby_problem()
    plan = solve(problem) if engine == "v1" else solve_generic(GenericProblem.from_v1(problem))
    people = render_people_list_html(plan)
    tables = render_table_list_html(plan)
    for page in (people, tables):
        assert "Mother" in page
        assert "Father" in page
        assert "Baby" in page
    assert plan.tables[0].occupied == 2  # exported table capacity is physical chairs
