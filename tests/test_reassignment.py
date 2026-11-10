"""Topic B option routes, precedence, capacity, and persisted user directions."""
from __future__ import annotations

from collections import Counter

import pytest
from fastapi.testclient import TestClient

from seating_optimizer.api.app import app
from seating_optimizer.models import Guest, ManualInstruction, Problem, Rule, Table, Zone
from seating_optimizer.reassignment import ReassignRequest, propose_reassignment
from seating_optimizer.solver import solve


def scene(capacities: dict[str, int], occupants: dict[str, tuple[str, int]], *,
          extra_rules=(), zones=None):
    zones = zones or {name: "ground" for name in capacities}
    all_guests = []
    locked = {}
    for group, (table, count) in occupants.items():
        for i in range(count):
            guest_id = f"{group}-{i}"
            all_guests.append(Guest(id=guest_id, name=guest_id, group_id=group,
                                    group_name=group, attributes={"role": group}))
            locked[guest_id] = table
    problem = Problem(session_id="test", zones=[Zone(id=z, name=z) for z in set(zones.values())],
                      tables=[Table(id=name, zone_id=zones[name], capacity=cap)
                              for name, cap in capacities.items()],
                      guests=all_guests, rules=list(extra_rules), locked_guest_tables=locked)
    baseline = solve(problem)
    assert baseline.status in {"optimal", "feasible"}, baseline.message
    unlocked = problem.model_copy(deep=True)
    unlocked.locked_guest_tables = {}
    return unlocked, baseline


def ask(problem, baseline, party, table="B", action="move_to", *, split=False,
        place_type="table"):
    instruction = ManualInstruction(id="request-1", group_id=party, action=action,
                                    place_type=place_type, place_id=table, allow_split=split)
    return propose_reassignment(ReassignRequest(problem=problem, plan=baseline,
                                                 instruction=instruction))


def locate(plan):
    return {g: a.table_id for a in plan.assignments for g in a.guest_ids}


def assert_safe(problem, response):
    for option in response.options:
        assert option.plan.status in {"optimal", "feasible"}
        used = Counter(locate(option.plan).values())
        assert all(used[t.id] <= t.capacity for t in problem.tables)
        assert option.plan.manual_instructions[-1].id == "request-1"
        # Pins, zone restrictions, pair hard relations, and capacity were all
        # re-checked by the unchanged CP-SAT solver with exact guest locks.
        check = problem.model_copy(deep=True)
        check.manual_instructions = option.plan.manual_instructions
        check.splittable_groups = (["A"] if option.plan.manual_instructions[-1].allow_split else [])
        check.locked_guest_tables = locate(option.plan)
        assert solve(check).status in {"optimal", "feasible"}


def test_direct_free_space_with_no_other_party_moved():
    problem, plan = scene({"A": 2, "B": 3}, {"A": ("A", 2)})
    response = ask(problem, plan, "A")
    direct = next(o for o in response.options if o.kind == "free-space")
    assert len(direct.movements) == 1
    assert direct.movements[0].party_name == "A"
    assert all(table == "B" for table in locate(direct.plan).values())
    assert_safe(problem, response)


def test_one_to_one_swap():
    problem, plan = scene({"A": 3, "B": 3}, {"A": ("A", 3), "B": ("B", 3)})
    response = ask(problem, plan, "A")
    swap = next(o for o in response.options if o.kind == "one-to-one")
    assert {m.group_id for m in swap.movements} == {"A", "B"}
    assert locate(swap.plan)["A-0"] == "B"
    assert locate(swap.plan)["B-0"] == "A"
    assert_safe(problem, response)


def test_many_for_one_exchange_with_two_smaller_parties():
    problem, plan = scene({"A": 4, "B": 4},
                          {"A": ("A", 4), "B1": ("B", 2), "B2": ("B", 2)})
    response = ask(problem, plan, "A")
    choice = next(o for o in response.options if o.kind == "many-for-one")
    assert {m.group_id for m in choice.movements} == {"A", "B1", "B2"}
    assert locate(choice.plan)["B1-0"] == "A"
    assert_safe(problem, response)


def test_reverse_many_for_one_moves_two_source_parties():
    problem, plan = scene({"A": 4, "B": 4},
                          {"A": ("A", 2), "extra": ("A", 2), "B": ("B", 4)})
    response = ask(problem, plan, "A")
    reverse = next(o for o in response.options if o.kind == "reverse-many-for-one")
    assert {m.group_id for m in reverse.movements} == {"A", "extra", "B"}
    assert locate(reverse.plan)["B-0"] == "A"
    assert_safe(problem, response)


