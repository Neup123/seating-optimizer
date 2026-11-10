"""Issue #67: instance metadata and universal disabled-rule semantics."""
from __future__ import annotations

import json
from copy import deepcopy

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from seating_optimizer import Guest, Problem, Rule, Table, Zone, solve
from seating_optimizer.api.app import app
from seating_optimizer.models import VenueConfiguration
from test_api_contract import validate


client = TestClient(app)


def scene(*rules: Rule):
    return Problem(
        session_id="instance-fields",
        zones=[Zone(id="z", name="Zone")],
        tables=[Table(id="A", zone_id="z", capacity=2),
                Table(id="B", zone_id="z", capacity=2)],
        guests=[
            Guest(id="a", name="Alice", group_id="alpha"),
            Guest(id="b", name="Bob", group_id="beta"),
        ], rules=list(rules))


def scored_rule(**overrides):
    value = {"id": "together", "name": "Seat these families together",
             "description": "For our own dinner event", "shape": "pair",
             "mode": "soft", "weight": 9,
             "parameters": {"left": "alpha", "right": "beta", "relation": "together"}}
    value.update(overrides)
    return Rule.model_validate(value)


def hard_pin(name, table, **overrides):
    data = {"id": name, "shape": "pin", "mode": "hard",
            "parameters": {"target": "alpha", "table": table}}
    data.update(overrides)
    return Rule.model_validate(data)


def all_rule_refs(plan):
    return {
        item.rule_id for item in plan.score_breakdown
    } | {r.rule_id for a in plan.assignments for r in a.reasons} | {
        item.rule_id for item in plan.compromises
    } | {match.rule_id for match in plan.pattern_matches} | set(plan.conflicting_constraints)


def test_disabled_soft_rule_scores_zero_and_disappears_from_all_explanations():
    active = scene(scored_rule())
    on = solve(active)
    assert on.status in {"feasible", "optimal"}
    assert on.total_score == 9
    assert "together" in all_rule_refs(on)
    assert on.score_breakdown[0].points == 9

    disabled = scene(scored_rule(enabled=False))
    off = solve(disabled)
    assert off.status in {"feasible", "optimal"}
    assert off.total_score == 0
    assert "together" not in all_rule_refs(off)
    assert all(entry.rule_id != "together" for entry in off.score_breakdown)
    assert disabled.rules[0].name == active.rules[0].name
    assert disabled.rules[0].description == active.rules[0].description
    assert disabled.rules[0].weight == active.rules[0].weight


def test_disabled_hard_rule_does_not_constrain_or_appear_in_conflicts():
    first = hard_pin("ground", "A")
    second = hard_pin("upper", "B")
    infeasible = solve(scene(first, second))
    assert infeasible.status == "infeasible"
    assert "rule:upper" in infeasible.conflicting_constraints

    freed = solve(scene(first, hard_pin("upper", "B", enabled=False)))
    assert freed.status in {"optimal", "feasible"}
    assert "upper" not in all_rule_refs(freed)
    assert "rule:upper" not in freed.conflicting_constraints
    assert next(a.table_id for a in freed.assignments if a.group_id == "alpha") == "A"
    # An inactive rule is also absent from parameter and target validation.
    missing = Rule(id="not-in-data", shape="pin", mode="hard",
                   parameters={"target": "ghost", "table": "not-a-table"},
                   enabled=False)
    assert solve(scene(first, missing)).status in {"optimal", "feasible"}


def _api_plan(problem):
    response = client.post("/v1/solve", json=problem)
    assert response.status_code == 200, response.text
    validate(response.json(), "Plan")
    return response.json()


