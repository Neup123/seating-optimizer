"""CP-SAT seating solver. No HTTP, persistence, global mutable state or UI."""
from __future__ import annotations

from collections import defaultdict
from itertools import combinations
from time import perf_counter

from ortools.sat.python import cp_model

from .adjacency import together_clusters, neighbouring_tables, largest_connected_capacity
from .display import counted, distinct_party_name, party_name_for
from .models import Assignment, Compromise, PatternMatch, Plan, Problem, Reason, ScoreItem, TableUsage
from .pattern_rules import add_pattern_match, pattern_matches, pattern_description, validate_pattern


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
            if rule.shape == "global_pattern":
                validate_pattern(p, rule_id=rule.id)
        except (KeyError, TypeError) as exc:
            raise ValueError(f"Rule {rule.id}: missing or invalid parameter: {exc}") from exc
    return groups, lookup


def _capacity_obstruction(groups, tables, splittable=frozenset()):
    """A sufficient (not guessed) capacity/party-packing explanation, if available."""
    sizes = [len(members) for gid, members in groups.items() if gid not in splittable]
    guests = sum(len(members) for members in groups.values())
    if not guests:
        return None
    chairs = sum(table.capacity for table in tables)
    if guests > chairs:
        return (f"Not enough chairs: {counted(guests, 'guest')} need seats, but only {counted(chairs, 'chair')} "
                f"are available across {counted(len(tables), 'table')} (short by {guests - chairs}).")
    if not sizes:
        return None
    largest = max(sizes)
    max_table = max(table.capacity for table in tables)
    if largest > max_table:
        return (f"Party too large — not achievable: an atomic group of {largest} cannot be "
                f"split across tables, but the largest table seats only {max_table}.")
    if not splittable and len({table.capacity for table in tables}) == 1:
        capacity = tables[0].capacity
        # Parties above half a table cannot share with each other or with
        # exactly-half-table parties. Two half-table parties can share.
        large = sum(2 * size > capacity for size in sizes)
        half = sum(2 * size == capacity for size in sizes)
        minimum_tables = large + (half + 1) // 2
        if minimum_tables > len(tables):
            return (f"Party packing: at least {minimum_tables} tables of {capacity} chairs "
                    f"are needed for these {counted(len(sizes), 'party', 'parties')} ({counted(guests, 'guest')}), "
                    f"but only {counted(len(tables), 'table')} ({counted(chairs, 'chair')}) are available. "
                    "Unused chairs at different tables cannot be combined while parties stay together.")
    return None


