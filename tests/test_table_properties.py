"""Guest-driven table property rules: tags never score on their own."""
from __future__ import annotations

import base64
import json

import pytest
from fastapi.testclient import TestClient

from seating_optimizer import (
    Guest, Problem, Rule, SolverConfig, Table, TableDrawing, VenueLayout, Zone,
    import_layout, solve,
)
from seating_optimizer.api.app import app
from test_api_contract import spec, validate

client = TestClient(app)


def guests():
    return [
        Guest(id="wheelchair", name="Wheelchair guest", group_id="family",
              attributes={"mobility": "wheelchair"}),
        Guest(id="escort", name="Escort", group_id="family", attributes={"mobility": "mobile"}),
        Guest(id="other", name="Another guest", attributes={"mobility": "mobile"}),
    ]


def tables(tagged=True, accessible_capacity=2):
    return [
        Table(id="A", zone_id="hall", capacity=accessible_capacity,
              properties=["accessible", "aisle-edge"] if tagged else []),
        Table(id="B", zone_id="hall", capacity=4, properties=["quiet"] if tagged else []),
    ]


def need(*, mode="soft", weight=9):
    return Rule(
        id="mobility-needs-accessible",
        shape="table_property_need", mode=mode,
        weight=weight if mode == "soft" else None,
        parameters={"attribute": "mobility", "value": "wheelchair", "property": "accessible"},
    )


def problem(*, tags=True, rules=(), accessible_capacity=2):
    return Problem(
        session_id="needs-from-guests",
        zones=[Zone(id="hall", name="Main hall")],
        tables=tables(tags, accessible_capacity),
        guests=guests(), rules=list(rules),
        config=SolverConfig(time_limit_seconds=3, workers=1, random_seed=42),
    )


def assignments(plan):
    return {guest_id: assignment.table_id
            for assignment in plan.assignments for guest_id in assignment.guest_ids}


def test_soft_need_earns_only_guest_weight_and_keeps_family_together():
    result = solve(problem(rules=[need(weight=9)]))
    assert result.status in ("feasible", "optimal"), result.conflicting_constraints
    assert assignments(result)["wheelchair"] == assignments(result)["escort"] == "A"
    assert result.total_score == 9  # One affected guest, not two family members or two tags.
    assert result.score_breakdown[0].points == 9
    group = next(a for a in result.assignments if a.group_id == "family")
    reason = next(r for r in group.reasons if r.rule_id == "mobility-needs-accessible")
    assert reason.points == 9
    assert "Guest need mobility=wheelchair" in reason.description
    assert "property accessible" in reason.description
    assert not result.compromises


def test_soft_need_unmet_reports_exact_lost_guest_points():
    pin = Rule(id="force-other", shape="pin", mode="hard",
               parameters={"target": "wheelchair", "table": "B"})
    result = solve(problem(rules=[need(weight=7), pin]))
    assert result.status in ("feasible", "optimal")
    assert assignments(result)["wheelchair"] == assignments(result)["escort"] == "B"
    assert result.total_score == 0
    assert [item.points for item in result.score_breakdown] == [0]
    loss = next(comp for comp in result.compromises if comp.rule_id == "mobility-needs-accessible")
    assert loss.lost_points == 7
    assert "family" in loss.description and "accessible" in loss.description
    reason = next(reason for assignment in result.assignments
                  for reason in assignment.reasons if reason.rule_id == "mobility-needs-accessible")
    assert reason.points == 0
    assert "7 preference points unavailable" in reason.description


def test_hard_need_requires_tag_for_all_matching_group_members():
    result = solve(problem(rules=[need(mode="hard")]))
    assert result.status in ("feasible", "optimal")
    assert assignments(result)["wheelchair"] == assignments(result)["escort"] == "A"
    assert result.total_score == 0  # Hard rules do not carry points.
    reason = next(reason for assignment in result.assignments
                  for reason in assignment.reasons if reason.rule_id == "mobility-needs-accessible")
    assert reason.points == 0
    assert "Guest need" in reason.description


def test_hard_need_reports_infeasible_when_only_tagged_table_too_small():
    result = solve(problem(rules=[need(mode="hard")], accessible_capacity=1))
    assert result.status == "infeasible"
    assert any("rule:mobility-needs-accessible" == name
               for name in result.conflicting_constraints)
    assert not result.assignments
    assert "No plan satisfies" in result.message

    untagged = solve(problem(tags=False, rules=[need(mode="hard")]))
    assert untagged.status == "infeasible"
    assert "rule:mobility-needs-accessible" in untagged.conflicting_constraints


