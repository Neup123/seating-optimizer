"""Topic #64: graded, data-owned priority and human selection boundary."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from seating_optimizer import Guest, ManualInstruction, Problem, Rule, SolverConfig, Table, Zone, solve
from seating_optimizer.api.app import create_app
from seating_optimizer.reassignment import ReassignRequest, propose_reassignment


def family(name: str, size: int):
    return [Guest(id=f"{name}-{i}", name=f"{name} person {i}", group_id=name,
                  group_name=f"{name} Family") for i in range(size)]


def marker(name: str, grade: int, *, target: str | None = None,
           below: int | None = None):
    if target is not None:
        data = {"selector": "group", "grade": grade, "group_id": target}
    else:
        data = {"selector": "size_below", "grade": grade, "threshold": below}
    return Rule(id=name, shape="low_priority", mode="mark", parameters=data)


def scene(sizes: dict[str, int], capacities: list[int], *,
          rules: list[Rule] | None = None, manual: list[ManualInstruction] | None = None):
    return Problem(
        session_id="priority-test", zones=[Zone(id="z", name="Room")],
        tables=[Table(id=f"T{i}", zone_id="z", capacity=c)
                for i, c in enumerate(capacities)],
        guests=[g for name, size in sizes.items() for g in family(name, size)],
        rules=rules or [], manual_instructions=manual or [],
        config=SolverConfig(time_limit_seconds=4, workers=2, random_seed=42))


def placed(plan):
    return {guest_id: a.table_id for a in plan.assignments for guest_id in a.guest_ids}


def test_grades_fit_in_ascending_order_then_pause_without_unseating():
    # Exactly ten chairs for ten guests, but the last two free chairs are
    # in separate one-chair tables. The more-low family of two is atomic.
    problem = scene({"ordinary": 5, "low1": 3, "low2": 2},
                    [5, 3, 1, 1], rules=[
        marker("first", 1, target="low1"), marker("last", 9, target="low2")
    ])
    plan = solve(problem)
    assert plan.status == "needs_review"
    assert [mark.group_id for mark in plan.priority_marks] == ["low1", "low2"]
    assert [mark.grade for mark in plan.priority_marks] == [1, 9]
    assert [mark.group_id for mark in plan.pending_groups] == ["low2"]
    assert plan.not_seated == []
    assert set(placed(plan)) == {g.id for g in problem.guests if g.group_id != "low2"}
    assert {a.table_id for a in plan.assignments if a.group_id == "ordinary"} == {"T0"}
    assert {a.table_id for a in plan.assignments if a.group_id == "low1"} == {"T1"}
    assert "grade 9" in plan.message
    assert sum(t.occupied for t in plan.tables) == 8


def test_overlap_uses_the_most_low_grade_criterion_derives_and_removal_clears():
    p = scene({"large": 5, "three": 3, "two": 2}, [5, 3, 2], rules=[
        marker("small", 2, below=4),
        marker("by-hand", 5, target="two"),
    ])
    plan = solve(p)
    assert plan.status in {"optimal", "feasible"}
    assert [(m.group_id, m.grade) for m in plan.priority_marks] == [
        ("three", 2), ("two", 5)]
    assert next(m for m in plan.priority_marks if m.group_id == "two").source_rule_ids == [
        "by-hand", "small"]
    assert plan.pending_groups == []
    assert plan.not_seated == []
    assert plan.total_score == 0  # Priority marks never add or subtract points.
    assert not plan.score_breakdown
    p.rules = [marker("by-hand", 5, target="two")]
    assert [(m.group_id, m.grade) for m in solve(p).priority_marks] == [("two", 5)]
    p.rules = []
    unmarked = solve(p)
    assert unmarked.priority_marks == []
    assert unmarked.pending_groups == []
    assert unmarked.not_seated == []
    assert unmarked.status in {"optimal", "feasible"}
    assert unmarked.total_score == 0


def test_plain_overcapacity_raises_shortfall_alarm_without_selecting_anyone():
    p = scene({"A": 3, "B": 2}, [4])
    alarm = solve(p)
    assert alarm.status == "infeasible"
    assert "short by 1" in alarm.message
    assert alarm.assignments == []
    assert alarm.not_seated == []
    assert alarm.pending_groups == []
    assert alarm.manual_instructions == []
    assert sum(t.capacity for t in p.tables) == 4
    assert len(p.guests) == 5
    # Even marked candidates are NOT automatically removed.
    p.rules = [marker("maybe", 3, target="B")]
    marked_alarm = solve(p)
    assert marked_alarm.status == "infeasible"
    assert marked_alarm.not_seated == []
    assert [mark.group_id for mark in marked_alarm.priority_marks] == ["B"]
    assert marked_alarm.assignments == []


def test_only_operator_unseat_instruction_creates_not_seated_state_and_is_reversible():
    p = scene({"A": 3, "B": 2}, [3], rules=[marker("low-B", 4, target="B")])
    assert solve(p).status == "infeasible"
    p.manual_instructions = [ManualInstruction(id="owner-1", group_id="B", action="unseat")]
    chosen = solve(p)
    assert chosen.status in {"optimal", "feasible"}
    assert {a.group_id for a in chosen.assignments} == {"A"}
    assert len(chosen.not_seated) == 1
    assert chosen.not_seated[0].group_id == "B"
    assert chosen.not_seated[0].group_name == "B Family"
    assert chosen.not_seated[0].guest_ids == ["B-0", "B-1"]
    assert chosen.not_seated[0].grade == 4
    assert chosen.manual_instructions == p.manual_instructions
    p.manual_instructions = []
    restored = solve(p)
    assert restored.status == "infeasible"
    assert restored.not_seated == []


def test_failed_pending_family_offers_verified_split_or_operator_unseat():
    # No whole table has six free seats, but four plus two are available:
    # the documented §11.3 pattern. Splitting is never automatic.
    p = scene({"ordinary": 4, "deferred": 6}, [8, 2], rules=[
        marker("defer", 2, target="deferred")
    ])
    partial = solve(p)
    assert partial.status == "needs_review"
    assert [a.group_id for a in partial.assignments] == ["ordinary"]
    assert [m.group_id for m in partial.pending_groups] == ["deferred"]
    assert partial.not_seated == []
    response = propose_reassignment(ReassignRequest(
        problem=p, plan=partial,
        instruction=ManualInstruction(id="owner-split", group_id="deferred", action="seat_pending")))
    assert response.status == "available"
    assert len(response.options) <= 8  # Search remains bounded even for larger venues.
    split = next(option for option in response.options if option.kind == "split")
    assert split.plan.status in {"optimal", "feasible"}
    assert split.plan.not_seated == []
    counts = {a.table_id: len(a.guest_ids) for a in split.plan.assignments
              if a.group_id == "deferred"}
    assert counts == {"T0": 4, "T1": 2}
    saved = split.plan.manual_instructions[-1]
    assert saved.action == "pin_placement" and saved.allow_split
    assert saved.id == "owner-split"
    assert saved.guest_tables
    p.manual_instructions = split.plan.manual_instructions
    replay = solve(p)
    assert replay.status in {"optimal", "feasible"}
    assert placed(replay) == placed(split.plan)

    p.manual_instructions = []
    again = solve(p)
    assert again.status == "needs_review" and again.not_seated == []
    unseat = next(option for option in response.options if option.kind == "leave_unseated")
    assert unseat.plan.not_seated[0].group_id == "deferred"
    assert unseat.plan.manual_instructions[-1].action == "unseat"
    p.manual_instructions = unseat.plan.manual_instructions
    acknowledged = solve(p)
    assert acknowledged.not_seated[0].group_id == "deferred"
    assert all(a.group_id == "ordinary" for a in acknowledged.assignments)


def test_pending_review_api_contract_and_human_only_application():
    p = scene({"ordinary": 4, "deferred": 6}, [8, 2], rules=[
        marker("defer", 2, target="deferred")
    ])
    client = TestClient(create_app())
    result = client.post("/v1/solve", json=p.model_dump())
    assert result.status_code == 200, result.text
    assert result.json()["status"] == "needs_review"
    assert result.json()["not_seated"] == []
    options = client.post("/v1/reassign/options", json={
        "problem": p.model_dump(), "plan": result.json(),
        "instruction": {"id": "operator-1", "group_id": "deferred", "action": "seat_pending"}
    })
    assert options.status_code == 200, options.text
    assert options.json()["options"]
    assert "leave_unseated" in {x["kind"] for x in options.json()["options"]}
    assert not p.manual_instructions  # Querying options commits nothing.


def test_invalid_grade_threshold_and_mark_type_rejected():
    for data in [
        {"selector": "group", "grade": 0, "group_id": "A"},
        {"selector": "group", "grade": True, "group_id": "A"},
        {"selector": "size_below", "grade": 1, "threshold": 0},
        {"selector": "size_below", "grade": 1, "threshold": 3.5},
        {"selector": "group", "grade": 2},
    ]:
        with pytest.raises(ValidationError):
            Rule(id="bad", shape="low_priority", mode="mark", parameters=data)
    with pytest.raises(ValidationError):
        Rule(id="bad", shape="low_priority", mode="soft", weight=5,
             parameters={"selector": "group", "grade": 1, "group_id": "A"})
    with pytest.raises(ValidationError):
        Rule(id="bad", shape="pair", mode="mark", parameters={})
    with pytest.raises(ValueError, match="unknown low-priority family"):
        solve(scene({"A": 1}, [2], rules=[marker("bad", 1, target="unknown")]))
    with pytest.raises(ValidationError):
        ManualInstruction(id="bad", group_id="A", action="unseat", place_type="table", place_id="T0")


def test_unmarked_paths_unchanged_for_constraints_scores_and_atomicity():
    p = scene({"A": 2, "B": 2}, [4, 4], rules=[
        Rule(id="prefer", shape="pair", mode="soft", weight=7,
             parameters={"left": "A", "right": "B", "relation": "together"})
    ])
    plan = solve(p)
    assert plan.status in {"optimal", "feasible"}
    assert plan.total_score == 7
    assert all(a.group_id in {"A", "B"} for a in plan.assignments)
    assert plan.priority_marks == plan.pending_groups == plan.not_seated == []
    assert plan.score_breakdown[0].points == 7
