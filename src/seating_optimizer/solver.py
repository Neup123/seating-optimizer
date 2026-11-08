"""CP-SAT seating solver. No HTTP, persistence, global mutable state or UI."""
from __future__ import annotations

from collections import defaultdict
from itertools import combinations
from time import perf_counter

from ortools.sat.python import cp_model

from .models import Assignment, Compromise, Plan, Problem, Reason, ScoreItem, TableUsage


def _group_id(guest):
    return guest.group_id if guest.group_id is not None else "guest:" + guest.id


def _matched(guest, rule):
    key = rule.parameters["attribute"]
    return key in guest.attributes and (
        "value" not in rule.parameters or str(guest.attributes[key]) == str(rule.parameters["value"])
    )


def _values(guest, rule):
    key = rule.parameters["attribute"]
    if key not in guest.attributes:
        return []
    val = str(guest.attributes[key])
    return [val] if "value" not in rule.parameters or str(rule.parameters["value"]) == val else []


def _allowed_zones(rule):
    p = rule.parameters
    zones = p.get("allowed_zones", [p["zone"]] if "zone" in p else None)
    if not isinstance(zones, list) or not zones or not all(isinstance(z, str) for z in zones):
        raise ValueError(f"Rule {rule.id}: zone restriction requires allowed_zones or zone")
    return set(zones)


def _prepare(problem):
    groups = defaultdict(list)
    for guest in problem.guests:
        groups[_group_id(guest)].append(guest)
    groups = dict(groups)
    lookup = {}
    for gid, guests in groups.items():
        lookup[gid] = gid
        for guest in guests:
            if guest.id in lookup and lookup[guest.id] != gid:
                raise ValueError(f"Ambiguous target {guest.id}")
            lookup[guest.id] = gid
            if guest.name in lookup and lookup[guest.name] != gid:
                raise ValueError(f"Ambiguous target {guest.name}")
            lookup[guest.name] = gid
    tables = {t.id: t for t in problem.tables}
    zones = {z.id for z in problem.zones}
    for rule in problem.rules:
        p = rule.parameters
        try:
            if rule.shape in ("attribute_grouping", "zone_restriction"):
                if not isinstance(p["attribute"], str) or not p["attribute"]:
                    raise ValueError("nonempty attribute required")
            if rule.shape == "zone_restriction":
                if not _allowed_zones(rule) <= zones:
                    raise ValueError("unknown zone")
            if rule.shape == "pair":
                if p["left"] not in lookup or p["right"] not in lookup:
                    raise ValueError("unknown guest/group target")
                if p["relation"] not in ("together", "apart"):
                    raise ValueError("relation must be together or apart")
            if rule.shape == "pin":
                if p["target"] not in lookup or p["table"] not in tables:
                    raise ValueError("unknown target or table")
        except (KeyError, TypeError) as exc:
            raise ValueError(f"Rule {rule.id}: missing or invalid parameter: {exc}") from exc
    return groups, lookup


