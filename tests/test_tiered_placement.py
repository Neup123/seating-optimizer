"""Issue #71: preference tiers are feasibility stages, not purchasable score terms."""
from __future__ import annotations

from copy import deepcopy

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from seating_optimizer import Guest, Problem, Rule, SolverConfig, Table, Zone, solve
from seating_optimizer.api.app import app
from test_api_contract import validate


def family(group: str, size: int, *, category: str = "") -> list[Guest]:
    return [Guest(id=f"{group}-{i}", name=f"{group} {i}", group_id=group,
                  attributes={"category": category} if category else {})
            for i in range(size)]


def tiers(*levels: dict, target: str = "main", rule_id: str = "tier") -> Rule:
    return Rule(id=rule_id, shape="tiered_placement", mode="staged", weight=None,
                parameters={"target": target, "tiers": list(levels)})


def zone(name: str) -> dict:
    return {"zones": [name], "tables": []}


def table(name: str) -> dict:
    return {"zones": [], "tables": [name]}


def preferred_lower(weight=1000):
    return Rule(id="lower-soft", shape="zone_restriction", mode="soft", weight=weight,
                parameters={"attribute": "category", "value": "main", "zone": "lower"})


def pin(group: str, table_id: str):
    return Rule(id=f"pin-{group}", shape="pin", mode="hard",
                parameters={"target": group, "table": table_id})


def scene(*, target=8, other=0, upper=8, lower=8,
          more_upper=None, rules=(), allow_split=False):
    tables = [Table(id="U", zone_id="upper", capacity=upper),
              Table(id="L", zone_id="lower", capacity=lower)]
    if more_upper:
        tables += [Table(id="U2", zone_id="upper", capacity=more_upper)]
    guests = family("main", target, category="main") + family("fixed", other)
    return Problem(
        session_id="tiered-session",
        zones=[Zone(id="upper", name="Floor 2"), Zone(id="lower", name="Floor 1")],
        tables=tables, guests=guests, rules=list(rules),
        splittable_groups=["main"] if allow_split else [],
        config=SolverConfig(time_limit_seconds=6, workers=1, random_seed=42))


def at(plan, group="main"):
    return [entry.table_id for entry in plan.assignments if entry.group_id == group]


def tier_reason(plan, rule_id="tier"):
    return [reason for entry in plan.assignments if entry.group_id == "main"
            for reason in entry.reasons if reason.rule_id == rule_id]


def assert_whole(plan, table_id):
    assert plan.status in {"optimal", "feasible"}, plan.message
    entries = [entry for entry in plan.assignments if entry.group_id == "main"]
    assert len(entries) == 1, "No tier overflow may divide a whole group"
    assert entries[0].table_id == table_id
    assert entries[0].guest_ids == [f"main-{i}" for i in range(8)]


def test_tier_one_is_absolutely_prior_to_huge_soft_rewards():
    prefer = tiers(zone("upper"), zone("lower"))
    p = scene(rules=[preferred_lower(weight=100_000), prefer])
    chosen = solve(p)
    assert_whole(chosen, "U")
    assert chosen.total_score == 0
    assert {r.rule_id for r in tier_reason(chosen)} == {"tier"}
    assert all(r.points == 0 for r in tier_reason(chosen))
    assert "tier" not in {row.rule_id for row in chosen.score_breakdown}
    assert "tier 1" in tier_reason(chosen)[0].description

    # The same ordinary scoring with no preference remains free to collect
    # its soft points instead: tiers cannot be bought off, regardless of size.
    baseline = solve(scene(rules=[preferred_lower(weight=100_000)]))
    assert_whole(baseline, "L")
    assert baseline.total_score == 800_000


def test_overflow_when_preferred_floor_has_no_room_and_entire_party_moves():
    p = scene(other=8, rules=[pin("fixed", "U"),
                              tiers(zone("upper"), zone("lower"))])
    chosen = solve(p)
    assert_whole(chosen, "L")
    assert at(chosen, "fixed") == ["U"]
    assert "tier 2" in tier_reason(chosen)[0].description
    assert chosen.total_score == 0


