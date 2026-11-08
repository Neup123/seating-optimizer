"""Deterministic 120-guest golden event spanning two floors."""
from __future__ import annotations

from time import perf_counter

from seating_optimizer import Guest, Problem, Rule, SolverConfig, Table, Zone, solve


def golden_problem() -> Problem:
    languages = ["English", "French", "Spanish"]
    guests = []
    for family in range(60):
        for member in range(2):
            mobility = "wheelchair" if family == 7 and member == 0 else "mobile"
            guests.append(Guest(
                id=f"guest-{family:02d}-{member}",
                name=f"Guest {family:02d} member {member}",
                group_id=f"family-{family:02d}",
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