def solve(problem: Problem) -> Plan:
    """Solve one session. A separate Problem is used for each meal sitting."""
    start = perf_counter()
    groups, lookup = _prepare(problem)
    tables = problem.tables
    model = cp_model.CpModel()
    ids = list(groups)
    n = len(tables)
    x = {(gid, j): model.NewBoolVar(f"x:{gid}:{tables[j].id}") for gid in ids for j in range(n)}
    loc = {}
    for gid in ids:
        model.Add(sum(x[gid, j] for j in range(n)) == 1)
        loc[gid] = model.NewIntVar(0, n - 1, f"table:{gid}")
        model.Add(loc[gid] == sum(j * x[gid, j] for j in range(n)))

    assumptions = {}

    def hard(name):
        if name not in assumptions:
            lit = model.NewBoolVar(name)
            model.AddAssumption(lit)
            assumptions[name] = lit
        return assumptions[name]

    seats = {}
    for j, table in enumerate(tables):
        seats[j] = sum(len(groups[gid]) * x[gid, j] for gid in ids)
        model.Add(seats[j] <= table.capacity).OnlyEnforceIf(hard(f"capacity:{table.id}"))

    terms = []
    for rule in problem.rules:
        p = rule.parameters
        if rule.shape == "capacity":
            continue  # Capacity is always enforced, even without an explicit rule record.
        if rule.shape == "pin":
            model.Add(loc[lookup[p["target"]]] == next(
                j for j, table in enumerate(tables) if table.id == p["table"]
            )).OnlyEnforceIf(hard(f"rule:{rule.id}"))
        elif rule.shape == "zone_restriction":
            allowed = _allowed_zones(rule)
            for gid, members in groups.items():
                matches = sum(_matched(guest, rule) for guest in members)
                if not matches:
                    continue
                for j, table in enumerate(tables):
                    if table.zone_id in allowed:
                        if rule.mode == "soft":
                            terms.append(rule.weight * matches * x[gid, j])
                    elif rule.mode == "hard":
                        model.Add(x[gid, j] == 0).OnlyEnforceIf(hard(f"rule:{rule.id}"))
        elif rule.shape == "pair":
            a, b = lookup[p["left"]], lookup[p["right"]]
            together = p["relation"] == "together"
            if rule.mode == "hard":
                relation = loc[a] == loc[b] if together else loc[a] != loc[b]
                model.Add(relation).OnlyEnforceIf(hard(f"rule:{rule.id}"))
            elif a == b:
                if together:
                    terms.append(rule.weight)
            else:
                same = model.NewBoolVar(f"same:{rule.id}")
                model.Add(loc[a] == loc[b]).OnlyEnforceIf(same)
                model.Add(loc[a] != loc[b]).OnlyEnforceIf(same.Not())
                terms.append(rule.weight * (same if together else (1 - same)))
        elif rule.shape == "attribute_grouping":
            grouped = defaultdict(dict)
            for gid, members in groups.items():
                for guest in members:
                    for value in _values(guest, rule):
                        grouped.setdefault(value, {}).setdefault(gid, 0)
                        grouped[value][gid] += 1
            if rule.mode == "hard":
                assumption = hard(f"rule:{rule.id}")
                for by_group in grouped.values():
                    for a, b in combinations(by_group, 2):
                        model.Add(loc[a] == loc[b]).OnlyEnforceIf(assumption)
            else:
                for value, by_group in grouped.items():
                    max_count = sum(by_group.values())
                    if max_count < 2:
                        continue
                    triangular = [k * (k - 1) // 2 for k in range(max_count + 1)]
                    for j in range(n):
                        count = model.NewIntVar(0, max_count, f"count:{rule.id}:{value}:{j}")
                        model.Add(count == sum(q * x[gid, j] for gid, q in by_group.items()))
                        score = model.NewIntVar(0, triangular[-1], f"pairs:{rule.id}:{value}:{j}")
                        model.AddElement(count, triangular, score)
                        terms.append(rule.weight * score)
        elif rule.shape == "fill_efficiency":
            for j, table in enumerate(tables):
                used = model.NewBoolVar(f"used:{rule.id}:{table.id}")
                model.Add(seats[j] >= 1).OnlyEnforceIf(used)
                model.Add(seats[j] == 0).OnlyEnforceIf(used.Not())
                # Negative lower bound avoids hiding a hard capacity constraint in this definition.
                holes = model.NewIntVar(-len(problem.guests), table.capacity, f"holes:{rule.id}:{table.id}")
                model.Add(holes == table.capacity * used - seats[j])
                terms.append(-rule.weight * holes)

    model.Maximize(sum(terms))
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = problem.config.time_limit_seconds
    solver.parameters.num_search_workers = problem.config.workers
    solver.parameters.random_seed = problem.config.random_seed
    status = solver.Solve(model)
    elapsed = perf_counter() - start
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        conflicts = []
        if status == cp_model.INFEASIBLE:
            names = {lit.Index(): name for name, lit in assumptions.items()}
            conflicts = [names.get(int(i), f"hard-assumption:{i}")
                         for i in solver.SufficientAssumptionsForInfeasibility()]
            if not conflicts:
                conflicts = ["group placement / structural hard constraints"]
        return Plan(
            session_id=problem.session_id,
            status="infeasible" if status == cp_model.INFEASIBLE else "unknown",
            conflicting_constraints=conflicts,
            solve_seconds=elapsed,
            message=("No plan satisfies all hard constraints." if status == cp_model.INFEASIBLE
                     else "Time limit reached without a feasible plan; infeasibility is unproven."),
        )

    placed = {gid: solver.Value(loc[gid]) for gid in ids}
    usage = {j: sum(len(groups[gid]) for gid in ids if placed[gid] == j) for j in range(n)}
    reasons = defaultdict(list)
    breakdown = []
    compromises = []
    for gid in ids:
        table = tables[placed[gid]]
        reasons[gid].append(Reason(rule_id=f"capacity:{table.id}",
                                   description=f"Within the hard {table.capacity}-chair capacity of table {table.id}."))
    for rule in problem.rules:
        p = rule.parameters
        points = 0
        if rule.shape == "attribute_grouping":
            value_counts = defaultdict(lambda: defaultdict(int))
            group_counts = defaultdict(lambda: defaultdict(int))
            for gid, members in groups.items():
                for guest in members:
                    for value in _values(guest, rule):
                        value_counts[value][placed[gid]] += 1
                        group_counts[gid][value] += 1
            for gid, vals in group_counts.items():
                contributed = 0.0
                for val, k in vals.items():
                    q = value_counts[val][placed[gid]]
                    if rule.mode == "soft":
                        contributed += rule.weight * (k * (k - 1) / 2 + k * (q - k) / 2)
                if vals:
                    reasons[gid].append(Reason(rule_id=rule.id,
                         description=f"Shares {p['attribute']} with guests at this table.",
                         points=contributed))
            if rule.mode == "soft":
                points = int(sum(rule.weight * sum(q * (q - 1) // 2 for q in per_table.values())
                                 for per_table in value_counts.values()))
                all_values = {v: sum(per_table.values()) for v, per_table in value_counts.items()}
                potential = sum(rule.weight * q * (q - 1) // 2 for q in all_values.values())
                if potential > points:
                    compromises.append(Compromise(rule_id=rule.id,
                        description="Some matching-attribute guest pairs sit at different tables.",
                        lost_points=potential - points))
        elif rule.shape == "zone_restriction":
            allowed = _allowed_zones(rule)
            total_matches = 0
            for gid, members in groups.items():
                k = sum(_matched(g, rule) for g in members)
                if not k:
                    continue
                total_matches += k
                zone = tables[placed[gid]].zone_id
                if zone in allowed:
                    share = (rule.weight * k if rule.mode == "soft" else 0)
                    points += share
                    reasons[gid].append(Reason(rule_id=rule.id,
                        description=f"Group placed in permitted zone {zone} because a member has {p['attribute']}.",
                        points=share))
            if rule.mode == "soft" and total_matches * rule.weight > points:
                compromises.append(Compromise(rule_id=rule.id,
                    description="Some affected groups are outside preferred zones.",
                    lost_points=total_matches * rule.weight - points))
        elif rule.shape == "pair":
            a, b = lookup[p["left"]], lookup[p["right"]]
            satisfied = (placed[a] == placed[b]) == (p["relation"] == "together")
            if satisfied:
                points = rule.weight if rule.mode == "soft" else 0
                for gid in {a, b}:
                    reasons[gid].append(Reason(rule_id=rule.id,
                        description=f"Pair preference met: {p['left']} and {p['right']} are {p['relation']}.",
                        points=points / len({a, b})))
            elif rule.mode == "soft":
                compromises.append(Compromise(rule_id=rule.id,
                    description=f"Pair preference not met: {p['left']} and {p['right']} should be {p['relation']}.",
                    lost_points=rule.weight))
        elif rule.shape == "pin":
            gid = lookup[p["target"]]
            reasons[gid].append(Reason(rule_id=rule.id,
                description=f"Hard pin keeps {p['target']} at table {p['table']}."))
        elif rule.shape == "fill_efficiency":
            for j, table in enumerate(tables):
                holes = table.capacity - usage[j] if usage[j] else 0
                points -= rule.weight * holes
                if holes:
                    compromises.append(Compromise(rule_id=rule.id,
                        description=f"Table {table.id} has {holes} empty chairs.",
                        lost_points=rule.weight * holes))
                    for gid in ids:
                        if placed[gid] == j:
                            share = -rule.weight * holes * len(groups[gid]) / usage[j]
                            reasons[gid].append(Reason(rule_id=rule.id,
                                description=f"Fill efficiency: {holes} empty chairs at table {table.id}.",
                                points=share))
        if rule.mode == "soft":
            breakdown.append(ScoreItem(rule_id=rule.id, points=points))
    assignments = [
        Assignment(group_id=gid, table_id=tables[placed[gid]].id,
                   guest_ids=[guest.id for guest in members],
                   guest_names=[guest.name for guest in members],
                   reasons=reasons[gid],
                   points=round(sum(r.points for r in reasons[gid]), 5))
        for gid, members in groups.items()
    ]
    table_usage = [
        TableUsage(table_id=t.id, zone_id=t.zone_id, capacity=t.capacity,
                   occupied=usage[j], empty_seats=t.capacity - usage[j])
        for j, t in enumerate(tables)
    ]
    calculated = sum(item.points for item in breakdown)
    if calculated != round(solver.ObjectiveValue()):
        raise RuntimeError(f"Score breakdown mismatch: {calculated} vs {solver.ObjectiveValue()}")
    return Plan(session_id=problem.session_id,
                status="optimal" if status == cp_model.OPTIMAL else "feasible",
                total_score=calculated, assignments=assignments,
                tables=table_usage, score_breakdown=breakdown,
                compromises=compromises, solve_seconds=elapsed,
                message="All hard constraints satisfied.")