@pytest.mark.parametrize("allow_split", [False, True])
def test_only_small_holes_remain_on_floor_two_so_eight_move_whole_to_floor_one(allow_split):
    # Floor 2: U has 8 places, 3 are locked to another group. Its remaining
    # five real seats cannot accept an atomic group of 8. Floor 1 has 8.
    p = scene(other=3, rules=[pin("fixed", "U"),
                              tiers(zone("upper"), zone("lower"))],
              allow_split=allow_split)
    chosen = solve(p)
    assert_whole(chosen, "L")
    assert at(chosen, "fixed") == ["U"]
    assert chosen.tables[0].empty_seats == 5
    assert chosen.total_score == 0


@pytest.mark.parametrize("allow_split", [False, True])
def test_reversed_negative_direction_keeps_floor_one_last_until_needed(allow_split):
    # "Not on floor 1" means upper first, floor 1 last. Even a significant
    # soft gain on the lower floor may not pull the group down while upper fits.
    rule = tiers(zone("upper"), zone("lower"))
    first = solve(scene(rules=[preferred_lower(900), rule], allow_split=allow_split))
    assert_whole(first, "U")
    # Once another family takes the upper seats, the whole group moves down.
    second = solve(scene(other=8, rules=[pin("fixed", "U"), rule],
                         allow_split=allow_split))
    assert_whole(second, "L")


def test_specific_tables_and_mixed_locations_use_union_and_explicit_order():
    rule = tiers({"zones": [], "tables": ["U"]},
                 {"zones": ["lower"], "tables": ["U2"]})
    p = scene(target=8, upper=5, more_upper=8, rules=[
        rule,
        Rule(id="scenic", shape="table_property_need", mode="soft", weight=4,
             parameters={"attribute": "category", "value": "main", "property": "scenic"}),
    ])
    p.tables[2].properties = ["scenic"]
    result = solve(p)
    # U alone is too small, U2 is available in the next tier.
    assert_whole(result, "U2")
    assert "tier 2" in tier_reason(result)[0].description


def test_unlisted_locations_are_only_an_implicit_last_resort_not_hard_exclusion():
    p = scene(other=8, rules=[pin("fixed", "U"), tiers(zone("upper"))])
    plan = solve(p)
    assert_whole(plan, "L")
    assert "tier 2" in tier_reason(plan)[0].description


def test_no_instance_no_effect_and_ordinary_soft_score_is_unchanged():
    p = scene(rules=[preferred_lower(9)])
    before = solve(p)
    assert_whole(before, "L")
    assert before.total_score == 72
    assert [r.rule_id for r in before.score_breakdown] == ["lower-soft"]
    no_op = solve(Problem.model_validate(p.model_dump(mode="json")))
    assert no_op.assignments == before.assignments
    assert no_op.score_breakdown == before.score_breakdown
    assert no_op.total_score == before.total_score
    # Adding then removing a tier instance restores the exact old outcome.
    p.rules.append(tiers(zone("upper"), zone("lower")))
    changed = solve(p)
    assert_whole(changed, "U")
    p.rules.pop()
    after = solve(p)
    assert after.assignments == before.assignments
    assert after.score_breakdown == before.score_breakdown
    assert after.total_score == before.total_score


def test_scores_still_decide_which_table_to_use_within_same_tier():
    p = scene(upper=8, more_upper=8, rules=[
        Rule(id="fav-property", shape="table_property_need", mode="soft", weight=10,
             parameters={"attribute": "category", "value": "main", "property": "scenic"}),
        tiers({"zones": ["upper"], "tables": []}, zone("lower")),
    ])
    # The preference covers both upper tables. Only U2 has the scenery tag.
    p.tables[2].properties = ["scenic"]
    result = solve(p)
    assert_whole(result, "U2")
    assert result.total_score == 80
    assert result.score_breakdown[0].rule_id == "fav-property"


