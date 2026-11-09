"""Generic global-pattern rules: multiple editable patterns, not hard-coded examples."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from seating_optimizer import Guest, Problem, Rule, SolverConfig, Table, Zone, solve
from seating_optimizer.api.app import app


def rule(conditions, *, effect="penalty", enabled=True, weight=7):
    return Rule(id="pattern", shape="global_pattern", mode="soft", weight=weight,
                parameters={"scope": "global", "enabled": enabled, "effect": effect,
                            "conditions": conditions})


def clause(fact, op, value):
    return {"fact": fact, "op": op, "value": value}


def problem(group_sizes, capacities, rules):
    guests = [
        Guest(id=f"{gid}-{i}", name=f"{gid} {i}", group_id=gid)
        for gid, count in group_sizes.items() for i in range(count)
    ]
    return Problem(session_id="pattern-test",
        zones=[Zone(id="hall", name="Hall")],
        tables=[Table(id=f"T{i}", zone_id="hall", capacity=capacity)
                for i, capacity in enumerate(capacities)],
        guests=guests, rules=rules, config=SolverConfig(workers=1))


def test_lonely_last_seat_avoided_when_equal_alternative_exists():
    lonely = rule([clause("groups_at_table", "==", 1),
                   clause("empty_seats", "==", 1)], weight=9)
    p = problem({"family": 3}, [4, 3], [lonely])
    out = solve(p)
    assert out.status == "optimal"
    assert out.assignments[0].table_id == "T1"
    assert out.total_score == 0
    assert out.pattern_matches == []
    assert out.score_breakdown[0].points == 0


def test_lonely_last_seat_penalty_reports_matching_table_and_compromise():
    lonely = rule([clause("groups_at_table", "==", 1),
                   clause("empty_seats", "==", 1)], weight=5)
    fixed = Rule(id="locked", shape="pin", mode="hard",
                 parameters={"target": "family", "table": "T0"})
    plan = solve(problem({"family": 3}, [4, 3], [lonely, fixed]))
    assert plan.status == "optimal"
    assert plan.total_score == -5
    assert next(x for x in plan.score_breakdown if x.rule_id == "pattern").points == -5
    assert len(plan.pattern_matches) == 1
    assert plan.pattern_matches[0].table_id == "T0"
    assert plan.pattern_matches[0].points == -5
    assert any(c.rule_id == "pattern" and c.lost_points == 5 for c in plan.compromises)
    assert any(r.rule_id == "pattern" and r.points == -5 for a in plan.assignments for r in a.reasons)


def test_different_pattern_reward_without_adding_solver_code():
    # Distinct example: reward a table with at least TWO groups and TWO used chairs.
    prefer_mixed = rule([clause("groups_at_table", ">=", 2),
                         clause("occupied_seats", ">=", 2)],
                        effect="reward", weight=11)
    out = solve(problem({"alpha": 1, "beta": 1}, [2, 2], [prefer_mixed]))
    assert out.status == "optimal"
    assert len({a.table_id for a in out.assignments}) == 1
    assert out.total_score == 11
    assert len(out.pattern_matches) == 1 and out.pattern_matches[0].points == 11
    assert out.score_breakdown == [out.score_breakdown[0]]
    assert out.score_breakdown[0].points == 11
    assert abs(sum(a.points for a in out.assignments) - 11) < .001


def test_off_by_default_and_no_pattern_are_neutral():
    conditions = [clause("groups_at_table", "==", 1),
                  clause("empty_seats", "==", 1)]
    off = rule(conditions, enabled=False)
    missing_enabled = Rule(id="default-off", shape="global_pattern",
                           mode="soft", weight=7,
                           parameters={"scope": "global", "effect": "penalty",
                                       "conditions": conditions})
    for rules in ([], [off], [missing_enabled]):
        out = solve(problem({"family": 3}, [4, 3], rules))
        assert out.status == "optimal"
        assert out.total_score == 0
        assert out.pattern_matches == []


def test_global_pattern_rejects_unknown_facts_bad_values_and_non_global_scope():
    for parameter in (
        {"enabled": True, "conditions": [clause("unknown", "==", 1)]},
        {"enabled": True, "conditions": [clause("empty_seats", "is", 1)]},
        {"enabled": True, "conditions": [clause("empty_seats", "==", -1)]},
        {"enabled": True, "conditions": []},
        {"enabled": True, "scope": "table", "conditions": [clause("empty_seats", "==", 1)]},
    ):
        bad = Rule(id="bad", shape="global_pattern", mode="soft", weight=2, parameters=parameter)
        with pytest.raises(ValueError):
            solve(problem({"family": 1}, [2], [bad]))
        response = TestClient(app).post("/v1/solve",
            json=problem({"family": 1}, [2], [bad]).model_dump(mode="json"))
        assert response.status_code == 422, response.text