def _party_packing_summary(groups, tables):
    guests = sum(len(members) for members in groups.values())
    chairs = sum(table.capacity for table in tables)
    return (f"Party packing: {counted(len(groups), 'party', 'parties')} ({counted(guests, 'guest')}) cannot be placed "
            f"at {counted(len(tables), 'table')} ({counted(chairs, 'chair')}) while keeping each party together. "
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
    # Resolve identity across the ENTIRE party, never from its first member.
    # This also protects direct API solve payloads that bypass the importer.
    group_names = {
        gid: distinct_party_name(
            gid, [guest.group_name for guest in members],
            [guest.name for guest in members])
        for gid, members in groups.items()
    }
    def group_name(gid):
        members = groups[gid]
        return party_name_for(gid, group_names[gid], [guest.name for guest in members])

    tables = problem.tables
    # The only exception to atomic groups is a lone group that fits no
    # table. A together-linked group is still handled by the existing
    # atomic linked-cluster model; its behaviour is unchanged.
    maximum_table = max(table.capacity for table in tables)
    linked = {
        lookup[target] for rule in problem.rules
        if rule.shape == "pair" and rule.parameters["relation"] == "together"
        for target in (rule.parameters["left"], rule.parameters["right"])
    }
    split_groups = {
        gid for gid, members in groups.items()
        if len(members) > maximum_table and gid not in linked
    }
    neighbours = neighbouring_tables(problem.layout, tables)
    for gid in sorted(split_groups):
        # Prune forbidden drawings BEFORE testing connected capacity. A route
        # through a forbidden or unoccupied intermediary does not qualify.
        admissible = set(range(len(tables)))
        blockers = []
        for rule in problem.rules:
            p = rule.parameters
            if rule.mode != "hard":
                continue
            if rule.shape == "zone_restriction" and any(
                    _matched(guest, rule) for guest in groups[gid]):
                admissible &= {j for j, table in enumerate(tables)
                               if table.zone_id in _allowed_zones(rule)}
                blockers.append(rule.id)
            elif rule.shape == "table_property_need" and any(
                    _matched(guest, rule) for guest in groups[gid]):
                admissible &= {j for j, table in enumerate(tables)
                               if _has_table_property(table, p["property"])}
                blockers.append(rule.id)
            elif rule.shape == "pin" and lookup[p["target"]] == gid:
                admissible &= {j for j, table in enumerate(tables)
                               if table.id == p["table"]}
                blockers.append(rule.id)
        reachable = {j: neighbours[j] & admissible for j in admissible}
        if largest_connected_capacity(reachable, tables) < len(groups[gid]):
            detail = (f" Hard rules limiting usable tables: {', '.join(blockers)}."
                      if blockers else "")
            return Plan(
                session_id=problem.session_id, status="infeasible",
                conflicting_constraints=[
                    f"Party too large — not achievable: group {group_name(gid)} has {counted(len(groups[gid]), 'guest')}; "
                    "no single table fits, and no connected adjacent-table "
                    "set on one drawn floor has sufficient permitted capacity."
                    + detail
                ],
                message="The oversized group cannot be seated at adjacent tables.",
                solve_seconds=perf_counter() - start, layout=problem.layout,
            )
    proven_obstruction = _capacity_obstruction(groups, tables, split_groups)
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
    # x is table occupancy. For ordinary groups it remains the original
    # exactly-one-table Boolean; only the permitted oversized lone groups
    # allocate their guests individually, preserving each guest identity.
    x = {(gid, j): model.NewBoolVar(f"x:{gid}:{tables[j].id}") for gid in ids for j in range(n)}
    guest_at = {}
    loc = {}
    for gid in ids:
        if gid in split_groups:
            for guest in groups[gid]:
                for j in range(n):
                    guest_at[guest.id, j] = model.NewBoolVar(f"guest:{guest.id}:{tables[j].id}")
                model.Add(sum(guest_at[guest.id, j] for j in range(n)) == 1)
            for j in range(n):
                count = sum(guest_at[guest.id, j] for guest in groups[gid])
                model.Add(count >= x[gid, j])
                model.Add(count <= len(groups[gid]) * x[gid, j])
        else:
            model.Add(sum(x[gid, j] for j in range(n)) == 1)
            loc[gid] = model.NewIntVar(0, n - 1, f"table:{gid}")
            model.Add(loc[gid] == sum(j * x[gid, j] for j in range(n)))
            for guest in groups[gid]:
                for j in range(n):
                    guest_at[guest.id, j] = x[gid, j]

    assumptions = {}

    def hard(name):
        if name not in assumptions:
            lit = model.NewBoolVar(name)
            model.AddAssumption(lit)
            assumptions[name] = lit
        return assumptions[name]

    seats = {}
    for j, table in enumerate(tables):
        seats[j] = sum(guest_at[guest.id, j] for guest in problem.guests)
        model.Add(seats[j] <= table.capacity)  # Physical limits are unconditional, not diagnostic assumptions.

    # Existing linked-cluster exception: distinct groups stay atomic and may
    # use connected adjacent tables only if no single table fits the cluster.
    # A Boolean enables adjacency for soft requests (and earns their pair points);
    # hard together requests force that Boolean via diagnostic assumptions.
    fallback_by_rule = {}
    for cluster_index, (members, cluster_rules) in enumerate(
            together_clusters(ids, lookup, problem.rules)):
        party_size = sum(len(groups[gid]) for gid in members)
        if party_size <= maximum_table:
            continue  # Same table remains the only qualifying together outcome.
        compulsory = [rule for rule in cluster_rules if rule.mode == "hard"]
        if compulsory and largest_connected_capacity(neighbours, tables) < party_size:
            return Plan(
                session_id=problem.session_id, status="infeasible",
                conflicting_constraints=[
                    f"Not achievable: together-linked party of {counted(party_size, 'person', 'people')} has "
                    "no connected adjacent-table cluster on a single drawn floor "
                    "with enough chairs. Keep each group whole and adjust the layout."
                ],
                message="The requested adjacent-table fallback cannot fit on this layout.",
                solve_seconds=perf_counter() - start, layout=problem.layout,
            )
        active = model.NewBoolVar(f"adjacent-fallback:{cluster_index}")
        for rule in compulsory:
            model.Add(active == 1).OnlyEnforceIf(hard(f"rule:{rule.id}"))
        for rule in cluster_rules:
            fallback_by_rule[rule.id] = (active, party_size, members)
        # The occupied table subset must be connected. Pick exactly one root,
        # and give every other occupied table an edge from a lower-rank parent;
        # strictly increasing ranks exclude disconnected cycles.
        occupied = {}
        roots = {}
        ranks = {}
        incoming = {j: [] for j in range(n)}
        for j in range(n):
            count = sum(x[gid, j] for gid in members)
            occupied[j] = model.NewBoolVar(f"fallback-used:{cluster_index}:{j}")
            roots[j] = model.NewBoolVar(f"fallback-root:{cluster_index}:{j}")
            ranks[j] = model.NewIntVar(0, n, f"fallback-rank:{cluster_index}:{j}")
            model.Add(count >= 1).OnlyEnforceIf([active, occupied[j]])
            model.Add(count == 0).OnlyEnforceIf([active, occupied[j].Not()])
            model.Add(roots[j] <= occupied[j]).OnlyEnforceIf(active)
            model.Add(ranks[j] == 0).OnlyEnforceIf([active, roots[j]])
        for i, neighbours_of_i in neighbours.items():
            for j in neighbours_of_i:
                arc = model.NewBoolVar(f"fallback-parent:{cluster_index}:{i}:{j}")
                incoming[j].append(arc)
                model.Add(arc <= occupied[i]).OnlyEnforceIf(active)
                model.Add(ranks[j] >= ranks[i] + 1).OnlyEnforceIf([active, arc])
        model.Add(sum(roots.values()) == 1).OnlyEnforceIf(active)
        for j in range(n):
            model.Add(sum(incoming[j]) + roots[j] == occupied[j]).OnlyEnforceIf(active)

    # A split lone group must occupy a connected, nonempty set of drawn
    # neighbours. All occupied tables (including intermediary tables) belong
    # to that very group; no empty table may bridge a gap or cross floors.
    for gid in sorted(split_groups):
        roots = {j: model.NewBoolVar(f"lone-root:{gid}:{j}") for j in range(n)}
        ranks = {j: model.NewIntVar(0, n, f"lone-rank:{gid}:{j}") for j in range(n)}
        incoming = {j: [] for j in range(n)}
        for j in range(n):
            model.Add(roots[j] <= x[gid, j])
            model.Add(ranks[j] == 0).OnlyEnforceIf(roots[j])
        for i, adjacent in neighbours.items():
            for j in adjacent:
                arc = model.NewBoolVar(f"lone-parent:{gid}:{i}:{j}")
                incoming[j].append(arc)
                model.Add(arc <= x[gid, i])
                model.Add(ranks[j] >= ranks[i] + 1).OnlyEnforceIf(arc)
        model.Add(sum(roots.values()) == 1)
        for j in range(n):
            model.Add(sum(incoming[j]) + roots[j] == x[gid, j])

    terms = []
    for rule in problem.rules:
        p = rule.parameters
        if rule.shape == "capacity":
            continue  # Capacity is always enforced, even without an explicit rule record.
        if rule.shape == "pin":
            gid = lookup[p["target"]]
            target = next(j for j, table in enumerate(tables) if table.id == p["table"])
            if gid in split_groups:
                # A hard pin still binds the entire imported party, not only
                # the named member: no illegal partial pin is introduced.
                for j in range(n):
                    if j != target:
                        model.Add(x[gid, j] == 0).OnlyEnforceIf(hard(f"rule:{rule.id}"))
            else:
                model.Add(loc[gid] == target).OnlyEnforceIf(hard(f"rule:{rule.id}"))
        elif rule.shape == "zone_restriction":
            allowed = _allowed_zones(rule)
            for gid, members in groups.items():
                matches = sum(_matched(guest, rule) for guest in members)
                if not matches:
                    continue
                for j, table in enumerate(tables):
                    if table.zone_id in allowed:
                        if rule.mode == "soft" and gid not in split_groups:
                            terms.append(rule.weight * matches * x[gid, j])
                    elif rule.mode == "hard":
                        model.Add(x[gid, j] == 0).OnlyEnforceIf(hard(f"rule:{rule.id}"))
                if rule.mode == "soft" and gid in split_groups:
                    allowed_tables = [x[gid, j] for j, t in enumerate(tables) if t.zone_id in allowed]
                    in_zone = model.NewBoolVar(f"zone:{rule.id}:{gid}")
                    if allowed_tables:
                        model.AddMaxEquality(in_zone, allowed_tables)
                    else:
                        model.Add(in_zone == 0)
                    terms.append(rule.weight * matches * in_zone)
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
                            if gid in split_groups:
                                terms.extend(rule.weight * guest_at[guest.id, j]
                                             for guest in members if _matched(guest, rule))
                            else:
                                terms.append(rule.weight * count * x[gid, j])
                    elif rule.mode == "hard":
                        model.Add(x[gid, j] == 0).OnlyEnforceIf(hard(f"rule:{rule.id}"))
        elif rule.shape == "pair":
            if rule.id in fallback_by_rule:
                if rule.mode == "soft":
                    terms.append(rule.weight * fallback_by_rule[rule.id][0])
                continue
            a, b = lookup[p["left"]], lookup[p["right"]]
            together = p["relation"] == "together"
            if a == b:
                if rule.mode == "hard" and not together:
                    model.Add(0 == 1).OnlyEnforceIf(hard(f"rule:{rule.id}"))
                elif rule.mode == "soft" and together:
                    terms.append(rule.weight)
            elif a in split_groups or b in split_groups:
                if together:
                    # These groups are excluded from lone-split eligibility,
                    # but retain a sound hard meaning if linked in future.
                    if rule.mode == "hard":
                        assumption = hard(f"rule:{rule.id}")
                        for j in range(n):
                            model.Add(x[a, j] == x[b, j]).OnlyEnforceIf(assumption)
                        model.Add(sum(x[a, j] for j in range(n)) == 1).OnlyEnforceIf(assumption)
                elif rule.mode == "hard":
                    assumption = hard(f"rule:{rule.id}")
                    for j in range(n):
                        model.Add(x[a, j] + x[b, j] <= 1).OnlyEnforceIf(assumption)
                else:
                    overlap = []
                    for j in range(n):
                        both = model.NewBoolVar(f"overlap:{rule.id}:{j}")
                        model.Add(both <= x[a, j])
                        model.Add(both <= x[b, j])
                        model.Add(both >= x[a, j] + x[b, j] - 1)
                        overlap.append(both)
                    apart = model.NewBoolVar(f"apart:{rule.id}")
                    model.Add(sum(overlap) == 0).OnlyEnforceIf(apart)
                    model.Add(sum(overlap) >= 1).OnlyEnforceIf(apart.Not())
                    terms.append(rule.weight * apart)
            elif rule.mode == "hard":
                relation = loc[a] == loc[b] if together else loc[a] != loc[b]
                model.Add(relation).OnlyEnforceIf(hard(f"rule:{rule.id}"))
            else:
                same = model.NewBoolVar(f"same:{rule.id}")
                model.Add(loc[a] == loc[b]).OnlyEnforceIf(same)
                model.Add(loc[a] != loc[b]).OnlyEnforceIf(same.Not())
                terms.append(rule.weight * (same if together else (1 - same)))
        elif rule.shape == "attribute_grouping":
            by_value = defaultdict(list)
            for guest in problem.guests:
                for value in _values(guest, rule):
                    by_value[value].append(guest.id)
            if rule.mode == "hard":
                assumption = hard(f"rule:{rule.id}")
                for member_ids in by_value.values():
                    if len(member_ids) < 2:
                        continue
                    first = member_ids[0]
                    for other in member_ids[1:]:
                        for j in range(n):
                            model.Add(guest_at[first, j] == guest_at[other, j]).OnlyEnforceIf(assumption)
            else:
                for value, member_ids in by_value.items():
                    max_count = len(member_ids)
                    if max_count < 2:
                        continue
                    triangular = [k * (k - 1) // 2 for k in range(max_count + 1)]
                    for j in range(n):
                        count = model.NewIntVar(0, max_count, f"count:{rule.id}:{value}:{j}")
                        model.Add(count == sum(guest_at[guest_id, j] for guest_id in member_ids))
                        score = model.NewIntVar(0, triangular[-1], f"pairs:{rule.id}:{value}:{j}")
                        model.AddElement(count, triangular, score)
                        terms.append(rule.weight * score)
        elif rule.shape == "global_pattern":
            if p.get("enabled", False):
                sign = -1 if p.get("effect", "penalty") == "penalty" else 1
                for j, table in enumerate(tables):
                    matched = add_pattern_match(
                        model, p, f"{rule.id}:{table.id}", table.capacity,
                        sum(x[gid, j] for gid in ids), seats[j])
                    terms.append(sign * rule.weight * matched)
        elif rule.shape == "fill_efficiency":
            for j, table in enumerate(tables):
                used = model.NewBoolVar(f"used:{rule.id}:{table.id}")
                model.Add(seats[j] >= 1).OnlyEnforceIf(used)
                model.Add(seats[j] == 0).OnlyEnforceIf(used.Not())
                # Negative lower bound avoids hiding a hard capacity constraint in this definition.
                holes = model.NewIntVar(-len(problem.guests), table.capacity, f"holes:{rule.id}:{table.id}")
                model.Add(holes == table.capacity * used - seats[j])
                terms.append(-rule.weight * holes)

    # A first-class venue preference, not a passive property tag or hard restriction.
    # Exactly one extra point per eligible group, including an adjacent-table
    # split pair when individual table capacities are only one seat.
    priority_rule = "venue:small-group-priority"
    priority_tables = {j for j, table in enumerate(tables) if table.small_group_priority}
    if priority_tables:
        for gid, members in groups.items():
            if len(members) <= 2:
                if gid in split_groups:
                    preferred = model.NewBoolVar(f"small-priority:{gid}")
                    model.AddMaxEquality(preferred, [x[gid, j] for j in priority_tables])
                    terms.append(preferred)
                else:
                    for j in priority_tables:
                        terms.append(x[gid, j])

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
                if split_groups:
                    conflicts = [
                        "Party too large — not achievable: oversized group(s) "
                        + ", ".join(sorted(split_groups))
                        + " cannot be seated on a connected adjacent-table set "
                        "while respecting all hard rules and table capacities."
                    ]
                    message = "The adjacent-table hard-case placement is not achievable."
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

    guest_placed = {
        guest.id: next(j for j in range(n) if solver.Value(guest_at[guest.id, j]))
        for guest in problem.guests
    }
    group_tables = {
        gid: {guest_placed[guest.id] for guest in members}
        for gid, members in groups.items()
    }
    placed = {gid: min(group_tables[gid]) for gid in ids}
    usage = {j: sum(guest_placed[guest.id] == j for guest in problem.guests) for j in range(n)}
    reasons = defaultdict(list)
    table_reasons = defaultdict(list)
    breakdown = []
    compromises = []
    matched_tables = []
    for gid in ids:
        if gid in split_groups:
            for j in group_tables[gid]:
                table = tables[j]
                table_reasons[gid, j].append(Reason(
                    rule_id=f"capacity:{table.id}",
                    description=f"Within the hard {table.capacity}-chair capacity of table {table.id}."))
        else:
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
                        j = guest_placed[guest.id]
                        value_counts[value][j] += 1
                        group_counts[gid][value, j] += 1
            for gid, vals in group_counts.items():
                contributed = 0.0
                for (val, j), k in vals.items():
                    q = value_counts[val][j]
                    if rule.mode == "soft":
                        contributed += rule.weight * (k * (k - 1) / 2 + k * (q - k) / 2)
                if vals:
                    reasons[gid].append(Reason(rule_id=rule.id,
                         description=f"Shares {p['attribute']} with guests at assigned tables.",
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
                        next((f"Group {group_name(gid)} sits in zone {tables[placed[gid]].zone_id} "
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
                if gid in split_groups:
                    matched = [guest for guest in members if _matched(guest, rule)]
                    successful = [g for g in matched if _has_table_property(
                        tables[guest_placed[g.id]], p["property"])]
                    earned = rule.weight * len(successful) if rule.mode == "soft" else 0
                    points += earned
                    reasons[gid].append(Reason(
                        rule_id=rule.id,
                        description=(f"Guest need {need}: {len(successful)} of "
                                     f"{counted(count, 'affected guest')} at tables with property {p['property']}."),
                        points=earned))
                    if rule.mode == "soft" and len(successful) < count:
                        lost = rule.weight * (count - len(successful))
                        compromises.append(Compromise(
                            rule_id=rule.id,
                            description=f"Group {group_name(gid)} has {counted(count - len(successful), 'guest')} without {p['property']}.",
                            lost_points=lost))
                    continue
                table = tables[placed[gid]]
                has_tag = _has_table_property(table, p["property"])
                earned = rule.weight * count if rule.mode == "soft" and has_tag else 0
                points += earned
                if has_tag:
                    reasons[gid].append(Reason(
                        rule_id=rule.id,
                        description=(f"Guest need {need} met: table {table.id} has "
                                     f"property {p['property']} ({counted(count, 'affected guest')})."),
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
                        description=(f"Group {group_name(gid)} needs {need} at a table with property "
                                     f"{p['property']}, but sits at {table.id}."),
                        lost_points=lost))
        elif rule.shape == "pair":
            a, b = lookup[p["left"]], lookup[p["right"]]
            if rule.id in fallback_by_rule:
                active, party_size, members = fallback_by_rule[rule.id]
                if solver.Value(active):
                    points = rule.weight if rule.mode == "soft" else 0
                    tables_used = ", ".join(sorted({tables[placed[gid]].id for gid in members}))
                    for gid in {a, b}:
                        reasons[gid].append(Reason(rule_id=rule.id,
                            description=(f"Sit together: split across adjacent tables {tables_used} "
                                         f"because no single table fits the {party_size}-person linked party."),
                            points=points / len({a, b})))
                elif rule.mode == "soft":
                    for gid in {a, b}:
                        reasons[gid].append(Reason(rule_id=rule.id,
                            description=(f"Sit together not achievable: no single table fits the "
                                         f"{party_size}-person party and adjacent placement was not achieved.")))
                    compromises.append(Compromise(rule_id=rule.id,
                        description=(f"Sit together not achievable for the linked "
                                     f"{party_size}-person party: no adjacent-table placement."),
                        lost_points=rule.weight))
            else:
                together_achieved = len(group_tables[a] | group_tables[b]) == 1
                apart_achieved = a != b and not (group_tables[a] & group_tables[b])
                satisfied = together_achieved if p["relation"] == "together" else apart_achieved
                if satisfied:
                    points = rule.weight if rule.mode == "soft" else 0
                    for gid in {a, b}:
                        description = (f"Sit together achieved at the same table {tables[placed[a]].id}."
                                       if p["relation"] == "together"
                                       else f"Pair apart achieved at different tables.")
                        reasons[gid].append(Reason(rule_id=rule.id,
                            description=description, points=points / len({a, b})))
                elif rule.mode == "soft":
                    compromises.append(Compromise(rule_id=rule.id,
                        description=(f"Pair preference not met: {group_name(a)} at "
                                     f"{', '.join(sorted(tables[j].id for j in group_tables[a]))} "
                                     f"and {group_name(b)} at "
                                     f"{', '.join(sorted(tables[j].id for j in group_tables[b]))} "
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
                description=f"Hard pin keeps {group_name(gid)} at table {p['table']}."))
        elif rule.shape == "global_pattern":
            if p.get("enabled", False):
                sign = -1 if p.get("effect", "penalty") == "penalty" else 1
                description = pattern_description(p)
                for j, table in enumerate(tables):
                    at_table = [gid for gid in ids if j in group_tables[gid]]
                    facts = {"groups_at_table": len(at_table),
                             "occupied_seats": usage[j],
                             "empty_seats": table.capacity - usage[j]}
                    if not pattern_matches(p, facts):
                        continue
                    earned = sign * rule.weight
                    points += earned
                    message = (f"Global pattern [{description}] matched table {table.id} "
                               f"({counted(facts['groups_at_table'], 'group')}, "
                               f"{counted(facts['occupied_seats'], 'occupied seat')}, "
                               f"{counted(facts['empty_seats'], 'empty seat')}); "
                               f"{p.get('effect', 'penalty')} {counted(rule.weight, 'point')}.")
                    matched_tables.append(PatternMatch(
                        rule_id=rule.id, table_id=table.id, description=message, points=earned))
                    if earned < 0:
                        compromises.append(Compromise(rule_id=rule.id,
                            description=message, lost_points=rule.weight))
                    if at_table:
                        for gid in at_table:
                            reason = Reason(rule_id=rule.id,
                                description=message, points=earned / len(at_table))
                            if gid in split_groups:
                                table_reasons[gid, j].append(reason)
                            else:
                                reasons[gid].append(reason)
        elif rule.shape == "fill_efficiency":
            for j, table in enumerate(tables):
                holes = table.capacity - usage[j] if usage[j] else 0
                points -= rule.weight * holes
                if holes:
                    compromises.append(Compromise(rule_id=rule.id,
                        description=f"Table {table.id} has {counted(holes, 'empty chair')}.",
                        lost_points=rule.weight * holes))
                    for gid in ids:
                        if j in group_tables[gid]:
                            count = sum(guest_placed[g.id] == j for g in groups[gid])
                            share = -rule.weight * holes * count / usage[j]
                            reason = Reason(rule_id=rule.id,
                                description=f"Fill efficiency: {counted(holes, 'empty chair')} at table {table.id}.",
                                points=share)
                            if gid in split_groups:
                                table_reasons[gid, j].append(reason)
                            else:
                                reasons[gid].append(reason)
        if rule.mode == "soft":
            breakdown.append(ScoreItem(rule_id=rule.id, points=points))
    if priority_tables:
        earned = 0
        for gid, members in groups.items():
            if len(members) > 2:
                continue
            matched = sorted(group_tables[gid] & priority_tables)
            if matched:
                earned += 1
                if gid in split_groups:
                    # Keep each split portion's reasons tied to its actual table,
                    # and award the group only one point across priority tables.
                    for j in matched:
                        table_reasons[gid, j].append(Reason(
                            rule_id=priority_rule,
                            description=(f"Small group ({counted(len(members), 'person', 'people')}) received "
                                         f"priority at table {tables[j].id}."),
                            points=1 / len(matched)))
                else:
                    table = tables[placed[gid]]
                    reasons[gid].append(Reason(
                        rule_id=priority_rule,
                        description=f"Small group ({counted(len(members), 'person', 'people')}) received priority at table {table.id}.",
                        points=1))
            else:
                table_names = ", ".join(tables[j].id for j in sorted(group_tables[gid]))
                reasons[gid].append(Reason(
                    rule_id=priority_rule,
                    description=f"Small group seated at {table_names}; no priority-table point earned."))
                compromises.append(Compromise(
                    rule_id=priority_rule,
                    description=f"Small group {gid} is at table {table_names}, not a designated small-group table.",
                    lost_points=1))
        breakdown.append(ScoreItem(rule_id=priority_rule, points=earned))
    assignments = []
    for gid, members in groups.items():
        if gid not in split_groups:
            assignments.append(Assignment(
                group_id=gid, group_name=group_names[gid], table_id=tables[placed[gid]].id,
                guest_ids=[guest.id for guest in members],
                guest_names=[guest.name for guest in members],
                guest_attributes=[guest.attributes for guest in members],
                reasons=reasons[gid],
                points=round(sum(r.points for r in reasons[gid]), 5)))
            continue
        table_names = ", ".join(sorted(tables[j].id for j in group_tables[gid]))
        explanation = Reason(
            rule_id=f"adjacent-fallback:{gid}",
            description=(f"Group {group_name(gid)} split across adjacent tables {table_names} because "
                         f"no single table fits its {counted(len(members), 'guest')}."))
        for j in sorted(group_tables[gid]):
            subset = [g for g in members if guest_placed[g.id] == j]
            share = len(subset) / len(members)
            item_reasons = list(table_reasons[gid, j]) + [
                Reason(rule_id=r.rule_id, description=r.description, points=r.points * share)
                for r in reasons[gid]
            ] + [explanation]
            assignments.append(Assignment(
                group_id=gid, group_name=group_names[gid], table_id=tables[j].id,
                guest_ids=[g.id for g in subset],
                guest_names=[g.name for g in subset],
                guest_attributes=[g.attributes for g in subset],
                reasons=item_reasons, points=round(sum(r.points for r in item_reasons), 5)))

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
                tables=table_usage, score_breakdown=breakdown, pattern_matches=matched_tables,
                compromises=compromises, solve_seconds=elapsed,
                layout=problem.layout,
                message="All hard constraints satisfied.")
