"""Integrated 92-person upper-floor fixture from the original 230-guest finding.

Unlike candidate-score fixtures this leaves the 36-person clan unpinned and
asks both solver engines to place it. The 56 other upper-floor guests are
pinned to their known, arithmetically feasible four-table packing. This is
a deterministic subset regression, NOT a replay of the missing 230-person
production input or a whole-event performance benchmark.
"""
from __future__ import annotations

import pytest

from seating_optimizer import (
    FloorLayout, GenericProblem, GenericRule, Guest, Problem, Rule,
    SolverConfig, Table, TableDrawing, VenueLayout, Zone, solve, solve_generic,
)


def upper_floor_fixture():
    tables = [
        Table(id=f"U{i}", zone_id="upper", capacity=14 if i <= 4 else 12)
        for i in range(1, 8)
    ]
    guests = [
        Guest(id=f"clan-{i}", name=f"Clan member {i}", group_id="clan")
        for i in range(36)
    ]
    sizes = [8, 4, 2, 7, 7, 5, 5, 4, 5, 5, 4]
    # 8+4+2, 7+7, 5+5+4 and 5+5+4 each fill one 14-chair table.
    tables_for_parties = ["U1"] * 3 + ["U2"] * 2 + ["U3"] * 3 + ["U4"] * 3
    locks = {}
    for index, (size, table_id) in enumerate(zip(sizes, tables_for_parties)):
        for member in range(size):
            guest_id = f"other-{index}-{member}"
            guests.append(
                Guest(id=guest_id, name=f"Other {index} member {member}",
                      group_id=f"other-{index}")
            )
            locks[guest_id] = table_id

    layout = VenueLayout(floors=[
        FloorLayout(
            zone_id="upper", width=1150, height=140,
            tables=[
                TableDrawing(table_id=f"U{i}", x=(i - 1) * 155, y=0,
                             width=120, height=100)
                for i in range(1, 8)
            ],
        )
    ])
    return dict(
        session_id="upper-92-integration",
        zones=[Zone(id="upper", name="Upper")],
        tables=tables, layout=layout, guests=guests,
        locked_guest_tables=locks, splittable_groups=["clan"],
        config=SolverConfig(time_limit_seconds=12, workers=1, random_seed=42),
    )


@pytest.mark.parametrize("engine", ["v1", "v2"])
def test_clan_is_solved_into_three_clean_twelve_chair_tables(engine):
    inputs = upper_floor_fixture()
    if engine == "v1":
        rules = [
            Rule(id="split", shape="split_penalty", mode="soft", weight=1),
            Rule(id="mix", shape="split_mixing_penalty", mode="soft", weight=10),
        ]
        plan = solve(Problem(**inputs, rules=rules))
    else:
        rules = [
            GenericRule(id="split", name="Minimize splits",
                        engine="intra", mechanism="split_term",
                        mode="soft", polarity="penalty", weight=1),
            GenericRule(id="mix", name="Avoid mixing split clan",
                        engine="intra", mechanism="split_mixing_term",
                        mode="soft", polarity="penalty", weight=10),
        ]
        plan = solve_generic(GenericProblem(**inputs, rules=rules))

    assert plan.status == "optimal", plan.message
    clan = [a for a in plan.assignments if a.group_id == "clan"]
    assert {a.table_id for a in clan} == {"U5", "U6", "U7"}
    assert sorted(len(a.guest_ids) for a in clan) == [12, 12, 12]
    assert {a.table_id for a in plan.assignments if a.group_id != "clan"} == {
        "U1", "U2", "U3", "U4"
    }
    assert sum(t.occupied for t in plan.tables) == 92
    assert all(t.occupied == t.capacity for t in plan.tables)
    score = {item.rule_id: item.points for item in plan.score_breakdown}
    assert score["split"] == -2
    assert score["mix"] == 0
    assert plan.total_score == -2
    assert plan.total_score == sum(item.points for item in plan.score_breakdown)
