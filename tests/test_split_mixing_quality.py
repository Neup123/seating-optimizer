"""Unrestricted mixed-table quality: only a genuinely split party is penalized.

Three-table case has a clean arrangement; two-table case forces one
unwanted connection, producing an exact negative score.
"""
from __future__ import annotations
from seating_optimizer import (
    FloorLayout, GenericProblem, GenericRule, Guest, Problem, Rule,
    SolverConfig, Table, TableDrawing, VenueLayout, Zone, solve, solve_generic
)


def scene(table_count=3):
    tables=[Table(id=f"T{i}",zone_id="z",capacity=4) for i in range(table_count)]
    layout=VenueLayout(floors=[FloorLayout(zone_id="z",width=600,height=120,tables=[
        TableDrawing(table_id=f"T{i}",x=i*160,y=0,width=120,height=90)
        for i in range(table_count)
    ])])
    guests=[Guest(id=f"c{i}",name=f"Clan {i}",group_id="clan") for i in range(6)]
    guests += [Guest(id="o1",name="Guest O1",group_id="other"),
               Guest(id="o2",name="Guest O2",group_id="other")]
    return dict(session_id="quality",zones=[Zone(id="z",name="Z")],
                tables=tables,layout=layout,guests=guests,
                config=SolverConfig(time_limit_seconds=8,workers=1,random_seed=42))


def compare(plan, forced):
    assert plan.status=="optimal",plan.message
    clan_tables={a.table_id for a in plan.assignments if a.group_id=="clan"}
    others={a.table_id for a in plan.assignments if a.group_id=="other"}
    assert len(clan_tables)==2
    assert len(others)==1
    assert (len(clan_tables & others)==1) is forced
    assert plan.total_score==(-11 if forced else -1)
    assert plan.total_score==sum(b.points for b in plan.score_breakdown)


def test_v1_prefers_whole_extra_table_to_avoidable_split_mixing():
    rules=[Rule(id="split",shape="split_penalty",mode="soft",weight=1),
           Rule(id="mix",shape="split_mixing_penalty",mode="soft",weight=10)]
    for forced in [False,True]:
        plan=solve(Problem(**scene(2 if forced else 3),rules=rules))
        compare(plan,forced)


def test_v2_prefers_whole_extra_table_to_avoidable_split_mixing():
    rules=[GenericRule(id="split",name="Avoid split",engine="intra",mechanism="split_term",
                       mode="soft",polarity="penalty",weight=1),
           GenericRule(id="mix",name="Avoid split mixing",engine="intra",mechanism="split_mixing_term",
                       mode="soft",polarity="penalty",weight=10)]
    for forced in [False,True]:
        plan=solve_generic(GenericProblem(**scene(2 if forced else 3),rules=rules))
        compare(plan,forced)


def test_unsplit_families_share_normally_with_zero_mixing_penalty():
    inputs=scene(2)
    inputs["guests"]=[Guest(id=f"g{i}",name=f"Guest {i}",group_id=f"family-{i//2}")
                      for i in range(4)]
    inputs["tables"]=[Table(id="T0",zone_id="z",capacity=4)]
    inputs["layout"]=VenueLayout(floors=[FloorLayout(zone_id="z",width=140,height=120,
          tables=[TableDrawing(table_id="T0",x=0,y=0,width=120,height=90)])])
    rule=Rule(id="mix",shape="split_mixing_penalty",mode="soft",weight=100)
    plan=solve(Problem(**inputs,rules=[rule]))
    assert plan.status=="optimal" and plan.total_score==0
    assert {a.table_id for a in plan.assignments}=={"T0"}
