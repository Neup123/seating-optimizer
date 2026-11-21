"""Unrestricted-search proof of split priority over arbitrarily large soft terms.

This is not a locked candidate score comparison: CP-SAT is free to choose
any placement and must prefer TWO connected portions over THREE.
"""
from __future__ import annotations

from seating_optimizer import (
    FloorLayout, GenericProblem, GenericRule, Guest, Problem, Rule,
    SolverConfig, Table, TableDrawing, VenueLayout, Zone, solve, solve_generic,
)


def fixture():
    tables=[Table(id=t,zone_id="z",capacity=3,properties=[t]) for t in ["A","B","C"]]
    layout=VenueLayout(floors=[FloorLayout(zone_id="z",width=300,height=120,tables=[
        TableDrawing(table_id=t,x=i*95,y=0,width=80,height=80)
        for i,t in enumerate(["A","B","C"])
    ])])
    guests=[Guest(id=f"{t}{i}",name=f"Clan {t}{i}",group_id="clan",
                  attributes={"favorite":t}) for t in "ABC" for i in range(2)]
    config=SolverConfig(time_limit_seconds=10,workers=1,random_seed=42)
    return [Zone(id="z",name="Z")],tables,layout,guests,config


def portions(plan):
    assert plan.status in {"optimal","feasible"}, plan.conflicting_constraints
    used={a.table_id for a in plan.assignments if a.group_id=="clan"}
    assert sum(len(a.guest_ids) for a in plan.assignments)==6
    assert plan.total_score==sum(item.points for item in plan.score_breakdown)
    return len(used)


def test_v1_unrestricted_search_prefers_two_portions_over_enormous_normal_weight():
    zones,tables,layout,guests,config=fixture()
    rules=[Rule(id="few-splits",shape="split_penalty",mode="soft",weight=1)]
    rules += [Rule(id=f"prefer-{t}",shape="table_property_need",mode="soft",weight=100_000,
                   parameters={"attribute":"favorite","value":t,"property":t}) for t in "ABC"]
    problem=Problem(session_id="v1-search",zones=zones,tables=tables,layout=layout,
                    guests=guests,rules=rules,config=config)
    result=solve(problem)
    assert result.status=="optimal",result.message
    assert portions(result)==2
    assert "globally minimal" in result.message


def test_v2_unrestricted_search_prefers_two_portions_over_enormous_normal_weight():
    zones,tables,layout,guests,config=fixture()
    rules=[GenericRule(id="few-splits",name="Avoid split portions",engine="intra",
                       mechanism="split_term",mode="soft",polarity="penalty",weight=1)]
    rules += [GenericRule(id=f"prefer-{t}",name=f"Prefer {t}",engine="venue",
             mechanism="property_need",mode="soft",polarity="penalty",weight=100_000,
             criterion={"subject":"guest","field":"favorite","op":"==","value":t},
             property=t) for t in "ABC"]
    result=solve_generic(GenericProblem(session_id="v2-search",zones=zones,tables=tables,
                         layout=layout,guests=guests,rules=rules,config=config))
    assert result.status=="optimal",result.message
    assert portions(result)==2
    assert "globally minimized" in result.message


def test_no_split_priority_rule_keeps_objective_exact_without_hidden_weights():
    zones,tables,layout,guests,config=fixture()
    rules=[Rule(id=f"prefer-{t}",shape="table_property_need",mode="soft",weight=100_000,
                parameters={"attribute":"favorite","value":t,"property":t}) for t in "ABC"]
    result=solve(Problem(session_id="no-split-rule",zones=zones,tables=tables,
                         layout=layout,guests=guests,rules=rules,config=config))
    assert result.status=="optimal"
    assert portions(result)==3
