"""Additional stress/strictness checks: performance goal and member restrictions."""
from __future__ import annotations

from time import perf_counter

from seating_optimizer import Guest, Problem, Rule, SolverConfig, Table, Zone, solve


def test_conflicting_member_zone_restrictions_name_both_rules():
    guests = [
        Guest(id="parent", name="Parent", group_id="party",
              attributes={"required_zone": "ground"}),
        Guest(id="child", name="Child", group_id="party",
              attributes={"required_zone": "upper"}),
    ]
    problem = Problem(
        session_id="strictest",
        zones=[Zone(id="ground", name="Ground"), Zone(id="upper", name="Upper")],
        tables=[Table(id="G", zone_id="ground", capacity=2),
                Table(id="U", zone_id="upper", capacity=2)],
        guests=guests,
        rules=[
            Rule(id="parent_ground", shape="zone_restriction", mode="hard",
                 parameters={"attribute": "required_zone", "value": "ground",
                             "zone": "ground"}),
            Rule(id="child_upper", shape="zone_restriction", mode="hard",
                 parameters={"attribute": "required_zone", "value": "upper",
                             "zone": "upper"}),
        ],
    )
    result = solve(problem)
    assert result.status == "infeasible"
    assert {"rule:parent_ground", "rule:child_upper"} <= set(result.conflicting_constraints)


def test_300_guest_performance_smoke():
    guests = [
        Guest(id=f"person-{i}", name=f"Person {i}",
              group_id=f"registration-{i // 4}",
              attributes={"language": "English" if i % 3 else "French"})
        for i in range(300)
    ]
    problem = Problem(
        session_id="performance-300",
        zones=[Zone(id="ground", name="Ground"), Zone(id="first", name="First")],
        tables=[Table(id=f"G-{i}", zone_id="ground", capacity=12) for i in range(15)]
             + [Table(id=f"F-{i}", zone_id="first", capacity=12) for i in range(15)],
        guests=guests,
        rules=[Rule(id="fill", shape="fill_efficiency", mode="soft", weight=3)],
        config=SolverConfig(time_limit_seconds=4, workers=8),
    )
    start = perf_counter()
    result = solve(problem)
    elapsed = perf_counter() - start
    print(f"SMOKE_300_SOLVE_SECONDS={result.solve_seconds:.3f} "
          f"SMOKE_300_WALL_SECONDS={elapsed:.3f} STATUS={result.status}", flush=True)
    assert result.status in ("feasible", "optimal"), result.message
    assert elapsed < 7.0
    assert sum(t.occupied for t in result.tables) == 300
    assert all(t.occupied <= t.capacity for t in result.tables)
    assert len(result.assignments) == 75