def test_split_is_opt_in_and_fractions_are_explicit():
    problem, plan = scene({"A": 3, "B": 2, "C": 1}, {"A": ("A", 3)})
    without_split = ask(problem, plan, "A")
    assert not any(o.kind == "split" for o in without_split.options)
    with_split = ask(problem, plan, "A", split=True)
    split = next(o for o in with_split.options if o.kind == "split")
    assert len([a for a in split.plan.assignments if a.group_id == "A"]) == 2
    assert "2/3" in split.title and "1/3" in split.title
    assert_safe(problem, with_split)


def test_three_way_chain_when_direct_swap_cannot_fit():
    problem, plan = scene({"A": 2, "B": 3, "C": 3},
                          {"A": ("A", 2), "B": ("B", 3), "C": ("C", 2)})
    response = ask(problem, plan, "A")
    chain = next(o for o in response.options if o.kind == "chain")
    assert {m.group_id for m in chain.movements} == {"A", "B", "C"}
    assert locate(chain.plan)["B-0"] == "C"
    assert locate(chain.plan)["C-0"] == "A"
    assert_safe(problem, response)


def test_infinite_pin_always_blocks_offered_move_and_names_rule():
    pin = Rule(id="pin-A", shape="pin", mode="hard",
               parameters={"target": "A", "table": "A"})
    problem, plan = scene({"A": 2, "B": 2}, {"A": ("A", 2)}, extra_rules=[pin])
    response = ask(problem, plan, "A")
    assert response.status == "blocked"
    assert not response.options
    assert "pin-A" in " ".join(response.blockers)


def test_hard_zone_and_capacity_never_bypassed_even_by_manual_instruction():
    zone = Rule(id="infinite-ground", shape="zone_restriction", mode="hard",
                parameters={"attribute": "role", "value": "A", "allowed_zones": ["ground"]})
    problem, plan = scene({"A": 2, "B": 2}, {"A": ("A", 2)}, extra_rules=[zone],
                          zones={"A": "ground", "B": "upstairs"})
    response = ask(problem, plan, "A")
    assert response.status == "blocked"
    assert not response.options
    assert "infinite-ground" in " ".join(response.blockers)
    # A physically impossible capacity request remains impossible even
    # when manual instructions explicitly demand the target.
    problem2, plan2 = scene({"A": 3, "B": 2}, {"A": ("A", 3)})
    blocked = ask(problem2, plan2, "A")
    assert blocked.status == "blocked"
    assert blocked.options == []


def test_soft_rule_warning_and_instruction_persists_until_removed():
    preference = Rule(id="prefer-ground", shape="zone_restriction", mode="soft",
                      weight=10, parameters={"attribute": "role", "value": "A",
                                             "allowed_zones": ["ground"]})
    problem, plan = scene({"A": 2, "B": 2}, {"A": ("A", 2)}, extra_rules=[preference],
                          zones={"A": "ground", "B": "upstairs"})
    offered = ask(problem, plan, "A")
    direct = next(o for o in offered.options if o.kind == "free-space")
    assert direct.score_delta == -20
    assert any("prefer-ground" in w for w in direct.soft_rule_warnings)
    assert_safe(problem, offered)
    instructed = problem.model_copy(deep=True)
    instructed.manual_instructions = direct.plan.manual_instructions
    again = solve(instructed)
    assert again.status in {"optimal", "feasible"}
    assert all(table == "B" for table in locate(again).values())
    assert again.manual_instructions[0].group_id == "A"
    instructed.manual_instructions = []  # User removed the stored direction.
    restored = solve(instructed)
    assert all(table == "A" for table in locate(restored).values())


def test_not_here_floor_and_api_contract():
    problem, plan = scene({"A": 2, "B": 2}, {"A": ("A", 2)},
                          zones={"A": "ground", "B": "upstairs"})
    response = ask(problem, plan, "A", table="ground", action="not_here",
                   place_type="floor")
    assert response.status == "available"
    assert all(locate(o.plan)["A-0"] == "B" for o in response.options)
    assert_safe(problem, response)
    client = TestClient(app)
    instruction = ManualInstruction(id="request-1", group_id="A", action="not_here",
                                    place_type="floor", place_id="ground")
    api = client.post("/v1/reassign/options", json={
        "problem": problem.model_dump(), "plan": plan.model_dump(),
        "instruction": instruction.model_dump()
    })
    assert api.status_code == 200, api.text
    assert api.json()["options"]
    assert api.json()["options"][0]["plan"]["manual_instructions"][0]["id"] == "request-1"


def test_stale_plan_rejected_instead_of_silently_dropping_directions():
    problem, plan = scene({"A": 2, "B": 2}, {"A": ("A", 2)})
    problem.manual_instructions = [ManualInstruction(
        id="old", group_id="A", action="not_here", place_type="table", place_id="B")]
    with pytest.raises(ValueError, match="Stored instructions changed"):
        ask(problem, plan, "A")
