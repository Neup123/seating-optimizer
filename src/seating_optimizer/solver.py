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


def _has_table_property(table, name: str) -> bool:
    """Tags are passive; only guest-need rules may query them."""
    expected = name.strip().casefold()
    return any(tag.casefold() == expected for tag in table.properties)


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
            if rule.shape in ("attribute_grouping", "zone_restriction", "table_property_need"):
                if not isinstance(p["attribute"], str) or not p["attribute"]:
                    raise ValueError("nonempty attribute required")
            if rule.shape == "zone_restriction":
                if not _allowed_zones(rule) <= zones:
                    raise ValueError("unknown zone")
            if rule.shape == "table_property_need":
                if not isinstance(p["property"], str) or not p["property"].strip():
                    raise ValueError("nonempty table property required")
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


def _capacity_obstruction(groups, tables):
    """A sufficient (not guessed) capacity/party-packing explanation, if available."""
    sizes = [len(members) for members in groups.values()]
    if not sizes:
        return None
    guests = sum(sizes)
    chairs = sum(table.capacity for table in tables)
    if guests > chairs:
        return (f"Not enough chairs: {guests} guests need seats, but only {chairs} chairs "
                f"are available across {len(tables)} tables (short by {guests - chairs}).")
    largest = max(sizes)
    max_table = max(table.capacity for table in tables)
    if largest > max_table:
        return (f"Party too large: a party of {largest} must stay together, "
                f"but the largest table seats only {max_table}.")
    if len({table.capacity for table in tables}) == 1:
        capacity = tables[0].capacity
        # Parties above half a table cannot share with each other or with
        # exactly-half-table parties. Two half-table parties can share.
        large = sum(2 * size > capacity for size in sizes)
        half = sum(2 * size == capacity for size in sizes)
        minimum_tables = large + (half + 1) // 2
        if minimum_tables > len(tables):
            return (f"Party packing: at least {minimum_tables} tables of {capacity} chairs "
                    f"are needed for these {len(sizes)} parties ({guests} guests), "
                    f"but only {len(tables)} tables ({chairs} chairs) are available. "
                    "Unused chairs at different tables cannot be combined while parties stay together.")
    return None


def _party_packing_summary(groups, tables):
    guests = sum(len(members) for members in groups.values())
    chairs = sum(table.capacity for table in tables)
    return (f"Party packing: {len(groups)} parties ({guests} guests) cannot be placed "
            f"at {len(tables)} tables ({chairs} chairs) while keeping each party together. "
            "Reconsider table sizes/counts or party grouping; total chairs alone do not guarantee a fit.")


def _conflicting_rules(model, assumptions, problem):
    """Use a single-worker feasibility solve for a useful assumption core.

    Optimizing or running multiple workers can return *all* assumptions, including
    irrelevant ones. Return None if the diagnostic solve cannot prove a core.
    """
    if not assumptions:
        return []
    model.clear_objective()
    diagnostic = cp_model.CpSolver()
    diagnostic.parameters.num_search_workers = 1
    diagnostic.parameters.max_time_in_seconds = min(problem.config.time_limit_seconds, 5.0)
    diagnostic.parameters.random_seed = problem.config.random_seed
    if diagnostic.Solve(model) != cp_model.INFEASIBLE:
        return None
    names = {lit.Index(): name for name, lit in assumptions.items()}
    return [names[int(index)] for index in diagnostic.SufficientAssumptionsForInfeasibility()
            if int(index) in names]