def test_unreferenced_properties_never_change_score_or_placement():
    plain = solve(problem(tags=False))
    tagged = solve(problem(tags=True))
    assert (plain.status, plain.total_score) == (tagged.status, tagged.total_score)
    assert assignments(plain) == assignments(tagged)
    assert plain.score_breakdown == tagged.score_breakdown == []
    assert plain.compromises == tagged.compromises == []
    assert all(not any(r.rule_id == "mobility-needs-accessible" for r in a.reasons)
               for a in tagged.assignments)

    another = Rule(id="prefer-same", shape="attribute_grouping", mode="soft",
                   weight=3, parameters={"attribute": "mobility"})
    plain_rule = solve(problem(tags=False, rules=[another]))
    tagged_rule = solve(problem(tags=True, rules=[another]))
    assert plain_rule.total_score == tagged_rule.total_score
    assert assignments(plain_rule) == assignments(tagged_rule)


def test_layout_json_and_solver_tables_roundtrip_properties_independently():
    layout = {
        "floors": [{"zone_id": "hall", "width": 400, "height": 300,
                    "tables": [{"table_id": "A", "x": 10, "y": 20,
                                "width": 120, "height": 100,
                                "properties": ["Accessible", "aisle-edge"]},
                               {"table_id": "B", "x": 155, "y": 20,
                                "width": 120, "height": 100, "properties": []}]}],
    }
    raw = json.dumps(layout).encode()
    parsed = import_layout(raw, "main-hall.json")
    assert parsed.floors[0].tables[0].properties == ["Accessible", "aisle-edge"]
    assert json.loads(parsed.model_dump_json())["floors"][0]["tables"][0]["properties"] == [
        "Accessible", "aisle-edge"
    ]
    request = {"files": [{"filename": "main-hall.json",
                          "content_base64": base64.b64encode(raw).decode()}]}
    imported = client.post("/v1/layouts/import", json=request)
    assert imported.status_code == 200, imported.text
    assert imported.json()["floors"][0]["tables"][0]["properties"] == ["Accessible", "aisle-edge"]
    validate(imported.json(), "VenueLayout")
    # Properties are passive and case-insensitive; solver reads Table properties,
    # not geometry, and never derives weight from either tag.
    p = problem(rules=[need()])
    p.tables[0].properties = ["Accessible", "aisle-edge"]
    assert solve(p).total_score == 9
    assert Table.model_validate(p.tables[0].model_dump()).properties == ["Accessible", "aisle-edge"]


def test_invalid_tags_and_guest_need_rule_parameters_are_rejected():
    for tags in (["", "accessible"], ["accessible", "Accessible"], ["   "]):
        with pytest.raises(ValueError, match="Table property|Duplicate table"):
            Table(id="A", zone_id="hall", capacity=2, properties=tags)
        with pytest.raises(ValueError, match="Table property|Duplicate table"):
            TableDrawing(table_id="A", x=0, y=0, width=100, height=100, properties=tags)

    missing_property = Rule(id="invalid", shape="table_property_need", mode="soft",
                            weight=2, parameters={"attribute": "mobility"})
    with pytest.raises(ValueError, match="invalid.*parameter|property"):
        solve(problem(rules=[missing_property]))

    empty_attribute = Rule(id="invalid", shape="table_property_need", mode="hard",
                           parameters={"attribute": "", "property": "accessible"})
    with pytest.raises(ValueError, match="nonempty attribute"):
        solve(problem(rules=[empty_attribute]))


def test_documented_table_tag_and_guest_need_contracts_match_api():
    document = spec()
    for schema in ("Table", "TableDrawing"):
        assert document["components"]["schemas"][schema]["properties"]["properties"]["items"]["type"] == "string"
    assert "table_property_need" in document["components"]["schemas"]["Rule"]["properties"]["shape"]["enum"]
    response = client.get("/v1/rules/catalog")
    assert response.status_code == 200
    catalog = response.json()["shapes"]
    matched = next(shape for shape in catalog if shape["shape"] == "table_property_need")
    assert set(matched["modes"]) == {"hard", "soft"}
    assert {field["name"] for field in matched["fields"]} == {"attribute", "value", "property"}
    validate(response.json(), "RuleCatalog")
    plan = problem(rules=[need()])
    result = client.post("/v1/solve", json=plan.model_dump(mode="json"))
    assert result.status_code == 200, result.text
    validate(result.json(), "Plan")
    assert result.json()["total_score"] == 9