def test_candidate_is_checked_against_all_hard_rules_not_just_raw_capacity():
    # Both floors have eight chairs, but the hard zone rule prohibits the
    # affected family from entering upper at all.
    blocked = Rule(id="hard-zone", shape="zone_restriction", mode="hard",
                   parameters={"attribute": "category", "value": "main",
                               "zone": "lower"})
    result = solve(scene(rules=[blocked, tiers(zone("upper"), zone("lower"))]))
    assert_whole(result, "L")
    assert "tier 2" in tier_reason(result)[0].description


def test_two_independent_tier_instances_follow_explicit_rule_instance_order():
    p = scene(target=8, other=8, rules=[
        tiers(zone("upper"), zone("lower"), target="main", rule_id="first"),
        tiers(zone("upper"), zone("lower"), target="fixed", rule_id="second"),
    ])
    result = solve(p)
    assert_whole(result, "U")
    assert at(result, "fixed") == ["L"]


@pytest.mark.parametrize("invalid", [
    {"target": "main", "tiers": []},
    {"target": "", "tiers": [zone("upper")]},
    {"target": "main", "tiers": [{"zones": [], "tables": []}]},
    {"target": "main", "tiers": [{"zones": ["upper"], "tables": ["U", "U"]}]},
    {"target": "main", "tiers": [{"zones": 12}]},
    {"target": "main", "tiers": [{"zones": ["upper"], "tables": [], "weight": 20}]},
])
def test_invalid_tier_configuration_is_rejected_in_rule_model(invalid):
    with pytest.raises(ValidationError):
        Rule.model_validate({"id": "tier", "shape": "tiered_placement",
                             "mode": "staged", "weight": None, "parameters": invalid})


@pytest.mark.parametrize("bad", ["unknown target", "unknown zone", "unknown table"])
def test_unknown_references_are_rejected_by_solve_validation(bad):
    params = {"target": "main", "tiers": [zone("upper")]}
    if bad == "unknown target":
        params["target"] = "missing"
    elif bad == "unknown zone":
        params["tiers"] = [zone("elsewhere")]
    else:
        params["tiers"] = [table("missing-table")]
    p = scene(rules=[Rule(id="tier", shape="tiered_placement",
                          mode="staged", parameters=params)])
    with pytest.raises(ValueError):
        solve(p)
    response = client.post("/v1/solve", json=p.model_dump(mode="json"))
    assert response.status_code == 422


def test_staged_rule_shape_and_weight_not_interchangeable_with_soft_or_hard():
    for mode, weight in (("hard", None), ("soft", 4), ("staged", 4)):
        with pytest.raises(ValidationError):
            Rule(id="bad", shape="tiered_placement", mode=mode, weight=weight,
                 parameters={"target": "main", "tiers": [zone("upper")]})
    with pytest.raises(ValidationError):
        Rule(id="bad", shape="pair", mode="staged",
             parameters={"left": "main", "right": "fixed", "relation": "apart"})


def test_api_rule_catalog_contract_round_trip_and_staged_solve():
    catalog = client.get("/v1/rules/catalog")
    assert catalog.status_code == 200
    validate(catalog.json(), "RuleCatalog")
    spec = next(shape for shape in catalog.json()["shapes"] if shape["shape"] == "tiered_placement")
    assert spec["modes"] == ["staged"]
    assert spec["default_mode"] == "staged"
    assert spec["default_weight"] is None
    assert {item["kind"] for item in spec["fields"]} == {"target", "tiers"}

    p = scene(rules=[preferred_lower(300), tiers(zone("upper"), zone("lower"))])
    wire = p.model_dump(mode="json")
    validate(wire, "Problem")
    api = client.post("/v1/solve", json=wire)
    assert api.status_code == 200, api.text
    assert api.json()["status"] in {"feasible", "optimal"}
    validate(api.json(), "Plan")
    assert next(a["table_id"] for a in api.json()["assignments"] if a["group_id"] == "main") == "U"
    assert api.json()["total_score"] == 0