def _api_assignment_score_bytes(plan):
    # Wall-clock duration is intentionally excluded: the rule contract's
    # byte-identical artifacts are the assignment records and score.
    return json.dumps({
        "assignments": plan["assignments"],
        "total_score": plan["total_score"],
        "score_breakdown": plan["score_breakdown"],
    }, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def test_api_disable_then_enable_reproduces_exact_original_assignment_and_score_bytes():
    payload = scene(
        hard_pin("fixed-alpha", "A"),
        Rule(id="fixed-beta", shape="pin", mode="hard",
             parameters={"target": "beta", "table": "B"}),
        Rule(id="apart", shape="pair", mode="soft", weight=7,
             name="Keep apart", description="The operator requested separate tables",
             parameters={"left": "alpha", "right": "beta", "relation": "apart"}),
    ).model_dump(mode="json")
    original = _api_plan(payload)
    assert original["total_score"] == 7
    off_payload = deepcopy(payload)
    off_payload["rules"][-1]["enabled"] = False
    off = _api_plan(off_payload)
    assert off["total_score"] == 0
    assert "apart" not in all_rule_refs(type("View", (), {
        "score_breakdown": [type("Item", (), x)() for x in off["score_breakdown"]],
        "assignments": [type("Ass", (), {
            "reasons": [type("Item", (), r)() for r in a["reasons"]]
        })() for a in off["assignments"]],
        "compromises": [], "pattern_matches": [],
        "conflicting_constraints": off["conflicting_constraints"]
    })())
    off_payload["rules"][-1]["enabled"] = True
    restored = _api_plan(off_payload)
    assert _api_assignment_score_bytes(restored) == _api_assignment_score_bytes(original)
    assert off_payload["rules"][-1]["name"] == "Keep apart"
    assert off_payload["rules"][-1]["description"] == "The operator requested separate tables"


def test_legacy_payload_defaults_enabled_and_displays_id_and_preserves_metadata():
    old = {"id": "legacy-language", "shape": "attribute_grouping",
           "mode": "soft", "weight": 4,
           "parameters": {"attribute": "language"}}
    rule = Rule.model_validate(old)
    assert rule.enabled is True
    assert rule.name == ""
    assert rule.description == ""
    assert rule.display_name == "legacy-language"
    assert Rule.model_validate({**old, "name": "  "}).display_name == "legacy-language"
    assert Rule.model_validate({**old, "name": "A note"}).display_name == "A note"
    assert rule.model_dump()["enabled"] is True
    payload = scene(rule).model_dump(mode="json")
    payload["rules"] = [old]  # Exact legacy request, fields omitted.
    plan = _api_plan(payload)
    assert plan["status"] in {"optimal", "feasible"}

    config = {
        "version": 1, "name": "Dinner",
        "zones": [{"id": "z", "name": "Zone"}],
        "tables": [{"id": "A", "zone_id": "z", "capacity": 2}],
        "layout": {"floors": [{"zone_id": "z", "width": 180, "height": 150,
                              "tables": [{"table_id": "A", "x": 10, "y": 10,
                                          "width": 80, "height": 80}]}]},
        "rules": [old],
    }
    response = client.post("/v1/configurations/validate", json=config)
    assert response.status_code == 200, response.text
    assert response.json()["rules"][0]["enabled"] is True
    assert response.json()["rules"][0]["name"] == ""
    assert response.json()["rules"][0]["description"] == ""
    config["rules"][0] = {**old, "name": " Custom title  ",
                           "description": "Keep this note\nas entered.", "enabled": False}
    edited = client.post("/v1/configurations/validate", json=config)
    assert edited.status_code == 200, edited.text
    validate(edited.json(), "VenueConfiguration")
    assert edited.json()["rules"][0]["name"] == " Custom title  "
    assert edited.json()["rules"][0]["description"] == "Keep this note\nas entered."
    assert edited.json()["rules"][0]["enabled"] is False
    assert VenueConfiguration.model_validate_json(edited.text).rules[0].display_name == "Custom title"


def test_disabled_pattern_bypasses_rule_specific_validation_and_score():
    inactive = Rule.model_validate({
        "id": "pattern-off", "shape": "global_pattern", "mode": "soft",
        "weight": 3, "parameters": {"scope": "invalid"},
        "enabled": False,
    })
    result = solve(scene(inactive))
    assert result.status in {"feasible", "optimal"}
    assert result.total_score == 0
    assert not any(x.rule_id == "pattern-off" for x in result.score_breakdown)
    with pytest.raises(ValidationError):
        Rule.model_validate({**inactive.model_dump(), "enabled": True})


def test_enabled_flag_is_strict_boolean_and_inactive_configuration_is_preserved():
    with pytest.raises(ValidationError):
        Rule.model_validate({**scored_rule().model_dump(), "enabled": "false"})
    with pytest.raises(ValidationError):
        Rule.model_validate({**scored_rule().model_dump(), "enabled": None})
    disabled = scored_rule(enabled=False)
    payload = disabled.model_dump(mode="json")
    assert payload["enabled"] is False
    assert Rule.model_validate(payload).model_dump(mode="json") == payload
    assert disabled.name == "Seat these families together"
    assert disabled.weight == 9
