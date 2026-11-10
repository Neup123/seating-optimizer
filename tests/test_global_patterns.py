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


def configuration_payload(rule_record):
    """Portable configuration: same Rule contract as the session solve API."""
    return {
        "version": 1, "name": "Pattern test venue",
        "zones": [{"id": "hall", "name": "Hall"}],
        "tables": [
            {"id": "T0", "zone_id": "hall", "capacity": 4},
            {"id": "T1", "zone_id": "hall", "capacity": 3},
        ],
        "layout": {"floors": [{
            "zone_id": "hall", "width": 400, "height": 300,
            "tables": [
                {"table_id": "T0", "x": 10, "y": 10, "width": 100, "height": 80},
                {"table_id": "T1", "x": 130, "y": 10, "width": 100, "height": 80},
            ],
        }]},
        "rules": [rule_record],
    }


def test_global_pattern_rejects_unknown_facts_bad_values_and_non_global_scope():
    for parameters in (
        {"enabled": True, "conditions": [clause("unknown", "==", 1)]},
        {"enabled": True, "conditions": [clause("empty_seats", "is", 1)]},
        {"enabled": True, "conditions": [clause("empty_seats", "==", -1)]},
        {"enabled": True, "conditions": []},
        {"enabled": True, "scope": "table", "conditions": [clause("empty_seats", "==", 1)]},
    ):
        record = {"id": "bad", "shape": "global_pattern", "mode": "soft",
                  "weight": 2, "parameters": parameters}
        with pytest.raises(ValueError):
            Rule.model_validate(record)
        payload = problem({"family": 1}, [2], []).model_dump(mode="json")
        payload["rules"] = [record]
        response = TestClient(app).post("/v1/solve", json=payload)
        assert response.status_code == 422, response.text


@pytest.mark.parametrize("value", ["", "not-a-number", -1, 2.5, True, None, "2", 100001])
def test_pattern_count_rejects_invalid_values_at_model_solve_and_configuration_api(value):
    record = {
        "id": "pattern", "shape": "global_pattern", "mode": "soft", "weight": 5,
        "parameters": {"scope": "global", "enabled": True, "effect": "penalty",
                       "conditions": [clause("groups_at_table", "==", value)]},
    }
    with pytest.raises(ValueError, match="nonnegative integer"):
        Rule.model_validate(record)
    client = TestClient(app)
    payload = problem({"family": 1}, [2], []).model_dump(mode="json")
    payload["rules"] = [record]
    response = client.post("/v1/solve", json=payload)
    assert response.status_code == 422, response.text
    configuration_response = client.post("/v1/configurations/validate",
                                         json=configuration_payload(record))
    assert configuration_response.status_code == 422, configuration_response.text


@pytest.mark.parametrize("value", [0, 17])
def test_pattern_count_accepts_nonnegative_integer_without_coercion(value):
    original = rule([clause("occupied_seats", ">=", value)], enabled=False)
    restored = Rule.model_validate_json(original.model_dump_json())
    assert type(restored.parameters["conditions"][0]["value"]) is int
    assert restored.parameters["conditions"][0]["value"] == value
    response = TestClient(app).post("/v1/configurations/validate",
                                    json=configuration_payload(original.model_dump(mode="json")))
    assert response.status_code == 200, response.text
    saved_value = response.json()["rules"][0]["parameters"]["conditions"][0]["value"]
    assert type(saved_value) is int and saved_value == value


def test_seeded_lonely_seat_pattern_round_trips_configuration_and_still_scores():
    seed = rule([clause("groups_at_table", "==", 1),
                 clause("empty_seats", "==", 1)], enabled=False, weight=5)
    response = TestClient(app).post("/v1/configurations/validate",
                                    json=configuration_payload(seed.model_dump(mode="json")))
    assert response.status_code == 200, response.text
    loaded = Rule.model_validate(response.json()["rules"][0])
    assert loaded.model_dump() == seed.model_dump()
    assert loaded.parameters["enabled"] is False
    loaded.parameters["enabled"] = True
    fixed = Rule(id="locked", shape="pin", mode="hard",
                 parameters={"target": "family", "table": "T0"})
    result = solve(problem({"family": 3}, [4, 3], [loaded, fixed]))
    assert result.status == "optimal"
    assert result.total_score == -5
    assert len(result.pattern_matches) == 1
    assert result.pattern_matches[0].table_id == "T0"
    assert result.pattern_matches[0].points == -5
    assert any(reason.rule_id == "pattern" and reason.points == -5
               for assignment in result.assignments for reason in assignment.reasons)