def solve(problem: Problem) -> Plan:
    """Solve one session. A separate Problem is used for each meal sitting."""
    start = perf_counter()
    groups, lookup = _prepare(problem)
    tables = problem.tables
    proven_obstruction = _capacity_obstruction(groups, tables)
    if proven_obstruction:
        return Plan(
            session_id=problem.session_id, status="infeasible",
            conflicting_constraints=[proven_obstruction],
            message="No seating arrangement is possible with the available table capacities and party sizes.",
            solve_seconds=perf_counter() - start, layout=problem.layout,
        )
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
        model.Add(seats[j] <= table.capacity)  # Physical limits are unconditional, not diagnostic assumptions.

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
        elif rule.shape == "table_property_need":
            # The weight belongs to each affected GUEST. Table tags cannot
            # grant points by themselves, and families remain atomic.
            for gid, members in groups.items():
                count = sum(_matched(guest, rule) for guest in members)
                if not count:
                    continue
                for j, table in enumerate(tables):
                    if _has_table_property(table, p["property"]):
                        if rule.mode == "soft":
                            terms.append(rule.weight * count * x[gid, j])
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
        message = "Time limit reached without a feasible plan; infeasibility is unproven."
        if status == cp_model.INFEASIBLE:
            core = _conflicting_rules(model, assumptions, problem)
            if core is None:
                message = ("No seating plan satisfies all hard constraints. "
                           "The conflicting rules could not be isolated within the diagnostic time limit.")
            elif core:
                conflicts = core
                message = ("These hard rules cannot all be satisfied together with the "
                           "table capacities and party grouping.")
            else:
                conflicts = [_party_packing_summary(groups, tables)]
                message = "The table capacities and whole-party placement prevent a seating plan."
        return Plan(
            session_id=problem.session_id,
            status="infeasible" if status == cp_model.INFEASIBLE else "unknown",
            conflicting_constraints=conflicts,
            solve_seconds=perf_counter() - start,
            layout=problem.layout,
            message=message,
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
                        description=(
                            next((f"{p['attribute']}={val} is split across " +
                                  ", ".join(tables[j].id for j, q in per_table.items() if q)
                                  for val, per_table in value_counts.items()
                                  if sum(q > 0 for q in per_table.values()) > 1),
                                 "Matching attribute values are split across tables")
                            + "; the separated guest pairs earn no grouping points."
                        ),
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
                    description=(
                        next((f"Group {gid} sits in zone {tables[placed[gid]].zone_id} "
                              f"instead of a preferred zone {', '.join(sorted(allowed))}."
                              for gid, members in groups.items()
                              if any(_matched(g, rule) for g in members)
                              and tables[placed[gid]].zone_id not in allowed),
                             "Affected groups are outside their preferred zone.")
                    ),
                    lost_points=total_matches * rule.weight - points))
        elif rule.shape == "table_property_need":
            need = p["attribute"] + (("=" + str(p["value"])) if "value" in p else " (any value)")
            for gid, members in groups.items():
                count = sum(_matched(guest, rule) for guest in members)
                if not count:
                    continue
                table = tables[placed[gid]]
                has_tag = _has_table_property(table, p["property"])
                earned = rule.weight * count if rule.mode == "soft" and has_tag else 0
                points += earned
                if has_tag:
                    reasons[gid].append(Reason(
                        rule_id=rule.id,
                        description=(f"Guest need {need} met: table {table.id} has "
                                     f"property {p['property']} ({count} affected guest(s))."),
                        points=earned))
                elif rule.mode == "soft":
                    lost = rule.weight * count
                    reasons[gid].append(Reason(
                        rule_id=rule.id,
                        description=(f"Guest need {need} not met at table {table.id}: "
                                     f"missing property {p['property']} ({lost} preference points unavailable)."),
                        points=0))
                    compromises.append(Compromise(
                        rule_id=rule.id,
                        description=(f"Group {gid} needs {need} at a table with property "
                                     f"{p['property']}, but sits at {table.id}."),
                        lost_points=lost))
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
                    description=(f"Pair preference not met: {p['left']} at {tables[placed[a]].id} "
                                 f"and {p['right']} at {tables[placed[b]].id} "
                                 f"should be {p['relation']}. "
                                 + ("Hard pins involved: " + ", ".join(r.id for r in problem.rules
                                      if r.shape == "pin" and r.mode == "hard" and
                                      lookup[r.parameters["target"]] in {a, b})
                                    if any(r.shape == "pin" and r.mode == "hard" and
                                           lookup[r.parameters["target"]] in {a, b}
                                           for r in problem.rules) else "")),
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
                layout=problem.layout,
                message="All hard constraints satisfied.")
